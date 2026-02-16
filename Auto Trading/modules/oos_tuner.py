import hashlib
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import backtester as backtester_module
from backtester import Backtester, calculate_advanced_metrics
from strategy import Strategy

from .labs_autotune import PARAM_SPACE
from .utils_json import safe_json_dump


def _to_timestamp(value):
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value
    return pd.to_datetime(value)


def _extract_index_datetime(df: pd.DataFrame):
    if df is None or df.empty:
        return pd.Series(dtype="datetime64[ns]")
    if "datetime" in df.columns:
        return pd.to_datetime(df["datetime"], errors="coerce")
    return pd.to_datetime(df.index, errors="coerce")


def latest_data_timestamp(raw_dfs: dict):
    latest = None
    for df in (raw_dfs or {}).values():
        dates = _extract_index_datetime(df)
        if dates.empty:
            continue
        cur = dates.max()
        if pd.isna(cur):
            continue
        if latest is None or cur > latest:
            latest = cur
    if latest is None:
        raise RuntimeError("No valid datetime found in raw_dfs")
    return latest


def build_split_windows(data_end_ts, train_days=180, oos_days=28, embargo_days=2):
    """
    Inclusive windows anchored to latest data timestamp T.
      OOS:       [T-(oos_days-1), T]
      Embargo:   [oos_start-embargo_days, oos_start-1]
      Training:  [train_end-(train_days-1), train_end], where train_end=oos_start-embargo_days-1
    """
    t = _to_timestamp(data_end_ts).normalize()
    oos_end = t
    oos_start = oos_end - timedelta(days=int(oos_days) - 1)
    train_end = oos_start - timedelta(days=int(embargo_days) + 1)
    train_start = train_end - timedelta(days=int(train_days) - 1)
    embargo_start = oos_start - timedelta(days=int(embargo_days))
    embargo_end = oos_start - timedelta(days=1)
    if train_start >= train_end:
        raise ValueError("Invalid training window")
    if oos_start > oos_end:
        raise ValueError("Invalid OOS window")
    return {
        "data_end": t,
        "train_start": train_start,
        "train_end": train_end,
        "embargo_start": embargo_start,
        "embargo_end": embargo_end,
        "oos_start": oos_start,
        "oos_end": oos_end,
        "train_days": int(train_days),
        "oos_days": int(oos_days),
        "embargo_days": int(embargo_days),
    }


def _normalize_symbol(sym: str):
    s = str(sym or "").upper()
    if "KRW-" in s:
        return s[s.find("KRW-"):]
    if "/KRW" in s:
        base = s.split("/")[0].split("-")[-1]
        return f"KRW-{base}"
    return s


def _allowed_symbol(norm_sym: str):
    if not norm_sym:
        return False
    if "USDT" in norm_sym or "USDC" in norm_sym:
        return False
    # Spec: BTC is observe-only, not trading universe.
    if norm_sym == "KRW-BTC":
        return False
    return True


def select_universe(raw_dfs: dict, universe=None):
    if not raw_dfs:
        return {}

    target = None
    if universe:
        target = set(_normalize_symbol(x) for x in universe)
        target = {x for x in target if x}

    selected = {}
    for sym, df in raw_dfs.items():
        if df is None or df.empty:
            continue
        norm = _normalize_symbol(sym)
        if not _allowed_symbol(norm):
            continue
        if target is not None and norm not in target:
            continue
        selected[sym] = df
    return selected


def _prepare_symbol_dfs(raw_dfs, params):
    strat = Strategy()
    analyzed = {}
    for sym in sorted(raw_dfs.keys()):
        df = raw_dfs[sym]
        try:
            analyzed[sym] = strat.analyze(df, params=params)
        except Exception:
            continue
    return analyzed


def _validate_lookahead_contract(analyzed_map):
    checked = 0
    for df in analyzed_map.values():
        if df is None or df.empty:
            continue
        if "turnover_exec" not in df.columns or "turnover" not in df.columns:
            raise RuntimeError("Lookahead contract broken: turnover_exec missing")
        expected = df["turnover"].shift(1).fillna(0)
        diff = (df["turnover_exec"].fillna(0) - expected).abs().max()
        if pd.notna(diff) and diff > 1e-9:
            raise RuntimeError("Lookahead contract broken: turnover_exec != turnover.shift(1)")
        checked += 1
        if checked >= 3:
            break
    if checked == 0:
        raise RuntimeError("No analyzed symbols available for lookahead validation")


