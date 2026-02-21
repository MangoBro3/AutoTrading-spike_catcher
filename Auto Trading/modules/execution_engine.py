import logging
import time
import threading
from datetime import datetime

from .logger_utils import CsvLogger

logger = logging.getLogger("ExecutionEngine")

# Global active symbol lock for race-safe entry blocking
_ACTIVE_SYMBOLS = set()
_ACTIVE_LOCK = threading.Lock()


class ExecutionEngine:
    def __init__(self, run_id, log_dir, budget_manager, notifier=None):
        self.run_id = run_id
        self.log_dir = log_dir
        self.budget_mgr = budget_manager
        self.notifier = notifier

        # Legacy gate values kept for compatibility with current signal payloads.
        self.MAX_SPREAD_BP = 50
        self.MIN_DEPTH_RATIO = 2.0
        self.MAX_CHASE_PCT = 3.0

        # Defensive execution defaults
        self.market_status_cache_ttl_sec = 60
        self.max_entry_slippage_pct = 0.01
        self.entry_timeout_sec = 10.0
        self.exit_timeout_sec = 3.0
        self.poll_interval_sec = 0.3
        self.backoff_factor = 1.5
        self.safe_cooldown_sec = 60

        self._market_status_cache = {}

        self.shadow_logger = CsvLogger(
            f"{log_dir}/shadow_entries.csv",
            [
                "timestamp",
                "symbol",
                "signal_price",
                "passed",
                "reason",
                "factor",
                "spread_bp",
                "depth_ratio",
                "chase_pct",
                "target_money",
            ],
        )
        self.exec_logger = CsvLogger(
            f"{log_dir}/execution_events.csv",
            [
                "timestamp",
                "symbol",
                "side",
                "event_type",
                "position_id",
                "price",
                "qty",
                "amount",
                "fee",
                "order_id",
                "reason",
            ],
        )

    def _to_ccxt_symbol(self, symbol):
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

    def _to_internal_symbol(self, symbol):
        if not symbol:
            return symbol
        if "-" in symbol:
            return symbol
        if "/" in symbol:
            base, quote = symbol.split("/")
            return f"{quote}-{base}"
        return symbol

    def _safe_float(self, value, default=0.0):
        try:
            if value is None:
                return default
            return float(value)
        except Exception:
            return default

    def _clamp_positive(self, value, min_value=0.0):
        val = self._safe_float(value, min_value)
        return max(min_value, val)

    def _is_rate_limit_error(self, error):
        txt = str(error).lower()
        return "429" in txt or "rate limit" in txt or "too many requests" in txt

    def get_tick_size(self, price):
        price = self._safe_float(price, 0.0)
        if price <= 0:
            return 1.0
        if price < 0.1:
            return 0.0001
        if price < 1:
            return 0.001
        if price < 10:
            return 0.01
        if price < 100:
            return 0.1
        if price < 1000:
            return 1
        if price < 10000:
            return 5
        if price < 100000:
            return 10
        if price < 500000:
            return 50
        if price < 1000000:
            return 100
        if price < 2000000:
            return 500
        return 1000

    def round_to_tick(self, price, tick_size, side="buy"):
        price = self._safe_float(price, 0.0)
        tick = self._safe_float(tick_size, 1.0)
        if price <= 0 or tick <= 0:
            return max(price, tick, 1.0)

        units = price / tick
        if side.lower() == "buy":
            rounded_units = int(units) if abs(units - int(units)) < 1e-12 else int(units) + 1
        elif side.lower() == "sell":
            rounded_units = int(units)
        else:
            rounded_units = int(round(units))

        rounded_price = rounded_units * tick
        if rounded_price <= 0:
            rounded_price = tick
        return rounded_price

    def check_gates(self, signal):
        spread_bp = signal.get("spread_bp", 0)
        depth_ratio = signal.get("ask_depth_sum", 0) / (signal.get("target_money", 1) + 1e-9)
        chase_pct = signal.get("chase_pct", 0)

        if spread_bp > self.MAX_SPREAD_BP:
            return False, f"SPREAD_TOO_WIDE ({spread_bp:.1f} > {self.MAX_SPREAD_BP})", 0.0
        if depth_ratio < self.MIN_DEPTH_RATIO:
            return False, f"DEPTH_INSUFFICIENT ({depth_ratio:.2f} < {self.MIN_DEPTH_RATIO})", 0.0
        if chase_pct > self.MAX_CHASE_PCT:
            return False, f"CHASE_TOO_HIGH ({chase_pct:.2f}% > {self.MAX_CHASE_PCT}%)", 0.0
        return True, "PASS", 1.0

    def _extract_market_status(self, market):
        info = market.get("info", {}) if isinstance(market, dict) else {}
        state = (
            market.get("state")
            or info.get("market_state")
            or info.get("state")
            or info.get("status")
            or "ACTIVE"
        )
        warning = (
            market.get("warning")
            or info.get("market_warning")
            or info.get("warning")
            or info.get("marketWarning")
            or "NONE"
        )
        active = bool(market.get("active", True))
        return str(state).upper(), str(warning).upper(), active

    def _check_market_status(self, exchange_api, ccxt_symbol, force_refresh=False):
        cache_key = ccxt_symbol
        now = time.time()
        cached = self._market_status_cache.get(cache_key)
        if cached and (not force_refresh) and (now - cached["ts"] <= self.market_status_cache_ttl_sec):
            return cached

        status = {
            "ok": False,
            "active": False,
            "state": "UNKNOWN",
            "warning": "UNKNOWN",
            "reason": "MARKET_STATUS_UNAVAILABLE",
            "ts": now,
        }

        try:
            markets = None
            if hasattr(exchange_api, "load_markets"):
                markets = exchange_api.load_markets()
            market = None
            if markets and isinstance(markets, dict):
                market = markets.get(ccxt_symbol)
            if market is None and hasattr(exchange_api, "market"):
                try:
                    market = exchange_api.market(ccxt_symbol)
                except Exception:
                    market = None
            if market is None:
                self._market_status_cache[cache_key] = status
                return status

            state, warning, active = self._extract_market_status(market)
            caution_words = {"CAUTION", "WARNING", "ALERT", "RISK"}
            warning_is_caution = any(word in warning for word in caution_words) and warning not in {"NONE", "NORMAL"}
            state_is_active = state in {"ACTIVE", "TRADING", "RUNNING"}
            ok = active and state_is_active and (not warning_is_caution)
            status = {
                "ok": ok,
                "active": active,
                "state": state,
                "warning": warning,
                "reason": "PASS" if ok else f"MARKET_BLOCK(state={state}, warning={warning}, active={active})",
                "ts": now,
            }
        except Exception as e:
            status["reason"] = f"MARKET_STATUS_ERROR:{e}"

        self._market_status_cache[cache_key] = status
        return status

    def _fetch_orderbook(self, exchange_api, ccxt_symbol):
        if not exchange_api or not hasattr(exchange_api, "fetch_order_book"):
            return None
        try:
            ob = exchange_api.fetch_order_book(ccxt_symbol)
        except Exception:
            return None
        if not ob or "asks" not in ob or "bids" not in ob:
            return None
        return ob

    def _simulate_buy_vwap(self, orderbook, target_money):
        target_money = self._safe_float(target_money, 0.0)
        if target_money <= 0:
            return {"ok": False, "reason": "INVALID_TARGET_MONEY"}
        asks = orderbook.get("asks") if isinstance(orderbook, dict) else None
        if not asks:
            return {"ok": False, "reason": "EMPTY_ASK_BOOK"}

        best_ask = self._safe_float(asks[0][0], 0.0) if asks and len(asks[0]) >= 1 else 0.0
        if best_ask <= 0:
            return {"ok": False, "reason": "INVALID_BEST_ASK"}

        remaining_quote = target_money
        filled_qty = 0.0
        spent_quote = 0.0
        for level in asks:
            if not isinstance(level, (list, tuple)) or len(level) < 2:
                continue
            ask_price = self._safe_float(level[0], 0.0)
            ask_qty = self._safe_float(level[1], 0.0)
            if ask_price <= 0 or ask_qty <= 0:
                continue
            max_quote = ask_price * ask_qty
            take_quote = min(remaining_quote, max_quote)
            take_qty = take_quote / ask_price if ask_price > 0 else 0.0
            if take_qty <= 0:
                continue
            filled_qty += take_qty
            spent_quote += take_quote
            remaining_quote -= take_quote
            if remaining_quote <= 1e-9:
                break

        if filled_qty <= 0 or spent_quote <= 0:
            return {"ok": False, "reason": "NO_SIMULATED_FILL"}
        if remaining_quote > 1e-6:
            return {"ok": False, "reason": "BOOK_DEPTH_INSUFFICIENT"}

        projected_vwap = spent_quote / filled_qty
        slippage = (projected_vwap - best_ask) / best_ask if best_ask > 0 else float("inf")
        return {
            "ok": True,
            "best_ask": best_ask,
            "projected_vwap": projected_vwap,
            "sim_qty": filled_qty,
            "slippage_pct": slippage,
        }

    def _submit_limit_order(self, exchange_api, ccxt_symbol, side, qty, price, params=None):
        qty = self._clamp_positive(qty, 0.0)
        price = self._clamp_positive(price, 0.0)
        if qty <= 0 or price <= 0:
            raise ValueError(f"Invalid order qty/price qty={qty}, price={price}")
        params = params or {}
        side = side.lower()
        if side == "buy" and hasattr(exchange_api, "create_limit_buy_order"):
            return exchange_api.create_limit_buy_order(ccxt_symbol, qty, price, params)
        if side == "sell" and hasattr(exchange_api, "create_limit_sell_order"):
            return exchange_api.create_limit_sell_order(ccxt_symbol, qty, price, params)
        if hasattr(exchange_api, "create_order"):
            return exchange_api.create_order(ccxt_symbol, "limit", side, qty, price, params)
        raise RuntimeError("Limit order method is unavailable")

    def _fetch_order(self, exchange_api, order_id, ccxt_symbol):
        if not order_id or not exchange_api or not hasattr(exchange_api, "fetch_order"):
            return None
        return exchange_api.fetch_order(order_id, ccxt_symbol)

    def _poll_order(self, exchange_api, order_id, ccxt_symbol, max_time_sec, interval_sec, backoff_factor):
        deadline = time.time() + max_time_sec
        interval = max(0.05, interval_sec)
        rate_limited = False
        last_order = None

        while time.time() < deadline:
            try:
                order = self._fetch_order(exchange_api, order_id, ccxt_symbol)
                if order:
                    last_order = order
                    status = str(order.get("status", "")).lower()
                    amount = self._safe_float(order.get("amount"), 0.0)
                    filled = self._safe_float(order.get("filled"), 0.0)
                    if status in {"closed", "filled"}:
                        return {"timeout": False, "order": order, "rate_limited": rate_limited}
                    if amount > 0 and filled >= amount - 1e-12:
                        return {"timeout": False, "order": order, "rate_limited": rate_limited}
                    if status in {"canceled", "cancelled", "rejected", "expired"}:
                        return {"timeout": False, "order": order, "rate_limited": rate_limited}
            except Exception as e:
                if self._is_rate_limit_error(e):
                    rate_limited = True
                    interval = min(interval * backoff_factor, 5.0)
                else:
                    logger.warning("[ORDER] Poll error %s", e)
            time.sleep(interval)

        return {"timeout": True, "order": last_order, "rate_limited": rate_limited}

    def _cancel_and_confirm(self, exchange_api, order_id, ccxt_symbol, wait_sec=3.0):
        if not order_id:
            return {"canceled": False, "order": None}
        try:
            if hasattr(exchange_api, "cancel_order"):
                exchange_api.cancel_order(order_id, ccxt_symbol)
        except Exception:
            pass

        deadline = time.time() + max(wait_sec, 0.5)
        last_order = None
        while time.time() < deadline:
            try:
                order = self._fetch_order(exchange_api, order_id, ccxt_symbol)
                if order:
                    last_order = order
                    status = str(order.get("status", "")).lower()
                    if status in {"canceled", "cancelled", "closed", "filled", "rejected", "expired"}:
                        return {"canceled": status in {"canceled", "cancelled"}, "order": order}
            except Exception:
                pass
            time.sleep(0.25)
        return {"canceled": False, "order": last_order}

    def _fetch_fills(self, exchange_api, ccxt_symbol, order_id, start_ts):
        fills = []

        if exchange_api and hasattr(exchange_api, "get_fills"):
            try:
                raw = exchange_api.get_fills(order_id)
                if isinstance(raw, list):
                    return raw
            except Exception:
                pass

        if exchange_api and hasattr(exchange_api, "fetch_my_trades"):
            try:
                since_ms = int(max(0.0, start_ts - 120.0) * 1000)
                recent = exchange_api.fetch_my_trades(ccxt_symbol, since=since_ms, limit=200) or []
                for tr in recent:
                    tr_order = tr.get("order") or tr.get("order_id")
                    if order_id and tr_order and str(tr_order) != str(order_id):
                        continue
                    fills.append(tr)
            except Exception:
                pass
        return fills

    def _aggregate_fills(self, fills):
        total_qty = 0.0
        total_amount = 0.0
        total_fee = 0.0
        parsed = []

        for fill in fills or []:
            qty = self._safe_float(fill.get("amount") or fill.get("qty"), 0.0)
            px = self._safe_float(fill.get("price"), 0.0)
            if qty <= 0 or px <= 0:
                continue
            amt = qty * px
            fee = 0.0
            fee_obj = fill.get("fee")
            if isinstance(fee_obj, dict):
                fee = self._safe_float(fee_obj.get("cost"), 0.0)
            if fee_obj is None and isinstance(fill.get("fees"), list):
                for x in fill.get("fees", []):
                    if isinstance(x, dict):
                        fee += self._safe_float(x.get("cost"), 0.0)

            total_qty += qty
            total_amount += amt
            total_fee += max(0.0, fee)
            parsed.append({"qty": qty, "price": px, "amount": amt, "fee": fee})

        real_vwap = total_amount / total_qty if total_qty > 0 else 0.0
        return {"qty": total_qty, "vwap": real_vwap, "amount": total_amount, "fee": total_fee, "fills": parsed}

    def _compose_result(
        self,
        ok,
        symbol,
        side,
        reason="",
        order_id=None,
        real_qty=0.0,
        real_vwap=0.0,
        amount=0.0,
        fee=0.0,
        fills=None,
        rate_limited=False,
        safe_cooldown=False,
        meta=None,
    ):
        data = {
            "ok": bool(ok),
            "symbol": symbol,
            "side": side,
            "reason": reason,
            "order_id": order_id,
            "real_qty": self._clamp_positive(real_qty, 0.0),
            "real_vwap": self._clamp_positive(real_vwap, 0.0),
            "amount": self._clamp_positive(amount, 0.0),
            "fee": self._clamp_positive(fee, 0.0),
            "fills": fills or [],
            "rate_limited": bool(rate_limited),
            "safe_cooldown": bool(safe_cooldown),
            "safe_cooldown_sec": self.safe_cooldown_sec if safe_cooldown else 0,
        }
        if meta:
            data.update(meta)
        return data

    def _log_execution(self, result):
        try:
            self.exec_logger.log(
                {
                    "timestamp": datetime.now().isoformat(),
                    "symbol": result.get("symbol"),
                    "side": result.get("side"),
                    "event_type": result.get("event_type", "EXECUTION"),
                    "position_id": result.get("position_id", ""),
                    "price": result.get("real_vwap", 0.0),
                    "qty": result.get("real_qty", 0.0),
                    "amount": result.get("amount", 0.0),
                    "fee": result.get("fee", 0.0),
                    "order_id": result.get("order_id", "unknown"),
                    "reason": result.get("reason", ""),
                }
            )
        except Exception:
            pass

    def execute_entry(self, signal, current_market_data, exchange_api=None):
        symbol = signal.get("symbol")
        if not symbol:
            return self._compose_result(False, symbol, "buy", reason="EMPTY_SYMBOL")

        with _ACTIVE_LOCK:
            if symbol in _ACTIVE_SYMBOLS:
                return self._compose_result(False, symbol, "buy", reason="ACTIVE_SYMBOL_LOCK")
            _ACTIVE_SYMBOLS.add(symbol)

        try:
            target_money = self._safe_float(signal.get("target_money"), 0.0)
            if target_money <= 0:
                return self._compose_result(False, symbol, "buy", reason="INVALID_TARGET_MONEY")

            passed, reason, _ = self.check_gates(signal)
            if not passed:
                return self._compose_result(False, symbol, "buy", reason=reason)

            balance = self._safe_float((current_market_data or {}).get("balance"), 0.0)
            available_for_bot = balance
            if hasattr(self.budget_mgr, "get_available_for_bot"):
                try:
                    available_for_bot = self._safe_float(self.budget_mgr.get_available_for_bot(balance), balance)
                except Exception:
                    available_for_bot = balance
            target_money = min(target_money, max(0.0, available_for_bot))
            if target_money <= 0:
                return self._compose_result(False, symbol, "buy", reason="BUDGET_FAIL:AVAILABLE_FOR_BOT_ZERO")

            if hasattr(self.budget_mgr, "can_buy"):
                can_buy, budget_msg = self.budget_mgr.can_buy(target_money, balance)
                if not can_buy:
                    return self._compose_result(False, symbol, "buy", reason=f"BUDGET_FAIL:{budget_msg}")

            ccxt_symbol = self._to_ccxt_symbol(symbol)
            market_ok = self._check_market_status(exchange_api, ccxt_symbol, force_refresh=True)
            if not market_ok.get("ok", False):
                return self._compose_result(False, symbol, "buy", reason=market_ok.get("reason", "MARKET_BLOCK"))

            orderbook = self._fetch_orderbook(exchange_api, ccxt_symbol)
            if not orderbook:
                return self._compose_result(False, symbol, "buy", reason="ORDERBOOK_UNAVAILABLE")

            sim = self._simulate_buy_vwap(orderbook, target_money)
            if not sim.get("ok", False):
                return self._compose_result(False, symbol, "buy", reason=sim.get("reason", "SIM_FAIL"))

            max_slip = self._safe_float(signal.get("max_entry_slippage_pct"), self.max_entry_slippage_pct)
            if sim["slippage_pct"] > max_slip:
                return self._compose_result(
                    False,
                    symbol,
                    "buy",
                    reason=f"SLIPPAGE_BLOCK({sim['slippage_pct']:.6f}>{max_slip:.6f})",
                    meta={"slippage_pct": sim["slippage_pct"], "projected_vwap": sim["projected_vwap"], "best_ask": sim["best_ask"]},
                )

            best_ask = sim["best_ask"]
            tick = self.get_tick_size(best_ask)
            limit_price = self.round_to_tick(best_ask + (2.0 * tick), tick, side="buy")
            if limit_price <= 0:
                return self._compose_result(False, symbol, "buy", reason="INVALID_LIMIT_PRICE")

            fee_buffer = 0.998
            qty = target_money * fee_buffer / limit_price
            qty = self._clamp_positive(qty, 0.0)
            if qty <= 0:
                return self._compose_result(False, symbol, "buy", reason="INVALID_ORDER_QTY")

            order_started_at = time.time()
            order = self._submit_limit_order(exchange_api, ccxt_symbol, "buy", qty, limit_price, params={})
            order_id = (order or {}).get("id")
            if not order_id:
                return self._compose_result(False, symbol, "buy", reason="ORDER_ID_MISSING")

            polled = self._poll_order(
                exchange_api,
                order_id,
                ccxt_symbol,
                max_time_sec=self.entry_timeout_sec,
                interval_sec=self.poll_interval_sec,
                backoff_factor=self.backoff_factor,
            )
            safe_cooldown = bool(polled.get("rate_limited", False))

            if polled.get("timeout", False):
                self._cancel_and_confirm(exchange_api, order_id, ccxt_symbol, wait_sec=3.0)

            fills = self._fetch_fills(exchange_api, ccxt_symbol, order_id, start_ts=order_started_at)
            agg = self._aggregate_fills(fills)

            real_qty = agg["qty"]
            real_vwap = agg["vwap"]
            amount = agg["amount"]
            fee = agg["fee"]
            ok = real_qty > 0.0

            result = self._compose_result(
                ok,
                symbol,
                "buy",
                reason="FILLED" if ok else "NO_REAL_FILL",
                order_id=order_id,
                real_qty=real_qty,
                real_vwap=real_vwap,
                amount=amount,
                fee=fee,
                fills=agg["fills"],
                rate_limited=polled.get("rate_limited", False),
                safe_cooldown=safe_cooldown,
                meta={
                    "limit_price": limit_price,
                    "best_ask": best_ask,
                    "projected_vwap": sim["projected_vwap"],
                    "slippage_pct": sim["slippage_pct"],
                },
            )
            self._log_execution(result)

            if result["ok"] and hasattr(self.budget_mgr, "update_on_trade"):
                self.budget_mgr.update_on_trade("buy", symbol, result["real_vwap"], result["real_qty"], result["fee"])
            return result

        except Exception as e:
            safe = self._is_rate_limit_error(e)
            return self._compose_result(
                False,
                symbol,
                "buy",
                reason=f"ENTRY_ERROR:{e}",
                rate_limited=safe,
                safe_cooldown=safe,
            )
        finally:
            with _ACTIVE_LOCK:
                _ACTIVE_SYMBOLS.discard(symbol)

    def get_best_bid_ask(self, symbol, exchange_api):
        ccxt_symbol = self._to_ccxt_symbol(symbol)
        orderbook = self._fetch_orderbook(exchange_api, ccxt_symbol)
        if not orderbook:
            return {"ok": False, "reason": "ORDERBOOK_UNAVAILABLE"}
        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])
        best_bid = self._safe_float(bids[0][0], 0.0) if bids and len(bids[0]) >= 1 else 0.0
        best_ask = self._safe_float(asks[0][0], 0.0) if asks and len(asks[0]) >= 1 else 0.0
        if best_bid <= 0:
            return {"ok": False, "reason": "INVALID_BEST_BID"}
        return {"ok": True, "best_bid": best_bid, "best_ask": best_ask, "orderbook": orderbook}

    def create_market_sell_order(self, symbol, qty, exchange_api=None, event_type="EXIT", position_id=None):
        # Compatibility method: implemented as marketable-limit sell (never true market).
        return self.create_marketable_limit_sell_order(
            symbol=symbol,
            qty=qty,
            exchange_api=exchange_api,
            aggressive_ticks=1,
            timeout_sec=self.exit_timeout_sec,
            params=None,
            event_type=event_type,
            position_id=position_id,
        )

    def create_marketable_limit_sell_order(
        self,
        symbol,
        qty,
        exchange_api=None,
        aggressive_ticks=1,
        timeout_sec=3.0,
        params=None,
        force_refresh_market=False,
        event_type="EXIT",
        position_id=None,
    ):
        qty = self._clamp_positive(qty, 0.0)
        if qty <= 0:
            return self._compose_result(False, symbol, "sell", reason="INVALID_QTY")

        try:
            ccxt_symbol = self._to_ccxt_symbol(symbol)
            market_ok = self._check_market_status(exchange_api, ccxt_symbol, force_refresh=force_refresh_market)
            if not market_ok.get("ok", False):
                return self._compose_result(False, symbol, "sell", reason=market_ok.get("reason", "MARKET_BLOCK"))

            ba = self.get_best_bid_ask(symbol, exchange_api)
            if not ba.get("ok", False):
                return self._compose_result(False, symbol, "sell", reason=ba.get("reason", "BID_UNAVAILABLE"))

            best_bid = ba["best_bid"]
            tick = self.get_tick_size(best_bid)
            raw_limit = best_bid - (max(1, int(aggressive_ticks)) * tick)
            limit_price = self.round_to_tick(max(tick, raw_limit), tick, side="sell")
            if limit_price <= 0:
                return self._compose_result(False, symbol, "sell", reason="INVALID_LIMIT_PRICE")

            order_started_at = time.time()
            order = self._submit_limit_order(exchange_api, ccxt_symbol, "sell", qty, limit_price, params=params or {})
            order_id = (order or {}).get("id")
            if not order_id:
                return self._compose_result(False, symbol, "sell", reason="ORDER_ID_MISSING")

            polled = self._poll_order(
                exchange_api,
                order_id,
                ccxt_symbol,
                max_time_sec=max(0.5, timeout_sec),
                interval_sec=self.poll_interval_sec,
                backoff_factor=self.backoff_factor,
            )
            safe_cooldown = bool(polled.get("rate_limited", False))
            if polled.get("timeout", False):
                self._cancel_and_confirm(exchange_api, order_id, ccxt_symbol, wait_sec=2.0)

            fills = self._fetch_fills(exchange_api, ccxt_symbol, order_id, start_ts=order_started_at)
            agg = self._aggregate_fills(fills)
            real_qty = agg["qty"]
            real_vwap = agg["vwap"]
            amount = agg["amount"]
            fee = agg["fee"]

            result = self._compose_result(
                real_qty > 0.0,
                symbol,
                "sell",
                reason="FILLED" if real_qty > 0 else "NO_REAL_FILL",
                order_id=order_id,
                real_qty=real_qty,
                real_vwap=real_vwap,
                amount=amount,
                fee=fee,
                fills=agg["fills"],
                rate_limited=polled.get("rate_limited", False),
                safe_cooldown=safe_cooldown,
                meta={
                    "limit_price": limit_price,
                    "best_bid": best_bid,
                    "event_type": event_type,
                    "position_id": str(position_id) if position_id is not None else "",
                },
            )
            self._log_execution(result)

            if result["ok"] and hasattr(self.budget_mgr, "update_on_trade"):
                self.budget_mgr.update_on_trade("sell", symbol, result["real_vwap"], result["real_qty"], result["fee"])
            return result
        except Exception as e:
            safe = self._is_rate_limit_error(e)
            return self._compose_result(
                False,
                symbol,
                "sell",
                reason=f"SELL_ERROR:{e}",
                rate_limited=safe,
                safe_cooldown=safe,
            )

    def _cancel_open_orders_for_symbol(self, symbol, exchange_api):
        if not exchange_api or not hasattr(exchange_api, "fetch_open_orders"):
            return
        ccxt_symbol = self._to_ccxt_symbol(symbol)
        try:
            orders = exchange_api.fetch_open_orders(ccxt_symbol) or []
        except Exception:
            return
        for od in orders:
            oid = od.get("id")
            if not oid:
                continue
            try:
                exchange_api.cancel_order(oid, ccxt_symbol)
            except Exception:
                continue

    def execute_panic_exit(
        self,
        symbol,
        qty,
        exchange_api=None,
        unrealized_pnl_pct=0.0,
        hard_loss_cap=-0.05,
    ):
        qty = self._clamp_positive(qty, 0.0)
        if qty <= 0:
            return self._compose_result(False, symbol, "sell", reason="INVALID_QTY")

        self._cancel_open_orders_for_symbol(symbol, exchange_api)

        remaining = qty
        legs = []

        first = self.create_marketable_limit_sell_order(
            symbol=symbol,
            qty=remaining,
            exchange_api=exchange_api,
            aggressive_ticks=3,
            timeout_sec=3.0,
            params=None,
            force_refresh_market=False,
        )
        legs.append(first)
        remaining = max(0.0, remaining - first.get("real_qty", 0.0))

        if remaining > 1e-12:
            second = self.create_marketable_limit_sell_order(
                symbol=symbol,
                qty=remaining,
                exchange_api=exchange_api,
                aggressive_ticks=6,
                timeout_sec=3.0,
                params=None,
                force_refresh_market=False,
            )
            legs.append(second)
            remaining = max(0.0, remaining - second.get("real_qty", 0.0))

        if remaining > 1e-12:
            allow_ioc = self._safe_float(unrealized_pnl_pct, -1.0) >= self._safe_float(hard_loss_cap, -0.05)
            if not allow_ioc:
                return self._compose_result(
                    False,
                    symbol,
                    "sell",
                    reason=f"PANIC_HALT(loss={unrealized_pnl_pct:.4f}, cap={hard_loss_cap:.4f})",
                    meta={"halted": True, "remaining_qty": remaining, "legs": legs},
                )

            ioc_leg = self.create_marketable_limit_sell_order(
                symbol=symbol,
                qty=remaining,
                exchange_api=exchange_api,
                aggressive_ticks=10,
                timeout_sec=2.0,
                params={"timeInForce": "IOC"},
                force_refresh_market=False,
            )
            legs.append(ioc_leg)
            remaining = max(0.0, remaining - ioc_leg.get("real_qty", 0.0))

        total_qty = 0.0
        total_amount = 0.0
        total_fee = 0.0
        rate_limited = False
        for leg in legs:
            leg_qty = self._safe_float(leg.get("real_qty"), 0.0)
            leg_px = self._safe_float(leg.get("real_vwap"), 0.0)
            total_qty += leg_qty
            total_amount += leg_qty * leg_px
            total_fee += self._safe_float(leg.get("fee"), 0.0)
            rate_limited = rate_limited or bool(leg.get("rate_limited", False))

        vwap = total_amount / total_qty if total_qty > 0 else 0.0
        ok = total_qty > 0
        reason = "PANIC_EXIT_FILLED" if remaining <= 1e-12 and ok else "PANIC_EXIT_PARTIAL"
        return self._compose_result(
            ok,
            symbol,
            "sell",
            reason=reason,
            order_id=legs[-1].get("order_id") if legs else None,
            real_qty=total_qty,
            real_vwap=vwap,
            amount=total_amount,
            fee=total_fee,
            fills=[],
            rate_limited=rate_limited,
            safe_cooldown=rate_limited,
            meta={"remaining_qty": remaining, "legs": legs, "halted": False},
        )

    def log_shadow(self, data):
        try:
            self.shadow_logger.log(data)
        except Exception:
            pass

    def update_shadow_outcomes(self, current_prices):
        # Placeholder for backward compatibility.
        return None
