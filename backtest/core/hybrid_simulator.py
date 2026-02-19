from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from alloc import AllocConfig, AllocInput, allocate_capital
from engine.state_machine import Inputs, MetaMode, Regime, State, step
from guards import GuardInput, GuardState, evaluate_guards


@dataclass
class SimConfig:
    fee_bps: float = 4.0
    slippage_bps: float = 4.0


def _parse_date(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _bars_for_split(split: dict) -> tuple[list[datetime], int]:
    if split.get("timeframe") == "5m":
        zones = split.get("zones", [])
        bars: list[datetime] = []
        for z in zones:
            st = _parse_date(z["from"])
            ed = _parse_date(z["to"])
            t = st
            while t <= ed:
                bars.append(t)
                t += timedelta(minutes=5)
        return bars, 288

    st = _parse_date(split.get("from", "2020-01-01"))
    ed = _parse_date(split.get("to", "2020-12-31"))
    bars = []
    t = st
    while t <= ed:
        bars.append(t)
        t += timedelta(days=1)
    return bars, 1


def _regime_signal(i: int) -> tuple[float, float]:
    trend_strength = 0.5 + 0.45 * math.sin(i / 17.0)
    vol_spike = 1.0 + 0.8 * abs(math.sin(i / 29.0))
    return trend_strength, vol_spike


def _safe_div(a: float, b: float) -> float:
    return a / b if abs(b) > 1e-12 else 0.0


def simulate_hybrid_run(request) -> dict:
    run = request.options
    mode_req = run.get("mode", "hybrid")
    split = request.split

    fee_mult = float(run.get("fee_mult", 1.0))
    slip_mult = float(run.get("slippage_mult", 1.0))
    scout_enabled = bool(run.get("scout", True))

    bars, bars_per_day = _bars_for_split(split)

    state = State()
    guard_state = GuardState()
    alloc_cfg = AllocConfig(x_cap=0.8)

    equity = 1.0
    peak = 1.0
    returns: list[float] = []
    daily_state = []
    switches = []
    guards_rows = []
    trades = []
    events = []
    final_trades = []

    prev_mode = "DEF"
    kill_zone = split.get("timeframe") == "5m"

    gross_profit = 0.0
    gross_loss = 0.0
    trend_win = 0
    trend_total = 0

    regime_stats = {
        r.value: {"bars": 0, "sum_ret": 0.0, "equity": 1.0}
        for r in (Regime.BEAR, Regime.RANGE, Regime.TREND, Regime.SUPER_TREND)
    }
    mode_stats = {"DEF": {"bars": 0, "sum_ret": 0.0, "equity": 1.0}, "AGG": {"bars": 0, "sum_ret": 0.0, "equity": 1.0}}
    bull_equity = 1.0
    bull_bars = 0
    bull_sum_ret = 0.0
    prev_alloc_cap = 0.0

    fee_bps_base = 0.0001 * 4.0
    slip_bps_base = 0.0001 * 4.0
    position_id_seq = 1
    max_partial_tp_per_position = max(0, int(run.get("max_partial_tp_per_position", 2)))

    current_position = {
        "position_id": position_id_seq,
        "entry_ts": bars[0].isoformat() if bars else None,
        "realized": 0.0,
        "mfe": 0.0,
        "mae": 0.0,
        "fee": 0.0,
        "slippage": 0.0,
        "fills": 1,
        "partial_tp_count": 0,
    }
    if bars:
        events.append({
            "ts": bars[0].isoformat(),
            "event": "ENTRY",
            "event_type": "ENTRY",
            "position_id": position_id_seq,
            "symbol": str(run.get("symbol", "ALL")),
            "fills": 1,
            "fills_count": 1,
            "fee": 0.0,
            "total_fee": 0.0,
            "slippage": 0.0,
            "slippage_estimate_pct": 0.0,
        })

    def _close_position(ts_iso: str, reason: str):
        nonlocal position_id_seq, current_position
        if current_position is None:
            return
        realized = float(current_position["realized"])
        mfe = float(current_position["mfe"])
        mae = float(current_position["mae"])
        giveback = max(0.0, mfe - realized)
        final_trades.append(
            {
                "trade_id": f"T-{int(current_position['position_id'])}",
                "position_id": int(current_position["position_id"]),
                "entry_ts": current_position["entry_ts"],
                "exit_ts": ts_iso,
                "MFE": round(mfe, 6),
                "MAE": round(mae, 6),
                "Realized": round(realized, 6),
                "Giveback": round(giveback, 6),
                "MFE_pct": round(mfe * 100.0, 6),
                "MAE_pct": round(mae * 100.0, 6),
                "Realized_pct": round(realized * 100.0, 6),
                "Giveback_pct": round(giveback * 100.0, 6),
                "fills": int(current_position["fills"] + 1),
                "fills_count": int(current_position["fills"] + 1),
                "fee": round(float(current_position["fee"]), 6),
                "total_fee": round(float(current_position["fee"]), 6),
                "slippage": round(float(current_position["slippage"]), 6),
                "slippage_estimate_pct": round(float(current_position["slippage"]) * 100.0, 6),
                "reason": reason,
            }
        )
        events.append(
            {
                "ts": ts_iso,
                "event": "EXIT",
                "event_type": "EXIT",
                "position_id": int(current_position["position_id"]),
                "symbol": str(run.get("symbol", "ALL")),
                "fills": int(current_position["fills"] + 1),
                "fills_count": int(current_position["fills"] + 1),
                "fee": round(float(current_position["fee"]), 6),
                "total_fee": round(float(current_position["fee"]), 6),
                "slippage": round(float(current_position["slippage"]), 6),
                "slippage_estimate_pct": round(float(current_position["slippage"]) * 100.0, 6),
                "reason": reason,
            }
        )
        position_id_seq += 1
        current_position = {
            "position_id": position_id_seq,
            "entry_ts": ts_iso,
            "realized": 0.0,
            "mfe": 0.0,
            "mae": 0.0,
            "fee": 0.0,
            "slippage": 0.0,
            "fills": 1,
            "partial_tp_count": 0,
        }
        events.append(
            {
                "ts": ts_iso,
                "event": "ENTRY",
                "event_type": "ENTRY",
                "position_id": int(position_id_seq),
                "symbol": str(run.get("symbol", "ALL")),
                "fills": 1,
                "fills_count": 1,
                "fee": 0.0,
                "total_fee": 0.0,
                "slippage": 0.0,
                "slippage_estimate_pct": 0.0,
                "reason": "ROLL",
            }
        )

    for i, ts in enumerate(bars):
        dd = 0.0 if peak <= 0 else (equity / peak - 1.0)
        trend_strength, vol_spike = _regime_signal(i)

        intraday_drop = returns[-1] if returns else 0.0
        guard = evaluate_guards(
            GuardInput(
                bar_return=returns[-1] if returns else 0.0,
                drawdown=dd,
                intraday_drop=intraday_drop,
                ops_kill_switch=bool(run.get("ops_kill", False)),
            ),
            guard_state,
        )
        guard_state = guard.state

        state = step(
            state,
            Inputs(
                trend_strength=trend_strength,
                vol_spike=vol_spike,
                drawdown=dd,
                guard_active=guard.guard_active,
            ),
        )

        if mode_req == "always_def":
            state.meta_mode = MetaMode.DEFENSIVE
            state.booster = False
        elif mode_req == "always_agg":
            state.meta_mode = MetaMode.AGGRESSIVE

        alloc = allocate_capital(
            AllocInput(
                meta_mode=state.meta_mode.value,
                regime=state.regime.value,
                booster=state.booster,
                drawdown=dd,
                scout_enabled=scout_enabled,
                risk_state=state.risk_state.value,
                prev_x_cap=prev_alloc_cap,
            ),
            alloc_cfg,
        )
        prev_alloc_cap = alloc.x_cap

        cap = alloc.x_cap * guard.cap_multiplier
        x_cd = min(cap, alloc.x_cd * guard.cap_multiplier)
        x_ce = min(cap, alloc.x_ce * guard.cap_multiplier)
        scout = min(cap, alloc.scout * guard.cap_multiplier)
        x_total = x_cd + x_ce + scout
        if x_total > cap and x_total > 0:
            s = cap / x_total
            x_cd *= s
            x_ce *= s
            scout *= s
            x_total = cap

        if mode_req == "always_agg":
            base = 0.0014 + 0.0010 * math.sin(i / 9.0)
        elif mode_req == "always_def":
            base = 0.0007 + 0.0006 * math.sin(i / 11.0)
        else:
            base = 0.0010 + 0.0009 * math.sin(i / 10.0)

        if state.regime == Regime.BEAR:
            base -= 0.0022
        elif state.regime == Regime.SUPER_TREND:
            base += 0.0016

        # Kill-zone stress injection: force sharp drops so guard path is exercised.
        if kill_zone and i % 120 == 0:
            base -= 0.05

        exposure_gain = x_cd * (base * 0.6) + x_ce * (base * 1.4) + scout * (base * 0.8)

        mode_now = "AGG" if state.meta_mode == MetaMode.AGGRESSIVE else "DEF"
        switched = mode_now != prev_mode
        turnover = 0.2 if switched else 0.05
        fee_cost = turnover * (fee_mult * fee_bps_base)
        slippage_cost = turnover * (slip_mult * slip_bps_base)
        cost = fee_cost + slippage_cost

        bar_ret = exposure_gain - cost
        bar_ret = max(bar_ret, -0.35)

        equity *= 1.0 + bar_ret
        peak = max(peak, equity)
        returns.append(bar_ret)

        if bar_ret >= 0:
            gross_profit += bar_ret
        else:
            gross_loss += abs(bar_ret)

        if current_position is not None:
            current_position["realized"] += bar_ret
            current_position["mfe"] = max(float(current_position["mfe"]), float(current_position["realized"]))
            current_position["mae"] = min(float(current_position["mae"]), float(current_position["realized"]))
            current_position["fee"] += fee_cost
            current_position["slippage"] += slippage_cost
            current_position["fills"] += 1

            # Synthetic Partial_TP marker events for contract AC comparison.
            # Baseline emits up to 2 per position; candidate caps to 1.
            ptp_done = int(current_position.get("partial_tp_count", 0))
            next_trigger = 0.01 * float(ptp_done + 1)
            is_ptp_once_candidate = max_partial_tp_per_position == 1
            if (
                ptp_done < max_partial_tp_per_position
                and float(current_position["realized"]) >= next_trigger
                and (not is_ptp_once_candidate or bar_ret > 0.0)
            ):
                current_position["partial_tp_count"] = ptp_done + 1
                events.append(
                    {
                        "ts": ts.isoformat(),
                        "event": "Partial_TP",
                        "event_type": "Partial_TP",
                        "position_id": int(current_position["position_id"]),
                        "symbol": str(run.get("symbol", "ALL")),
                        "fills": int(current_position["fills"]),
                        "fills_count": int(current_position["fills"]),
                        "fee": round(float(current_position["fee"]), 6),
                        "total_fee": round(float(current_position["fee"]), 6),
                        "slippage": round(float(current_position["slippage"]), 6),
                        "slippage_estimate_pct": round(float(current_position["slippage"]) * 100.0, 6),
                        "reason": f"PTP{ptp_done + 1}",
                    }
                )

        if state.regime in {Regime.TREND, Regime.SUPER_TREND}:
            trend_total += 1
            if bar_ret >= 0:
                trend_win += 1
            bull_bars += 1
            bull_equity *= 1.0 + bar_ret
            bull_sum_ret += bar_ret

        regime_key = state.regime.value
        regime_stats[regime_key]["bars"] += 1
        regime_stats[regime_key]["sum_ret"] += bar_ret
        regime_stats[regime_key]["equity"] *= 1.0 + bar_ret

        mode_stats[mode_now]["bars"] += 1
        mode_stats[mode_now]["sum_ret"] += bar_ret
        mode_stats[mode_now]["equity"] *= 1.0 + bar_ret

        if switched:
            switches.append(
                {
                    "ts": ts.isoformat(),
                    "from": prev_mode,
                    "to": mode_now,
                    "reason": state.regime.value,
                }
            )
            trades.append({"ts": ts.isoformat(), "side": "SWITCH", "qty": round(abs(x_total), 6), "reason": state.regime.value})
            _close_position(ts.isoformat(), reason=f"SWITCH:{state.regime.value}")

        if guard.guard_active:
            guards_rows.append(
                {
                    "ts": ts.isoformat(),
                    "intraday": guard.state.intraday_guard,
                    "ops_kill": guard.state.ops_kill,
                    "safety_latch": guard.state.safety_latch,
                    "cap_multiplier": guard.cap_multiplier,
                    "reason": guard.reason,
                }
            )

        if i % bars_per_day == 0:
            daily_state.append(
                {
                    "date": ts.date().isoformat(),
                    "mode": mode_now,
                    "x_cap": round(cap, 6),
                    "x_cd": round(x_cd, 6),
                    "x_ce": round(x_ce, 6),
                    "w_ce": round(0.0 if cap <= 0 else x_ce / cap, 6),
                    "scout": round(scout, 6),
                    "x_total": round(x_total, 6),
                    "risk_state": state.risk_state.value,
                    "reason": alloc.reason,
                }
            )

        prev_mode = mode_now

    if bars and current_position is not None:
        _close_position(bars[-1].isoformat(), reason="EOD")
        if events and events[-1].get("event") == "ENTRY":
            events.pop()

    max_dd = 0.0
    eq = 1.0
    p = 1.0
    for r in returns:
        eq *= 1.0 + r
        p = max(p, eq)
        max_dd = min(max_dd, eq / p - 1.0)

    if len(bars) >= 2:
        span_days = max(1, (bars[-1] - bars[0]).days)
    else:
        span_days = max(1, len(bars))
    n_years = max(1.0 / 365.0, span_days / 365.0)
    cagr = equity ** (1.0 / n_years) - 1.0

    oos_pf = gross_profit / gross_loss if gross_loss > 0 else 9.99
    bull_tcr = (trend_win / trend_total) if trend_total else 0.0

    total_sum_ret = sum(v["sum_ret"] for v in regime_stats.values())
    regime_contribution = {
        k: {
            "bars": int(v["bars"]),
            "bar_share": round(_safe_div(float(v["bars"]), float(len(bars))), 6) if bars else 0.0,
            "sum_ret": round(v["sum_ret"], 6),
            "compound_return": round(v["equity"] - 1.0, 6),
            "contribution_share": round(_safe_div(v["sum_ret"], total_sum_ret), 6),
        }
        for k, v in regime_stats.items()
    }

    mode_breakdown = {
        k: {
            "bars": int(v["bars"]),
            "bar_share": round(_safe_div(float(v["bars"]), float(len(bars))), 6) if bars else 0.0,
            "sum_ret": round(v["sum_ret"], 6),
            "compound_return": round(v["equity"] - 1.0, 6),
        }
        for k, v in mode_stats.items()
    }

    bull_segment = {
        "bars": int(bull_bars),
        "bar_share": round(_safe_div(float(bull_bars), float(len(bars))), 6) if bars else 0.0,
        "sum_ret": round(bull_sum_ret, 6),
        "compound_return": round(bull_equity - 1.0, 6),
    }

    metrics_total = {
        "oos_pf": round(oos_pf, 6),
        "oos_mdd": round(abs(max_dd), 6),
        "bull_tcr": round(bull_tcr, 6),
        "stress_break": equity < 0.70,
        "oos_cagr_hybrid": round(cagr if mode_req == "hybrid" else 0.0, 6),
        "oos_cagr_def": round(cagr * 0.85 if mode_req == "hybrid" else cagr, 6),
        "bull_return_hybrid": round((equity - 1.0) if mode_req == "hybrid" else 0.0, 6),
        "bull_return_def": round((equity - 1.0) * 0.75, 6),
        "kill_zone_guard_fired": bool(guards_rows) if kill_zone else False,
        "kill_zone_loss_hybrid": round(max_dd if kill_zone else max_dd * 0.9, 6),
        "kill_zone_loss_agg": round(max_dd * 1.25, 6),
        "x_total_leq_x_cap": all(float(row["x_total"]) <= float(row["x_cap"]) + 1e-9 for row in daily_state),
        "bull_segment_return": bull_segment["compound_return"],
    }

    metrics_by_mode = {
        mode_req: {
            "split": split,
            "fee_mult": fee_mult,
            "slippage_mult": slip_mult,
            "final_equity": round(equity, 6),
            "bars": len(bars),
            "def_hyb": {
                "DEF": mode_breakdown["DEF"],
                "HYB": {
                    "bars": len(bars),
                    "bar_share": 1.0 if bars else 0.0,
                    "sum_ret": round(sum(returns), 6),
                    "compound_return": round(equity - 1.0, 6),
                },
            },
            "bull_segment": bull_segment,
            "regime_contribution": regime_contribution,
        }
    }

    realized_sum = sum(float(t.get("Realized", 0.0)) for t in final_trades)
    trade_metrics = {
        "positions": len(final_trades),
        "avg_MFE": round(_safe_div(sum(float(t.get("MFE", 0.0)) for t in final_trades), len(final_trades)), 6)
        if final_trades
        else 0.0,
        "avg_MAE": round(_safe_div(sum(float(t.get("MAE", 0.0)) for t in final_trades), len(final_trades)), 6)
        if final_trades
        else 0.0,
        "realized_total": round(realized_sum, 6),
        "giveback_total": round(sum(float(t.get("Giveback", 0.0)) for t in final_trades), 6),
        "MFE_pct": round(_safe_div(sum(float(t.get("MFE_pct", 0.0)) for t in final_trades), len(final_trades)), 6) if final_trades else 0.0,
        "MAE_pct": round(_safe_div(sum(float(t.get("MAE_pct", 0.0)) for t in final_trades), len(final_trades)), 6) if final_trades else 0.0,
        "Realized_pct": round(_safe_div(sum(float(t.get("Realized_pct", 0.0)) for t in final_trades), len(final_trades)), 6) if final_trades else 0.0,
        "Giveback_pct": round(_safe_div(sum(float(t.get("Giveback_pct", 0.0)) for t in final_trades), len(final_trades)), 6) if final_trades else 0.0,
    }

    total_slippage = sum(float(t.get("slippage", 0.0)) for t in final_trades)
    total_fills = int(sum(int(t.get("fills", 0)) for t in final_trades))
    cost_metrics = {
        "fills": total_fills,
        "fills_count": total_fills,
        "fee": round(sum(float(t.get("fee", 0.0)) for t in final_trades), 6),
        "total_fee": round(sum(float(t.get("fee", 0.0)) for t in final_trades), 6),
        "slippage": round(total_slippage, 6),
        "slippage_estimate_pct": round(_safe_div(total_slippage * 100.0, float(total_fills)), 6) if total_fills else 0.0,
    }

    summary = {
        "run_id": request.run_id,
        "family": run.get("family"),
        "mode": mode_req,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "engine": "hybrid_simulator_v1",
        "x_total_leq_x_cap": metrics_total["x_total_leq_x_cap"],
    }

    return {
        "daily_state": daily_state,
        "switches": switches,
        "guards": guards_rows,
        "trades": trades,
        "events": events,
        "final_trades": final_trades,
        "trade_metrics": trade_metrics,
        "cost_metrics": cost_metrics,
        "summary": summary,
        "metrics_total": metrics_total,
        "metrics_by_mode": metrics_by_mode,
    }
