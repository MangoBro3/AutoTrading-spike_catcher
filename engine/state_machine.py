from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MetaMode(str, Enum):
    DEFENSIVE = "DEFENSIVE"
    AGGRESSIVE = "AGGRESSIVE"


class Regime(str, Enum):
    RANGE = "RANGE"
    TREND = "TREND"
    BEAR = "BEAR"
    SUPER_TREND = "SUPER_TREND"


class RiskState(str, Enum):
    RISK_ON = "risk_on"
    NEUTRAL = "neutral"
    RISK_OFF = "risk_off"


@dataclass
class State:
    meta_mode: MetaMode = MetaMode.DEFENSIVE
    regime: Regime = Regime.RANGE
    booster: bool = False
    hold_bars: int = 0
    cooldown_bars: int = 0
    risk_state: RiskState = RiskState.NEUTRAL


@dataclass
class Inputs:
    trend_strength: float
    vol_spike: float
    drawdown: float
    guard_active: bool


def _derive_risk_state(regime: Regime, x: Inputs) -> RiskState:
    if x.guard_active or x.drawdown <= -0.12 or regime == Regime.BEAR:
        return RiskState.RISK_OFF
    if regime == Regime.SUPER_TREND:
        return RiskState.RISK_ON
    if regime == Regime.TREND and x.trend_strength >= 0.65 and x.vol_spike <= 1.45:
        return RiskState.RISK_ON
    return RiskState.NEUTRAL


def step(state: State, x: Inputs, *, min_hold: int = 3, cooldown: int = 2) -> State:
    hold = max(0, state.hold_bars - 1)
    cd = max(0, state.cooldown_bars - 1)

    regime = state.regime
    if x.drawdown <= -0.12:
        regime = Regime.BEAR
    elif x.trend_strength >= 0.8 and x.vol_spike >= 1.5:
        regime = Regime.SUPER_TREND
    elif x.trend_strength >= 0.55:
        regime = Regime.TREND
    else:
        regime = Regime.RANGE

    mode = state.meta_mode
    if x.guard_active:
        mode = MetaMode.DEFENSIVE
        cd = max(cd, cooldown)
    elif hold == 0 and cd == 0:
        if regime in (Regime.TREND, Regime.SUPER_TREND):
            mode = MetaMode.AGGRESSIVE
            hold = min_hold
        elif regime in (Regime.RANGE, Regime.BEAR):
            mode = MetaMode.DEFENSIVE
            hold = min_hold

    booster = mode == MetaMode.AGGRESSIVE and regime == Regime.SUPER_TREND and not x.guard_active
    risk_state = _derive_risk_state(regime, x)

    return State(
        meta_mode=mode,
        regime=regime,
        booster=booster,
        hold_bars=hold,
        cooldown_bars=cd,
        risk_state=risk_state,
    )
