"""Adapter that maps Auto Trading run_summary outputs into backtest scaffold payload format."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

from backtest.core.engine_interface import RunRequest

logger = logging.getLogger(__name__)


class AdapterSchemaError(RuntimeError):
    """Raised when run_summary schema/artifact contract is invalid for adapter consumption."""


def _to_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def _to_percent_points(v: float) -> float:
    """Normalize decimal-ratio or already-percent values to percent points.

    Examples:
      0.152 -> 15.2
      -0.18 -> -18.0
      47.1 -> 47.1
    """
    if -1.5 <= v <= 1.5:
        return v * 100.0
    return v


def _win_rate_hint(v) -> float | None:
    try:
        x = float(v)
    except Exception:
        return None
    if x < 0:
        return None
    if x > 1.0:
        x = x / 100.0
    return max(0.0, min(1.0, x))


def _extract_return_drawdown_pct(raw: dict) -> tuple[float, float, str]:
    """Extract total return/max drawdown in percent points across known schemas."""
    metrics = raw.get("metrics", {}) or {}

    if ("total_return" in metrics) or ("max_dd" in metrics):
        total_return_pct = _to_float(metrics.get("total_return", 0.0), 0.0)
        max_dd_pct = _to_float(metrics.get("max_dd", 0.0), 0.0)
        return total_return_pct, max_dd_pct, "metrics.total_return,max_dd"

    # Legacy archive schema
    oos_metrics = ((raw.get("candidate", {}) or {}).get("oos_metrics", {}) or {})
    if ("roi" in oos_metrics) or ("mdd" in oos_metrics):
        total_return_pct = _to_percent_points(_to_float(oos_metrics.get("roi", 0.0), 0.0))
        max_dd_pct = _to_percent_points(_to_float(oos_metrics.get("mdd", 0.0), 0.0))
        return total_return_pct, max_dd_pct, "candidate.oos_metrics.roi,mdd"

    return 0.0, 0.0, "missing_return_drawdown_fields"


def _latest_run_summary(base_dir: Path) -> Path:
    runs_dir = base_dir / "Auto Trading" / "results" / "runs"
    files = sorted(runs_dir.glob("*/run_summary.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No run_summary.json found under {runs_dir}")
    return files[0]


def _resolve_artifact_path(base: Path, artifact_rel_or_abs: str | Path) -> Path:
    artifact_path = Path(str(artifact_rel_or_abs).replace("\\", "/"))
    return base / "Auto Trading" / artifact_path if not artifact_path.is_absolute() else artifact_path


def _validate_backtest_schema_or_raise(raw: dict, base: Path) -> tuple[Path, str]:
    """Minimal strict schema guard for backtest summaries.

    Contract (hard): run_type=backtest MUST provide files.guards_csv and the file must exist.
    """

    if str(raw.get("run_type", "")).lower() != "backtest":
        return Path(), "not_backtest_mode"

    files_meta = raw.get("files", {}) or {}
    guards_rel = files_meta.get("guards_csv")
    if not guards_rel:
        raise AdapterSchemaError("BACKTEST_SCHEMA_INVALID: missing required files.guards_csv")

    guards_path = _resolve_artifact_path(base, guards_rel)
    if not guards_path.exists():
        raise AdapterSchemaError(f"BACKTEST_SCHEMA_INVALID: guards_csv_path_not_found:{guards_path}")

    if guards_path.stat().st_size <= 0:
        raise AdapterSchemaError(f"BACKTEST_SCHEMA_INVALID: guards_csv_empty:{guards_path}")

    return guards_path, "backtest_schema_valid"


def _read_guards_rows(path: Path, reason: str = "mapped_from_autotrading") -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            # Normalized guard view used by report_writer/evaluator.
            ts = row.get("ts") or row.get("Date") or row.get("date") or row.get("dt") or ""
            guard_name = row.get("guard") or row.get("name") or "kill_zone"
            value = row.get("value")
            if value is None:
                # Preserve real artifact signal columns when present
                if "intraday" in row:
                    value = row.get("intraday")
                elif "action" in row:
                    value = row.get("action")
                else:
                    value = "fired"
            rows.append({"ts": ts, "guard": guard_name, "value": value, "reason": reason})
            if i >= 999:
                break
    return rows


def _find_fallback_guards_path(base: Path, run_id: str, summary_file: Path) -> tuple[Path | None, str]:
    # 1) same run folder artifact (preferred)
    same_run = summary_file.parent / "guards.csv"
    if same_run.exists() and same_run.stat().st_size > 0:
        return same_run, "run_dir_guards_csv"

    # 2) previously generated backtest artifacts (real outputs only)
    candidates = sorted(base.glob(f"backtest/out*/{run_id}/guards.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in candidates:
        try:
            if p.exists() and p.stat().st_size > 0:
                return p, "backtest_artifact_guards_csv"
        except OSError:
            continue

    return None, "guards_csv_missing_in_run_summary"


def _find_fallback_trades_path(base: Path, run_id: str, summary_file: Path) -> tuple[Path | None, str]:
    same_run = summary_file.parent / "trades.csv"
    if same_run.exists() and same_run.stat().st_size > 0:
        return same_run, "run_dir_trades_csv"

    candidates = sorted(base.glob(f"backtest/out*/{run_id}/trades.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in candidates:
        try:
            if p.exists() and p.stat().st_size > 0:
                return p, "backtest_artifact_trades_csv"
        except OSError:
            continue

    # Legacy/backtest-run summaries may not be mapped per run_id, but Auto Trading
    # run artifacts still provide deterministic realized trades for bull_tcr mapping.
    run_candidates = sorted(
        (base / "Auto Trading" / "results" / "runs").glob("*/trades.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in run_candidates:
        try:
            if p.exists() and p.stat().st_size > 0:
                return p, "autotrading_runs_trades_csv"
        except OSError:
            continue

    return None, "trades_csv_missing_in_run_summary"


def _compute_bull_tcr(
    trades_rows: list[dict],
    total_return_pct: float,
    max_dd_pct: float,
    win_rate_hint: float | None = None,
) -> tuple[float, str]:
    """Map bull_tcr from run_summary/trades in a deterministic way.

    Priority:
      1) Realized round-trip win ratio from trades.csv (BUY->SELL FIFO matching)
      2) win_rate_hint(raw.candidate.oos_metrics.win_rate)
      3) Fallback proxy from return-vs-drawdown profile
    """

    buys: list[list[float]] = []  # [remaining_qty, buy_price]
    win_count = 0
    close_count = 0

    for row in trades_rows:
        side = str(row.get("side", "")).upper()
        qty = _to_float(row.get("qty", 0.0), 0.0)
        price = _to_float(row.get("price", 0.0), 0.0)
        if qty <= 0 or price <= 0:
            continue

        if side in {"BUY", "B"}:
            buys.append([qty, price])
            continue

        if side in {"SELL", "S"}:
            remaining = qty
            while remaining > 0 and buys:
                open_qty, open_px = buys[0]
                matched = min(remaining, open_qty)
                remaining -= matched
                open_qty -= matched
                close_count += 1
                if price > open_px:
                    win_count += 1
                if open_qty <= 1e-12:
                    buys.pop(0)
                else:
                    buys[0][0] = open_qty

    if close_count > 0:
        return max(0.0, min(1.0, win_count / close_count)), "trades_roundtrip_win_ratio"

    if win_rate_hint is not None:
        return max(0.0, min(1.0, win_rate_hint)), "win_rate_hint_candidate_oos_metrics"

    # Fallback: positive return and shallow DD imply stronger trend-capture behavior.
    ret = max(0.0, total_return_pct)
    dd = abs(min(0.0, max_dd_pct))
    proxy = ret / (ret + (dd * 2.0) + 1e-9)
    return max(0.0, min(1.0, proxy)), "proxy_return_drawdown"


def _compute_oos_pf_from_trades(trades_rows: list[dict]) -> tuple[float | None, str]:
    """Compute profit factor from realized long-only round trips (BUY->SELL FIFO)."""
    buys: list[list[float]] = []  # [remaining_qty, buy_price]
    gross_profit = 0.0
    gross_loss = 0.0
    close_count = 0

    for row in trades_rows:
        side = str(row.get("side", "")).upper()
        qty = _to_float(row.get("qty", 0.0), 0.0)
        price = _to_float(row.get("price", 0.0), 0.0)
        if qty <= 0 or price <= 0:
            continue

        if side in {"BUY", "B"}:
            buys.append([qty, price])
            continue

        if side in {"SELL", "S"}:
            remaining = qty
            while remaining > 0 and buys:
                open_qty, open_px = buys[0]
                matched = min(remaining, open_qty)
                remaining -= matched
                open_qty -= matched
                pnl = (price - open_px) * matched
                close_count += 1
                if pnl >= 0:
                    gross_profit += pnl
                else:
                    gross_loss += abs(pnl)
                if open_qty <= 1e-12:
                    buys.pop(0)
                else:
                    buys[0][0] = open_qty

    if close_count <= 0:
        return None, "pf_unavailable_no_closed_trades"
    if gross_loss <= 1e-12:
        return max(1.0, gross_profit), "pf_from_trades_no_losses"
    return gross_profit / gross_loss, "pf_from_trades"


def build_adapter(base_dir: str | Path = ".", run_summary_path: str | None = None):
    """Build adapter with optional per-run run_summary mapping.

    Mapping priority per run_id:
      1) backtest/config/autotrading_run_summary_map.json (explicit)
      2) --run-summary default path (if provided)
      3) latest Auto Trading run_summary.json (legacy fallback)

    If explicit map exists but a run_id is missing, adapter returns explicit
    unmapped status with neutral-zero metrics instead of silently reusing
    another run summary.
    """

    base = Path(base_dir)
    explicit_map_path = base / "backtest" / "config" / "autotrading_run_summary_map.json"
    run_summary_map: dict[str, Path] = {}
    run_summary_map_status = "run_map_not_found"

    if explicit_map_path.exists():
        try:
            raw_map = json.loads(explicit_map_path.read_text(encoding="utf-8"))
            if isinstance(raw_map, dict):
                for k, v in raw_map.items():
                    if not isinstance(k, str) or not v:
                        continue
                    resolved = _resolve_artifact_path(base, str(v))
                    run_summary_map[k] = resolved
                run_summary_map_status = "run_map_loaded" if run_summary_map else "run_map_loaded_empty"
            else:
                run_summary_map_status = "run_map_invalid_type"
        except Exception as e:
            run_summary_map_status = f"run_map_read_error:{e.__class__.__name__}"
            logger.warning("[autotrading_adapter] failed to load run map: %s (%s)", explicit_map_path, e)

    default_summary_file: Path | None = None
    default_summary_status = "default_unset"
    if run_summary_path:
        default_summary_file = Path(run_summary_path)
        default_summary_status = "default_from_cli"
    else:
        try:
            default_summary_file = _latest_run_summary(base)
            default_summary_status = "default_latest"
        except FileNotFoundError:
            default_summary_status = "default_latest_missing"

    # Cache parsed summary context by source path.
    summary_ctx_cache: dict[str, dict] = {}

    def _build_summary_ctx(summary_file: Path) -> dict:
        cache_key = str(summary_file)
        if cache_key in summary_ctx_cache:
            return summary_ctx_cache[cache_key]

        raw = json.loads(summary_file.read_text(encoding="utf-8"))
        schema_guards_path, schema_status = _validate_backtest_schema_or_raise(raw, base)
        total_return_pct, max_dd_pct, returns_mapping_source = _extract_return_drawdown_pct(raw)
        win_rate_hint = _win_rate_hint(
            (((raw.get("candidate", {}) or {}).get("oos_metrics", {}) or {}).get("win_rate"))
        )

        oos_pf = 1.0 + max(0.0, total_return_pct) / 100.0
        oos_pf_source = "pf_from_return"
        oos_mdd = abs(max_dd_pct) / 100.0

        trades_rows: list[dict] = []
        files_meta = raw.get("files", {}) or {}
        trades_rel = files_meta.get("trades_csv")
        if trades_rel:
            trades_path = _resolve_artifact_path(base, trades_rel)
            if trades_path.exists():
                with trades_path.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for i, row in enumerate(reader):
                        trades_rows.append({
                            "ts": row.get("Date") or row.get("date") or row.get("dt") or "",
                            "side": row.get("Type") or row.get("side") or "",
                            "qty": row.get("Qty") or row.get("qty") or row.get("size") or "",
                            "price": row.get("price") or row.get("Price") or "",
                            "reason": "mapped_from_autotrading",
                        })
                        if i >= 999:
                            break

        trades_cache: dict[str, list[dict]] = {}

        def _trades_for_run(run_id: str) -> list[dict]:
            if run_id in trades_cache:
                return trades_cache[run_id]

            rows = list(trades_rows)
            if not rows:
                fallback_path, _ = _find_fallback_trades_path(base, run_id, summary_file)
                if fallback_path:
                    try:
                        with fallback_path.open("r", encoding="utf-8", newline="") as f:
                            reader = csv.DictReader(f)
                            for i, row in enumerate(reader):
                                rows.append({
                                    "ts": row.get("Date") or row.get("date") or row.get("dt") or "",
                                    "side": row.get("Type") or row.get("side") or "",
                                    "qty": row.get("Qty") or row.get("qty") or row.get("size") or "",
                                    "price": row.get("price") or row.get("Price") or "",
                                    "reason": f"mapped_from_artifact:{fallback_path}",
                                })
                                if i >= 999:
                                    break
                    except Exception:
                        rows = list(trades_rows)

            trades_cache[run_id] = rows
            return trades_cache[run_id]

        guards_rows_default: list[dict] = []
        guard_mapping_status_default = schema_status
        guards_rel = files_meta.get("guards_csv")
        if schema_status == "backtest_schema_valid":
            guards_rows_default = _read_guards_rows(schema_guards_path)
            guard_mapping_status_default = "guards_csv_loaded" if guards_rows_default else "guards_csv_loaded_but_empty"
        elif guards_rel:
            guards_path = _resolve_artifact_path(base, guards_rel)
            if guards_path.exists():
                guards_rows_default = _read_guards_rows(guards_path)
                guard_mapping_status_default = "guards_csv_loaded" if guards_rows_default else "guards_csv_loaded_but_empty"
            else:
                guard_mapping_status_default = f"guards_csv_path_not_found:{guards_path}"
                logger.warning("[autotrading_adapter] guards_csv path not found: %s", guards_path)
        else:
            guard_mapping_status_default = "guards_csv_missing_in_run_summary"

        guards_cache: dict[str, tuple[list[dict], str]] = {}

        def _guards_for_run(run_id: str) -> tuple[list[dict], str]:
            if run_id in guards_cache:
                return guards_cache[run_id]

            rows = list(guards_rows_default)
            status = guard_mapping_status_default
            if not rows:
                fallback_path, fallback_status = _find_fallback_guards_path(base, run_id, summary_file)
                status = fallback_status
                if fallback_path:
                    try:
                        rows = _read_guards_rows(fallback_path, reason=f"mapped_from_artifact:{fallback_path}")
                        if rows:
                            status = f"{fallback_status}_loaded"
                    except Exception as e:
                        status = f"{fallback_status}_read_error:{e.__class__.__name__}"
                        logger.warning("[autotrading_adapter] failed to read fallback guards_csv: %s (%s)", fallback_path, e)

            if not rows:
                logger.info("[autotrading_adapter] kill_zone guard not fired for run_id=%s; cause=%s", run_id, status)

            guards_cache[run_id] = (rows, status)
            return guards_cache[run_id]

        ctx = {
            "summary_file": summary_file,
            "raw": raw,
            "schema_status": schema_status,
            "returns_mapping_source": returns_mapping_source,
            "oos_pf": oos_pf,
            "oos_pf_source": oos_pf_source,
            "oos_mdd": oos_mdd,
            "total_return_pct": total_return_pct,
            "max_dd_pct": max_dd_pct,
            "win_rate_hint": win_rate_hint,
            "trades_for_run": _trades_for_run,
            "guards_for_run": _guards_for_run,
        }
        summary_ctx_cache[cache_key] = ctx
        return ctx

    def _resolve_summary_for_run(run_id: str) -> tuple[dict | None, str]:
        if run_summary_map:
            mapped = run_summary_map.get(run_id)
            if not mapped:
                return None, f"run_id_unmapped:{run_id}|{run_summary_map_status}"
            if not mapped.exists():
                return None, f"mapped_summary_missing:{mapped}"
            return _build_summary_ctx(mapped), f"mapped_by_run_id:{run_id}"

        # Conventional per-run path (opt-in without extra config)
        conventional = base / "Auto Trading" / "results" / "runs" / run_id / "run_summary.json"
        if conventional.exists():
            return _build_summary_ctx(conventional), f"mapped_by_convention:{run_id}"

        if default_summary_file is not None:
            if not default_summary_file.exists():
                return None, f"{default_summary_status}_missing:{default_summary_file}"

            return _build_summary_ctx(default_summary_file), f"run_id_path_missing:{run_id}|{default_summary_status}_reused"

        return None, f"run_id_path_missing:{run_id}|summary_unavailable"

    def adapter(request: RunRequest) -> dict:
        mode = request.mode
        ctx, input_mapping_status = _resolve_summary_for_run(request.run_id)

        if ctx is None:
            guards_rows: list[dict] = []
            guard_mapping_status = "guards_unavailable_no_summary"
            oos_pf = 0.0
            oos_mdd = 0.0
            bull_tcr = 0.0
            bull_tcr_source = "unavailable_no_summary"
            oos_pf_source = "unavailable_no_summary"
            total_return_pct = 0.0
            max_dd_pct = 0.0
            trades_rows: list[dict] = []
            mapped_from = None
            raw_created_at = ""
            schema_status = "summary_unavailable"
            returns_mapping_source = "summary_unavailable"
        else:
            guards_rows, guard_mapping_status = ctx["guards_for_run"](request.run_id)
            trades_rows = ctx["trades_for_run"](request.run_id)
            oos_pf = ctx["oos_pf"]
            oos_pf_source = ctx.get("oos_pf_source", "pf_from_return")
            oos_pf_run, oos_pf_run_source = _compute_oos_pf_from_trades(trades_rows)
            if oos_pf_run is not None:
                oos_pf = oos_pf_run
                oos_pf_source = oos_pf_run_source
            oos_mdd = ctx["oos_mdd"]
            total_return_pct = ctx["total_return_pct"]
            max_dd_pct = ctx["max_dd_pct"]
            bull_tcr, bull_tcr_source = _compute_bull_tcr(
                trades_rows,
                total_return_pct,
                max_dd_pct,
                ctx.get("win_rate_hint"),
            )
            mapped_from = str(ctx["summary_file"])
            raw_created_at = ctx["raw"].get("created_at", "")
            schema_status = ctx["schema_status"]
            returns_mapping_source = ctx["returns_mapping_source"]

        kill_zone_guard_fired = bool(guards_rows)
        kill_zone_loss = -oos_mdd if kill_zone_guard_fired else 0.0
        mode_return = total_return_pct / 100.0
        metrics_total = {
            "oos_pf": oos_pf,
            "oos_mdd": oos_mdd,
            "bull_tcr": bull_tcr,
            "stress_break": False,
            "oos_cagr_hybrid": mode_return if mode == "hybrid" else 0.0,
            "oos_cagr_def": mode_return if mode == "always_def" else 0.0,
            "bull_return_hybrid": mode_return if mode == "hybrid" else 0.0,
            "bull_return_def": mode_return if mode == "always_def" else 0.0,
            "kill_zone_guard_fired": kill_zone_guard_fired,
            "kill_zone_guard_reason": guard_mapping_status,
            "kill_zone_loss_hybrid": kill_zone_loss,
            "kill_zone_loss_agg": kill_zone_loss,
        }

        return {
            "daily_state": [
                {
                    "date": raw_created_at,
                    "mode": mode,
                    "x_cap": "",
                    "x_cd": "",
                    "x_ce": "",
                    "w_ce": "",
                    "scout": "",
                    "reason": "mapped_from_run_summary" if ctx is not None else "summary_unavailable",
                }
            ],
            "switches": [],
            "guards": guards_rows,
            "trades": trades_rows,
            "summary": {
                "run_id": request.run_id,
                "source": "auto_trading.run_summary" if ctx is not None else "auto_trading.run_summary.unavailable",
                "mapped_from": mapped_from,
                "mode": mode,
                "bull_tcr_source": bull_tcr_source,
                "oos_pf_source": oos_pf_source,
                "returns_mapping_source": returns_mapping_source,
                "schema_guard_status": schema_status,
                "guard_mapping_status": guard_mapping_status,
                "input_mapping_status": input_mapping_status,
                "run_summary_map_status": run_summary_map_status,
            },
            "metrics_total": metrics_total,
            "metrics_by_mode": {mode: {"total_return_pct": total_return_pct, "max_dd_pct": max_dd_pct}},
        }

    return adapter
