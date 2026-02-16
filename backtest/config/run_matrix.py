"""Backtest run matrix (R0~R4) for Hybrid Spec v1.2."""

from __future__ import annotations

RUN_MATRIX = [
    # R0 Baseline
    {"run_id": "R0_DEF", "family": "R0", "mode": "always_def", "split": "full_cycle_1d"},
    {"run_id": "R0_AGG", "family": "R0", "mode": "always_agg", "split": "full_cycle_1d"},
    {"run_id": "R0_HYB", "family": "R0", "mode": "hybrid", "split": "full_cycle_1d"},

    # R1 AB
    {"run_id": "R1_SCOUT_ON", "family": "R1", "mode": "hybrid", "split": "oos_1d", "scout": True},
    {"run_id": "R1_SCOUT_OFF", "family": "R1", "mode": "hybrid", "split": "oos_1d", "scout": False},
    {"run_id": "R1_ATR_IGN_ON", "family": "R1", "mode": "hybrid", "split": "oos_1d", "atr_ignore_ok": True},
    {"run_id": "R1_ATR_IGN_OFF", "family": "R1", "mode": "hybrid", "split": "oos_1d", "atr_ignore_ok": False},
    {"run_id": "R1_RATE_ON", "family": "R1", "mode": "hybrid", "split": "oos_1d", "rate_limit": True},
    {"run_id": "R1_RATE_OFF", "family": "R1", "mode": "hybrid", "split": "oos_1d", "rate_limit": False},

    # R2 Trigger path
    {"run_id": "R2_MULTI", "family": "R2", "mode": "hybrid", "split": "oos_1d", "agg_trigger": "multi"},
    {"run_id": "R2_SIMPLE", "family": "R2", "mode": "hybrid", "split": "oos_1d", "agg_trigger": "simple"},

    # R3 비용 스트레스
    {"run_id": "R3_FEE_X2", "family": "R3", "mode": "hybrid", "split": "oos_1d", "fee_mult": 2.0, "slippage_mult": 1.0},
    {"run_id": "R3_SLIP_X2", "family": "R3", "mode": "hybrid", "split": "oos_1d", "fee_mult": 1.0, "slippage_mult": 2.0},
    {"run_id": "R3_BOTH_X2", "family": "R3", "mode": "hybrid", "split": "oos_1d", "fee_mult": 2.0, "slippage_mult": 2.0},

    # R4 Kill zones (5m)
    {"run_id": "R4_KILL", "family": "R4", "mode": "hybrid", "split": "kill_zones_5m"},
]


def get_runs():
    return RUN_MATRIX
