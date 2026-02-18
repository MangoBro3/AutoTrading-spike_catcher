from __future__ import annotations

from pathlib import Path

from backtest.config.run_matrix import get_runs
from backtest.core.engine_interface import RunRequest, default_mock_adapter
from backtest.core.evaluator import evaluate_go_no_go
from backtest.core.report_writer import write_reports
from backtest.core.splits_loader import load_splits


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

        ev = evaluate_go_no_go(payload["metrics_total"], payload["metrics_by_mode"])
        payload.setdefault("summary", {})
        payload["summary"]["go_no_go"] = ev.verdict
        payload["summary"]["checks"] = ev.checks

        out_dir = out_root / run_id
        files = write_reports(out_dir, payload)
        results.append({"run_id": run_id, "verdict": ev.verdict, "checks": ev.checks, "files": files})

    return results
