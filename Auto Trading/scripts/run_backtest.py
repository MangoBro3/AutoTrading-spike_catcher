#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Contract-compatible wrapper for root run_backtest.py")
    parser.add_argument("--scenario", default="")
    parser.add_argument("--set", dest="set_name", default="")
    parser.add_argument("--lock-input", action="store_true")
    parser.add_argument("--emit-hash", action="store_true")
    parser.add_argument("--adapter", default="mock")
    parser.add_argument("--run-summary", default=None)
    parser.add_argument("--out", default="backtest/out")
    args, unknown = parser.parse_known_args()

    root_script = Path(__file__).resolve().parents[2] / "run_backtest.py"
    cmd = [sys.executable, str(root_script), "--adapter", args.adapter, "--out", args.out]
    if args.run_summary:
        cmd += ["--run-summary", args.run_summary]
    cmd += unknown

    print(f"[wrapper] scenario={args.scenario} set={args.set_name} lock_input={args.lock_input} emit_hash={args.emit_hash}")
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
