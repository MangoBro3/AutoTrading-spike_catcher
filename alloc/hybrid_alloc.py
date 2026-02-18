from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AllocInput:
    meta_mode: str
    regime: str
    booster: bool
    drawdown: float
    scout_enabled: bool
    risk_state: str = "neutral"
    prev_x_cap: float = 0.0


@dataclass
class AllocConfig:
    x_cap: float = 0.8
    x_cap_def: float = 0.55
    x_cap_agg: float = 0.8
    dd_ladder: tuple[tuple[float, float], ...] = ((0.05, 0.90), (0.10, 0.75), (0.15, 0.50), (0.20, 0.20))
    risk_budget: dict[str, float] | None = None
    cap_up_step: float = 0.03
    cap_down_step: float = 0.12


@dataclass
class Allocation:
    x_cap: float
    x_cd: float
    x_ce: float
    w_ce: float
    scout: float
    x_total: float
    reason: str


def _dd_scale(drawdown_abs: float, ladder: tuple[tuple[float, float], ...]) -> float:
    scale = 1.0
    for dd_th, factor in ladder:
        if drawdown_abs >= dd_th:
            scale = min(scale, factor)
    return max(0.0, min(1.0, scale))


def _rate_limited_cap(target: float, prev: float, up_step: float, down_step: float) -> float:
    prev = max(0.0, prev)
    target = max(0.0, target)
    if target >= prev:
        return min(target, prev + max(0.0, up_step))
    return max(target, prev - max(0.0, down_step))


def allocate_capital(inp: AllocInput, cfg: AllocConfig) -> Allocation:
    base_cap = cfg.x_cap_agg if inp.meta_mode == "AGGRESSIVE" else cfg.x_cap_def
    base_cap = min(base_cap, cfg.x_cap)

    budget = cfg.risk_budget or {"risk_on": 1.05, "neutral": 0.82, "risk_off": 0.50}
    risk_mult = float(budget.get(inp.risk_state, budget.get("neutral", 0.80)))

    dd_scale = _dd_scale(abs(inp.drawdown), cfg.dd_ladder)
    cap_target = max(0.0, min(cfg.x_cap, base_cap * risk_mult * dd_scale))
    cap = _rate_limited_cap(cap_target, inp.prev_x_cap, cfg.cap_up_step, cfg.cap_down_step)
    cap = max(0.0, min(cfg.x_cap, cap))

    if inp.meta_mode == "AGGRESSIVE":
        x_ce = 0.40 if inp.regime == "SUPER_TREND" else 0.28
        x_cd = 1.0 - x_ce
    else:
        x_ce = 0.0
        x_cd = 1.0

    if inp.booster:
        x_ce = min(0.45, x_ce + 0.05)
        x_cd = 1.0 - x_ce

    scout = 0.0
    if inp.scout_enabled and inp.meta_mode == "DEFENSIVE" and inp.regime in {"TREND", "SUPER_TREND"}:
        scout = 0.05

    # raw exposures under cap
    gross_cd = cap * x_cd
    gross_ce = cap * x_ce
    gross_scout = cap * scout

    x_total = gross_cd + gross_ce + gross_scout
    if x_total > cap and x_total > 0:
        scale = cap / x_total
        gross_cd *= scale
        gross_ce *= scale
        gross_scout *= scale
        x_total = cap

    w_ce = 0.0 if cap <= 0 else gross_ce / cap
    reason = (
        f"mode={inp.meta_mode};regime={inp.regime};risk_state={inp.risk_state};"
        f"risk_mult={risk_mult:.2f};dd_scale={dd_scale:.2f};cap_tgt={cap_target:.2f}"
    )

    return Allocation(
        x_cap=round(cap, 6),
        x_cd=round(gross_cd, 6),
        x_ce=round(gross_ce, 6),
        w_ce=round(w_ce, 6),
        scout=round(gross_scout, 6),
        x_total=round(x_total, 6),
        reason=reason,
    )