def _compute_mdd(trade_list):
    if not trade_list:
        return 0.0
    mdd_vals = []
    for t in trade_list:
        val = t.get("max_dd", 0.0)
        try:
            mdd_vals.append(float(val))
        except Exception:
            pass
    return min(mdd_vals) if mdd_vals else 0.0


def compute_score(metrics):
    roi = float(metrics.get("roi", 0.0) or 0.0)
    mdd = float(metrics.get("mdd", 0.0) or 0.0)
    cost_drop = float(metrics.get("cost_drop", 0.0) or 0.0)
    return roi - 0.5 * abs(mdd) - 0.2 * cost_drop


def evaluate_params(raw_dfs, params, start_dt, end_dt, include_cost_stress=False):
    analyzed = _prepare_symbol_dfs(raw_dfs, params)
    if not analyzed:
        raise RuntimeError("No analyzed symbols after strategy.analyze")
    _validate_lookahead_contract(analyzed)
    bt = Backtester()
    # Spec: no line-spam output. Backtester uses module-level tqdm when present,
    # so temporarily disable it for this deterministic worker path.
    prev_tqdm = getattr(backtester_module, "tqdm", None)
    backtester_module.tqdm = None
    try:
        base_res = bt.run_portfolio(
            analyzed,
            params,
            start_date=_to_timestamp(start_dt),
            end_date=_to_timestamp(end_dt),
            verbose=False,
            cost_multiplier=1.0,
        )
        stress_res = None
        if bool(include_cost_stress):
            stress_res = bt.run_portfolio(
                analyzed,
                params,
                start_date=_to_timestamp(start_dt),
                end_date=_to_timestamp(end_dt),
                verbose=False,
                cost_multiplier=1.5,
            )
    finally:
        backtester_module.tqdm = prev_tqdm
    metrics = calculate_advanced_metrics(base_res, stress_res)
    metrics["score"] = compute_score(metrics)
    return metrics, base_res


def _candidate_space():
    # deterministic key order
    return {k: list(PARAM_SPACE[k]) for k in sorted(PARAM_SPACE.keys())}


def _emit_progress(progress_cb, pct, stage, message):
    if not callable(progress_cb):
        return
    try:
        progress_cb(float(pct), str(stage), str(message))
    except Exception:
        pass


def generate_candidates(base_params, n_trials, seed=42):
    rng = random.Random(int(seed))
    space = _candidate_space()
    keys = list(space.keys())
    out = [dict(base_params)]
    seen = set()
    seen.add(tuple((k, out[0].get(k)) for k in keys))
    max_unique = 1
    for k in keys:
        max_unique *= max(1, len(space[k]))
    while len(out) < int(n_trials) and len(seen) < max_unique:
        cand = dict(base_params)
        for k in keys:
            cand[k] = rng.choice(space[k])
        key = tuple((k, cand.get(k)) for k in keys)
        if key in seen:
            continue
        seen.add(key)
        out.append(cand)
    return out


def find_best_candidate(
    raw_dfs,
    base_params,
    train_start,
    train_end,
    n_trials=30,
    seed=42,
    progress_cb=None,
):
    cands = generate_candidates(base_params, n_trials=n_trials, seed=seed)
    ranked = []
    total = max(1, len(cands))
    for idx, cand in enumerate(cands):
        metrics, _ = evaluate_params(raw_dfs, cand, train_start, train_end)
        ranked.append(
            {
                "index": idx,
                "params": cand,
                "metrics": metrics,
            }
        )
        if callable(progress_cb):
            try:
                progress_cb(int(idx + 1), int(total), metrics)
            except Exception:
                pass
    ranked.sort(
        key=lambda x: (
            x["metrics"]["score"],
            -abs(x["metrics"]["mdd"]),  # lower abs drawdown is better
            -x["metrics"]["trades"],
            -x["index"],  # deterministic tie order toward earlier candidate
        ),
        reverse=True,
    )
    return ranked[0], ranked


