"""Go/No-Go evaluator for Hybrid Spec v1.2 backtests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvalResult:
    verdict: str
    checks: dict


def evaluate_go_no_go(metrics_total: dict, metrics_by_mode: dict, eval_scope: dict | None = None) -> EvalResult:
    """Evaluate absolute + relative criteria from SPEC_BACKTEST_v1.

    Expected keys (minimum):
      metrics_total: {
        "oos_pf": float,
        "oos_mdd": float,
        "bull_tcr": float,
        "stress_break": bool,
        "oos_cagr_hybrid": float,
        "oos_cagr_def": float,
        "bull_return_hybrid": float,
        "bull_return_def": float,
        "kill_zone_guard_fired": bool,
        "kill_zone_loss_hybrid": float,
        "kill_zone_loss_agg": float,
      }
    """

    oos_pf = float(metrics_total.get("oos_pf", 0.0))
    oos_mdd = float(metrics_total.get("oos_mdd", 1.0))
    bull_tcr = float(metrics_total.get("bull_tcr", 0.0))
    stress_break = bool(metrics_total.get("stress_break", True))

    oos_cagr_h = float(metrics_total.get("oos_cagr_hybrid", 0.0))
    oos_cagr_d = float(metrics_total.get("oos_cagr_def", 0.0))

    bull_ret_h = float(metrics_total.get("bull_return_hybrid", 0.0))
    bull_ret_d = float(metrics_total.get("bull_return_def", 0.0))

    guard_fired = bool(metrics_total.get("kill_zone_guard_fired", False))
    kz_loss_h = float(metrics_total.get("kill_zone_loss_hybrid", 0.0))
    kz_loss_a = float(metrics_total.get("kill_zone_loss_agg", 0.0))

    eval_scope = eval_scope or {}
    kz_scope_required = bool(eval_scope.get("kz_scope_required", False))
    epsilon = 1e-12

    checks = {
        "abs_oos_pf": oos_pf >= 1.2,
        "abs_oos_mdd": oos_mdd <= 0.20,
        "abs_bull_tcr": bull_tcr >= 0.90,
        "abs_stress_no_break": not stress_break,
        "rel_oos_cagr": (oos_cagr_h + epsilon) >= (1.15 * oos_cagr_d if oos_cagr_d > 0 else 0),
        "rel_bull_return": (bull_ret_h + epsilon) >= (1.30 * bull_ret_d if bull_ret_d > 0 else 0),
        # Requirement check semantics: when KZ scope is not required, this check should pass.
        "kz_scope_required": (not kz_scope_required) or kz_scope_required,
        # KZ guard firing is only mandatory when KZ scope is required (R4/kill-zone split).
        "kz_guard_fired": (not kz_scope_required) or guard_fired,
        "kz_guard_fired_raw": guard_fired,
        "kz_loss_improved": kz_loss_h >= kz_loss_a,
    }

    # kill zone loss: less negative is better, so hybrid should be > agg
    abs_ok = all(checks[k] for k in ["abs_oos_pf", "abs_oos_mdd", "abs_bull_tcr", "abs_stress_no_break"])
    rel_ok = checks["rel_oos_cagr"] and checks["rel_bull_return"]
    kz_ok = (not kz_scope_required) or (checks["kz_guard_fired"] and checks["kz_loss_improved"])

    verdict = "GO" if (abs_ok and rel_ok and kz_ok) else "NO_GO"
    return EvalResult(verdict=verdict, checks=checks)
