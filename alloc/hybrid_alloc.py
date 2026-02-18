from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AllocInput:
    meta_mode: str
    regime: str
    booster: bool
    drawdown: float
    scout_enabled: bool


@dataclass
class AllocConfig:
    x_cap: float = 0.8
    x_cap_def: float = 0.55
    x_cap_agg: float = 0.8
    dd_ladder: tuple[tuple[float, float], ...] = ((0.05, 0.90), (0.10, 0.75), (0.15, 0.50), (0.20, 0.20))


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


def allocate_capital(inp: AllocInput, cfg: AllocConfig) -> Allocation:
    base_cap = cfg.x_cap_agg if inp.meta_mode == "AGGRESSIVE" else cfg.x_cap_def
    base_cap = min(base_cap, cfg.x_cap)

    dd_scale = _dd_scale(abs(inp.drawdown), cfg.dd_ladder)
    cap = max(0.0, min(cfg.x_cap, base_cap * dd_scale))

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
    reason = f"mode={inp.meta_mode};regime={inp.regime};dd_scale={dd_scale:.2f}"

    return Allocation(
        x_cap=round(cap, 6),
        x_cd=round(gross_cd, 6),
        x_ce=round(gross_ce, 6),
        w_ce=round(w_ce, 6),
        scout=round(gross_scout, 6),
        x_total=round(x_total, 6),
        reason=reason,
    )
