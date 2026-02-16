
import asyncio
import ccxt.async_support as ccxt
import pandas as pd

async def test_btc_fetch():
    print("Testing Upbit...")
    exchange = ccxt.upbit()
    try:
        ohlcv = await exchange.fetch_ohlcv('BTC/KRW', '1d', limit=5)
        print(f"Upbit Success: {len(ohlcv)} rows")
        print(ohlcv[0])
    except Exception as e:
        print(f"Upbit Failed: {e}")
    await exchange.close()

    print("\nTesting Bithumb...")
    exchange = ccxt.bithumb()
    try:
        # Bithumb sometimes requires different symbol format in past versions, but BTC/KRW is standard
        ohlcv = await exchange.fetch_ohlcv('BTC/KRW', '1d', limit=5)
        print(f"Bithumb Success: {len(ohlcv)} rows")
    except Exception as e:
        print(f"Bithumb Failed: {e}")
    await exchange.close()

if __name__ == "__main__":
    asyncio.run(test_btc_fetch())
