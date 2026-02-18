"""Adapter that maps Auto Trading run_summary outputs into backtest scaffold payload format."""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

from backtest.core.engine_interface import RunRequest

logger = logging.getLogger(__name__)


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

    total_return_pct = _to_float(metrics.get("total_return", 0.0), 0.0)
    max_dd_pct = _to_float(metrics.get("max_dd", 0.0), 0.0)

    # Convert to evaluator-friendly shape (approximation until full engine integration)
    oos_pf = 1.0 + max(0.0, total_return_pct) / 100.0
    oos_mdd = abs(max_dd_pct) / 100.0

    trades_rows = []
    guards_rows = []
    files_meta = raw.get("files", {}) or {}

    trades_rel = files_meta.get("trades_csv")
    if trades_rel:
        trades_csv = Path(str(trades_rel).replace("\\", "/"))
        trades_path = base / "Auto Trading" / trades_csv if not trades_csv.is_absolute() else trades_csv
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

    guard_mapping_status = "unknown"
    guards_rel = files_meta.get("guards_csv")
    if guards_rel:
        guards_csv = Path(str(guards_rel).replace("\\", "/"))
        guards_path = base / "Auto Trading" / guards_csv if not guards_csv.is_absolute() else guards_csv
        if guards_path.exists():
            with guards_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    guards_rows.append({
                        "ts": row.get("ts") or row.get("Date") or row.get("date") or "",
                        "guard": row.get("guard") or row.get("name") or "kill_zone",
                        "value": row.get("value") or row.get("action") or "fired",
                        "reason": "mapped_from_autotrading",
                    })
                    if i >= 999:
                        break
            guard_mapping_status = "guards_csv_loaded" if guards_rows else "guards_csv_loaded_but_empty"
        else:
            guard_mapping_status = f"guards_csv_path_not_found:{guards_path}"
            logger.warning("[autotrading_adapter] guards_csv path not found: %s", guards_path)
    else:
        guard_mapping_status = "guards_csv_missing_in_run_summary"

    bull_tcr, bull_tcr_source = _compute_bull_tcr(trades_rows, total_return_pct, max_dd_pct)

    if not guards_rows:
        logger.info("[autotrading_adapter] kill_zone guard not fired; cause=%s", guard_mapping_status)

    def adapter(request: RunRequest) -> dict:
        mode = request.mode
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
            "kill_zone_guard_reason": "mapped_guard_rows_present" if kill_zone_guard_fired else guard_mapping_status,
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
                "guard_mapping_status": guard_mapping_status,
            },
            "metrics_total": metrics_total,
            "metrics_by_mode": {mode: {"total_return_pct": total_return_pct, "max_dd_pct": max_dd_pct}},
        }

    return adapter
