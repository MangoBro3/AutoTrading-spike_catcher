
import logging
import time
import json
import threading
import math
import pandas as pd
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("RunController")

class RunController:
    MODE_LIVE = "LIVE"
    MODE_PAPER = "PAPER"

    SAFETY_NORMAL = "NORMAL"
    SAFETY_WARNING = "WARNING"
    SAFETY_CRITICAL = "CRITICAL"

    STATE_FLAT = "FLAT"
    STATE_ENTRY_PENDING = "ENTRY_PENDING"
    STATE_IN_POSITION = "IN_POSITION"
    STATE_EXIT_PENDING = "EXIT_PENDING"
    STATE_SAFE_COOLDOWN = "SAFE_COOLDOWN"

    def __init__(self, adapter, ledger, watch_engine, notifier, mode=MODE_PAPER, disable_strategy: bool = False, execution_engine=None):
        self.adapter = adapter
        self.ledger = ledger
        self.watch_engine = watch_engine
        self.notifier = notifier
        self.mode = mode.upper()
        self.running = False
        self.disable_strategy = disable_strategy
        self.execution_engine = execution_engine

        # Persistent Trade State (P0)
        self.runtime_state_path = Path("results/runtime_state.json")
        self.state_lock = threading.RLock()
        self.cooldown_min = 15
        self.idempotency_ttl_candles = 2
        self.safe_cooldown_default_sec = 60
        self.panic_halt_sec = 3600
        self.runtime_state = self._load_runtime_state()
        self._startup_reconciled = False

        # Telemetry
        self.last_tick_ts = None
        self.last_error = None
        self.last_error_ts = None
        
        self.safety_level = self.SAFETY_NORMAL
        self.size_multiplier = 1.0

        # Latency Metrics
        self.latency_log = []
        
        # STAGE 10: Locking & Limits
        self.lock_file = Path("results/locks/bot.lock")
        self.max_daily_loss_pct = 0.05 # 5%
        self.consecutive_losses = 0
        self.max_consecutive_losses = 3
        self.daily_state_path = Path("results/daily_risk_state.json")
        self.daily_risk_state = self._load_daily_risk_state()
        
        # Register cleanup
        import atexit
        atexit.register(self._release_lock)

    def _acquire_lock(self, force=False):
        """
        Attempts to acquire a file lock.
        Strict Policy: If lock exists, ABORT unless force=True.
        """
        import os
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)

        def _pid_alive(pid_value):
            try:
                pid_int = int(pid_value)
                if pid_int <= 0:
                    return False
                # signal 0 checks process existence without sending a real signal.
                os.kill(pid_int, 0)
                return True
            except ProcessLookupError:
                return False
            except PermissionError:
                # Process exists but access is restricted.
                return True
            except Exception:
                return False
        
        if self.lock_file.exists():
            if force:
                logger.warning("[LOCK] Force flag detected. Overwriting existing lock.")
            else:
                try:
                    content = self.lock_file.read_text().strip().split(',')
                    old_pid = content[0] if len(content) >= 1 else "?"
                    if old_pid != "?" and not _pid_alive(old_pid):
                        logger.warning(f"[LOCK] Stale lock detected (PID {old_pid} not running). Removing stale lock.")
                        try:
                            self.lock_file.unlink(missing_ok=True)
                        except Exception as e:
                            logger.error(f"[LOCK] Failed to remove stale lock: {e}")
                            return False
                    else:
                        logger.error(f"[LOCK] Lock file exists (PID {old_pid}). ABORTING. Use --force-unlock to override.")
                        return False
                except Exception:
                    logger.error("[LOCK] Lock file exists and is unreadable. ABORTING.")
                    return False
        
        # Write Lock
        try:
            pid = os.getpid()
            ts = datetime.now().isoformat()
            self.lock_file.write_text(f"{pid},{ts},{self.mode}")
            logger.info(f"[LOCK] Acquired lock for PID {pid}")
            return True
        except Exception as e:
            logger.error(f"[LOCK] Failed to write lock: {e}")
            return False

    def _release_lock(self):
        """
        Idempotent lock release.
        """
        try:
            if self.lock_file.exists():
                import os
                # Only remove if it's OUR lock
                content = self.lock_file.read_text().strip().split(',')
                if len(content) >= 1 and int(content[0]) == os.getpid():
                    self.lock_file.unlink()
                    logger.info("[LOCK] Released lock.")
        except Exception as e:
            logger.error(f"[LOCK] Error releasing lock: {e}")

    def _today_key_local(self):
        return datetime.now().strftime("%Y-%m-%d")

    def _load_daily_risk_state(self):
        default = {
            "day": self._today_key_local(),
            "daily_start_equity": None,
            "intraday_peak_equity": None,
            "hard_stop_triggered": False,
            "last_trigger_reason": None,
            "updated_at": time.time(),
        }
        try:
            if self.daily_state_path.exists():
                raw = self.daily_state_path.read_text(encoding="utf-8")
                data = json.loads(raw) if raw else {}
                if isinstance(data, dict):
                    default.update(data)
        except Exception as e:
            logger.error(f"[RISK] Failed to load daily risk state: {e}")
        return default

    def _save_daily_risk_state(self):
        try:
            self.daily_state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.daily_state_path.with_suffix(".tmp")
            self.daily_risk_state["updated_at"] = time.time()
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.daily_risk_state, f)
            import os
            os.replace(tmp, self.daily_state_path)
        except Exception as e:
            logger.error(f"[RISK] Failed to save daily risk state: {e}")

    def _estimate_equity(self):
        try:
            state = self.ledger.get_state()
            v = state.get("equity")
            if v is not None:
                return float(v)
        except Exception:
            pass
        return None

    def _rollover_daily_state_if_needed(self, equity_now):
        today = self._today_key_local()
        if self.daily_risk_state.get("day") != today:
            self.daily_risk_state = {
                "day": today,
                "daily_start_equity": equity_now,
                "intraday_peak_equity": equity_now,
                "hard_stop_triggered": False,
                "last_trigger_reason": None,
                "updated_at": time.time(),
            }
            self._save_daily_risk_state()

    def _cancel_open_orders_best_effort(self):
        cancelled = 0
        try:
            orders = self.adapter.get_open_orders() if hasattr(self.adapter, "get_open_orders") else []
            client = getattr(self.adapter, "client", None)
            if client is None:
                return cancelled
            for order in orders or []:
                try:
                    oid = order.get("id")
                    sym = order.get("symbol")
                    if oid and sym:
                        client.cancel_order(oid, self._to_ccxt_symbol(sym))
                        cancelled += 1
                except Exception as e:
                    logger.warning(f"[RISK] cancel_order failed ({order}): {e}")
        except Exception as e:
            logger.warning(f"[RISK] cancel open orders check failed: {e}")
        return cancelled

    def _force_flatten_position_best_effort(self):
        try:
            state = self._get_runtime_state()
            symbol = state.get("symbol")
            qty = float(state.get("position_qty") or 0.0)
            if symbol and qty > 0:
                self.process_exit_signal(symbol=symbol, qty=qty, reason="EMERGENCY_DAILY_DD")
                return True
        except Exception as e:
            logger.error(f"[RISK] force flatten failed: {e}")
        return False

    def check_risk_limits(self):
        """Evaluates true daily drawdown on mark-to-market equity."""
        equity_now = self._estimate_equity()
        if equity_now is None or equity_now <= 0:
            return True

        self._rollover_daily_state_if_needed(equity_now)

        start_eq = self.daily_risk_state.get("daily_start_equity")
        peak_eq = self.daily_risk_state.get("intraday_peak_equity")
        if start_eq is None or start_eq <= 0:
            start_eq = equity_now
        if peak_eq is None or peak_eq <= 0:
            peak_eq = equity_now

        peak_eq = max(peak_eq, equity_now)
        self.daily_risk_state["daily_start_equity"] = float(start_eq)
        self.daily_risk_state["intraday_peak_equity"] = float(peak_eq)
        self._save_daily_risk_state()

        dd_from_start = (equity_now - start_eq) / start_eq
        dd_from_peak = (equity_now - peak_eq) / peak_eq

        if dd_from_start <= -self.max_daily_loss_pct:
            msg = (
                f"[RISK] Daily DD hard limit triggered! "
                f"eq={equity_now:,.0f}, start={start_eq:,.0f}, peak={peak_eq:,.0f}, "
                f"dd_start={dd_from_start*100:.2f}%, dd_peak={dd_from_peak*100:.2f}%"
            )
            self._trigger_emergency_stop(msg)
            return False

        return True

    def _trigger_emergency_stop(self, reason):
        logger.critical(reason)

        cancelled = self._cancel_open_orders_best_effort()
        flattened = self._force_flatten_position_best_effort()

        self.daily_risk_state["hard_stop_triggered"] = True
        self.daily_risk_state["last_trigger_reason"] = reason
        self._save_daily_risk_state()

        if self.mode == self.MODE_LIVE:
            self.mode = self.MODE_PAPER

        msg = (
            f"📉 **EMERGENCY STOP**\n"
            f"Reason: {reason}\n"
            f"Action: cancel_open_orders={cancelled}, flatten_attempt={flattened}, mode={self.mode}"
        )
        if self.notifier:
            self.notifier.emit_event("RISK", "SYSTEM", "STOP LOSS", msg, severity="CRITICAL")

    def perform_preflight_check(self, confirm_live: bool = False) -> bool:
        """
        Force user to acknowledge settings before start.
        """
        # STAGE 10: Check Lock first
        if not self._acquire_lock():
            print(" [ABORT] Could not acquire lock. Instance already running?")
            return False

        print("\n" + "="*50)
        print(" [PRE-FLIGHT CHECK] (TANK MODE ACTIVE)")
        print("="*50)
        print(f" 1. MODE          : {self.mode}")
        print(f" 2. EXCHANGE      : {self.adapter.__class__.__name__}")
        print(f" 3. TARGET MARKET : KRW Check (Spot Only)")
        print(f" 4. BTC TRADING   : BANNED (Indicator Only)")
        
        state = self.ledger.get_state()
        print(f" 5. SEED (Available): {state['baseline_seed']:,.0f} KRW")
        print(f" 6. TG NOTIFIER   : {'Ready' if self.notifier else 'DISABLED'}")
        print(f" 7. LOCK FILE     : {self.lock_file}")
        print("="*50)
        
        if self.mode == self.MODE_LIVE:
            if confirm_live:
                print(" [INFO] LIVE MODE - confirm_live flag set. Skipping interactive confirm.")
            else:
                confirm = input(" >>> CONFIRM START? (Type 'Y' to proceed): ").strip().upper()
                if confirm != 'Y':
                    print(" [ABORT] User cancelled.")
                    self._release_lock()
                    return False
        else:
            print(" [INFO] PAPER MODE - Skipping interactive confirm (Auto-Y)")
            
        print(" [OK] Pre-flight Passed.\n")
        return True

    def measure_latency(self, checkpoint_name):
        """
        Simple latency logger.
        """
        ts = time.time()
        self.latency_log.append((checkpoint_name, ts))
        # Keep log small
        if len(self.latency_log) > 100:
            self.latency_log.pop(0)

    def check_performance_degrade(self, history_df: pd.DataFrame) -> dict:
        """
        Circuit Breaker Logic.
        Input: DataFrame with columns ['pnl_pct', 'dt']
        """
        if history_df is None or len(history_df) < 3:
            return {'level': self.SAFETY_NORMAL, 'size_mult': 1.0}

        # Calculate metrics (Simple)
        wins = history_df[history_df['pnl_pct'] > 0]
        # CHECK: Consecutive losses
        # Get last 3 trades
        last_3 = history_df['pnl_pct'].tail(3).tolist()
        if len(last_3) == 3 and all(p < 0 for p in last_3):
             # Consecutive Loss Warning
             pass # Logic handles via Win Rate mostly, but explicit check good.

        win_rate = len(wins) / len(history_df)
        
        # Max Drawdown (Accumulated PnL)
        # We must assume starting equity is 1.0 to capture initial losses correctly
        cum_ret = (1 + history_df['pnl_pct']).cumprod()
        
        # Track running peak, ensuring it never drops below 1.0 (initial capital) if we want absolute DD from start
        # OR: Standard DD is Peak-to-Valley.
        # If we have [0.9, 0.81], Peak sequence should be [1.0, 1.0] ideally if we consider start.
        running_peak = cum_ret.cummax()
        # If the very first trade is a loss, running_peak will be < 1.0, which under-reports DD from seed.
        # Let's enforce peak >= 1.0 for safety (Seed Preservation View)
        running_peak = running_peak.clip(lower=1.0)
        
        dd = (cum_ret - running_peak) / running_peak
        max_dd = dd.min() # negative value

        result = {'level': self.SAFETY_NORMAL, 'size_mult': 1.0, 'reason': ''}

        # 1. Critical Check (Max DD < -15%)
        # STAGE 10 UPDATE: Also check max_daily_loss_pct from Ledger in main loop, 
        # but here we check historical stats.
        if max_dd < -0.15:
            result['level'] = self.SAFETY_CRITICAL
            result['size_mult'] = 0.0
            result['reason'] = f"Max DD {max_dd*100:.1f}% exceeds limit."
            
            # Action: Force Paper & Alert
            if self.mode == self.MODE_LIVE:
                msg = f"[CRITICAL] Circuit Breaker Triggered! {result['reason']} -> Switching to PAPER."
                logger.critical(msg)
                self.mode = self.MODE_PAPER # Downgrade
                
                if self.notifier:
                    self.notifier.emit_event("RISK", "SYSTEM", "CIRCUIT BREAKER", msg, severity="CRITICAL")

        # 2. Warning Check (Win Rate < 30%)
        elif win_rate < 0.30:
            result['level'] = self.SAFETY_WARNING
            result['size_mult'] = 0.5
            result['reason'] = f"Win Rate {win_rate*100:.1f}% too low."
            
        self.safety_level = result['level']
        self.size_multiplier = result['size_mult']
        return result

    def start(self):
        """
        Main Entry Point.
        """
        if not self.perform_preflight_check():
            logger.warning("Start Aborted.")
            return

        self.running = True
        
        # Notify Startup
        state = self.ledger.get_state()
        regime = self.watch_engine.current_regime
        
        msg = (
            f"🚀 **RUN START**\n"
            f"- Mode: {self.mode}\n"
            f"- Equity: {state['equity']:,.0f} KRW\n"
            f"- BTC Regime: {regime}\n"
            f"- PID: {Path(self.lock_file).read_text().split(',')[0] if self.lock_file.exists() else '?'}"
        )
        logger.info(msg.replace('\n', ' | '))
        
        if self.notifier:
            self.notifier.emit_event("SYSTEM", "ALL", "BOT STARTED", msg)

        # Main Loop would go here...
        # STAGE 10: Ensure check_risk_limits() is called in loop

    def stop(self):
        self.running = False
        msg = "🛑 **RUN STOPPED**"
        logger.info(msg)
        if self.notifier:
            self.notifier.emit_event("SYSTEM", "ALL", "BOT STOPPED", msg)
        
        # Release Lock
        self._release_lock()

    # ===== P0: Persistent State Machine =====
    def _default_runtime_state(self):
        return {
            "state": self.STATE_FLAT,
            "symbol": None,
            "position_qty": 0.0,
            "avg_entry_price": 0.0,
            "cumulative_fee": 0.0,
            "entry_candle_idx": None,
            "tp_stage": 0,
            "last_tp_candle_ts": None,
            "peak_vol_ratio": 0.0,
            "liq_collapse_bars": 0,
            "last_entry_ts": None,
            "last_exit_ts": None,
            "last_order_id": None,
            "safe_cooldown_until": 0.0,
            "cooldown_prev_state": self.STATE_FLAT,
            "active_keys": {}
        }

    def _load_runtime_state(self):
        default = self._default_runtime_state()
        data = {}
        try:
            if self.runtime_state_path.exists():
                raw = self.runtime_state_path.read_text()
                data = json.loads(raw) if raw else {}
        except Exception as e:
            logger.error(f"[STATE] Failed to read runtime_state: {e}")
            data = {}

        if not isinstance(data, dict):
            data = {}

        for key, val in default.items():
            data.setdefault(key, val)

        if data.get("state") not in {
            self.STATE_FLAT,
            self.STATE_ENTRY_PENDING,
            self.STATE_IN_POSITION,
            self.STATE_EXIT_PENDING,
            self.STATE_SAFE_COOLDOWN
        }:
            data["state"] = self.STATE_FLAT

        for key in [
            "position_qty",
            "avg_entry_price",
            "cumulative_fee",
            "peak_vol_ratio",
            "safe_cooldown_until",
        ]:
            try:
                data[key] = float(data.get(key) or 0.0)
            except Exception:
                data[key] = 0.0

        for key in [
            "tp_stage",
            "liq_collapse_bars",
        ]:
            try:
                data[key] = int(data.get(key) or 0)
            except Exception:
                data[key] = 0

        if data.get("cooldown_prev_state") not in {
            self.STATE_FLAT,
            self.STATE_IN_POSITION
        }:
            data["cooldown_prev_state"] = self.STATE_FLAT

        for key in ["last_entry_ts", "last_exit_ts"]:
            if data.get(key) is not None:
                try:
                    data[key] = float(data[key])
                except Exception:
                    data[key] = None

        for key in ["entry_candle_idx", "last_tp_candle_ts"]:
            if data.get(key) is not None:
                try:
                    data[key] = int(data[key])
                except Exception:
                    data[key] = None

        active_keys = data.get("active_keys")
        if not isinstance(active_keys, dict):
            active_keys = {}
        cleaned_keys = {}
        now = time.time()
        for key, meta in active_keys.items():
            if not isinstance(meta, dict):
                continue
            expire_ts = meta.get("expire_ts")
            try:
                expire_ts = float(expire_ts)
            except Exception:
                continue
            if expire_ts <= now:
                continue
            cleaned_keys[str(key)] = {
                "expire_ts": expire_ts,
                "created_ts": float(meta.get("created_ts") or now),
                "timeframe_sec": int(meta.get("timeframe_sec") or 60),
            }
        data["active_keys"] = cleaned_keys

        if data.get("state") == self.STATE_SAFE_COOLDOWN and data.get("safe_cooldown_until", 0.0) <= now:
            data["state"] = self.STATE_IN_POSITION if data.get("position_qty", 0.0) > 0 else self.STATE_FLAT

        return data

    def _save_runtime_state(self):
        try:
            self.runtime_state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.runtime_state_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.runtime_state, f)
            import os
            os.replace(tmp_path, self.runtime_state_path)
        except Exception as e:
            logger.error(f"[STATE] Failed to write runtime_state: {e}")

    def _update_runtime_state(self, **kwargs):
        with self.state_lock:
            self.runtime_state.update(kwargs)
            self._save_runtime_state()
            return dict(self.runtime_state)

    def _get_runtime_state(self):
        with self.state_lock:
            return dict(self.runtime_state)

    def _allowed_transitions(self):
        return {
            self.STATE_FLAT: {self.STATE_ENTRY_PENDING, self.STATE_SAFE_COOLDOWN},
            self.STATE_ENTRY_PENDING: {self.STATE_FLAT, self.STATE_IN_POSITION, self.STATE_SAFE_COOLDOWN},
            self.STATE_IN_POSITION: {self.STATE_EXIT_PENDING, self.STATE_SAFE_COOLDOWN},
            self.STATE_EXIT_PENDING: {self.STATE_IN_POSITION, self.STATE_FLAT, self.STATE_SAFE_COOLDOWN},
            self.STATE_SAFE_COOLDOWN: {self.STATE_FLAT, self.STATE_IN_POSITION, self.STATE_EXIT_PENDING},
        }

    def _transition_state(self, next_state, reason="", allow_same=False):
        with self.state_lock:
            cur = self.runtime_state.get("state", self.STATE_FLAT)
            if next_state == cur and allow_same:
                return True

            allowed = self._allowed_transitions().get(cur, set())
            if next_state not in allowed:
                logger.error(f"[STATE] Invalid transition {cur} -> {next_state} ({reason})")
                return False

            self.runtime_state["state"] = next_state
            self._save_runtime_state()
            logger.info(f"[STATE] {cur} -> {next_state} ({reason})")
            return True

    def _reconcile_transition(self, target_state, context="reconcile"):
        """
        Reconcile transition with no-skip rule preserved.
        """
        cur_state = self._get_runtime_state().get("state", self.STATE_FLAT)
        if cur_state == target_state:
            return True

        # Keep cooldown sticky until expiry.
        if cur_state == self.STATE_SAFE_COOLDOWN and target_state != self.STATE_SAFE_COOLDOWN:
            return False

        # Bridge transitions to respect mandatory state path.
        if cur_state == self.STATE_FLAT and target_state == self.STATE_IN_POSITION:
            if not self._transition_state(self.STATE_ENTRY_PENDING, reason=f"reconcile_bridge:{context}:flat_to_in"):
                return False
            return self._transition_state(self.STATE_IN_POSITION, reason=f"reconcile_target:{context}")

        if cur_state == self.STATE_IN_POSITION and target_state == self.STATE_FLAT:
            if not self._transition_state(self.STATE_EXIT_PENDING, reason=f"reconcile_bridge:{context}:in_to_flat"):
                return False
            return self._transition_state(self.STATE_FLAT, reason=f"reconcile_target:{context}")

        return self._transition_state(target_state, reason=f"reconcile_target:{context}", allow_same=True)

    def _safe_float(self, value, default=0.0):
        try:
            if value is None:
                return default
            return float(value)
        except Exception:
            return default

    def _safe_int(self, value, default=0):
        try:
            if value is None:
                return default
            return int(value)
        except Exception:
            return default

    def _parse_timeframe_seconds(self, timeframe):
        tf = str(timeframe or "1m").strip().lower()
        if not tf:
            return 60
        if tf.endswith("m"):
            return max(60, self._safe_int(tf[:-1], 1) * 60)
        if tf.endswith("h"):
            return max(60, self._safe_int(tf[:-1], 1) * 3600)
        if tf.endswith("d"):
            return max(60, self._safe_int(tf[:-1], 1) * 86400)
        if tf.endswith("s"):
            return max(1, self._safe_int(tf[:-1], 1))
        # Bare number -> minutes
        return max(60, self._safe_int(tf, 1) * 60)

    def _extract_signal_timeframe(self, signal):
        if not isinstance(signal, dict):
            return "1m"
        return (
            signal.get("timeframe")
            or signal.get("tf")
            or signal.get("bar_interval")
            or "1m"
        )

    def _extract_candle_ts(self, signal, timeframe_sec=None):
        timeframe_sec = max(1, int(timeframe_sec or 60))
        ts_candidates = []
        if isinstance(signal, dict):
            ts_candidates.extend([
                signal.get("candle_timestamp"),
                signal.get("candle_ts"),
                signal.get("bar_ts"),
                signal.get("timestamp"),
                signal.get("ts"),
            ])
        for value in ts_candidates:
            if value is None:
                continue
            try:
                ts = float(value)
                # Normalize ms/seconds
                if ts > 1e12:
                    ts = ts / 1000.0
                if ts <= 0:
                    continue
                return int(math.floor(ts / timeframe_sec) * timeframe_sec)
            except Exception:
                continue

        now = time.time()
        return int(math.floor(now / timeframe_sec) * timeframe_sec)

    def _build_idempotency_key(self, symbol, timeframe, candle_ts, side):
        return f"{symbol}_{timeframe}_{int(candle_ts)}_{side}"

    def _purge_expired_active_keys(self, now_ts=None):
        now_ts = self._safe_float(now_ts, time.time())
        with self.state_lock:
            active = self.runtime_state.get("active_keys")
            if not isinstance(active, dict):
                self.runtime_state["active_keys"] = {}
                self._save_runtime_state()
                return
            before = len(active)
            keys = list(active.keys())
            for key in keys:
                meta = active.get(key) or {}
                expire_ts = self._safe_float(meta.get("expire_ts"), 0.0)
                if expire_ts <= now_ts:
                    active.pop(key, None)
            if len(active) != before:
                self._save_runtime_state()

    def _active_key_exists(self, key):
        self._purge_expired_active_keys()
        with self.state_lock:
            active = self.runtime_state.get("active_keys") or {}
            return key in active

    def _claim_active_key(self, key, timeframe_sec, ttl_candles=None):
        ttl_candles = int(ttl_candles or self.idempotency_ttl_candles)
        ttl_candles = max(1, ttl_candles)
        now_ts = time.time()
        expire_ts = now_ts + (max(1, int(timeframe_sec)) * ttl_candles)
        with self.state_lock:
            self._purge_expired_active_keys(now_ts=now_ts)
            active = self.runtime_state.get("active_keys")
            if not isinstance(active, dict):
                active = {}
            if key in active:
                return False
            active[key] = {
                "created_ts": now_ts,
                "expire_ts": expire_ts,
                "timeframe_sec": int(timeframe_sec),
            }
            self.runtime_state["active_keys"] = active
            self._save_runtime_state()
            return True

    def _in_safe_cooldown(self):
        with self.state_lock:
            if self.runtime_state.get("state") != self.STATE_SAFE_COOLDOWN:
                return False
            until = self._safe_float(self.runtime_state.get("safe_cooldown_until"), 0.0)
        return time.time() < until

    def _release_safe_cooldown_if_due(self):
        with self.state_lock:
            if self.runtime_state.get("state") != self.STATE_SAFE_COOLDOWN:
                return
            until = self._safe_float(self.runtime_state.get("safe_cooldown_until"), 0.0)
            if time.time() < until:
                return
            target = self.STATE_IN_POSITION if self._safe_float(self.runtime_state.get("position_qty"), 0.0) > 0 else self.STATE_FLAT
        self._transition_state(target, reason="safe_cooldown_expired")

    def _enter_safe_cooldown(self, reason, cooldown_sec=None, preserve_position=True):
        cooldown_sec = self._safe_int(cooldown_sec, self.safe_cooldown_default_sec)
        cooldown_sec = max(1, cooldown_sec)
        with self.state_lock:
            cur = self.runtime_state.get("state", self.STATE_FLAT)
            qty = self._safe_float(self.runtime_state.get("position_qty"), 0.0)
            prev = self.STATE_IN_POSITION if preserve_position and qty > 0 else self.STATE_FLAT
            if cur == self.STATE_ENTRY_PENDING:
                prev = self.STATE_FLAT
            elif cur == self.STATE_EXIT_PENDING:
                prev = self.STATE_IN_POSITION if qty > 0 else self.STATE_FLAT
            self.runtime_state["cooldown_prev_state"] = prev
            self.runtime_state["safe_cooldown_until"] = time.time() + cooldown_sec
            self._save_runtime_state()

        # Transition with guard
        if cur != self.STATE_SAFE_COOLDOWN:
            self._transition_state(self.STATE_SAFE_COOLDOWN, reason=reason)
        logger.warning(f"[COOLDOWN] SAFE_COOLDOWN entered for {cooldown_sec}s ({reason})")

    def _to_ccxt_symbol(self, symbol: str) -> str:
        if not symbol:
            return symbol
        if "/" in symbol:
            return symbol
        if "-" in symbol:
            parts = symbol.split("-")
            if len(parts) == 2 and parts[0].upper() == "KRW":
                return f"{parts[1]}/KRW"
            if len(parts) == 2:
                return f"{parts[0]}/{parts[1]}"
        return symbol

    def _base_from_symbol(self, symbol: str):
        if not symbol:
            return None
        if symbol.startswith("UPBIT_"):
            symbol = symbol.replace("UPBIT_", "")
        if symbol.startswith("BITHUMB_"):
            symbol = symbol.replace("BITHUMB_", "")
        if "/" in symbol:
            return symbol.split("/")[0]
        if "-" in symbol:
            parts = symbol.split("-")
            if len(parts) == 2 and parts[0].upper() == "KRW":
                return parts[1]
            if len(parts) == 2:
                return parts[0]
        return None

    def _resolve_exchange_api(self, exchange_api=None):
        if exchange_api is not None:
            return exchange_api
        if getattr(self.adapter, "client", None) is not None:
            return self.adapter.client
        return self.adapter

    def _get_balance_map(self):
        try:
            if hasattr(self.adapter, "get_balances"):
                return self.adapter.get_balances() or {}
        except Exception:
            pass
        try:
            exchange_api = self._resolve_exchange_api()
            if hasattr(exchange_api, "fetch_balance"):
                raw = exchange_api.fetch_balance() or {}
                return raw.get("total", {}) or {}
        except Exception:
            pass
        return {}

    def _extract_qty(self, balances, currency):
        if not balances or not currency:
            return 0.0
        val = balances.get(currency, 0.0)
        if isinstance(val, dict):
            return float(val.get("total", 0.0) or 0.0)
        try:
            return float(val or 0.0)
        except Exception:
            return 0.0

    def _get_position_qty(self, symbol: str) -> float:
        balances = self._get_balance_map()
        base = self._base_from_symbol(symbol)
        return self._extract_qty(balances, base)

    def _get_krw_balance(self) -> float:
        balances = self._get_balance_map()
        if not balances:
            return 0.0
        krw = balances.get("KRW", 0.0)
        if isinstance(krw, dict):
            return float(krw.get("free", krw.get("total", 0.0)) or 0.0)
        try:
            return float(krw or 0.0)
        except Exception:
            return 0.0

    def _cooldown_active(self, symbol: str) -> bool:
        if not symbol:
            return False
        with self.state_lock:
            last_exit_ts = self.runtime_state.get("last_exit_ts")
            last_symbol = self.runtime_state.get("symbol")
        if not last_exit_ts or last_symbol != symbol:
            return False
        try:
            return (time.time() - float(last_exit_ts)) < (self.cooldown_min * 60)
        except Exception:
            return False

    def _reconcile_state_once(self, context="reconcile", symbol_override=None):
        symbol = symbol_override or self.runtime_state.get("symbol")
        if not symbol:
            return

        open_order = None
        try:
            if hasattr(self.adapter, "get_open_orders"):
                orders = self.adapter.get_open_orders() or []
                for order in orders:
                    if order.get("symbol") == symbol:
                        open_order = order
                        break
        except Exception as e:
            logger.warning(f"[STATE] Open order check failed ({context}): {e}")

        if open_order:
            transition_target = None
            with self.state_lock:
                current = self.runtime_state.get("state")
                if current in [self.STATE_ENTRY_PENDING, self.STATE_EXIT_PENDING]:
                    side = str(open_order.get("side", "")).lower()
                    new_state = self.STATE_EXIT_PENDING if side == "sell" else self.STATE_ENTRY_PENDING
                    self.runtime_state["last_order_id"] = open_order.get("id", self.runtime_state.get("last_order_id"))
                    self._save_runtime_state()
                    transition_target = new_state
            if transition_target is not None:
                self._transition_state(transition_target, reason=f"reconcile_open_order:{context}", allow_same=True)
                logger.info(f"[STATE] Reconcile ({context}): open order detected -> {transition_target}")
                return

        try:
            qty = self._get_position_qty(symbol)
        except Exception as e:
            logger.warning(f"[STATE] Reconcile failed ({context}): {e}")
            return

        transition_target = None
        prev_state = None
        with self.state_lock:
            current = self.runtime_state.get("state")
            prev_state = current
            desired = self.STATE_IN_POSITION if qty > 0 else self.STATE_FLAT
            cooldown_active = (
                current == self.STATE_SAFE_COOLDOWN
                and time.time() < self._safe_float(self.runtime_state.get("safe_cooldown_until"), 0.0)
            )

            saved_qty = self._safe_float(self.runtime_state.get("position_qty"), 0.0)
            qty_mismatch = abs(saved_qty - (qty if qty > 0 else 0.0)) > 1e-12
            should_update = (
                current in [self.STATE_ENTRY_PENDING, self.STATE_EXIT_PENDING]
                or (current != desired and not cooldown_active)
                or qty_mismatch
            )
            if should_update:
                self.runtime_state["position_qty"] = qty if qty > 0 else 0.0
                if qty <= 0:
                    self.runtime_state["avg_entry_price"] = 0.0
                    self.runtime_state["tp_stage"] = 0
                    self.runtime_state["entry_candle_idx"] = None
                    self.runtime_state["last_tp_candle_ts"] = None
                    self.runtime_state["peak_vol_ratio"] = 0.0
                    self.runtime_state["liq_collapse_bars"] = 0
                if symbol_override:
                    self.runtime_state["symbol"] = symbol_override
                self._save_runtime_state()
                transition_target = desired

        if transition_target is not None:
            if not (prev_state == self.STATE_SAFE_COOLDOWN and transition_target != self.STATE_SAFE_COOLDOWN):
                self._reconcile_transition(transition_target, context=context)
            logger.info(f"[STATE] Reconcile ({context}): {prev_state} -> {transition_target} qty={qty}")

    def _build_market_snapshot(self, symbol: str, exchange_api=None):
        exchange_api = self._resolve_exchange_api(exchange_api)
        price = None
        try:
            if exchange_api and hasattr(exchange_api, "fetch_ticker"):
                ccxt_symbol = self._to_ccxt_symbol(symbol)
                ticker = exchange_api.fetch_ticker(ccxt_symbol)
                price = ticker.get("last") or ticker.get("close")
        except Exception as e:
            logger.warning(f"[ENTRY] Failed to fetch ticker for {symbol}: {e}")

        balance = self._get_krw_balance()
        if price is None:
            return None
        return {"price": price, "balance": balance}

    def _ensure_execution_engine(self) -> bool:
        if self.execution_engine is not None:
            return True
        try:
            from .execution_engine import ExecutionEngine

            class _BudgetStub:
                def __init__(self):
                    self.bot_cash = 0.0

                def can_buy(self, required_krw, current_real_krw):
                    try:
                        if current_real_krw is None:
                            return True, "OK"
                        if float(required_krw) <= float(current_real_krw):
                            return True, "OK"
                        return False, f"REAL_BALANCE_INSUFFICIENT (Req:{required_krw:.0f} > Real:{current_real_krw:.0f})"
                    except Exception:
                        return True, "OK"

                def update_on_trade(self, side, symbol, price, qty, fee):
                    return None

            run_id = datetime.now().strftime("runtime_%Y%m%d_%H%M%S")
            log_dir = "results/logs"
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            self.execution_engine = ExecutionEngine(run_id, log_dir, _BudgetStub(), notifier=self.notifier)
            return True
        except Exception as e:
            logger.error(f"[STATE] Failed to init ExecutionEngine: {e}")
            return False

    def process_entry_signal(self, signal: dict, current_market_data: dict = None, exchange_api=None):
        """
        Entry path with state machine + persistence.
        """
        if not signal:
            return None
        symbol = signal.get("symbol")
        if not symbol:
            logger.warning("[ENTRY] BLOCK: empty symbol.")
            return None

        self._release_safe_cooldown_if_due()

        timeframe = self._extract_signal_timeframe(signal)
        timeframe_sec = self._parse_timeframe_seconds(timeframe)
        candle_ts = self._extract_candle_ts(signal, timeframe_sec=timeframe_sec)
        entry_key = self._build_idempotency_key(symbol, timeframe, candle_ts, "buy")

        with self.state_lock:
            state = self.runtime_state.get("state")
            if state == self.STATE_SAFE_COOLDOWN and time.time() < self._safe_float(self.runtime_state.get("safe_cooldown_until"), 0.0):
                logger.warning(f"[ENTRY] BLOCK: SAFE_COOLDOWN active (symbol={symbol})")
                return None
            if state != self.STATE_FLAT:
                logger.warning(f"[ENTRY] BLOCK: state={state} (symbol={symbol})")
                return None
            if self._cooldown_active(symbol):
                logger.warning(f"[ENTRY] BLOCK: post-exit cooldown active for {symbol}")
                return None

        if self._active_key_exists(entry_key):
            logger.warning(f"[ENTRY] BLOCK: idempotency key active ({entry_key})")
            return None
        if not self._claim_active_key(entry_key, timeframe_sec=timeframe_sec):
            logger.warning(f"[ENTRY] BLOCK: failed to claim idempotency key ({entry_key})")
            return None

        with self.state_lock:
            self.runtime_state["symbol"] = symbol
            self.runtime_state["last_order_id"] = None
            self._save_runtime_state()
        if not self._transition_state(self.STATE_ENTRY_PENDING, reason=f"entry_signal:{symbol}"):
            return None

        if not self._ensure_execution_engine():
            self._transition_state(self.STATE_FLAT, reason="entry_engine_init_fail")
            return None

        exchange_api = self._resolve_exchange_api(exchange_api)
        if current_market_data is None:
            current_market_data = self._build_market_snapshot(symbol, exchange_api)
        if not current_market_data:
            logger.warning(f"[ENTRY] BLOCK: market snapshot unavailable for {symbol}")
            self._reconcile_state_once(context="entry_snapshot_fail", symbol_override=symbol)
            with self.state_lock:
                if self.runtime_state.get("state") == self.STATE_ENTRY_PENDING:
                    self.runtime_state["position_qty"] = 0.0
                    self._save_runtime_state()
            self._transition_state(self.STATE_FLAT, reason="entry_snapshot_fail")
            return None

        try:
            order_res = self.execution_engine.execute_entry(
                signal,
                current_market_data,
                exchange_api=exchange_api
            )
        except Exception as e:
            logger.error(f"[ENTRY] Order error: {e}")
            order_res = None

        if order_res and bool(order_res.get("ok", False)):
            real_qty = self._safe_float(order_res.get("real_qty"), 0.0)
            real_vwap = self._safe_float(order_res.get("real_vwap"), 0.0)
            fee = self._safe_float(order_res.get("fee"), 0.0)
            if real_qty > 0:
                now_ts = time.time()
                with self.state_lock:
                    self.runtime_state.update({
                        "symbol": symbol,
                        "position_qty": real_qty,
                        "avg_entry_price": real_vwap,
                        "cumulative_fee": self._safe_float(self.runtime_state.get("cumulative_fee"), 0.0) + fee,
                        "last_entry_ts": now_ts,
                        "last_order_id": order_res.get("order_id"),
                        "entry_candle_idx": int(candle_ts // max(1, timeframe_sec)),
                        "tp_stage": 0,
                        "last_tp_candle_ts": None,
                        "peak_vol_ratio": max(0.0, self._safe_float(signal.get("vol_spike"), 0.0)),
                        "liq_collapse_bars": 0,
                    })
                    self._save_runtime_state()
                self._transition_state(self.STATE_IN_POSITION, reason=f"entry_filled:{symbol}")
                if bool(order_res.get("safe_cooldown", False)):
                    self._enter_safe_cooldown(
                        reason="entry_rate_limit",
                        cooldown_sec=order_res.get("safe_cooldown_sec"),
                        preserve_position=True,
                    )
                return order_res

        # Failure -> reconcile once, then revert if still pending
        self._reconcile_state_once(context="entry_fail", symbol_override=symbol)
        safe_cooldown = bool((order_res or {}).get("safe_cooldown", False))
        with self.state_lock:
            if self.runtime_state.get("state") == self.STATE_ENTRY_PENDING:
                self.runtime_state["position_qty"] = 0.0
                self.runtime_state["avg_entry_price"] = 0.0
                self.runtime_state["last_order_id"] = (order_res or {}).get("order_id")
                self._save_runtime_state()
        if safe_cooldown:
            self._enter_safe_cooldown(
                reason=f"entry_fail:{(order_res or {}).get('reason', 'unknown')}",
                cooldown_sec=(order_res or {}).get("safe_cooldown_sec"),
                preserve_position=False,
            )
        else:
            self._transition_state(self.STATE_FLAT, reason="entry_fail_recover")
        return None

    def process_exit_signal(self, symbol: str = None, qty=None, exchange_api=None, reason: str = None):
        """
        Exit path with real market sell execution.
        """
        self._release_safe_cooldown_if_due()

        prev_state = None
        with self.state_lock:
            state = self.runtime_state.get("state")
            active_symbol = self.runtime_state.get("symbol")
            if state not in {self.STATE_IN_POSITION, self.STATE_SAFE_COOLDOWN}:
                logger.warning(f"[EXIT] BLOCK: state={state}")
                return None
            if symbol is None:
                symbol = active_symbol
            if symbol != active_symbol:
                logger.warning(f"[EXIT] BLOCK: symbol mismatch (active={active_symbol}, req={symbol})")
                return None

            prev_state = state
            self.runtime_state["last_order_id"] = None
            self._save_runtime_state()

        if not self._transition_state(self.STATE_EXIT_PENDING, reason=f"exit_signal:{symbol}"):
            return None

        if not self._ensure_execution_engine():
            with self.state_lock:
                qty_snapshot = self._safe_float(self.runtime_state.get("position_qty"), 0.0)
            fallback = self.STATE_IN_POSITION if qty_snapshot > 0 else self.STATE_FLAT
            self._transition_state(fallback, reason="exit_engine_init_fail")
            return None

        exchange_api = self._resolve_exchange_api(exchange_api)
        if qty is None or str(qty).upper() == "ALL":
            qty = self._get_runtime_state().get("position_qty") or self._get_position_qty(symbol)

        try:
            qty = float(qty or 0.0)
        except Exception:
            qty = 0.0

        if qty <= 0:
            logger.warning(f"[EXIT] BLOCK: invalid qty for {symbol} ({qty})")
            self._reconcile_state_once(context="exit_invalid_qty", symbol_override=symbol)
            with self.state_lock:
                has_position = self._safe_float(self.runtime_state.get("position_qty"), 0.0) > 0
            fallback = self.STATE_IN_POSITION if has_position else self.STATE_FLAT
            self._transition_state(fallback, reason="exit_invalid_qty")
            return None

        try:
            order_res = self.execution_engine.create_market_sell_order(
                symbol,
                qty,
                exchange_api=exchange_api
            )
        except Exception as e:
            logger.error(f"[EXIT] Order error: {e}")
            order_res = None

        if order_res and bool(order_res.get("ok", False)):
            sold_qty = self._safe_float(order_res.get("real_qty"), 0.0)
            sold_fee = self._safe_float(order_res.get("fee"), 0.0)
            if sold_qty > 0:
                now_ts = time.time()
                final_state = self.STATE_IN_POSITION
                with self.state_lock:
                    current_qty = self._safe_float(self.runtime_state.get("position_qty"), 0.0)
                    remain_qty = max(0.0, current_qty - sold_qty)
                    self.runtime_state["position_qty"] = remain_qty
                    self.runtime_state["cumulative_fee"] = self._safe_float(self.runtime_state.get("cumulative_fee"), 0.0) + sold_fee
                    self.runtime_state["last_order_id"] = order_res.get("order_id")
                    if remain_qty <= 1e-12:
                        final_state = self.STATE_FLAT
                        self.runtime_state["last_exit_ts"] = now_ts
                        self.runtime_state["avg_entry_price"] = 0.0
                        self.runtime_state["entry_candle_idx"] = None
                        self.runtime_state["tp_stage"] = 0
                        self.runtime_state["last_tp_candle_ts"] = None
                        self.runtime_state["peak_vol_ratio"] = 0.0
                        self.runtime_state["liq_collapse_bars"] = 0
                    self._save_runtime_state()

                if final_state == self.STATE_FLAT:
                    self._transition_state(self.STATE_FLAT, reason=f"exit_filled:{reason or 'signal'}", allow_same=True)
                else:
                    self._transition_state(self.STATE_IN_POSITION, reason=f"exit_partial:{reason or 'signal'}", allow_same=True)

                if bool(order_res.get("safe_cooldown", False)):
                    self._enter_safe_cooldown(
                        reason="exit_rate_limit",
                        cooldown_sec=order_res.get("safe_cooldown_sec"),
                        preserve_position=self._safe_float(self._get_runtime_state().get("position_qty"), 0.0) > 0,
                    )
                return order_res

        # Failure -> reconcile once, then revert if still pending
        self._reconcile_state_once(context="exit_fail", symbol_override=symbol)
        with self.state_lock:
            has_position = self._safe_float(self.runtime_state.get("position_qty"), 0.0) > 0
        safe_cooldown = bool((order_res or {}).get("safe_cooldown", False))
        if safe_cooldown:
            self._enter_safe_cooldown(
                reason=f"exit_fail:{(order_res or {}).get('reason', 'unknown')}",
                cooldown_sec=(order_res or {}).get("safe_cooldown_sec"),
                preserve_position=has_position,
            )
        else:
            fallback = self.STATE_IN_POSITION if has_position else self.STATE_FLAT
            if prev_state == self.STATE_SAFE_COOLDOWN and has_position:
                fallback = self.STATE_IN_POSITION
            self._transition_state(fallback, reason="exit_fail_recover")
        return None

    def _get_unrealized_pnl_pct(self, symbol: str, exchange_api=None):
        if not symbol or not self._ensure_execution_engine():
            return 0.0
        exchange_api = self._resolve_exchange_api(exchange_api)
        avg_entry = self._safe_float(self._get_runtime_state().get("avg_entry_price"), 0.0)
        if avg_entry <= 0:
            return 0.0
        ba = self.execution_engine.get_best_bid_ask(symbol, exchange_api)
        if not ba or not ba.get("ok", False):
            return 0.0
        best_bid = self._safe_float(ba.get("best_bid"), 0.0)
        if best_bid <= 0:
            return 0.0
        return (best_bid - avg_entry) / avg_entry

    def process_tp_signal(
        self,
        symbol: str = None,
        tp_ratio: float = 0.01,
        sell_ratio: float = 0.25,
        expected_stage: int = None,
        signal: dict = None,
        exchange_api=None,
    ):
        """
        Bid-based partial TP with duplicate guard and idempotency key.
        """
        self._release_safe_cooldown_if_due()
        if not self._ensure_execution_engine():
            return None

        state = self._get_runtime_state()
        cur_state = state.get("state")
        if cur_state not in {self.STATE_IN_POSITION, self.STATE_SAFE_COOLDOWN}:
            return None

        active_symbol = state.get("symbol")
        symbol = symbol or active_symbol
        if not symbol or symbol != active_symbol:
            return None

        position_qty = self._safe_float(state.get("position_qty"), 0.0)
        if position_qty <= 0:
            return None

        exchange_api = self._resolve_exchange_api(exchange_api)
        ba = self.execution_engine.get_best_bid_ask(symbol, exchange_api)
        if not ba or not ba.get("ok", False):
            return None

        best_bid = self._safe_float(ba.get("best_bid"), 0.0)
        avg_entry = self._safe_float(state.get("avg_entry_price"), 0.0)
        if best_bid <= 0 or avg_entry <= 0:
            return None

        tp_ratio = max(0.0, self._safe_float(tp_ratio, 0.0))
        if best_bid < avg_entry * (1.0 + tp_ratio):
            return None

        current_stage = self._safe_int(state.get("tp_stage"), 0)
        expected_stage = self._safe_int(expected_stage, current_stage + 1)
        if current_stage != expected_stage - 1:
            logger.info(f"[TP] BLOCK: stage mismatch current={current_stage}, expected={expected_stage}")
            return None

        timeframe = self._extract_signal_timeframe(signal or {})
        timeframe_sec = self._parse_timeframe_seconds(timeframe)
        candle_ts = self._extract_candle_ts(signal or {}, timeframe_sec=timeframe_sec)
        if state.get("last_tp_candle_ts") == candle_ts:
            logger.info(f"[TP] BLOCK: duplicate trigger in candle {candle_ts}")
            return None

        tp_key = self._build_idempotency_key(symbol, timeframe, candle_ts, f"tp{expected_stage}_sell")
        if self._active_key_exists(tp_key):
            logger.info(f"[TP] BLOCK: idempotency key active {tp_key}")
            return None
        if not self._claim_active_key(tp_key, timeframe_sec=timeframe_sec):
            logger.info(f"[TP] BLOCK: failed to claim idempotency key {tp_key}")
            return None

        sell_ratio = min(1.0, max(0.0, self._safe_float(sell_ratio, 0.25)))
        sell_qty = position_qty * sell_ratio
        if sell_qty <= 0:
            return None

        if not self._transition_state(self.STATE_EXIT_PENDING, reason=f"tp_stage_{expected_stage}:{symbol}"):
            return None

        try:
            order_res = self.execution_engine.create_marketable_limit_sell_order(
                symbol=symbol,
                qty=sell_qty,
                exchange_api=exchange_api,
                aggressive_ticks=1,
                timeout_sec=3.0,
                params=None,
                force_refresh_market=False,
            )
        except Exception as e:
            logger.error(f"[TP] Sell error: {e}")
            order_res = None

        if order_res and bool(order_res.get("ok", False)):
            sold_qty = self._safe_float(order_res.get("real_qty"), 0.0)
            sold_fee = self._safe_float(order_res.get("fee"), 0.0)
            if sold_qty > 0:
                now_ts = time.time()
                final_state = self.STATE_IN_POSITION
                with self.state_lock:
                    cur_qty = self._safe_float(self.runtime_state.get("position_qty"), 0.0)
                    remain_qty = max(0.0, cur_qty - sold_qty)
                    self.runtime_state["position_qty"] = remain_qty
                    self.runtime_state["cumulative_fee"] = self._safe_float(self.runtime_state.get("cumulative_fee"), 0.0) + sold_fee
                    self.runtime_state["last_order_id"] = order_res.get("order_id")
                    self.runtime_state["tp_stage"] = expected_stage
                    self.runtime_state["last_tp_candle_ts"] = candle_ts
                    if remain_qty <= 1e-12:
                        final_state = self.STATE_FLAT
                        self.runtime_state["last_exit_ts"] = now_ts
                        self.runtime_state["avg_entry_price"] = 0.0
                        self.runtime_state["entry_candle_idx"] = None
                        self.runtime_state["peak_vol_ratio"] = 0.0
                        self.runtime_state["liq_collapse_bars"] = 0
                    self._save_runtime_state()
                self._transition_state(final_state, reason=f"tp_filled_stage_{expected_stage}", allow_same=True)
                if bool(order_res.get("safe_cooldown", False)):
                    self._enter_safe_cooldown(
                        reason="tp_rate_limit",
                        cooldown_sec=order_res.get("safe_cooldown_sec"),
                        preserve_position=(final_state == self.STATE_IN_POSITION),
                    )
                return order_res

        self._reconcile_state_once(context="tp_fail", symbol_override=symbol)
        has_position = self._safe_float(self._get_runtime_state().get("position_qty"), 0.0) > 0
        if bool((order_res or {}).get("safe_cooldown", False)):
            self._enter_safe_cooldown(
                reason=f"tp_fail:{(order_res or {}).get('reason', 'unknown')}",
                cooldown_sec=(order_res or {}).get("safe_cooldown_sec"),
                preserve_position=has_position,
            )
        else:
            self._transition_state(self.STATE_IN_POSITION if has_position else self.STATE_FLAT, reason="tp_fail_recover")
        return None

    def update_liquidity_ratio(self, current_vol_ratio: float):
        """
        Track peak volume ratio after entry and count consecutive collapse bars.
        """
        vol = max(0.0, self._safe_float(current_vol_ratio, 0.0))
        with self.state_lock:
            state = self.runtime_state.get("state")
            if state not in {self.STATE_IN_POSITION, self.STATE_SAFE_COOLDOWN}:
                return dict(self.runtime_state)
            peak = max(self._safe_float(self.runtime_state.get("peak_vol_ratio"), 0.0), vol)
            self.runtime_state["peak_vol_ratio"] = peak
            if peak > 0 and vol < (0.5 * peak):
                self.runtime_state["liq_collapse_bars"] = self._safe_int(self.runtime_state.get("liq_collapse_bars"), 0) + 1
            else:
                self.runtime_state["liq_collapse_bars"] = 0
            self._save_runtime_state()
            return dict(self.runtime_state)

    def process_panic_exit(self, symbol: str = None, exchange_api=None, hard_loss_cap: float = -0.05):
        """
        Panic exit when liquidity collapse persists for 2 bars.
        """
        self._release_safe_cooldown_if_due()
        if not self._ensure_execution_engine():
            return None

        state = self._get_runtime_state()
        if state.get("state") not in {self.STATE_IN_POSITION, self.STATE_SAFE_COOLDOWN}:
            return None
        if self._safe_int(state.get("liq_collapse_bars"), 0) < 2:
            return None

        symbol = symbol or state.get("symbol")
        if not symbol:
            return None

        qty = self._safe_float(state.get("position_qty"), 0.0)
        if qty <= 0:
            return None

        exchange_api = self._resolve_exchange_api(exchange_api)
        unrealized = self._get_unrealized_pnl_pct(symbol, exchange_api=exchange_api)

        if not self._transition_state(self.STATE_EXIT_PENDING, reason=f"panic_exit:{symbol}"):
            return None

        try:
            order_res = self.execution_engine.execute_panic_exit(
                symbol=symbol,
                qty=qty,
                exchange_api=exchange_api,
                unrealized_pnl_pct=unrealized,
                hard_loss_cap=hard_loss_cap,
            )
        except Exception as e:
            logger.error(f"[PANIC] Exit error: {e}")
            order_res = None

        if order_res and bool(order_res.get("halted", False)):
            self._enter_safe_cooldown(
                reason=f"panic_halt:{order_res.get('reason')}",
                cooldown_sec=self.panic_halt_sec,
                preserve_position=True,
            )
            if self.notifier:
                msg = f"[PANIC HALT] {symbol} unrealized={unrealized*100:.2f}% reason={order_res.get('reason')}"
                self.notifier.emit_event("RISK", "SYSTEM", "PANIC HALT", msg, severity="CRITICAL")
            return order_res

        if order_res and bool(order_res.get("ok", False)):
            sold_qty = self._safe_float(order_res.get("real_qty"), 0.0)
            sold_fee = self._safe_float(order_res.get("fee"), 0.0)
            final_state = self.STATE_IN_POSITION
            with self.state_lock:
                cur_qty = self._safe_float(self.runtime_state.get("position_qty"), 0.0)
                remain_qty = max(0.0, cur_qty - sold_qty)
                self.runtime_state["position_qty"] = remain_qty
                self.runtime_state["cumulative_fee"] = self._safe_float(self.runtime_state.get("cumulative_fee"), 0.0) + sold_fee
                self.runtime_state["last_order_id"] = order_res.get("order_id")
                if remain_qty <= 1e-12:
                    final_state = self.STATE_FLAT
                    self.runtime_state["last_exit_ts"] = time.time()
                    self.runtime_state["avg_entry_price"] = 0.0
                    self.runtime_state["entry_candle_idx"] = None
                    self.runtime_state["tp_stage"] = 0
                    self.runtime_state["last_tp_candle_ts"] = None
                    self.runtime_state["peak_vol_ratio"] = 0.0
                    self.runtime_state["liq_collapse_bars"] = 0
                self._save_runtime_state()

            self._transition_state(final_state, reason="panic_exit_filled", allow_same=True)
            if bool(order_res.get("safe_cooldown", False)):
                self._enter_safe_cooldown(
                    reason="panic_rate_limit",
                    cooldown_sec=order_res.get("safe_cooldown_sec"),
                    preserve_position=(final_state == self.STATE_IN_POSITION),
                )
            return order_res

        self._reconcile_state_once(context="panic_fail", symbol_override=symbol)
        has_position = self._safe_float(self._get_runtime_state().get("position_qty"), 0.0) > 0
        self._transition_state(self.STATE_IN_POSITION if has_position else self.STATE_FLAT, reason="panic_fail_recover")
        return None

    def process_time_stop(
        self,
        symbol: str = None,
        current_candle_idx: int = None,
        max_hold_bars: int = 0,
        target_profit: float = 0.0,
        exchange_api=None,
    ):
        """
        Bar-based time stop: exit if held too long and unrealized profit is below target.
        """
        self._release_safe_cooldown_if_due()
        state = self._get_runtime_state()
        if state.get("state") not in {self.STATE_IN_POSITION, self.STATE_SAFE_COOLDOWN}:
            return None

        symbol = symbol or state.get("symbol")
        if not symbol:
            return None

        entry_idx = state.get("entry_candle_idx")
        if entry_idx is None:
            return None
        if current_candle_idx is None:
            return None

        hold_bars = int(current_candle_idx) - int(entry_idx)
        if hold_bars <= int(max_hold_bars):
            return None

        unrealized = self._get_unrealized_pnl_pct(symbol, exchange_api=exchange_api)
        if unrealized >= self._safe_float(target_profit, 0.0):
            return None

        return self.process_exit_signal(
            symbol=symbol,
            qty="ALL",
            exchange_api=exchange_api,
            reason=f"TIME_STOP(hold={hold_bars}, pnl={unrealized:.5f})",
        )

    # STAGE 11: Main Loop & IPC
    def _execute_strategy(self):
        """
        Real Trading Logic (One Tick).
        1. Fetch Market Data (BTC)
        2. Update Regime
        3. (Ops) Update Safety/Risk
        """
        try:
            self.last_tick_ts = time.time()
            # 1. Fetch BTC OHLCV for Regime (Daily)
            # CCXT Symbols are usually 'BTC/KRW' for Upbit.
            # Adapter normalizes to KRW-BTC, but client needs CCXT symbol?
            # UpbitAdapter uses ccxt.upbit.
            # Let's try fetching 'KRW-BTC' and if fail 'BTC/KRW'.
            # Or safer: use self.adapter.client.fetch_ohlcv
            
            # Note: Upbit CCXT 'fetch_ohlcv' expects symbol.
            # Our adapter standard is KRW-BTC. CCXT usually handles it or wants BTC/KRW.
            # Proper way: Check adapter helper or try both.
            # We will try 'KRW-BTC' first (internal convention), then fallback to CCXT style 'BTC/KRW'.
            symbols_to_try = ["KRW-BTC", "BTC/KRW"]

            candles = None
            for symbol in symbols_to_try:
                try:
                    candles = self.adapter.client.fetch_ohlcv(symbol, timeframe='1d', limit=30)
                    if candles:
                        break
                except Exception:
                    candles = None
                    continue
            if not candles:
                return
                
            df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
            
            # 2. Update Regime
            regime = self.watch_engine.update_regime(df)
            
            # 3. (Optional) Score Candidates if Regime is ON
            # if regime == self.watch_engine.REGIME_RISK_ON:
            #     tickers = self.adapter.client.fetch_tickers()
            #     ...
            
        except Exception as e:
            logger.error(f"[Strategy] Tick Failed: {e}")
            self.last_error = str(e)
            self.last_error_ts = time.time()

    def _write_runtime_status(self, error=None):
        """
        Writes atomic JSON status for Launcher Dashboard.
        """
        import json
        import os
        
        current_state = "STOPPED"
        if error:
            current_state = "ERROR"
        elif self.running:
            current_state = "RUNNING"
            
        # Safely get ledger state
        ledger_state = {'equity': 0.0, 'total_pnl_pct': 0.0}
        try:
            if self.ledger:
                ledger_state = self.ledger.get_state()
        except:
            pass

        # Watch Info
        regime = "N/A"
        btc_price = 0.0
        try:
            if self.watch_engine:
                regime = self.watch_engine.current_regime
                btc_price = self.watch_engine.last_btc_price
        except:
            pass

        # Optional: expose watchlist for UI/debug
        watchlist = []
        try:
            if self.watch_engine and hasattr(self.watch_engine, "watchlist"):
                watchlist = list(self.watch_engine.watchlist)
        except:
            watchlist = []

        last_error = str(error) if error else self.last_error
        last_error_ts = time.time() if error else self.last_error_ts

        status_data = {
            'ts': time.time(),
            'pid': os.getpid(),
            'mode': self.mode,
            'status': current_state,
            'equity': ledger_state.get('equity', 0.0) or 0.0,
            # Ledger returns roi_pct as percent (e.g. 2.5). Store as ratio for dashboard (% = ratio*100).
            'pnl_pct': (ledger_state.get('roi_pct', 0.0) or 0.0) / 100.0,
            'regime': regime,
            'btc_price': btc_price,
            'watchlist': watchlist,
            'last_tick_ts': self.last_tick_ts,
            'last_error': last_error,
            'last_error_ts': last_error_ts
        }
        
        try:
            target_path = Path("results/runtime_status.json")
            tmp_path = target_path.with_suffix('.tmp')
            
            with open(tmp_path, 'w') as f:
                json.dump(status_data, f)
            
            os.replace(tmp_path, target_path)
        except Exception as e:
            logger.error(f"[IPC] Failed to write status: {e}")

    def run(self):
        """
        Main Trading Loop.
        """
        self.running = True
        logger.info(f"[RunController] Loop STARTED. Mode={self.mode}")

        if not self._startup_reconciled:
            try:
                self._reconcile_state_once(context="startup")
            finally:
                self._startup_reconciled = True
        
        last_tick = 0
        tick_interval = 60 # 1 minute
        
        try:
            while self.running:
                # Runtime hygiene for persistent execution controls.
                self._purge_expired_active_keys()
                self._release_safe_cooldown_if_due()

                # 1. Update Strategy (Throttle)
                if not self.disable_strategy and time.time() - last_tick > tick_interval:
                    self._execute_strategy()
                    last_tick = time.time()
                
                # 2. Check Safety & Limits (Every second)
                if not self.check_risk_limits():
                    logger.warning("[RunController] Risk Limit Triggered. Stopping Loop.")
                    self.running = False
                    break
                
                # 3. IPC Update
                self._write_runtime_status()
                time.sleep(1) 
                
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.critical(f"[RunController] CRASH detected: {e}\n{tb}")
            self.last_error = str(e)
            self.last_error_ts = time.time()
            
            try:
                Path("results/logs/crash_log.txt").write_text(f"Timestamp: {datetime.now()}\nError: {e}\nTraceback:\n{tb}\n" + "="*50 + "\n", encoding='utf-8')
            except:
                pass
                
            self._write_runtime_status(error=str(e))
            self.running = False
            time.sleep(5)
            
        finally:
            logger.info("[RunController] Loop STOPPED.")
            self._write_runtime_status()
            # Ensure lock is released even if stop() wasn't called
            self._release_lock()

