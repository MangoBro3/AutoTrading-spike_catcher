import pandas as pd
import numpy as np
try:
    import streamlit as st
except Exception:
    st = None
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def calculate_advanced_metrics(base_result, stress_result=None):
    """
    Advanced metric pack for OOS judge.
    Expected input is the current backtester result dict:
      {
        total_return, trades, win_rate, trade_list=[{return, max_dd, exit_date, ...}]
      }
    """
    if not isinstance(base_result, dict):
        return {
            "roi": 0.0,
            "mdd": 0.0,
            "trades": 0,
            "win_rate": 0.0,
            "roi_cost_1_0": 0.0,
            "roi_cost_1_5": 0.0,
            "cost_drop": 0.0,
            "worst_week": 0.0,
            "negative_weeks": 0,
            "positive_weeks": 0,
            "weekly_std": 0.0,
            "weekly_pnl": [],
        }

    trades = base_result.get("trade_list", []) or []
    roi_1_0 = _safe_float(base_result.get("total_return", 0.0), 0.0)
    trades_count = int(_safe_float(base_result.get("trades", len(trades)), len(trades)))
    win_rate = _safe_float(base_result.get("win_rate", 0.0), 0.0)

    mdd_vals = []
    rows = []
    for t in trades:
        try:
            mdd_vals.append(_safe_float(t.get("max_dd", 0.0), 0.0))
        except Exception:
            pass
        exit_dt = pd.to_datetime(t.get("exit_date"), errors="coerce")
        if pd.isna(exit_dt):
            continue
        rows.append({"exit_date": exit_dt, "ret": _safe_float(t.get("return", 0.0), 0.0)})

    mdd = min(mdd_vals) if mdd_vals else 0.0

    if rows:
        wdf = pd.DataFrame(rows).set_index("exit_date").sort_index()
        weekly_returns = wdf["ret"].resample("W").sum()
    else:
        weekly_returns = pd.Series(dtype="float64")

    worst_week = _safe_float(weekly_returns.min(), 0.0) if len(weekly_returns) > 0 else 0.0
    negative_weeks = int((weekly_returns < 0).sum()) if len(weekly_returns) > 0 else 0
    positive_weeks = int((weekly_returns > 0).sum()) if len(weekly_returns) > 0 else 0
    weekly_std = _safe_float(weekly_returns.std(ddof=1), 0.0) if len(weekly_returns) > 1 else 0.0
    weekly_pnl = [float(x) for x in weekly_returns.tolist()] if len(weekly_returns) > 0 else []

    roi_1_5 = roi_1_0
    if isinstance(stress_result, dict):
        roi_1_5 = _safe_float(stress_result.get("total_return", roi_1_0), roi_1_0)
    cost_drop = roi_1_0 - roi_1_5

    return {
        "roi": roi_1_0,
        "mdd": mdd,
        "trades": trades_count,
        "win_rate": win_rate,
        "roi_cost_1_0": roi_1_0,
        "roi_cost_1_5": roi_1_5,
        "cost_drop": cost_drop,
        "worst_week": worst_week,
        "negative_weeks": negative_weeks,
        "positive_weeks": positive_weeks,
        "weekly_std": weekly_std,
        "weekly_pnl": weekly_pnl,
    }


