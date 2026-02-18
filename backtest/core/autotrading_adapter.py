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


def _compute_bull_tcr(trades_rows: list[dict], total_return_pct: float, max_dd_pct: float) -> tuple[float, str]:
    """Map bull_tcr from run_summary/trades in a deterministic way.

    Priority:
      1) Realized round-trip win ratio from trades.csv (BUY->SELL FIFO matching)
      2) Fallback proxy from return-vs-drawdown profile
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

    # Fallback: positive return and shallow DD imply stronger trend-capture behavior.
    ret = max(0.0, total_return_pct)
    dd = abs(min(0.0, max_dd_pct))
    proxy = ret / (ret + (dd * 2.0) + 1e-9)
    return max(0.0, min(1.0, proxy)), "proxy_return_drawdown"


def build_adapter(base_dir: str | Path = ".", run_summary_path: str | None = None):
    base = Path(base_dir)

    if run_summary_path:
        summary_file = Path(run_summary_path)
    else:
        summary_file = _latest_run_summary(base)

    raw = json.loads(summary_file.read_text(encoding="utf-8"))
    metrics = raw.get("metrics", {})

    schema_guards_path, schema_status = _validate_backtest_schema_or_raise(raw, base)

    total_return_pct = _to_float(metrics.get("total_return", 0.0), 0.0)
    max_dd_pct = _to_float(metrics.get("max_dd", 0.0), 0.0)

    # Convert to evaluator-friendly shape (approximation until full engine integration)
    oos_pf = 1.0 + max(0.0, total_return_pct) / 100.0
    oos_mdd = abs(max_dd_pct) / 100.0

    trades_rows = []
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

    guards_rows_default: list[dict] = []
    guard_mapping_status_default = schema_status
    guards_rel = files_meta.get("guards_csv")

    # Backtest schema-valid case: required guards path already resolved/validated.
    if schema_status == "backtest_schema_valid":
        guards_rows_default = _read_guards_rows(schema_guards_path)
        guard_mapping_status_default = "guards_csv_loaded" if guards_rows_default else "guards_csv_loaded_but_empty"

    # Non-backtest (or legacy) permissive branch.
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

    bull_tcr, bull_tcr_source = _compute_bull_tcr(trades_rows, total_return_pct, max_dd_pct)

    # per-run fallback cache (run_summary may not contain guards_csv)
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

    def adapter(request: RunRequest) -> dict:
        mode = request.mode
        guards_rows, guard_mapping_status = _guards_for_run(request.run_id)
        kill_zone_guard_fired = bool(guards_rows)
        kill_zone_loss = -oos_mdd if kill_zone_guard_fired else 0.0
        metrics_total = {
            "oos_pf": oos_pf,
            "oos_mdd": oos_mdd,
            "bull_tcr": bull_tcr,
            "stress_break": False,
            "oos_cagr_hybrid": total_return_pct / 100.0 if mode == "hybrid" else 0.0,
            "oos_cagr_def": 0.0,
            "bull_return_hybrid": total_return_pct / 100.0 if mode == "hybrid" else 0.0,
            "bull_return_def": 0.0,
            "kill_zone_guard_fired": kill_zone_guard_fired,
            "kill_zone_guard_reason": guard_mapping_status if kill_zone_guard_fired else guard_mapping_status,
            "kill_zone_loss_hybrid": kill_zone_loss,
            "kill_zone_loss_agg": kill_zone_loss,
        }

        return {
            "daily_state": [
                {
                    "date": raw.get("created_at", ""),
                    "mode": mode,
                    "x_cap": "",
                    "x_cd": "",
                    "x_ce": "",
                    "w_ce": "",
                    "scout": "",
                    "reason": "mapped_from_run_summary",
                }
            ],
            "switches": [],
            "guards": guards_rows,
            "trades": trades_rows,
            "summary": {
                "run_id": request.run_id,
                "source": "auto_trading.run_summary",
                "mapped_from": str(summary_file),
                "mode": mode,
                "bull_tcr_source": bull_tcr_source,
                "schema_guard_status": schema_status,
                "guard_mapping_status": guard_mapping_status,
            },
            "metrics_total": metrics_total,
            "metrics_by_mode": {mode: {"total_return_pct": total_return_pct, "max_dd_pct": max_dd_pct}},
        }

    return adapter
