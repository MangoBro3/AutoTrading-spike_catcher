import pandas as pd
import numpy as np

class Strategy:
    def __init__(self):
        self.default_params = {
            'breakout_days_A': 7,
            'trigger_vol_A': 2.0,
            'close_confirm_pct_A': 0.005,
            'rsi_ceiling_A': 70,
            'max_gap_pct_A': 0.15,
            'use_regime_filter_A': True,
            'trend_ma_fast_B': 20,
            'trend_ma_slow_B': 60,
            'rsi_entry_B': 45,
            
            # Risk & Allocation Defaults
            'allocation_A_pct': 60,
            'allocation_B_pct': 40,
            'max_entries_per_day': 2,
            'max_open_positions': 3,
            'daily_loss_limit_pct': 2.0,
            'cooldown_days_after_sl': 3,
            'min_turnover_krw': 100000000,
            'universe_top_n': 50,

            # Anti-chase / re-entry (daily mode)
            'pump_high_pct_th': 0.15,
            'chase_ret_1d_th': 0.12,
            'chase_gap_pct_th': 0.08,
            'chase_ext_atr_k': 1.8,
            'chase_rsi_th': 78,
            'no_atr_gap_block_th': 0.01,
            'cooling_pullback_min': 0.06,
            'cooling_box_lookback': 5,
            'reentry_breakout_buffer': 0.002,
            'reentry_vol_mult': 1.2,
            'reentry_rsi_max': 72,
            'rearmed_ttl_days': 1,
            'reentry_score_boost': 1.15,
        }

    def calculate_rsi(self, series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-9) # Add a small epsilon to prevent division by zero
        return 100 - (100 / (1 + rs))

    def analyze(self, df, btc_df=None, params=None):
        if df.empty: return df
        if params is None: params = {}
        
        df = df.copy()
        epsilon = 1e-9

        # Normalize timestamp column for replay-safe state transitions.
        if 'datetime' in df.columns:
            df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
        else:
            try:
                df['datetime'] = pd.to_datetime(df.index, errors='coerce')
            except Exception:
                df['datetime'] = pd.NaT

        # --- 1. Common Indicators ---
        if 'vol_ma20' not in df.columns:
            df['vol_ma20'] = pd.to_numeric(df['volume'], errors='coerce').rolling(window=20).mean()
        if 'vol_spike' not in df.columns:
            df['vol_spike'] = pd.to_numeric(df['volume'], errors='coerce') / (df['vol_ma20'] + epsilon)
        if 'ret_1d' not in df.columns:
            df['ret_1d'] = pd.to_numeric(df['close'], errors='coerce').pct_change()
        if 'atr' not in df.columns:
            h = pd.to_numeric(df['high'], errors='coerce')
            l = pd.to_numeric(df['low'], errors='coerce')
            c = pd.to_numeric(df['close'], errors='coerce')
            prev_c = c.shift(1)
            tr = pd.concat([(h - l).abs(), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
            df['atr'] = tr.rolling(window=14).mean()
        if 'rsi' not in df.columns:
            df['rsi'] = self.calculate_rsi(df['close'])
             
        df['turnover'] = df['close'] * df['volume']
        df['gap_pct'] = (df['open'] / df['close'].shift(1) - 1).fillna(0)
        
        # BTC Returns for Correlation
        if btc_df is not None:
             pass 
        else:
             df['rel_strength'] = 0
             df['is_bear'] = False

        # --- 2. Strategy A: Breakout + Retest (Trend Following) ---
        p_bo_days_A = params.get('breakout_days_A', 7)
        p_trig_vol_A = params.get('trigger_vol_A', 2.0)
        p_confirm_A = params.get('close_confirm_pct_A', 0.005)
        p_delay_A = params.get('entry_delay_bars_A', 1)
        p_rsi_cap_A = params.get('rsi_ceiling_A', 70)
        p_gap_cap_A = params.get('max_gap_pct_A', 0.15)
        p_use_regime_filter_A = params.get('use_regime_filter_A', True)
        
        # A Logic
        # Breakout Level: Max High of last N days (shifted so we compare today's Close to PREVIOUS N days)
        df['bo_level_A'] = df['high'].shift(1).rolling(window=int(p_bo_days_A)).max()
        
        is_confirm = df['close'] >= df['bo_level_A'] * (1 + p_confirm_A)
        is_vol_ok = df['vol_spike'] >= p_trig_vol_A
        
        # Check Bear Market
        if p_use_regime_filter_A:
            is_regime_ok = ~df['is_bear'] 
        else:
            is_regime_ok = True 
        is_rsi_ok = df['rsi'] <= p_rsi_cap_A
        is_gap_ok = df['gap_pct'] <= p_gap_cap_A
        
        signal_confirm_A = (is_confirm & is_vol_ok & is_regime_ok & is_rsi_ok & is_gap_ok)
        
        # Entry Delay Logic (Enter at T+1 Open if T has signal)
        # If Delay=1, we check if T-1 had signal. But the Screener checks T.
        # So we just mark Signal at T.
        
        # To strictly match "Retest" or "Holding":
        # Simple Breakout: Signal at T.
        df['signal_A'] = signal_confirm_A
        
        # Score for ranking
        df['score_A'] = (df['vol_spike'] * (df['close'] / (df['bo_level_A']+epsilon)))
        df['tag_A'] = "A_Breakout"

        # --- 3. Strategy B: Pullback (Mean Reversion) ---
        p_ma_fast_B = params.get('trend_ma_fast_B', 20)
        p_ma_slow_B = params.get('trend_ma_slow_B', 60)
        p_rsi_entry_B = params.get('rsi_entry_B', 45)
        
        ma_fast = df['close'].rolling(window=int(p_ma_fast_B)).mean()
        ma_slow = df['close'].rolling(window=int(p_ma_slow_B)).mean()
        
        df['ma_fast'] = ma_fast
        
        is_uptrend = (df['close'] > ma_slow) & (ma_fast > ma_slow)
        # Pullback: RSI dipped below threshold recently (e.g. within last 3 days)
        is_pullback = (df['rsi'] <= p_rsi_entry_B).rolling(window=3).max().astype(bool)
        # Reclaim: Price > MA_Fast (Support held/reclaimed)
        is_reclaim = (df['close'] > ma_fast)
        
        df['signal_B'] = is_uptrend & is_pullback & is_reclaim
        df['score_B'] = ma_fast / (ma_slow+epsilon)
        df['tag_B'] = "B_Pullback"

        # --- 3.5 Anti-chase + Re-entry state machine (daily bar based) ---
        p_pump_high_pct_th = float(params.get('pump_high_pct_th', 0.15))
        p_chase_ret_1d_th = float(params.get('chase_ret_1d_th', 0.12))
        p_chase_gap_pct_th = float(params.get('chase_gap_pct_th', 0.08))
        p_chase_ext_atr_k = float(params.get('chase_ext_atr_k', 1.8))
        p_chase_rsi_th = float(params.get('chase_rsi_th', 78))
        p_no_atr_gap_block_th = float(params.get('no_atr_gap_block_th', 0.01))
        p_cooling_pullback_min = float(params.get('cooling_pullback_min', 0.06))
        p_cooling_box_lookback = max(3, int(params.get('cooling_box_lookback', 5)))
        p_reentry_breakout_buffer = float(params.get('reentry_breakout_buffer', 0.002))
        p_reentry_vol_mult = float(params.get('reentry_vol_mult', 1.2))
        p_reentry_rsi_max = float(params.get('reentry_rsi_max', 72))
        p_rearmed_ttl_days = max(1, int(params.get('rearmed_ttl_days', 1)))
        p_reentry_score_boost = float(params.get('reentry_score_boost', 1.15))

        state_penalty = {
            "NORMAL": 1.0,
            "PUMPED": 0.2,
            "COOLING": 0.45,
            "REARMED": 1.0,
            "CONSUMED": 0.35,
        }

        n = len(df)
        pump_state = np.array(["NORMAL"] * n, dtype=object)
        penalty_factor = np.ones(n, dtype=float)
        anti_chase_block = np.zeros(n, dtype=bool)
        anti_chase_reason = np.array([""] * n, dtype=object)
        reentry_signal = np.zeros(n, dtype=bool)
        reentry_reason = np.array([""] * n, dtype=object)
        cooling_box_high = np.full(n, np.nan, dtype=float)

        close_s = pd.to_numeric(df['close'], errors='coerce').to_numpy()
        high_s = pd.to_numeric(df['high'], errors='coerce').to_numpy()
        gap_s = pd.to_numeric(df['gap_pct'], errors='coerce').fillna(0.0).to_numpy()
        ret_s = pd.to_numeric(df['ret_1d'], errors='coerce').fillna(0.0).to_numpy()
        atr_s = pd.to_numeric(df['atr'], errors='coerce').to_numpy()
        ma_fast_s = pd.to_numeric(df['ma_fast'], errors='coerce').to_numpy()
        rsi_s = pd.to_numeric(df['rsi'], errors='coerce').to_numpy()
        vol_s = pd.to_numeric(df['volume'], errors='coerce').to_numpy()
        vol_ma_s = pd.to_numeric(df['vol_ma20'], errors='coerce').to_numpy()
        ts_s = pd.to_datetime(df['datetime'], errors='coerce')

        state = "NORMAL"
        peak_price = np.nan
        cooling_start_idx = -1
        rearmed_expires_at = None

        for i in range(n):
            cp = close_s[i]
            hp = high_s[i]
            gp = gap_s[i]
            ret = ret_s[i]
            atr = atr_s[i]
            ma_fast_i = ma_fast_s[i]
            rsi = rsi_s[i]
            vol = vol_s[i]
            vol_ma = vol_ma_s[i]
            ts = ts_s.iloc[i] if i < len(ts_s) else pd.NaT

            prev_close = close_s[i - 1] if i > 0 else np.nan
            high_spike = (hp / prev_close - 1.0) if (i > 0 and np.isfinite(prev_close) and prev_close > 0) else 0.0
            atr_ext = np.nan
            if np.isfinite(atr) and atr > 0 and np.isfinite(ma_fast_i):
                atr_ext = (cp - ma_fast_i) / (atr + epsilon)

            is_vol_ready = bool(np.isfinite(vol_ma) and vol_ma > 0)
            is_vol_ok = bool(is_vol_ready and np.isfinite(vol) and vol >= (vol_ma * p_reentry_vol_mult))

            is_chase_hot = bool(
                (high_spike >= p_pump_high_pct_th)
                or (ret >= p_chase_ret_1d_th)
                or (gp >= p_chase_gap_pct_th)
                or (np.isfinite(atr_ext) and atr_ext >= p_chase_ext_atr_k and np.isfinite(rsi) and rsi >= p_chase_rsi_th)
            )

            # Pump detection updates peak and enters/keeps pumped state.
            if is_chase_hot:
                if not np.isfinite(peak_price):
                    peak_price = hp
                elif np.isfinite(hp):
                    peak_price = max(peak_price, hp)
                if state in ("NORMAL", "CONSUMED", "COOLING"):
                    state = "PUMPED"
                    cooling_start_idx = -1
                    rearmed_expires_at = None

            if state == "PUMPED":
                if np.isfinite(hp):
                    peak_price = hp if not np.isfinite(peak_price) else max(peak_price, hp)
                pullback = ((peak_price - cp) / peak_price) if (np.isfinite(peak_price) and peak_price > 0) else 0.0
                if pullback >= p_cooling_pullback_min:
                    state = "COOLING"
                    cooling_start_idx = i

            if state == "COOLING":
                if cooling_start_idx < 0:
                    cooling_start_idx = i
                box_start = max(cooling_start_idx, i - p_cooling_box_lookback + 1)
                win = high_s[box_start:i + 1]
                box_high = float(np.nanmax(win)) if len(win) > 0 and np.isfinite(np.nanmax(win)) else np.nan
                cooling_box_high[i] = box_high
                breakout = bool(np.isfinite(box_high) and np.isfinite(cp) and cp >= box_high * (1.0 + p_reentry_breakout_buffer))
                rsi_ok = bool((not np.isfinite(rsi)) or (rsi <= p_reentry_rsi_max))
                if breakout and is_vol_ok and rsi_ok:
                    state = "REARMED"
                    reentry_signal[i] = True
                    reentry_reason[i] = f"rebreak_n{p_cooling_box_lookback}"
                    if pd.notna(ts):
                        rearmed_expires_at = ts + pd.Timedelta(days=p_rearmed_ttl_days)
                    else:
                        rearmed_expires_at = None

            elif state == "REARMED":
                # Keep re-entry window open until TTL expires (daily mode).
                if rearmed_expires_at is not None and pd.notna(ts) and ts >= rearmed_expires_at:
                    state = "CONSUMED"

            elif state == "CONSUMED":
                # Relax back to normal only after momentum cools down.
                if (not is_chase_hot) and gp < 0.02 and ret < 0.03:
                    state = "NORMAL"
                    peak_price = np.nan
                    cooling_start_idx = -1
                    rearmed_expires_at = None

            reason_parts = []
            blocked = False
            if state == "PUMPED":
                blocked = True
                reason_parts.append("pump_chase")
            elif state == "COOLING" and not reentry_signal[i]:
                blocked = True
                reason_parts.append("cooling_wait_rebreak")
            if (not np.isfinite(atr) or atr <= 0) and gp >= p_no_atr_gap_block_th and not reentry_signal[i]:
                blocked = True
                reason_parts.append("guard_no_atr_gap")

            anti_chase_block[i] = blocked
            anti_chase_reason[i] = ",".join(reason_parts)
            pump_state[i] = state
            penalty_factor[i] = state_penalty.get(state, 1.0)

        df['pump_state'] = pump_state
        df['penalty_factor'] = penalty_factor
        df['anti_chase_block'] = anti_chase_block
        df['anti_chase_reason'] = anti_chase_reason
        df['reentry_signal'] = reentry_signal
        df['reentry_reason'] = reentry_reason
        df['cooling_box_high'] = cooling_box_high

        # --- 4. Legacy Support (Safe Defaults) ---
        t_vol = params.get('trigger_vol', 2.5)
        bo_days = params.get('breakout_days', 7)
        
        rolling_high = df['high'].rolling(window=int(bo_days)).max().shift(1)
        is_breakout = df['close'] > rolling_high
        is_vol = df['vol_spike'] >= t_vol
        
        df['signal_action'] = is_breakout & is_vol
        base_signal_buy = df['signal_A'].astype(bool) | df['signal_B'].astype(bool)
        df['signal_buy_base'] = base_signal_buy
        df['signal_buy_reentry'] = df['reentry_signal'].astype(bool)
        df['signal_buy'] = (base_signal_buy | df['signal_buy_reentry']) & (~df['anti_chase_block'])
        
        # --- STAGE 1: Lookahead Removal (Execution Align) ---
        # Goal: Decisions at T(Open) must use only T-1 info.
        
        # 1. Turnover: Use T-1 Turnover for T(Open) Slippage
        df['turnover_exec'] = df['turnover'].shift(1).fillna(0)
        
        # 2. Signals: Use T-1 Close Signal for T(Open) Entry
        # Avoid pandas downcast warning by casting before fillna.
        sig = df['signal_buy']
        try:
            sig = sig.infer_objects(copy=False)
        except Exception:
            pass
        sig = sig.astype('boolean').shift(1).fillna(False)
        df['signal_buy_exec'] = sig.astype(bool)
        
        # 3. Ranking/Filters: Shift Score/Tag/ATR to T-1
        # Helper: Unified Score (Current Day)
        # Logic: If A fires, use A. Else B. (Priority A)
        base_score = pd.Series(
            np.where(df['signal_A'], df['score_A'], df['score_B']),
            index=df.index,
            dtype="float64",
        )
        reentry_score = pd.to_numeric(df['score_B'], errors='coerce').fillna(0.0) * p_reentry_score_boost
        score = pd.Series(
            np.where(df['reentry_signal'], reentry_score, base_score),
            index=df.index,
        )
        score = pd.to_numeric(score, errors='coerce').fillna(0.0)
        df['score'] = score * pd.to_numeric(df['penalty_factor'], errors='coerce').fillna(1.0)

        tag = np.where(df['signal_A'], df['tag_A'], df['tag_B'])
        tag = np.where(df['reentry_signal'], "B_ReEntry", tag)
        tag = np.where(df['anti_chase_block'] & (base_signal_buy | df['reentry_signal']), "CHASE_BLOCKED", tag)
        df['tag'] = tag
        
        # Shift
        df['score_exec'] = df['score'].shift(1).fillna(0)
        df['tag_exec'] = df['tag'].shift(1).fillna("None")
        df['atr_exec'] = df.get('atr', pd.Series(0, index=df.index)).shift(1).fillna(0)
        df['pump_state_exec'] = df['pump_state'].shift(1).fillna("NORMAL")
        df['penalty_factor_exec'] = df['penalty_factor'].shift(1).fillna(1.0)
        df['anti_chase_reason_exec'] = df['anti_chase_reason'].shift(1).fillna("")
        df['reentry_reason_exec'] = df['reentry_reason'].shift(1).fillna("")
        
        # Debug: Regimes should also be T-1? 
        # Backtester determines regime from Benmark T-1. 
        # If strategy uses internal regime filter, it uses 'is_bear' (Current T).
        # We should shift 'is_bear' if we want strictly T-1 regime filter.
        # But 'is_bear' is used inside 'signal_buy' calculation above.
        # Since we shift 'signal_buy' -> 'signal_buy_exec', the 'is_bear' effect is also shifted.
        # So we are consistent.
        
        return df

    def get_rejection_reasons(self, row, params):
        reasons = []
        # Simple debug reasons
        if not row.get('signal_A', False):
             if row.get('rsi', 50) > params.get('rsi_ceiling_A', 70): reasons.append("RSI과열")
        return reasons
