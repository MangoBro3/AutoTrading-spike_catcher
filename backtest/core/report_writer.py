"""Report writer for mandatory backtest artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path


MANDATORY_FILES = [
    "daily_state.csv",
    "switches.csv",
    "guards.csv",
    "trades.csv",
    "summary.json",
    "metrics_total.json",
    "metrics_by_mode.json",
]


def _write_csv(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_reports(out_dir: str | Path, payload: dict):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    _write_csv(out / "daily_state.csv", payload.get("daily_state", []))
    _write_csv(out / "switches.csv", payload.get("switches", []))
    _write_csv(out / "guards.csv", payload.get("guards", []))
    _write_csv(out / "trades.csv", payload.get("trades", []))

    _write_json(out / "summary.json", payload.get("summary", {}))
    _write_json(out / "metrics_total.json", payload.get("metrics_total", {}))
    _write_json(out / "metrics_by_mode.json", payload.get("metrics_by_mode", {}))

    return [str(out / name) for name in MANDATORY_FILES]
