import ccxt
import time
import os
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
import glob

# Local Modules
import data_loader
from strategy import Strategy
from telegram_bot import send_telegram_message

class LiveTrader:
    def __init__(self, budget_krw=100_000):
        load_dotenv()
        
        # 1. Exchange Setup
        self.api_key = os.getenv("BITHUMB_KEY")
        self.secret = os.getenv("BITHUMB_SECRET")
        
        if not self.api_key or not self.secret:
            print("[Trader] ⚠️ API Keys missing in .env. Execution disabled.")
            self.exchange = None
        else:
            self.exchange = ccxt.bithumb({
                'apiKey': self.api_key,
                'secret': self.secret,
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'}
            })
            print("[Trader] ✅ Connected to Bithumb")
            
        self.budget_krw = budget_krw
        self.strat = Strategy()
        self.min_order_krw = 5000 # Bithumb Minimum Order Size (Safety Buffer)
        
    def get_balance(self, currency='KRW'):
        if not self.exchange: return 0.0
        try:
            bal = self.exchange.fetch_balance()
            return bal[currency]['free']
        except Exception as e:
            print(f"[Trader Error] Balance check failed: {e}")
            return 0.0

    def load_and_analyze(self):
        """Reuse logic from monitor.py but streamlined"""
        data_dir = "data"
        files = glob.glob(os.path.join(data_dir, "*.parquet"))
        
        data_map = {}
        for f in files:
            basename = os.path.basename(f).replace(".parquet", "")
            try:
                data_map[basename] = pd.read_parquet(f)
            except: pass
        return data_map

    def execute_buy(self, symbol, amount_krw):
        if not self.exchange: return
        
        try:
            # 1. Get Ticker for price
            ticker = self.exchange.fetch_ticker(symbol)
            price = ticker['last']
            
            # 2. Calculate Amount (Volume)
            # Fee buffer (approx 0.25% safely)
            amount_krw_safe = amount_krw * 0.9975 
            volume = amount_krw_safe / price
            
            print(f"[Trader] 🛒 Buying {symbol} : {amount_krw_safe:,.0f} KRW ({volume:.4f} @ {price:,.0f})")
            
            # 3. Place Order (Market Buy)
            # Note: Bithumb market buy usually requires 'cost' (KRW amount) or 'amount' (Volume) depending on implementation
            # CCXT normalize: createMarketBuyOrder(symbol, amount) -> amount is usually base currency volume.
            
            # IMPORTANT: For KRW markets, precision checks are vital.
            # Using create_order directly for safety if needed, but create_market_buy_order is standard.
            order = self.exchange.create_market_buy_order(symbol, volume)
            
            print(f"[Trader] ✅ Order Placed: {order['id']}")
            send_telegram_message(f"🛒 **BUY Executed**\n{symbol}\nPrice: {price:,.0f}\nAmt: {amount_krw_safe:,.0f} KRW")
            return order
            
        except Exception as e:
            print(f"[Trader Error] Buy Failed: {e}")
            send_telegram_message(f"⚠️ **Buy Failed** {symbol}\n`{e}`")

    def run_strategy_cycle(self):
        """
        Main Loop Step:
        1. Update Data
        2. Analyze
        3. Check Signals
        4. Execute
        """
        print(f"\n[Trader] Cycle Start: {datetime.now()}")
        
        # 1. Update Data (Live)
        try:
            data_loader.update_data()
        except Exception as e:
            print(f"[Trader Warning] Data update error: {e}")
            
        # 2. Analyze
        data_map = self.load_and_analyze()
        
        # 3. Signals
        # Using Strategy A/B params (Default for now, or load from autotune?)
        # Let's use robust defaults.
        params = {
            'trigger_vol_A': 2.0,
            'close_confirm_pct_A': 0.02, # 2% confirm
            'universe_top_n': 10 # Only trade top 10
        }
        
        # Filter Universe (Simulate Backtester logic)
        # Find Top N Turnover
        tos = []
        for sym, df in data_map.items():
            if df.empty: continue
            last = df.iloc[-1]
            tos.append((sym, last.get('turnover', 0)))
            
        tos.sort(key=lambda x: x[1], reverse=True)
        universe = set([x[0] for x in tos[:params['universe_top_n']]])
        
        signals = []
        
        for sym, df in data_map.items():
            if sym not in universe: continue
            if "BTC" in sym: continue # Skip BTC for now if Strategy is Alts
            
            df_res = self.strat.analyze(df, params=params)
            last = df_res.iloc[-1]
            
            # Check Signal (A or B)
            if last.get('signal_confirm_A', False) or last.get('signal_B', False):
                 signals.append(sym)
                 
        print(f"[Trader] Signals: {signals}")
        
        # 4. Execute
        if signals and self.exchange:
            balance = self.get_balance('KRW')
            # Check limit
            if balance < 5000:
                print("[Trader] Insufficient KRW Balance.")
                return

            # Allocation: Split budget among signals? 
            # Or use fixed size? User said "100k total".
            # Let's use available balance / len(signals) but capped.
            
            per_trade = balance / len(signals)
            per_trade = min(per_trade, self.budget_krw) # Don't exceed budget
            
            if per_trade < self.min_order_krw:
                print(f"[Trader] Alloc per trade ({per_trade:,.0f}) too small.")
                return
                
            for sym in signals:
                # Check if already holding? (Requires checking fetch_positions)
                # Simple logic for V1: Just buy if balance exists.
                # Assuming Day Trading / Swing.
                
                # Check Coin Balance
                coin_sym = sym.split("-")[1] # "UPBIT_KRW-XRP" -> "XRP"
                # Wait, CCXT symbol format might be "XRP/KRW".
                # My symbol map keys are "UPBIT_KRW-XRP".
                # Need to convert local symbol to CCXT symbol.
                
                ccxt_sym = coin_sym + "/KRW" # Bithumb format
                
                # Check current holding
                coin_bal = self.get_balance(coin_sym)
                current_val = coin_bal * df_res.iloc[-1]['close'] # Approx
                
                if current_val > 5000:
                     print(f"[Trader] Already holding {coin_sym} ({current_val:,.0f} KRW). Skip.")
                     continue
                     
                self.execute_buy(ccxt_sym, per_trade)

if __name__ == "__main__":
    bot = LiveTrader(budget_krw=100_000)
    
    # Run loop
    while True:
        try:
            bot.run_strategy_cycle()
        except Exception as e:
            print(f"[Trader Error] Loop Crash: {e}")
            send_telegram_message(f"⚠️ **Trader Crashed**\n`{e}`")
        
        print("[Trader] Sleeping 30 min...")
        time.sleep(1800) # 30 min interval
