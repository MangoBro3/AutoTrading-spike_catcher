from __future__ import annotations

import argparse
import json
from pathlib import Path

from backtest.core.runner import run_all


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", choices=["mock", "auto_trading"], default="mock")
    parser.add_argument("--run-summary", default=None, help="Path to Auto Trading run_summary.json")
    parser.add_argument("--out", default="backtest/out")
    args = parser.parse_args()

    adapter = None
    if args.adapter == "auto_trading":
        from backtest.core.autotrading_adapter import build_adapter

        adapter = build_adapter(base_dir=".", run_summary_path=args.run_summary)

    results = run_all(args.out, adapter=adapter) if adapter else run_all(args.out)
    summary_path = Path(args.out) / "runner_summary.json"
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"generated runs: {len(results)}")
    print(f"summary: {summary_path}")


if __name__ == "__main__":
    main()