def _week_buckets_from_trades(trades, oos_start):
    buckets = [0.0, 0.0, 0.0, 0.0]
    for t in trades:
        exit_dt = _to_timestamp(t.get("exit_date"))
        if exit_dt is None or pd.isna(exit_dt):
            continue
        diff_days = int((exit_dt.normalize() - oos_start.normalize()).days)
        if diff_days < 0:
            continue
        idx = min(3, max(0, diff_days // 7))
        try:
            buckets[idx] += float(t.get("return", 0.0) or 0.0)
        except Exception:
            continue
    return buckets


def evaluate_candidate_logic(cand_metrics, active_metrics, config):
    """
    Gate -> Score -> Promote judge.
    """
    min_trades = int(config.get("tuning_min_trades", 20))
    mdd_cap = float(config.get("tuning_mdd_cap", -0.15))
    delta_min = float(config.get("tuning_delta_min", 0.005))

    fail_reasons = []
    cand_pos_weeks = int(cand_metrics.get("positive_weeks", 0) or 0)
    cand_trades = int(cand_metrics.get("trades", 0) or 0)
    cand_mdd = float(cand_metrics.get("mdd", 0.0) or 0.0)

    if cand_pos_weeks < 3:
        fail_reasons.append(f"Positive Weeks < 3 ({cand_pos_weeks})")
    if cand_trades < min_trades:
        fail_reasons.append(f"Trades < {min_trades} ({cand_trades})")
    if cand_mdd < mdd_cap:
        fail_reasons.append(f"MDD Exceeded {mdd_cap:.2%} ({cand_mdd:.2%})")

    cand_score = compute_score(cand_metrics)
    if fail_reasons:
        return {
            "decision": "FAIL",
            "reason": ", ".join(fail_reasons),
            "fail_reasons": fail_reasons,
            "score": cand_score,
            "active_score": None,
            "delta": None,
        }

    if active_metrics is None:
        return {
            "decision": "PROMOTE",
            "reason": "First Active Model Initialization",
            "fail_reasons": [],
            "score": cand_score,
            "active_score": 0.0,
            "delta": cand_score,
        }

    active_score = compute_score(active_metrics)
    delta = cand_score - active_score
    if delta >= delta_min:
        return {
            "decision": "PROMOTE",
            "reason": f"Score Improved (+{delta:.6f} >= {delta_min:.6f})",
            "fail_reasons": [],
            "score": cand_score,
            "active_score": active_score,
            "delta": delta,
        }
    return {
        "decision": "KEEP_ACTIVE",
        "reason": f"Delta Insufficient (+{delta:.6f} < {delta_min:.6f})",
        "fail_reasons": [],
        "score": cand_score,
        "active_score": active_score,
        "delta": delta,
    }


def evaluate_oos_gate(
    candidate_metrics,
    candidate_res,
    active_metrics,
    oos_start,
    min_trades=20,
    delta_min=0.01,
    mdd_cap=-0.15,
):
    trades = candidate_res.get("trade_list", []) or []
    weekly = _week_buckets_from_trades(trades, _to_timestamp(oos_start))
    positive_weeks = sum(1 for x in weekly if x > 0)
    worst_week = min(weekly) if weekly else 0.0
    negative_weeks = sum(1 for x in weekly if x < 0)

    cand = dict(candidate_metrics or {})
    cand["positive_weeks"] = int(positive_weeks)
    cand["worst_week"] = float(worst_week)
    cand["negative_weeks"] = int(negative_weeks)
    cand["weekly_pnl"] = list(weekly)

    decision = evaluate_candidate_logic(
        cand_metrics=cand,
        active_metrics=active_metrics,
        config={
            "tuning_min_trades": int(min_trades),
            "tuning_delta_min": float(delta_min),
            "tuning_mdd_cap": float(mdd_cap),
        },
    )

    legacy_reasons = []
    if int(cand.get("positive_weeks", 0) or 0) < 3:
        legacy_reasons.append("weekly_robustness_fail")
    if int(cand.get("trades", 0) or 0) < int(min_trades):
        legacy_reasons.append("min_trades_fail")
    if float(cand.get("mdd", 0.0) or 0.0) < float(mdd_cap):
        legacy_reasons.append("max_dd_fail")

    reasons = []
    if decision["decision"] == "FAIL":
        reasons = legacy_reasons + (decision.get("fail_reasons", []) or [decision.get("reason", "gate_fail")])
    elif decision["decision"] == "KEEP_ACTIVE":
        reasons = ["delta_min_fail", decision.get("reason", "keep_active")]
    # de-dup while preserving order
    reasons = list(dict.fromkeys([str(x) for x in reasons if str(x)]))

    return {
        "pass": decision["decision"] == "PROMOTE",
        "decision": decision["decision"],
        "reason": decision.get("reason"),
        "score": decision.get("score"),
        "active_score": decision.get("active_score"),
        "delta": decision.get("delta"),
        "reasons": reasons,
        "positive_weeks": positive_weeks,
        "weekly_pnl": weekly,
        "worst_week": worst_week,
        "negative_weeks": negative_weeks,
    }


def _hash_strategy_payload(params):
    raw = json.dumps(params, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def run_tuning_cycle(
    raw_dfs,
    base_params,
    model_manager,
    strategy_name="default",
    global_seed=42,
    universe=None,
    train_days=180,
    oos_days=28,
    embargo_days=2,
    n_trials=30,
    oos_min_trades=20,
    delta_min=0.01,
    mdd_cap=-0.15,
    promotion_cooldown_hours=24,
    run_id=None,
    progress_cb=None,
):
    _emit_progress(progress_cb, 1, "init", "Initializing tuning cycle")
    if not raw_dfs:
        raise RuntimeError("raw_dfs is empty")
    scoped_raw = select_universe(raw_dfs, universe=universe)
    if not scoped_raw:
        raise RuntimeError("No symbols left after universe/market filters")
    _emit_progress(progress_cb, 5, "universe_ready", f"Universe prepared ({len(scoped_raw)} symbols)")

    data_end = latest_data_timestamp(scoped_raw)
    windows = build_split_windows(
        data_end_ts=data_end,
        train_days=int(train_days),
        oos_days=int(oos_days),
        embargo_days=int(embargo_days),
    )
    _emit_progress(progress_cb, 10, "split_ready", "Train/OOS windows computed")

    def _on_candidate_progress(done, total, _metrics):
        total = max(1, int(total))
        ratio = min(1.0, max(0.0, float(done) / float(total)))
        pct = 10 + (ratio * 50.0)
        _emit_progress(
            progress_cb,
            pct,
            "train_search",
            f"Training candidates {int(done)}/{int(total)}",
        )

    best, ranked = find_best_candidate(
        scoped_raw,
        base_params=base_params,
        train_start=windows["train_start"],
        train_end=windows["train_end"],
        n_trials=int(n_trials),
        seed=int(global_seed),
        progress_cb=_on_candidate_progress,
    )
    _emit_progress(progress_cb, 62, "candidate_selected", "Best candidate selected")

    cand_oos_metrics, cand_oos_res = evaluate_params(
        scoped_raw,
        best["params"],
        windows["oos_start"],
        windows["oos_end"],
        include_cost_stress=True,
    )
    _emit_progress(progress_cb, 72, "candidate_oos_done", "Candidate OOS evaluation complete")

    active_model_id = model_manager.active_model_id()
    active_params = model_manager.load_active_params() if active_model_id else None
    active_oos_metrics = None
    if active_params is not None:
        active_oos_metrics, _ = evaluate_params(
            scoped_raw,
            active_params,
            windows["oos_start"],
            windows["oos_end"],
            include_cost_stress=True,
        )
    _emit_progress(progress_cb, 82, "active_oos_done", "Active baseline OOS evaluation complete")

    gate = evaluate_oos_gate(
        candidate_metrics=cand_oos_metrics,
        candidate_res=cand_oos_res,
        active_metrics=active_oos_metrics,
        oos_start=windows["oos_start"],
        min_trades=int(oos_min_trades),
        delta_min=float(delta_min),
        mdd_cap=float(mdd_cap),
    )

    # Promotion cooldown to reduce noisy churn between consecutive promotions.
    cooldown_hours = max(0, int(promotion_cooldown_hours or 0))
    if gate.get("pass") and active_model_id and cooldown_hours > 0:
        try:
            active_meta_path = model_manager.active_dir / "model_meta.json"
            if active_meta_path.exists():
                with open(active_meta_path, "r", encoding="utf-8") as f:
                    active_meta = json.load(f) or {}
                created_at = active_meta.get("created_at")
                created_ts = _to_timestamp(created_at)
                if created_ts is not None and not pd.isna(created_ts):
                    elapsed_h = (pd.Timestamp.now() - created_ts).total_seconds() / 3600.0
                    if elapsed_h < cooldown_hours:
                        gate = {
                            **gate,
                            "pass": False,
                            "decision": "KEEP_ACTIVE",
                            "reason": f"Promotion cooldown active ({elapsed_h:.1f}h < {cooldown_hours}h)",
                            "reasons": list(dict.fromkeys((gate.get("reasons") or []) + ["promotion_cooldown_active"])),
                        }
        except Exception:
            pass

    _emit_progress(progress_cb, 88, "gate_evaluated", "Gate decision computed")

    now = datetime.now()
    run_id = run_id or f"run_{now.strftime('%Y%m%d_%H%M%S')}_{int(global_seed)}"
    model_id = run_id

    run_summary = {
        "run_id": run_id,
        "created_at": now.isoformat(),
        "strategy_name": strategy_name,
        "seed": int(global_seed),
        "windows": {k: str(v) if isinstance(v, (pd.Timestamp, datetime)) else v for k, v in windows.items()},
        "policy": {
            "score_formula": "ROI - 0.5 * abs(MDD) - 0.2 * CostDrop",
            "oos_gate": {
                "positive_weeks_min": 3,
                "oos_min_trades": int(oos_min_trades),
                "mdd_cap": float(mdd_cap),
                "delta_min": float(delta_min),
                "promotion_cooldown_hours": int(promotion_cooldown_hours),
            },
            "invariants": {
                "signal_lag_gte_1": True,
                "turnover_lag_gte_1": True,
                "cost_unit_rate": True,
            },
        },
        "candidate": {
            "params": best["params"],
            "train_metrics": best["metrics"],
            "oos_metrics": cand_oos_metrics,
            "weekly_pnl": gate["weekly_pnl"],
            "positive_weeks": gate["positive_weeks"],
        },
        "active_baseline": {
            "model_id": active_model_id,
            "oos_metrics": active_oos_metrics,
        },
        "gate": {
            "pass": bool(gate["pass"]),
            "decision": gate.get("decision"),
            "reasons": gate["reasons"],
            "reason": gate.get("reason"),
            "delta": gate.get("delta"),
        },
        "ranking_top5": [
            {
                "rank": i + 1,
                "score": row["metrics"]["score"],
                "roi": row["metrics"]["roi"],
                "mdd": row["metrics"]["mdd"],
                "trades": row["metrics"]["trades"],
            }
            for i, row in enumerate(ranked[:5])
        ],
    }

    model_meta = {
        "model_id": model_id,
        "created_at": now.isoformat(),
        "strategy_name": strategy_name,
        "strategy_hash": _hash_strategy_payload(best["params"]),
        "seed": int(global_seed),
        "train_range": {
            "start": str(windows["train_start"]),
            "end": str(windows["train_end"]),
        },
        "oos_range": {
            "start": str(windows["oos_start"]),
            "end": str(windows["oos_end"]),
        },
    }

    model_manager.write_staging_artifacts(
        run_id=run_id,
        best_params=best["params"],
        run_summary=run_summary,
        model_meta=model_meta,
    )
    _emit_progress(progress_cb, 94, "artifacts_written", "Staging artifacts written")

    if gate["pass"]:
        model_manager.promote(run_id)
        result_state = "PROMOTED"
    else:
        model_manager.archive_staging(run_id)
        result_state = "ARCHIVED"
    _emit_progress(progress_cb, 100, "done", f"Tuning cycle finished ({result_state})")

    return {
        "run_id": run_id,
        "state": result_state,
        "decision": gate.get("decision"),
        "decision_reason": gate.get("reason"),
        "gate_delta": gate.get("delta"),
        "gate_pass": bool(gate["pass"]),
        "gate_reasons": gate["reasons"],
        "windows": windows,
        "candidate_train_metrics": best["metrics"],
        "candidate_oos_metrics": cand_oos_metrics,
        "active_oos_metrics": active_oos_metrics,
        "weekly_pnl": gate["weekly_pnl"],
        "positive_weeks": gate["positive_weeks"],
        "negative_weeks": gate.get("negative_weeks", 0),
        "worst_week": gate.get("worst_week", 0.0),
        "candidate_params": best["params"],
        "active_baseline_params": active_params,
    }


def write_trainer_state(path, payload):
    safe_json_dump(payload, Path(path))
