from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from backtest.core.runner import run_all


def _sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", choices=["mock", "auto_trading"], default="mock")
    parser.add_argument("--run-summary", default=None, help="Path to Auto Trading run_summary.json")
    parser.add_argument("--out", default="backtest/out")

    # Contract tooling compatibility flags (best-effort; no hard coupling with engine internals)
    parser.add_argument("--scenario", default="")
    parser.add_argument("--set", dest="set_name", default="")
    parser.add_argument("--lock-input", action="store_true")
    parser.add_argument("--emit-hash", action="store_true")

    # allow forward-compatible passthrough flags without parser hard-fail
    args, unknown = parser.parse_known_args()

    out_path = Path(args.out)
    out_path.mkdir(parents=True, exist_ok=True)

    if args.lock_input:
        lock_payload = {
            "scenario": args.scenario,
            "set": args.set_name,
            "adapter": args.adapter,
            "run_summary": args.run_summary,
            "unknown_args": unknown,
        }
        (out_path / "input_lock.json").write_text(json.dumps(lock_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    adapter = None
    if args.adapter == "auto_trading":
        from backtest.core.autotrading_adapter import build_adapter

        adapter = build_adapter(base_dir=".", run_summary_path=args.run_summary)

    results = run_all(str(out_path), adapter=adapter) if adapter else run_all(str(out_path))
    summary_path = out_path / "runner_summary.json"
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.emit_hash:
        hashes = {
            "runner_summary_hash": _sha256_file(summary_path),
            "run_summary_hash": _sha256_file(Path(args.run_summary)) if args.run_summary else "",
            "input_lock_hash": _sha256_file(out_path / "input_lock.json"),
        }
        (out_path / "artifact_hashes.json").write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"generated runs: {len(results)}")
    print(f"summary: {summary_path}")
    if unknown:
        print(f"[info] ignored extra args: {' '.join(unknown)}")


if __name__ == "__main__":
    main()
