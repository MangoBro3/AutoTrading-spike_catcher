#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path
from statistics import median
from typing import Dict, List, Tuple

MIN_TOP_WINNERS = 20
COST_EPS = 1e-12


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: List[Dict[str, object]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def resolve_run(base: Path, run_ref: str) -> Path:
    p = Path(run_ref)
    if p.exists():
        return p.resolve()
    cand = base / run_ref
    if cand.exists():
        return cand.resolve()
    raise FileNotFoundError(f"run not found: {run_ref}")


def _f(x, default=0.0) -> float:
    try:
        if x in ("", None):
            return default
        return float(x)
    except Exception:
        return default


def detect_columns(rows: List[Dict[str, str]]) -> set:
    return set(rows[0].keys()) if rows else set()


def _first_nonempty(record: Dict[str, str], keys: List[str], default="") -> str:
    for k in keys:
        v = record.get(k, "")
        if v not in ("", None):
            return v
    return default


def materialize_schema(run_dir: Path) -> Tuple[Dict[str, object], List[str]]:
    fails: List[str] = []
    events_p = run_dir / "events.csv"
    trades_p = run_dir / "final_trades.csv"

    if not events_p.exists():
        fails.append(f"missing file: {events_p}")
    if not trades_p.exists():
        fails.append(f"missing file: {trades_p}")
    if fails:
        return {"run_id": run_dir.name}, fails

    events = read_csv_rows(events_p)
    trades = read_csv_rows(trades_p)

    ev_cols = detect_columns(events)
    tr_cols = detect_columns(trades)

    for c in ["position_id"]:
        if c not in ev_cols:
            fails.append("events.csv missing required column: position_id")
    if "type" not in ev_cols and "event_type" not in ev_cols:
        fails.append("events.csv missing required column: type/event_type")
    if "date" not in ev_cols and "ts" not in ev_cols:
        fails.append("events.csv missing required column: date/ts")
    if "fee" not in ev_cols:
        fails.append("events.csv missing required column: fee")

    required_tr_trade_cols = [
        "trade_id",
        "position_id",
    ]
    for c in required_tr_trade_cols:
        if c not in tr_cols:
            fails.append(f"final_trades.csv missing required column: {c}")
    if "entry_ts" not in tr_cols and "entry_date" not in tr_cols:
        fails.append("final_trades.csv missing required column: entry_ts/entry_date")
    if "exit_ts" not in tr_cols and "exit_date" not in tr_cols:
        fails.append("final_trades.csv missing required column: exit_ts/exit_date")
    if (
        "Realized_pct" not in tr_cols
        and "realized_pct" not in tr_cols
        and "Realized" not in tr_cols
        and "realized" not in tr_cols
        and "return" not in tr_cols
    ):
        fails.append("final_trades.csv missing required column: realized_pct")
    if "MFE" not in tr_cols and "MFE_pct" not in tr_cols:
        fails.append("final_trades.csv missing required column: MFE/MFE_pct")
    if "MAE" not in tr_cols and "MAE_pct" not in tr_cols:
        fails.append("final_trades.csv missing required column: MAE/MAE_pct")
    if "Giveback" not in tr_cols and "Giveback_pct" not in tr_cols:
        fails.append("final_trades.csv missing required column: Giveback/Giveback_pct")

    trade_metrics_rows: List[Dict[str, object]] = []
    realized_missing = 0
    mfe_missing = 0
    mae_missing = 0
    giveback_missing = 0
    fee_missing = 0

    for i, r in enumerate(trades, start=1):
        trade_id = _first_nonempty(r, ["trade_id", "id"], str(i))
        position_id = _first_nonempty(r, ["position_id"])
        entry_ts = _first_nonempty(r, ["entry_ts", "entry_date"])
        exit_ts = _first_nonempty(r, ["exit_ts", "exit_date"])

        realized = _first_nonempty(r, ["Realized_pct", "realized_pct", "return", "Realized", "realized"])
        if realized == "":
            realized_missing += 1
        mfe = _first_nonempty(r, ["MFE", "MFE_pct", "mfe", "mfe_pct"])
        if mfe == "":
            mfe_missing += 1
        mae = _first_nonempty(r, ["MAE", "MAE_pct", "mae", "mae_pct"])
        if mae == "":
            mae_missing += 1
        giveback = _first_nonempty(r, ["Giveback", "Giveback_pct", "giveback", "giveback_pct"])
        if giveback == "":
            if mfe != "" and realized != "":
                try:
                    giveback = str(_f(mfe) - _f(realized))
                except Exception:
                    giveback = ""
            if giveback == "":
                giveback_missing += 1

        fee = _first_nonempty(r, ["fee", "total_fee"])
        if fee == "":
            fee_missing += 1

        trade_metrics_rows.append(
            {
                "trade_id": trade_id,
                "position_id": position_id,
                "entry_ts": entry_ts,
                "exit_ts": exit_ts,
                "realized_pct": realized,
                "MFE": mfe,
                "MAE": mae,
                "Giveback": giveback,
                "mfe_pct": _first_nonempty(r, ["MFE_pct", "mfe_pct", mfe], ""),
                "mae_pct": _first_nonempty(r, ["MAE_pct", "mae_pct", mae], ""),
                "giveback_pct": _first_nonempty(r, ["Giveback_pct", "giveback_pct", giveback], ""),
                "fee": fee,
            }
        )

    if realized_missing > 0:
        fails.append(f"final_trades.csv missing realized_pct coverage in {realized_missing} row(s)")
    if mfe_missing > 0:
        fails.append(f"final_trades.csv missing MFE coverage in {mfe_missing} row(s)")
    if mae_missing > 0:
        fails.append(f"final_trades.csv missing MAE coverage in {mae_missing} row(s)")
    if giveback_missing > 0:
        fails.append(f"final_trades.csv missing Giveback coverage in {giveback_missing} row(s)")
    if fee_missing > 0:
        fails.append(f"final_trades.csv missing fee coverage in {fee_missing} row(s)")

    trade_metrics_p = run_dir / "trade_metrics.csv"
    write_csv(
        trade_metrics_p,
        trade_metrics_rows,
        [
            "trade_id",
            "position_id",
            "entry_ts",
            "exit_ts",
            "realized_pct",
            "MFE",
            "MAE",
            "Giveback",
            "mfe_pct",
            "mae_pct",
            "giveback_pct",
            "fee",
        ],
    )

    if not any((r.get("mfe_pct") not in ("", None)) for r in trade_metrics_rows):
        fails.append("trade_metrics.csv missing populated MFE_pct/MAE_pct/Giveback_pct values")

    fee_vals = []
    slip_vals = []
    slip_source = ""
    for r in events:
        v = r.get("fee", "")
        if v not in ("", None):
            fee_vals.append(_f(v))

        # Prefer explicit slippage metric. If unavailable, fallback to pnl_leg proxy.
        if r.get("slippage_estimate_pct", "") not in ("", None):
            slip_vals.append(abs(_f(r.get("slippage_estimate_pct"))))
            slip_source = "slippage_estimate_pct"
        elif r.get("slippage_pct", "") not in ("", None):
            slip_vals.append(abs(_f(r.get("slippage_pct"))))
            slip_source = "slippage_pct"
        elif r.get("pnl_leg", "") not in ("", None):
            # pnl_leg is usually negative cost contribution; use absolute magnitude as cost proxy.
            slip_vals.append(abs(_f(r.get("pnl_leg"))))
            slip_source = "pnl_leg(abs_proxy)"

    fee_total = sum(fee_vals) if fee_vals else ""
    cost_rows = [
        {
            "fills_count": len(events),
            "fee": fee_total,
            "total_fee": fee_total,
            "slippage_estimate_pct": (sum(slip_vals) / len(slip_vals)) if slip_vals else "",
            "slippage_source": slip_source,
        }
    ]
    cost_metrics_p = run_dir / "cost_metrics.csv"
    write_csv(
        cost_metrics_p,
        cost_rows,
        ["fills_count", "fee", "total_fee", "slippage_estimate_pct", "slippage_source"],
    )

    if fee_total == "":
        fails.append("cost_metrics.csv fee/total_fee not derivable from current logs")

    if cost_rows[0]["slippage_estimate_pct"] == "":
        fails.append("cost_metrics.csv slippage_estimate_pct not derivable from current logs")

    # top-10% winner median (realized_pct)
    realized_vals = sorted([_f(r.get("realized_pct", 0.0)) for r in trade_metrics_rows], reverse=True)
    top_n = max(1, int(len(realized_vals) * 0.1)) if realized_vals else 0
    top_vals = realized_vals[:top_n] if top_n else []
    top10_med = median(top_vals) if top_vals else 0.0

    summary = {
        "run_id": run_dir.name,
        "events_count": len(events),
        "trades_count": len(trades),
        "partial_tp_count": sum(1 for r in events if (r.get("event_type") or r.get("type")) == "Partial_TP"),
        "top10_winner_count": len(top_vals),
        "top10_realized_median_pct": top10_med,
        "trade_metrics_path": str(trade_metrics_p),
        "cost_metrics_path": str(cost_metrics_p),
        "fills_count": len(events),
        "total_fee": cost_rows[0]["total_fee"] if cost_rows else "",
        "slippage_estimate_pct": cost_rows[0]["slippage_estimate_pct"] if cost_rows else "",
        "slippage_source": cost_rows[0]["slippage_source"] if cost_rows else "",
    }
    return summary, fails


def git_commit_hash(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(repo_root), text=True)
        return out.strip()
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--min-top-winners", type=int, default=MIN_TOP_WINNERS)
    parser.add_argument("--out", default="report_exit_ptp_once.json")
    parser.add_argument("--base-dir", default="Auto Trading/autotune_runs")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    base_dir = (repo_root / args.base_dir).resolve()

    baseline_dir = resolve_run(base_dir, args.baseline)
    candidate_dir = resolve_run(base_dir, args.candidate)

    b_sum, b_fail = materialize_schema(baseline_dir)
    c_sum, c_fail = materialize_schema(candidate_dir)

    # AC-oriented basic comparison (best-effort; no hard exception)
    ptp_reduction_ratio = 0.0
    if _f(b_sum.get("partial_tp_count", 0), 0) > 0:
        ptp_reduction_ratio = 1.0 - (_f(c_sum.get("partial_tp_count", 0)) / _f(b_sum.get("partial_tp_count", 1)))

    winner_delta = _f(c_sum.get("top10_realized_median_pct", 0.0)) - _f(b_sum.get("top10_realized_median_pct", 0.0))

    cost_axes = 0
    if _f(c_sum.get("fills_count", 0)) < _f(b_sum.get("fills_count", 0)) - COST_EPS:
        cost_axes += 1
    if b_sum.get("total_fee", "") not in ("", None) and c_sum.get("total_fee", "") not in ("", None):
        if _f(c_sum.get("total_fee", 0)) < _f(b_sum.get("total_fee", 0)) - COST_EPS:
            cost_axes += 1
    if b_sum.get("slippage_estimate_pct", "") not in ("", None) and c_sum.get("slippage_estimate_pct", "") not in ("", None):
        if _f(c_sum.get("slippage_estimate_pct", 0)) < _f(b_sum.get("slippage_estimate_pct", 0)) - COST_EPS:
            cost_axes += 1

    min_top_winners_observed = int(min(_f(b_sum.get("top10_winner_count", 0), 0), _f(c_sum.get("top10_winner_count", 0), 0)))
    winner_sample_shortage = max(0, args.min_top_winners - min_top_winners_observed)
    winner_sample_ok = winner_sample_shortage == 0

    run_summary_source_hash_baseline = sha256_file(baseline_dir / "run_summary.json")
    run_summary_source_hash_candidate = sha256_file(candidate_dir / "run_summary.json")
    config_hash_baseline = sha256_file(baseline_dir / "run_config.json")
    config_hash_candidate = sha256_file(candidate_dir / "run_config.json")

    derived_gate_failures: List[str] = []
    if ptp_reduction_ratio < 0.5:
        derived_gate_failures.append("partial_tp_reduction_below_50pct")
    if not winner_sample_ok:
        derived_gate_failures.append(f"top10_winner_sample_lt_min({min_top_winners_observed}<{args.min_top_winners})")
    elif winner_delta < 3.0:
        derived_gate_failures.append("top10_realized_median_delta_below_3.0pp")
    if cost_axes < 2:
        derived_gate_failures.append("cost_reduction_axes_lt_2")
    if not run_summary_source_hash_baseline or not run_summary_source_hash_candidate:
        derived_gate_failures.append("run_summary_source_hash_empty")
    if not config_hash_baseline or not config_hash_candidate:
        derived_gate_failures.append("config_hash_empty")

    all_fail = b_fail + c_fail + derived_gate_failures

    report = {
        "run_summary_source_hash": {
            "baseline": run_summary_source_hash_baseline,
            "candidate": run_summary_source_hash_candidate,
        },
        "code_commit_hash": git_commit_hash(repo_root),
        "config_hash": {
            "baseline": config_hash_baseline,
            "candidate": config_hash_candidate,
        },
        "baseline_run_id": baseline_dir.name,
        "candidate_run_id": candidate_dir.name,
        "metrics_summary": {
            "baseline": b_sum,
            "candidate": c_sum,
            "min_top_winners": args.min_top_winners,
            "derived": {
                "partial_tp_reduction_ratio": ptp_reduction_ratio,
                "winner_sample_ok": winner_sample_ok,
                "winner_sample_shortage": winner_sample_shortage,
                "top10_realized_median_delta_pctp": winner_delta,
                "cost_reduction_axes": cost_axes,
            },
        },
        "cost_summary": {
            "baseline_cost_metrics": str(baseline_dir / "cost_metrics.csv"),
            "candidate_cost_metrics": str(candidate_dir / "cost_metrics.csv"),
        },
        "gate_summary": {
            "status": "PASS" if not all_fail else "FAIL",
            "baseline_fail_reasons": b_fail,
            "candidate_fail_reasons": c_fail,
            "derived_fail_reasons": derived_gate_failures,
        },
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
