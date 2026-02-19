#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path
from statistics import median
from typing import Dict, List, Tuple


def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: List[Dict[str, object]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def resolve_run(base: Path, run_ref: str) -> Path:
    p = Path(run_ref)
    if p.exists():
        return p.resolve()
    cand = base / run_ref
    if cand.exists():
        return cand.resolve()
    raise FileNotFoundError(f"run not found: {run_ref}")


def _f(x, default=0.0) -> float:
    try:
        if x in ("", None):
            return default
        return float(x)
    except Exception:
        return default


def detect_columns(rows: List[Dict[str, str]]) -> set:
    return set(rows[0].keys()) if rows else set()


def materialize_schema(run_dir: Path) -> Tuple[Dict[str, object], List[str]]:
    fails: List[str] = []
    events_p = run_dir / "events.csv"
    trades_p = run_dir / "final_trades.csv"

    if not events_p.exists():
        fails.append(f"missing file: {events_p}")
    if not trades_p.exists():
        fails.append(f"missing file: {trades_p}")
    if fails:
        return {"run_id": run_dir.name}, fails

    events = read_csv_rows(events_p)
    trades = read_csv_rows(trades_p)

    ev_cols = detect_columns(events)
    tr_cols = detect_columns(trades)

    for c in ["position_id"]:
        if c not in ev_cols:
            fails.append("events.csv missing required column: position_id")
    if "type" not in ev_cols and "event_type" not in ev_cols:
        fails.append("events.csv missing required column: type/event_type")
    if "date" not in ev_cols and "ts" not in ev_cols:
        fails.append("events.csv missing required column: date/ts")

    for c in ["position_id", "entry_date", "exit_date", "return"]:
        if c not in tr_cols:
            fails.append(f"final_trades.csv missing required column: {c}")

    trade_metrics_rows: List[Dict[str, object]] = []
    for i, r in enumerate(trades, start=1):
        realized = r.get("realized_pct", r.get("return", ""))
        mfe = r.get("MFE_pct", r.get("mfe_pct", ""))
        mae = r.get("MAE_pct", r.get("mae_pct", ""))
        giveback = r.get("Giveback_pct", r.get("giveback_pct", ""))
        if giveback in ("", None) and mfe not in ("", None) and realized not in ("", None):
            giveback = _f(mfe) - _f(realized)

        trade_metrics_rows.append(
            {
                "trade_id": r.get("trade_id", str(i)),
                "position_id": r.get("position_id", ""),
                "entry_ts": r.get("entry_ts", r.get("entry_date", "")),
                "exit_ts": r.get("exit_ts", r.get("exit_date", "")),
                "realized_pct": realized,
                "mfe_pct": mfe,
                "mae_pct": mae,
                "giveback_pct": giveback,
            }
        )

    trade_metrics_p = run_dir / "trade_metrics.csv"
    write_csv(
        trade_metrics_p,
        trade_metrics_rows,
        ["trade_id", "position_id", "entry_ts", "exit_ts", "realized_pct", "mfe_pct", "mae_pct", "giveback_pct"],
    )

    if not any((r.get("mfe_pct") not in ("", None)) for r in trade_metrics_rows):
        fails.append("trade_metrics.csv missing populated MFE_pct/MAE_pct/Giveback_pct values")

    fee_vals = []
    slip_vals = []
    for r in events:
        v = r.get("fee", "")
        if v not in ("", None):
            fee_vals.append(_f(v))
        sv = r.get("slippage_estimate_pct", r.get("pnl_leg", ""))
        if sv not in ("", None):
            slip_vals.append(_f(sv))

    cost_rows = [
        {
            "fills_count": len(events),
            "total_fee": sum(fee_vals) if fee_vals else "",
            "slippage_estimate_pct": (sum(slip_vals) / len(slip_vals)) if slip_vals else "",
        }
    ]
    cost_metrics_p = run_dir / "cost_metrics.csv"
    write_csv(cost_metrics_p, cost_rows, ["fills_count", "total_fee", "slippage_estimate_pct"])

    if cost_rows[0]["total_fee"] == "":
        fails.append("cost_metrics.csv total_fee not derivable from current logs")

    # top-10% winner median (realized_pct)
    realized_vals = sorted([_f(r.get("realized_pct", 0.0)) for r in trade_metrics_rows], reverse=True)
    top_n = max(1, int(len(realized_vals) * 0.1)) if realized_vals else 0
    top_vals = realized_vals[:top_n] if top_n else []
    top10_med = median(top_vals) if top_vals else 0.0

    summary = {
        "run_id": run_dir.name,
        "events_count": len(events),
        "trades_count": len(trades),
        "partial_tp_count": sum(1 for r in events if (r.get("event_type") or r.get("type")) == "Partial_TP"),
        "top10_winner_count": len(top_vals),
        "top10_realized_median_pct": top10_med,
        "trade_metrics_path": str(trade_metrics_p),
        "cost_metrics_path": str(cost_metrics_p),
        "fills_count": len(events),
        "total_fee": cost_rows[0]["total_fee"] if cost_rows else "",
        "slippage_estimate_pct": cost_rows[0]["slippage_estimate_pct"] if cost_rows else "",
    }
    return summary, fails


def git_commit_hash(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(repo_root), text=True)
        return out.strip()
    except Exception:
        return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--min-top-winners", type=int, default=20)
    parser.add_argument("--out", default="report_exit_ptp_once.json")
    parser.add_argument("--base-dir", default="Auto Trading/autotune_runs")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    base_dir = (repo_root / args.base_dir).resolve()

    baseline_dir = resolve_run(base_dir, args.baseline)
    candidate_dir = resolve_run(base_dir, args.candidate)

    b_sum, b_fail = materialize_schema(baseline_dir)
    c_sum, c_fail = materialize_schema(candidate_dir)

    # AC-oriented basic comparison (best-effort; no hard exception)
    ptp_reduction_ratio = 0.0
    if _f(b_sum.get("partial_tp_count", 0), 0) > 0:
        ptp_reduction_ratio = 1.0 - (_f(c_sum.get("partial_tp_count", 0)) / _f(b_sum.get("partial_tp_count", 1)))

    winner_delta = _f(c_sum.get("top10_realized_median_pct", 0.0)) - _f(b_sum.get("top10_realized_median_pct", 0.0))

    cost_axes = 0
    if _f(c_sum.get("fills_count", 0)) < _f(b_sum.get("fills_count", 0)):
        cost_axes += 1
    if _f(c_sum.get("total_fee", 0)) < _f(b_sum.get("total_fee", 0)):
        cost_axes += 1
    if _f(c_sum.get("slippage_estimate_pct", 0)) < _f(b_sum.get("slippage_estimate_pct", 0)):
        cost_axes += 1

    winner_sample_ok = min(_f(b_sum.get("top10_winner_count", 0)), _f(c_sum.get("top10_winner_count", 0))) >= args.min_top_winners

    derived_gate_failures: List[str] = []
    if ptp_reduction_ratio < 0.5:
        derived_gate_failures.append("partial_tp_reduction_below_50pct")
    if winner_sample_ok and winner_delta < 3.0:
        derived_gate_failures.append("top10_realized_median_delta_below_3.0pp")
    if cost_axes < 2:
        derived_gate_failures.append("cost_reduction_axes_lt_2")

    all_fail = b_fail + c_fail + derived_gate_failures

    report = {
        "run_summary_source_hash": sha256_file(baseline_dir / "run_summary.json") or sha256_file(candidate_dir / "run_summary.json"),
        "code_commit_hash": git_commit_hash(repo_root),
        "config_hash": sha256_file(baseline_dir / "run_config.json") or sha256_file(candidate_dir / "run_config.json"),
        "baseline_run_id": baseline_dir.name,
        "candidate_run_id": candidate_dir.name,
        "metrics_summary": {
            "baseline": b_sum,
            "candidate": c_sum,
            "min_top_winners": args.min_top_winners,
            "derived": {
                "partial_tp_reduction_ratio": ptp_reduction_ratio,
                "winner_sample_ok": winner_sample_ok,
                "top10_realized_median_delta_pctp": winner_delta,
                "cost_reduction_axes": cost_axes,
            },
        },
        "cost_summary": {
            "baseline_cost_metrics": str(baseline_dir / "cost_metrics.csv"),
            "candidate_cost_metrics": str(candidate_dir / "cost_metrics.csv"),
        },
        "gate_summary": {
            "status": "PASS" if not all_fail else "FAIL",
            "baseline_fail_reasons": b_fail,
            "candidate_fail_reasons": c_fail,
            "derived_fail_reasons": derived_gate_failures,
        },
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
