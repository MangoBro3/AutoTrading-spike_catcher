import ccxt
import time
import logging

logger = logging.getLogger("AdapterBithumb")

class BithumbAdapter:
    def __init__(self, access_key, secret_key):
        self.client = ccxt.bithumb({
            'apiKey': access_key,
            'secret': secret_key,
            'enableRateLimit': True
        })
        self.client.load_markets()

    def _normalize_symbol(self, ccxt_symbol):
        """
        Converts CCXT symbol (BTC/KRW) to Internal Standard (KRW-BTC).
        """
        if '/' in ccxt_symbol:
            base, quote = ccxt_symbol.split('/')
            return f"{quote}-{base}"
        return ccxt_symbol

    def health(self):
        """
        Checks exchange connectivity (Latency check).
        Uses fetch_ticker('BTC/KRW') as proxy.
        """
        try:
            start = time.time()
            # self.client.fetch_time() 
            self.client.fetch_ticker('BTC/KRW')
            latency = (time.time() - start) * 1000
            return {'status': 'ok', 'latency_ms': round(latency, 2)}
        except Exception as e:
            logger.error(f"[Bithumb] Health Check Failed: {e}")
            return {'status': 'error', 'details': str(e)}

    def get_balances(self):
        """
        Same structure as Upbit.
        """
        try:
            raw = self.client.fetch_balance()
            result = {}
            for currency, total_val in raw.get('total', {}).items():
                if total_val > 0:
                    free_val = raw['free'].get(currency, 0.0)
                    used_val = raw['used'].get(currency, 0.0)
                    
                    result[currency] = {
                        'free': float(free_val),
                        'used': float(used_val),
                        'total': float(total_val)
                    }
            return result
        except Exception as e:
            logger.error(f"[Bithumb] Get Balances Failed: {e}")
            return {}

    def get_open_orders(self):
        """
        Returns list of open orders with normalized symbols.
        """
        try:
            # Bithumb CCXT fetch_open_orders may imply all or specific symbol
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
            logger.error(f"[Bithumb] Get Open Orders Failed: {e}")
            return []

    def get_recent_fills(self, limit=20):
        """
        Placeholder for consistency.
        """
        return []
