"""Backtest runner scaffold.

Current behavior:
- loads run matrix/splits
- emits placeholder artifacts per run
- evaluates GO/NO_GO for quick wiring test

Replace `simulate_run` with real engine/data integration.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from backtest.config.run_matrix import get_runs
from backtest.core.engine_interface import RunRequest, default_mock_adapter
from backtest.core.evaluator import evaluate_go_no_go
from backtest.core.report_writer import write_reports
from backtest.core.splits_loader import load_splits


def simulate_run(run: dict, split: dict) -> dict:
    """Placeholder metrics. Swap with real backtest output."""
    mode = run.get("mode", "hybrid")
    is_hybrid = mode == "hybrid"

    metrics_total = {
        "oos_pf": 1.25 if is_hybrid else 1.05,
        "oos_mdd": 0.18 if is_hybrid else 0.22,
        "bull_tcr": 0.92 if is_hybrid else 0.78,
        "stress_break": False,
        "oos_cagr_hybrid": 0.21 if is_hybrid else 0.0,
        "oos_cagr_def": 0.16,
        "bull_return_hybrid": 1.35 if is_hybrid else 0.0,
        "bull_return_def": 1.00,
        "kill_zone_guard_fired": is_hybrid,
        "kill_zone_loss_hybrid": -0.09 if is_hybrid else -0.14,
        "kill_zone_loss_agg": -0.17,
    }

    metrics_by_mode = {
        mode: {
            "split": split,
            "fee_mult": run.get("fee_mult", 1.0),
            "slippage_mult": run.get("slippage_mult", 1.0),
        }
    }

    summary = {
        "run_id": run["run_id"],
        "family": run["family"],
        "mode": mode,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }

    payload = {
        "daily_state": [
            {
                "date": split.get("from", "2020-01-01"),
                "mode": "AGG" if is_hybrid else "DEF",
                "x_cap": 0.8 if is_hybrid else 0.5,
                "x_cd": 0.5,
                "x_ce": 0.3 if is_hybrid else 0.0,
                "w_ce": 0.375 if is_hybrid else 0.0,
                "scout": bool(run.get("scout", False)),
                "reason": "scaffold",
            }
        ],
        "switches": [
            {
                "ts": datetime.utcnow().isoformat() + "Z",
                "from": "DEF",
                "to": "AGG" if is_hybrid else "DEF",
                "reason": "scaffold",
            }
        ],
        "guards": [],
        "trades": [],
        "summary": summary,
        "metrics_total": metrics_total,
        "metrics_by_mode": metrics_by_mode,
    }

    return payload


def run_all(out_root: str | Path = "backtest/out", adapter=default_mock_adapter) -> list[dict]:
    out_root = Path(out_root)
    runs = get_runs()
    splits_doc = load_splits()

    split_map = splits_doc.get("splits", {})
    results = []

    for run in runs:
        run_id = run["run_id"]
        split_key = run["split"]
        split = split_map.get(split_key, {"name": split_key})
        if split_key == "kill_zones_5m":
            split = {"timeframe": "5m", "zones": splits_doc.get("kill_zones_5m", [])}

        request = RunRequest(run_id=run_id, mode=run.get("mode", "hybrid"), split=split, options=run)
        payload = adapter(request)
        out_dir = out_root / run_id
        files = write_reports(out_dir, payload)

        ev = evaluate_go_no_go(payload["metrics_total"], payload["metrics_by_mode"])
        results.append({"run_id": run_id, "verdict": ev.verdict, "checks": ev.checks, "files": files})

    return results