class Backtester:
    def __init__(self):
        pass

    def get_slippage_rate(self, turnover):
        """Tiered Slippage Policy (Conservative)"""
        if pd.isna(turnover) or turnover <= 0: return 0.005 # Default 0.5%
        if turnover < 200_000_000: return 0.005 # 0.5%
        if turnover < 800_000_000: return 0.003 # 0.3%
        if turnover < 2_000_000_000: return 0.002 # 0.2%
        return 0.001 # 0.1%

    def apply_cost(self, price: float, side: str, cost: float) -> float:
        """
        Apply transaction cost (slippage/fee) to execution price.
        
        Args:
            price: Raw market price
            side: "BUY" or "SELL"
            cost: Rate unit (e.g. 0.002 for 0.2%). MUST be >= 0.
            
        Returns:
            Executed price inclusive of cost.
            - BUY: price * (1 + cost)  [Price goes UP, unfavorable]
            - SELL: price * (1 - cost) [Price goes DOWN, unfavorable]
        """
        side = side.upper()
        if side not in ("BUY", "SELL"): raise ValueError(f"Invalid side: {side}")
        if cost < 0: raise ValueError(f"Cost must be non-negative rate: {cost}")
        
        return price * (1 + cost) if side == "BUY" else price * (1 - cost)

    def determine_regime(self, row, ma_short, ma_long, volatility):
        """
        Determine Market Regime based on BTC/Benchmark.
        Returns: 'Bull', 'Bear', 'Crash', 'Sideways'
        """
        if pd.isna(row['close']): return 'Neutral'
        
        price = row['close']
        
        # Crash Check: High Volatility + Downside
        # Simple definition: Price < MA_Short AND Daily Drop > 3%? 
        # Or RSI < 30?
        # Let's use simple Trend + Vol check provided by args
        
        # 1. Trend
        is_bull = price > ma_long
        
        # 2. Crash / Panic
        # If daily return < -5% or drawdown from recent high is huge?
        # Let's use simple logic for v1:
        # Crash: Price < MA_Long AND (Price < MA_Short * 0.9) ? (Sudden drop)
        
        if not is_bull:
            if price < ma_short * 0.92: # 8% below short MA -> Panic dump
                return 'Crash'
            return 'Bear'
        
        # If Bull
        if price < ma_short:
             return 'Sideways' # Bull trend but short term dipping
             
        return 'Bull'

    def run_portfolio(self, symbol_dfs, params, start_date=None, end_date=None, ml_model=None, benchmark_df=None, verbose=True, debug=False, cost_multiplier=1.0):
        """
        Portfolio Backtest Engine (Phase 0 SSOT Compliant)
        - Final Trades: One row per trade lifecycle (entry to full exit).
        - Events: Partial exits, signal updates.
        - Candidates Debug: Full log of daily screening.
        - ML Ranking: If ml_model is provided, use it to re-rank candidates.
        - Phase 3: Regime-based Param Adaptation (requires benchmark_df)
        - debug: If True, prints daily signals and entries (scrolling). If False, only progress bar (if installed).
        """
        # 1. Setup Base Params
        base_params = params.copy()
        p_cost_mul = max(0.0, _safe_float(cost_multiplier, 1.0))
        
        # Helper to get current param (with regime override)
        def get_param(key, current_regime='Neutral'):
            # Check regime overrides
            # expecting params['regime_overrides'] = {'Crash': {'max_open_positions': 0}, ...}
            overrides = base_params.get('regime_overrides', {})
            if current_regime in overrides and key in overrides[current_regime]:
                return overrides[current_regime][key]
            return base_params.get(key)

        # Initial Load (Default 'Neutral')
        p_alloc_A = base_params.get('allocation_A_pct', 60) / 100
        # ... (We will reload these inside day loop if Dynamic)

        p_alloc_A = params.get('allocation_A_pct', 60) / 100
        p_alloc_B = params.get('allocation_B_pct', 40) / 100
        p_max_entries = params.get('max_entries_per_day', 2)
        p_max_pos = params.get('max_open_positions', 3)
        p_cooldown = params.get('cooldown_days_after_sl', 5)
        p_loss_limit = params.get('daily_loss_limit_pct', 2.0) / 100
        p_min_turnover = params.get('min_turnover_krw', 100_000_000)
        
        if verbose:
            print(f"[BT Params] MinTurnover: {p_min_turnover:,.0f}, UnivTopN: {params.get('universe_top_n', 0)}, MaxPos: {p_max_pos}")
        
        # Strategy A
        p_sl_mul_A = params.get('sl_atr_mult_A', 1.8)
        p_tp_r_A = params.get('partial_tp_r_A', 1.2)
        p_trail_mul_A = params.get('trail_atr_mult_A', 2.5)
        p_time_A = params.get('time_stop_days_A', 3)
        
        # Strategy B
        p_sl_mul_B = params.get('sl_atr_mult_B', 1.4)
        p_tp_r_B = params.get('partial_tp_r_B', 1.0)
        p_time_B = params.get('max_hold_days_B', 5)

        # 2. Data Alignment
        all_dates = set()
        for df in symbol_dfs.values():
            if not df.empty:
                if 'datetime' in df.columns:
                    all_dates.update(pd.to_datetime(df['datetime']))
                else:
                    all_dates.update(df.index)
        
        full_dates = sorted(list(all_dates))
        
        # Date Range Filter
        if start_date:
            full_dates = [d for d in full_dates if d >= pd.to_datetime(start_date)]
        if end_date:
            full_dates = [d for d in full_dates if d <= pd.to_datetime(end_date)]
            
        dates = full_dates
        
        aligned_dfs = {}
        for sym, df in symbol_dfs.items():
            if df.empty: continue
            df = df[~df.index.duplicated(keep='first')]
            if 'datetime' in df.columns:
                df = df.set_index('datetime')
            # Avoid pandas FutureWarning on silent downcasting during ffill.
            with pd.option_context('future.no_silent_downcasting', True):
                aligned = df.reindex(dates).ffill()
            aligned_dfs[sym] = aligned.infer_objects(copy=False)
            
        # 3. State Variables
        active_positions = [] 
        closed_trades = []      # Final Trades (SSOT)
        events_list = []        # Events (Partial TP, etc.)
        daily_debug = {}        # Debug Log
        cooldowns = {}          # symbol -> release_idx
        
        cumulative_return = 0.0 # Portfolio Equity Tracker (Simple sum of returns for now, or compound?)
        # Spec says "final PnL in final_trades". We'll calculate portfolio metrics from that later.

        # Loop Variables
        daily_pnl = 0
        cumulative_return = 0
        
        p_universe_top_n = params.get('universe_top_n', 0) # 0 means disabled
        
        # --- Progress Bar Logic ---
        iterator = dates
        # Use tqdm if installed. If verbose is False, we might still want progress? 
        # Usually yes. Let's enable it by default if debug is OFF.
        # If debug is ON, tqdm might interfere (though tqdm.write helps).
        use_tqdm = (tqdm is not None)
        if use_tqdm:
            iterator = tqdm(dates, desc="Backtesting", unit="day")
        
        for t_idx, current_date in enumerate(iterator):
            if t_idx == 0: continue # Need T-1 for signals
            
            # Init Buffers on first run
            if t_idx == 1:
                self.universe_debug_log = []
                self.rejection_counts = {}

            # --- Phase 3: Regime Detection ---
            current_regime = 'Neutral'
            if benchmark_df is not None and t_idx < len(benchmark_df):
                 # Use T-1 for decision (No Lookahead)
                 # Or use T Close? Close is available at EOD.
                 # Actually, we need Regime for T's *Entry*. We know T-1 Close.
                 # Let's use T-1.
                 try:
                     btc_row = benchmark_df.loc[dates[t_idx-1]]
                     # Need MA/Vol pre-calc? Assumed passed in btc_df
                     # If btc_df has cols: ma_fast, ma_slow, vol
                     ma_short = btc_row.get('ma_fast', btc_row['close'])
                     ma_long = btc_row.get('ma_slow', btc_row['close'])
                     # We can calc on fly if needed but slow. Assume pre-calc.
                     current_regime = self.determine_regime(btc_row, ma_short, ma_long, 0)
                 except: pass
            
            # Refresh Params based on Regime (Safe Get)
            p_alloc_A = (get_param('allocation_A_pct', current_regime) or 60) / 100
            p_alloc_B = (get_param('allocation_B_pct', current_regime) or 40) / 100
            p_max_entries = get_param('max_entries_per_day', current_regime) or 2
            p_max_pos = get_param('max_open_positions', current_regime) or 3
            p_loss_limit = (get_param('daily_loss_limit_pct', current_regime) or 2.0) / 100
            
            day_pnl = 0
            
            # --- A. Manage Active Positions ---
            # State Machine: Check SL -> TP -> Trail -> Time
            # 4. Select Candidates (Filter by Signal)
            candidates = []
            
            # Debug: Count potential signals before filtering
            signal_count_db = 0
            
            day_slice = {s: df.loc[current_date] for s, df in aligned_dfs.items() if current_date in df.index}
            
            for sym, row in day_slice.items():
                # Check formatting/NaN
                if pd.isna(row['close']): continue
                
                # Check signal
                if row.get('signal_buy', False):
                    signal_count_db += 1
                    candidates.append(row)
            
            # Debug Print (Only for first few days or if signals found)
            # Debug Print (Only for first few days or if signals found)
            # Debug Print (Only for first few days or if signals found)
            if signal_count_db > 0 and debug:
                msg = f"[BT Debug] {current_date}: Found {signal_count_db} signals. Regime: {current_regime}"
                if use_tqdm: tqdm.write(msg)
                else: print(msg)
                
            # ML Ranking (Optional)
            
            remaining_positions = []
            day_pnl = 0.0 # For daily loss limit check
            
            for pos in active_positions:
                sym = pos['symbol']
                row = aligned_dfs[sym].loc[current_date]
                
                # Handling Missing Data
                if pd.isna(row['open']):
                    pos['days_held'] += 1
                    remaining_positions.append(pos)
                    continue
                
                # Market Data
                high, low, open_p, close = row['high'], row['low'], row['open'], row['close']
                atr = row.get('atr', 0)
                
                # Track Max DD
                dd = (low - pos['entry_price']) / pos['entry_price']
                if dd < pos['max_dd']: pos['max_dd'] = dd
                
                pos['days_held'] += 1
                
                # Logic Triggers
                exit_signal = None
                exit_price = None
                
                # --- STAGE 4: Exit Logic (Sell) ---
                # 1. Stop Loss (Exact hit check) - PESSIMISTIC: Check SL FIRST
                
                # Re-fetch T-1 for Exit Cost (same as entry)
                prev_date = dates[t_idx-1]
                try: ref_turnover_exit = aligned_dfs[sym].loc[prev_date]['turnover']
                except: ref_turnover_exit = 0
                
                slip_exit = self.get_slippage_rate(ref_turnover_exit) * p_cost_mul

                # Prioritize SL over TP (Conservative)
                sl_triggered = False
                
                # A. Stop Loss
                if low <= pos['sl_price']:
                    exit_signal = "SL"
                    sl_triggered = True
                    
                    # Gap Logic: If Open < SL, we gap down. Execution at Open.
                    if open_p < pos['sl_price']:
                        raw_exit = open_p
                    else:
                        raw_exit = pos['sl_price']
                        
                    # Apply Cost (SELL -> Price DOWN)
                    exit_price = self.apply_cost(raw_exit, "SELL", slip_exit)
                    
                    cooldowns[sym] = t_idx + p_cooldown
                
                # B. Take Profit (Partial logic skipped for now, assuming Full Exit if TP hit?)
                # For V2.1 MVP, we stick to strict SL/Trail. TP is usually purely an event or partial.
                # If we wanted Full TP, it would go here.
                        
                # C. Trailing Stop (If activated)
                if not sl_triggered:
                   if low <= pos['trail_price']:
                       exit_signal = "Trail"
                       # Gap Check for Trail
                       if open_p < pos['trail_price']:
                           raw_exit = open_p
                       else:
                           raw_exit = pos['trail_price']
                       
                       exit_price = self.apply_cost(raw_exit, "SELL", slip_exit)

                # D. Time Exit
                if not exit_signal:
                    if pos['days_held'] >= pos['max_days']:
                         exit_signal = "Time"
                         # Time Exit: Execute at Close of T
                         raw_exit = close
                         exit_price = self.apply_cost(raw_exit, "SELL", slip_exit)
                
                # Final Execution Decision
                if exit_signal:
                    # Final PnL Calculation
                    # Total PnL = Realized_PnL (from partials) + (Exit - Entry)/Entry * Remaining_Size
                    
                    remaining_ret = (exit_price - pos['entry_price']) / pos['entry_price'] * pos['size']
                    total_ret = pos['realized_pnl'] + remaining_ret
                    
                    # Integrity Check: SL must be < 0 (unless Gap Up into SL? Impossible for Long)
                    final_reason = exit_signal
                    if exit_signal == "SL" and total_ret >= 0:
                        final_reason = "SL_Profit" 
                        
                    closed_trades.append({
                        'symbol': sym,
                        'strategy_tag': pos['tag'],
                        'entry_date': dates[pos['entry_idx']],
                        'entry_price': pos['entry_price'],
                        'exit_date': current_date,
                        'exit_price': exit_price,
                        'return': total_ret,
                        'reason': final_reason,
                        'hold_days': pos['days_held'],
                        'max_dd': pos['max_dd'],
                        'entry_rsi': pos['entry_rsi'],
                        'sl_price': pos['sl_price'], 
                        'exit_open': open_p, # For debug
                        'turnover_krw_entry': pos.get('turnover_entry', 0),
                        'turnover_krw_exit': ref_turnover_exit
                    })
                    
                    day_pnl += total_ret 
                    
                else:
                    # Not Exited -> Update Logic (Trail)
                    # Strategy specific logic
                    if 'A' in pos['tag']: mult = p_trail_mul_A
                    else: mult = 2.0 
                        
                    # Ratchet Trail Up
                    new_trail = close - mult * atr
                    if new_trail > pos['trail_price']:
                        pos['trail_price'] = new_trail
                        
                    remaining_positions.append(pos)
            
            active_positions = remaining_positions
            
            # --- B. Screening & Entry ---
            
            # Daily Loss Check (Stop entering if today is bad)
            # Simplification: If day_pnl < -Limit, skip entries
            if day_pnl < -p_loss_limit:
                # Log this constraint in debug?
                pass
                
            prev_date = dates[t_idx-1]
            candidates = []
            debug_candidates = [] # For daily_debug
            
            # --- Dynamic Universe (Phase 1.5) ---
            # Calc Top N Turnover for prev_date
            universe_set = None
            if p_universe_top_n > 0:
                # Gather all turnovers
                tos = []
                for sym, df in aligned_dfs.items():
                    if t_idx < len(df):
                        try: 
                             r = df.loc[prev_date]
                             tos.append((sym, r.get('turnover', 0)))
                        except: pass
                
                # Sort descending
                tos.sort(key=lambda x: float(x[1]) if pd.notna(x[1]) else 0, reverse=True)
                top_n = tos[:int(p_universe_top_n)]
                universe_set = set([x[0] for x in top_n])

                # Debug Universe for specific day (e.g. first day or specific date)
                if t_idx == 1 or current_date.day == 1: 
                     msg = f"[BT Debug Universe] {current_date}: Top 5 TO: {[ (x[0], f'{x[1]:,.0f}') for x in top_n[:5] ]}"
                     self.universe_debug_log.append(msg)
                     if 'GLOBAL_BTC' not in universe_set and any(x[0]=='GLOBAL_BTC' for x in tos):
                         btc_val = next((x[1] for x in tos if x[0]=='GLOBAL_BTC'), 0)
                         rank = next((i for i, x in enumerate(tos) if x[0]=='GLOBAL_BTC'), -1)
                         self.universe_debug_log.append(f"[BT Debug Universe] GLOBAL_BTC excluded! Rank: {rank}, Val: {btc_val:,.0f}")

            # Gather Candidates
            for sym, df in aligned_dfs.items():
                if t_idx >= len(df): continue
                try: prev_row = df.loc[prev_date]
                except KeyError: continue
                
                if pd.isna(prev_row['close']): continue
                
                # 4. Signals (Extract Score BEFORE Rejection for visibility)
                sig_A = prev_row.get('signal_A', False)
                sig_B = prev_row.get('signal_B', False)
                
                tag = None
                score = 0
                
                # Assign prelim score for logging
                if sig_A and params.get('enable_strategy_A', True):
                    tag = 'A'
                    score = prev_row.get('score_A', 0)
                elif sig_B and params.get('enable_strategy_B', True):
                    tag = 'B'
                    score = prev_row.get('score_B', 0)

                # Rejections
                rejection = None
                
                # 0. Universe Check
                if universe_set is not None and sym not in universe_set:
                    rejection = 'UniverseFilter'
                
                # 1. Turnover
                elif prev_row.get('turnover', 0) < p_min_turnover:
                    rejection = 'LowTurnover'
                
                # 2. Cooldown
                elif sym in cooldowns and t_idx < cooldowns[sym]:
                    rejection = 'Cooldown'
                    
                # 3. Existing Pos
                elif any(p['symbol'] == sym for p in active_positions):
                    rejection = 'Held'
                    
                if not rejection:
                    if not tag:
                        rejection = 'NoSignal'
                
                # Debug Print for failures
                if rejection and rejection != 'NoSignal':
                   # Count rejections
                   self.rejection_counts[rejection] = self.rejection_counts.get(rejection, 0) + 1
                   # Suppress immediate print to avoid clutter, user requested summary at end
                   # if debug:
                   #    msg = f"[BT Reject] {sym}: {rejection}. TO: {prev_row.get('turnover',0):,.0f}, Score: {score}"
                   #    if use_tqdm: tqdm.write(msg)
                   #    else: print(msg)

                # Debug Object
                c_obj = {
                    'symbol': sym,
                    'rejection': rejection,
                    'score': score,
                    'tag': tag,
                    'rsi': prev_row.get('rsi', 0),
                    'turnover': prev_row.get('turnover', 0),
                    'atr': prev_row.get('atr', 0)
                }
                debug_candidates.append(c_obj)
                
                if not rejection and tag:
                    candidates.append(c_obj)

            # Sanitize Candidates (Filter out NaNs)
            valid_candidates = []
            for c in candidates:
                sym = c['symbol']
                try:
                    row = aligned_dfs[sym].loc[current_date]
                    if pd.notna(row['open']) and pd.notna(row['close']):
                         valid_candidates.append(c)
                except:
                    pass
            candidates = valid_candidates

            # Debug: Candidate Count
            # Debug: Candidate Count
            if len(candidates) > 0:
                if debug: 
                    msg = f"[BT Debug] {current_date}: Candidates formed: {len(candidates)}"
                    if use_tqdm: tqdm.write(msg)
                    else: print(msg)
            elif signal_count_db > 0:
                 if debug: 
                    msg = f"[BT Debug] {current_date}: Signals found ({signal_count_db}) but 0 Candidates formed."
                    if use_tqdm: tqdm.write(msg)
                    else: print(msg)

            # --- ML Scoring ---
            if ml_model and candidates:
                # Predict scores
                try:
                    ml_scores = ml_model.predict(candidates)
                    for i, c in enumerate(candidates):
                        c['ml_score'] = ml_scores[i]
                except Exception as e:
                    # Fallback
                    for c in candidates: c['ml_score'] = 0.0
                
                # Sort by ML Score first, then Rule Score
                candidates.sort(key=lambda x: (x.get('ml_score', -999), x['score']), reverse=True)
            else:
                # Rule Sorting
                candidates.sort(key=lambda x: x['score'], reverse=True)

            debug_candidates.sort(key=lambda x: x['score'], reverse=True)
            
            # Save Debug Info (SSOT)
            daily_debug[current_date] = {
                'regime': current_regime,
                'candidates': debug_candidates
            }
            
            # Select Top N
            slots_avail = p_max_pos - len(active_positions)
            entries_today = 0
            
            for c in candidates:
                if slots_avail <= 0 or entries_today >= p_max_entries:
                    break
                    
                
                # Daily Loss Limit Check

                    
                if day_pnl < -p_loss_limit:
                    break
                
                sym = c['symbol']
                try: row = aligned_dfs[sym].loc[current_date]
                except: continue
                
                # Check for valid data
                if pd.isna(row['open']) or pd.isna(row['close']):
                    continue
                
                if debug:
                    msg = f"[BT Entry] Taking Trade: {sym} @ {current_date} Type: {c.get('tag')} Score: {c.get('score')}"
                    if use_tqdm: tqdm.write(msg)
                    else: print(msg)
                
                # --- STAGE 3: Strict Lookahead Check ---
                # Entry Execution: T(Open)
                # Cost Calculation: Must use T-1 Turnover (Known at T Open)
                
                raw_entry = row['open']
                
                # Fetch Previous Row for Cost Basis
                # We are at t_idx. Prev is t_idx - 1.
                # aligned_dfs are strictly indexed by 'dates'.
                # t_idx=0 is skipped in loop. t_idx >= 1.
                prev_date = dates[t_idx-1]
                try:
                    prev_row = aligned_dfs[sym].loc[prev_date]
                    # Use 'turnover' from T-1 (Raw or Exec, doesn't matter as long as it's T-1)
                    # Stage 1 added 'turnover_exec' (which is shift(1) of current).
                    # So row['turnover_exec'] == prev_row['turnover'].
                    # User requested explicit previous row usage for clarity.
                    ref_turnover = prev_row['turnover'] 
                except:
                    # Fallback if T-1 missing (should not happen due to alignment)
                    ref_turnover = 0 

                slip_rate = self.get_slippage_rate(ref_turnover) * p_cost_mul
                
                # Apply Cost: BUY -> Price Scales UP
                entry_price = self.apply_cost(raw_entry, "BUY", slip_rate)
                
                # TODO: Ensure PnL calc doesn't double-count fee if we baked it into price.
                # Currently, realized_pnl is (Exit - Entry) * Size. 
                # Since Entry is higher, PnL is lower. Correct.
                
                atr = c.get('atr_exec', c.get('atr', 0)) # Use Exec ATR if avail (Stage 1)
                
                # Logic Parameters (Based on Entry Price for Risk Check)
                if c['tag'] == 'A' or c.get('tag_exec') == 'A_Breakout':
                    # Use params relative to Entry
                    sl = entry_price - p_sl_mul_A * atr
                    tp = entry_price + p_tp_r_A * (entry_price - sl)
                    trail = entry_price - p_trail_mul_A * atr
                    max_d = p_time_A
                else:
                    sl = entry_price - p_sl_mul_B * atr
                    tp = entry_price + p_tp_r_B * (entry_price - sl)
                    trail = entry_price - 2.0 * atr 
                    max_d = p_time_B
                
                active_positions.append({
                    'symbol': sym,
                    'entry_date': current_date,
                    'entry_idx': t_idx,
                    'entry_price': entry_price,
                    'entry_rsi': c.get('rsi', 0),
                    'sl_price': sl,
                    'tp_price': tp,
                    'trail_price': trail,
                    'tp_hit': False,
                    'days_held': 0,
                    'max_days': max_d,
                    'tag': c.get('tag', 'Unknown'),
                    'max_dd': 0.0,
                    'size': 1.0,         
                    'realized_pnl': 0.0, 
                    'turnover_entry': ref_turnover # Store for debugging
                })
                
                slots_avail -= 1
                entries_today += 1
                
        # 5. Return Results
        
        # Unclosed positions?
        # Option: Force close at last price
        for pos in active_positions:
            # Mark as 'Holding' or force close
            # Spec doesn't strictly say, but usually force close for stats
            pass 
            # We omit them from 'final_trades' or mark as 'Open'?
            # Usually for backtest result, we force close.
            # Let's force close at last available price
            
            sym = pos['symbol']
            try:
                last_row = aligned_dfs[sym].iloc[-1]
                exit_price = last_row['close']
                current_date = last_row.name # Date index
            except:
                exit_price = pos['entry_price']
                current_date = dates[-1]
                
            remaining_ret = (exit_price - pos['entry_price']) / pos['entry_price'] * pos['size']
            total_ret = pos['realized_pnl'] + remaining_ret
            
            closed_trades.append({
                'symbol': sym,
                'strategy_tag': pos['tag'],
                'entry_date': dates[pos['entry_idx']],
                'entry_price': pos['entry_price'],
                'exit_date': current_date,
                'exit_price': exit_price,
                'return': total_ret,
                'reason': 'ForceClose',
                'hold_days': pos['days_held'],
                'max_dd': pos['max_dd'],
                'entry_rsi': pos['entry_rsi'],
                'sl_price': pos['sl_price'],
                'exit_open': exit_price,
                'turnover_krw_entry': pos.get('turnover_entry', 0),
                'turnover_krw_exit': 0
            })

        # Summary
        trades_df = pd.DataFrame(closed_trades)
        
        # Calculate Stats
        if trades_df.empty:
            tot_ret = 0.0
            win_rate = 0.0
        else:
            # Compounding with Portfolio Allocation Weighting
            # Avg exposure per trade ~= 1 / max_pos
            # Adjusted Return = Trade_Return * (1 / max_pos)
            # Portfolio_Growth = Product(1 + Adjusted_Return)
            
            # Note: This is an approximation. A full equity curve is better but requires day-by-day tracking.
            # Using simple scaling ensures we don't overestimate sequential compounding.
            
            weight = 1.0 / max(1, p_max_pos)
            tot_ret = (1 + trades_df['return'] * weight).prod() - 1
            
            win_rate = (trades_df['return'] > 0).mean()

        # --- Print Execution Summary at the End ---
        if verbose:
            print("\n" + "="*50)
            print("          BACKTEST EXECUTION SUMMARY")
            print("="*50)
            
            if hasattr(self, 'universe_debug_log') and self.universe_debug_log:
                print("\n[Universe Debug Logs]")
                for log in self.universe_debug_log[-20:]: # Show last 20
                    print(log)
                    
            if hasattr(self, 'rejection_counts'):
                print("\n[Rejection Statistics]")
                for reason, count in self.rejection_counts.items():
                    print(f" - {reason}: {count}")
                
            print("\n[Trade Execution]")
            # print(f"Total Signals Processed: {len(debug_candidates)}") # Variable scope issue, removed
            print(f"Executed Trades: {len(closed_trades)}")
            print("="*50 + "\n")

        return {
            'trades': len(trades_df),
            'total_return': tot_ret,
            'win_rate': win_rate,
            'trade_list': closed_trades,   # Mapped to 'final_trades'
            'event_list': events_list,
            'daily_debug': daily_debug
        }
