#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


def _sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


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

    out_path = Path(args.out)
    # If set is provided and caller left default out, keep runs separated by set name.
    if args.set_name and args.out == "backtest/out":
        out_path = out_path / args.set_name

    out_path.mkdir(parents=True, exist_ok=True)

    # lock-input: persist reproducibility context (best-effort, never hard-fail)
    if args.lock_input:
        lock_payload: Dict[str, Any] = {
            "scenario": args.scenario,
            "set": args.set_name,
            "adapter": args.adapter,
            "run_summary": args.run_summary,
            "unknown_args": unknown,
        }
        if args.run_summary:
            rs = Path(args.run_summary)
            lock_payload["run_summary_resolved"] = str(rs.resolve()) if rs.exists() else str(rs)
            lock_payload["run_summary_hash"] = _sha256_file(rs)
            lock_payload["run_summary_keys"] = sorted(_safe_read_json(rs).keys())
        (out_path / "input_lock.json").write_text(
            json.dumps(lock_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    cmd = [sys.executable, str(root_script), "--adapter", args.adapter, "--out", str(out_path)]
    if args.run_summary:
        cmd += ["--run-summary", args.run_summary]
    # pass-through for forward compatibility
    cmd += unknown

    print(
        f"[wrapper] scenario={args.scenario} set={args.set_name} lock_input={args.lock_input} "
        f"emit_hash={args.emit_hash} out={out_path}"
    )
    rc = subprocess.call(cmd)

    # emit-hash: publish simple artifact hash map (best-effort)
    if args.emit_hash:
        hash_payload = {
            "scenario": args.scenario,
            "set": args.set_name,
            "out": str(out_path),
            "runner_summary_hash": _sha256_file(out_path / "runner_summary.json"),
            "run_summary_hash": _sha256_file(Path(args.run_summary)) if args.run_summary else "",
            "input_lock_hash": _sha256_file(out_path / "input_lock.json"),
        }
        (out_path / "artifact_hashes.json").write_text(
            json.dumps(hash_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
