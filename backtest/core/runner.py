from __future__ import annotations

import json
from pathlib import Path

from backtest.config.run_matrix import get_runs
from backtest.core.engine_interface import RunRequest, default_mock_adapter
from backtest.core.evaluator import evaluate_go_no_go
from backtest.core.report_writer import write_reports
from backtest.core.splits_loader import load_splits


def _build_regime_extension_report(payloads_by_run: dict) -> dict:
    def_payload = payloads_by_run.get("R0_DEF")
    hyb_payload = payloads_by_run.get("R0_HYB")
    if not def_payload or not hyb_payload:
        return {}

    def_total = def_payload.get("metrics_total", {})
    hyb_total = hyb_payload.get("metrics_total", {})
    def_mode = next(iter(def_payload.get("metrics_by_mode", {}).values()), {})
    hyb_mode = next(iter(hyb_payload.get("metrics_by_mode", {}).values()), {})

    def_reg = def_mode.get("regime_contribution", {})
    hyb_reg = hyb_mode.get("regime_contribution", {})

    regime_compare = {}
    for key in sorted(set(def_reg.keys()) | set(hyb_reg.keys())):
        d = def_reg.get(key, {})
        h = hyb_reg.get(key, {})
        regime_compare[key] = {
            "def_sum_ret": d.get("sum_ret", 0.0),
            "hyb_sum_ret": h.get("sum_ret", 0.0),
            "delta_sum_ret_hyb_minus_def": round(float(h.get("sum_ret", 0.0)) - float(d.get("sum_ret", 0.0)), 6),
            "def_contribution_share": d.get("contribution_share", 0.0),
            "hyb_contribution_share": h.get("contribution_share", 0.0),
        }

    return {
        "baseline_runs": ["R0_DEF", "R0_HYB"],
        "def_hyb": {
            "oos_cagr_def": def_total.get("oos_cagr_def", 0.0),
            "oos_cagr_hyb": hyb_total.get("oos_cagr_hybrid", 0.0),
            "bull_return_def": def_total.get("bull_return_def", 0.0),
            "bull_return_hyb": hyb_total.get("bull_return_hybrid", 0.0),
        },
        "bull_segment": {
            "def": def_mode.get("bull_segment", {}),
            "hyb": hyb_mode.get("bull_segment", {}),
            "delta_compound_return_hyb_minus_def": round(
                float(hyb_total.get("bull_segment_return", 0.0)) - float(def_total.get("bull_segment_return", 0.0)), 6
            ),
        },
        "regime_contribution": regime_compare,
    }


def _apply_r0_relative_anchors(payloads_by_run: dict) -> None:
    """Inject R0-relative comparison anchors into each R0 payload.

    Relative criteria are defined as HYB vs DEF. For per-run payload evaluation,
    keep the criteria unchanged but normalize the source path so R0_DEF/R0_AGG
    use the same HYB/DEF anchor pair as R0_HYB.
    """

    p_def = payloads_by_run.get("R0_DEF", {})
    p_hyb = payloads_by_run.get("R0_HYB", {})
    m_def = (p_def or {}).get("metrics_total", {})
    m_hyb = (p_hyb or {}).get("metrics_total", {})

    cagr_def = float(m_def.get("oos_cagr_def", 0.0))
    bull_def = float(m_def.get("bull_return_def", 0.0))
    cagr_hyb = float(m_hyb.get("oos_cagr_hybrid", 0.0))
    bull_hyb = float(m_hyb.get("bull_return_hybrid", 0.0))

    if not (cagr_def > 0 and cagr_hyb > 0):
        return

    for run_id, payload in payloads_by_run.items():
        if not str(run_id).startswith("R0_"):
            continue
        mt = payload.setdefault("metrics_total", {})
        mt["oos_cagr_hybrid"] = cagr_hyb
        mt["oos_cagr_def"] = cagr_def
        mt["bull_return_hybrid"] = bull_hyb
        mt["bull_return_def"] = bull_def


def run_all(out_root: str | Path = "backtest/out", adapter=default_mock_adapter) -> list[dict]:
    out_root = Path(out_root)
    runs = get_runs()
    splits_doc = load_splits()

    split_map = splits_doc.get("splits", {})
    results = []
    payloads_by_run = {}

    for run in runs:
        run_id = run["run_id"]
        split_key = run["split"]
        split = split_map.get(split_key, {"name": split_key})
        if split_key == "kill_zones_5m":
            split = {"timeframe": "5m", "zones": splits_doc.get("kill_zones_5m", [])}

        request = RunRequest(run_id=run_id, mode=run.get("mode", "hybrid"), split=split, options=run)
        payload = adapter(request)
        payloads_by_run[run_id] = payload

    _apply_r0_relative_anchors(payloads_by_run)

    for run in runs:
        run_id = run["run_id"]
        payload = payloads_by_run[run_id]
        eval_scope = {
            "kz_scope_required": (run.get("family") == "R4") or (run.get("split") == "kill_zones_5m"),
            # Architect option B: for R0 family, only HYB requires relative checks.
            "rel_required": (run.get("run_id") == "R0_HYB") if str(run.get("family", "")).startswith("R0") else True,
        }
        ev = evaluate_go_no_go(payload["metrics_total"], payload["metrics_by_mode"], eval_scope=eval_scope)
        payload.setdefault("summary", {})
        payload["summary"]["go_no_go"] = ev.verdict
        payload["summary"]["checks"] = ev.checks

        out_dir = out_root / run_id
        files = write_reports(out_dir, payload)
        results.append({"run_id": run_id, "verdict": ev.verdict, "go_no_go": ev.verdict, "checks": ev.checks, "files": files})

    extension = _build_regime_extension_report(payloads_by_run)
    if extension:
        ext_path = out_root / "regime_extension_report.json"
        ext_path.parent.mkdir(parents=True, exist_ok=True)
        ext_path.write_text(json.dumps(extension, ensure_ascii=False, indent=2), encoding="utf-8")

    return results
