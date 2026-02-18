from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GuardInput:
    bar_return: float
    drawdown: float
    intraday_drop: float
    ops_kill_switch: bool


@dataclass
class GuardState:
    intraday_guard: bool = False
    ops_kill: bool = False
    safety_latch: bool = False


@dataclass
class GuardResult:
    state: GuardState
    guard_active: bool
    cap_multiplier: float
    reason: str


def evaluate_guards(inp: GuardInput, prev: GuardState) -> GuardResult:
    intraday_guard = inp.intraday_drop <= -0.03 or inp.bar_return <= -0.02
    safety_latch = prev.safety_latch or abs(inp.drawdown) >= 0.18
    ops_kill = bool(inp.ops_kill_switch)

    guard_active = intraday_guard or safety_latch or ops_kill

    cap_multiplier = 1.0
    reason = []
    if intraday_guard:
        cap_multiplier = min(cap_multiplier, 0.55)
        reason.append("intraday")
    if safety_latch:
        cap_multiplier = min(cap_multiplier, 0.35)
        reason.append("safety_latch")
    if ops_kill:
        cap_multiplier = 0.0
        reason.append("ops_kill")

    if not reason:
        reason.append("none")

    return GuardResult(
        state=GuardState(intraday_guard=intraday_guard, ops_kill=ops_kill, safety_latch=safety_latch),
        guard_active=guard_active,
        cap_multiplier=cap_multiplier,
        reason="+".join(reason),
    )
