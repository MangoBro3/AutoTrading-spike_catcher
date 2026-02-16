
import ccxt
import time
import logging

logger = logging.getLogger("AdapterUpbit")

class UpbitAdapter:
    def __init__(self, use_env=True, access_key=None, secret_key=None):
        import os
        from dotenv import load_dotenv
        
        if use_env:
            load_dotenv()
            access_key = os.getenv("UPBIT_ACCESS") or os.getenv("UPBIT_ACCESS_KEY")
            secret_key = os.getenv("UPBIT_SECRET") or os.getenv("UPBIT_SECRET_KEY")
            
        self.logger = logging.getLogger("UpbitAdapter")
        
        if not access_key or not secret_key:
             self.logger.warning("Upbit Keys missing. Read-Only potential issues.")
             
        self.client = ccxt.upbit({
            'apiKey': access_key,
            'secret': secret_key,
            'enableRateLimit': True,
            'options': {'createMarketBuyOrderRequiresPrice': False}
        })
        
        # STAGE 10: Circuit Breaker
        self.error_count = 0
        self.status = "OK"  # OK, DEGRADED
        self.last_error_ts = 0

    def _normalize_symbol(self, ccxt_symbol):
        """
        Converts CCXT symbol (BTC/KRW) to Internal Standard (KRW-BTC).
        Upbit CCXT usually returns 'BTC/KRW'.
        """
        if '/' in ccxt_symbol:
            base, quote = ccxt_symbol.split('/')
            return f"{quote}-{base}"
        return ccxt_symbol

    def _handle_error(self, e):
        """
        Updates circuit breaker state on error.
        """
        self.error_count += 1
        self.last_error_ts = time.time()
        
        if self.error_count > 3:
            if self.status != "DEGRADED":
                self.status = "DEGRADED"
                self.logger.warning(f"[CircuitBreaker] Too many errors ({self.error_count}). Entering DEGRADED mode.")
    
    def _reset_error_stats(self):
        """
        Slowly recovers if successful.
        """
        if self.error_count > 0:
            self.error_count = max(0, self.error_count - 1)
            if self.error_count == 0 and self.status == "DEGRADED":
                self.status = "OK"
                self.logger.info("[CircuitBreaker] Recovered to OK status.")

    def health(self):
        """
        Checks exchange connectivity (Latency check).
        Uses fetch_ticker('BTC/KRW') as proxy since fetch_time is not universally supported.
        """
        try:
            start = time.time()
            # self.client.fetch_time() # Not supported by Upbit CCXT
            self.client.fetch_ticker('BTC/KRW')
            latency = (time.time() - start) * 1000
            
            self._reset_error_stats() # Recovery
            
            return {
                'status': self.status, 
                'latency_ms': round(latency, 2)
            }
        except Exception as e:
            self.logger.error(f"[Upbit] Health Check Failed: {e}")
            self._handle_error(e)
            return {'status': 'error', 'details': str(e)}

    def get_balances(self):
        """
        Returns simplified balance dict.
        """
        try:
            raw = self.client.fetch_balance()
            result = {}
            for currency, total_val in raw.get('total', {}).items():
                if total_val > 0:
                    result[currency] = {
                        'free': float(raw['free'].get(currency, 0.0)),
                        'used': float(raw['used'].get(currency, 0.0)),
                        'total': float(total_val)
                    }
            return result
        except Exception as e:
            self.logger.error(f"[Upbit] Get Balances Failed: {e}")
            return {}

    def get_open_orders(self):
        """
        Returns list of open orders with normalized symbols.
        """
        try:
            raw_orders = self.client.fetch_open_orders()
            orders = []
            for o in raw_orders:
                orders.append({
                    'id': o['id'],
                    'symbol': self._normalize_symbol(o['symbol']),
                    'type': o['type'],
                    'side': o['side'],
                    'price': o['price'],
                    'amount': o['amount'],
                    'remaining': o['remaining'],
                    'created_at': o['datetime']
                })
            return orders
        except Exception as e:
            self.logger.error(f"[Upbit] Get Open Orders Failed: {e}")
            return []

    def get_recent_fills(self, limit=20):
        """
        Refetches recent trades/fills history.
        """
        try:
            # Stage 3 Constraint: Just implement structure.
            return [] 
        except Exception as e:
            self.logger.error(f"[Upbit] Get Fills Failed: {e}")
            return []

    def create_order(self, symbol, type, side, amount, price=None, params=None):
        """
        Places an order.
        Strict Safety: Block NEW entries if DEGRADED.
        """
        params = params or {}

        # 1. Circuit Breaker Check
        if self.status == "DEGRADED":
            # Check for reduce_only in params (CCXT or internal)
            is_reduce_only = params.get('reduce_only', False) or params.get('params', {}).get('reduce_only', False)
            if not is_reduce_only:
                self.logger.warning(f"[CircuitBreaker] BLOCKED Order {side} {symbol} due to DEGRADED status.")
                return None

        # 2. Hard fail when API keys are missing in non-readonly contexts
        if not self.client.apiKey or not self.client.secret:
            raise RuntimeError("LIVE order blocked: Upbit API keys are missing.")

        # 3. Real exchange call (no mock fills in live path)
        try:
            order = self.client.create_order(symbol, type, side, amount, price, params)
            self._reset_error_stats()
            return order
        except Exception as e:
            self._handle_error(e)
            self.logger.error(f"[Upbit] create_order failed: {e}")
            raise
