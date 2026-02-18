"""Adapter that maps Auto Trading run_summary outputs into backtest scaffold payload format."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from backtest.core.engine_interface import RunRequest


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
                        "ts": row.get("Date") or row.get("date") or "",
                        "side": row.get("Type") or row.get("side") or "",
                        "qty": row.get("Qty") or row.get("qty") or "",
                        "reason": "mapped_from_autotrading",
                    })
                    if i >= 999:
                        break

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

    def adapter(request: RunRequest) -> dict:
        mode = request.mode
        kill_zone_guard_fired = bool(guards_rows)
        kill_zone_loss = -oos_mdd if kill_zone_guard_fired else 0.0
        metrics_total = {
            "oos_pf": oos_pf,
            "oos_mdd": oos_mdd,
            "bull_tcr": 0.0,
            "stress_break": False,
            "oos_cagr_hybrid": total_return_pct / 100.0 if mode == "hybrid" else 0.0,
            "oos_cagr_def": 0.0,
            "bull_return_hybrid": total_return_pct / 100.0 if mode == "hybrid" else 0.0,
            "bull_return_def": 0.0,
            "kill_zone_guard_fired": kill_zone_guard_fired,
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
            },
            "metrics_total": metrics_total,
            "metrics_by_mode": {mode: {"total_return_pct": total_return_pct, "max_dd_pct": max_dd_pct}},
        }

    return adapter
