
import ccxt
import time

def test_sync():
    print("Testing CCXT Sync (Upbit)...")
    upbit = ccxt.upbit()
    try:
        tickers = upbit.fetch_tickers()
        print(f"Tickers: {len(tickers)}")
        ohlcv = upbit.fetch_ohlcv('BTC/KRW', '1d', limit=5)
        print(f"OHLCV: {len(ohlcv)}")
        print("Success!")
    except Exception as e:
        print(f"Failed: {e}")
    
if __name__ == "__main__":
    test_sync()
