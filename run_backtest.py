from __future__ import annotations

import json
from pathlib import Path

from backtest.core.runner import run_all


def main():
    results = run_all("backtest/out")
    summary_path = Path("backtest/out/runner_summary.json")
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"generated runs: {len(results)}")
    print(f"summary: {summary_path}")


if __name__ == "__main__":
    main()
