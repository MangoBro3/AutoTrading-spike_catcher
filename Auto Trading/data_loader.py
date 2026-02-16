
import ccxt
import pandas as pd
import numpy as np
import os
import time
import asyncio
from datetime import datetime, timedelta

# Configuration
DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# Global Semaphore for Concurrency Control
CONCURRENCY_LIMIT = 5 # Safe limit for threads
# CMD_SEM removed from global scope to avoid event loop mismatch

# Helpers to get Sync Exchange Instances (Thread-safe creation usually preferred, or cached)
def get_exchange_sync(exchange_id):
    if exchange_id == 'upbit':
        return ccxt.upbit({'enableRateLimit': True})
    elif exchange_id == 'bithumb':
        return ccxt.bithumb({'enableRateLimit': True})
    return None

async def fetch_tickers(exchange_id):
    """Fetch KRW tickers (Threaded Sync)"""
    def _fetch():
        ex = get_exchange_sync(exchange_id)
        try:
            markets = ex.load_markets()
            tickers = [m for m in markets.keys() if m.endswith('/KRW')]
            return tickers
        except Exception as e:
            print(f"Error loading markets for {exchange_id}: {e}")
            return []
            
    return await asyncio.to_thread(_fetch)

async def fetch_ohlcv_async(exchange_id_or_instance, symbol, sem, timeframe='1d', since=None, limit=2000):
    """
    Fetch OHLCV data using Threaded Sync CCXT.
    Arg can be ex_id or instance (instance ignored in threaded creation pattern for safety)
    """
    # Detect exchange id
    if isinstance(exchange_id_or_instance, str):
        ex_id = exchange_id_or_instance
    else:
        ex_id = exchange_id_or_instance.id

    async with sem: # Limiting concurrency
        def _fetch():
            ex = get_exchange_sync(ex_id)
            try:
                if since:
                    ohlcv = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
                else:
                    ohlcv = ex.fetch_ohlcv(symbol, timeframe, limit=limit)
                
                if not ohlcv:
                    return pd.DataFrame()

                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
                return df
            except Exception as e:
                # print(f"Error fetching {symbol}: {e}")
                return pd.DataFrame()
            
        return await asyncio.to_thread(_fetch)

def calculate_atr(df, period=14):
    high = df['high']
    low = df['low']
    close = df['close']
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr

def calculate_features(df, btc_df=None):
    if df.empty: return df
    df = df.copy()
    
    # Ensure numeric
    cols = ['open', 'high', 'low', 'close', 'volume']
    for c in cols: df[c] = pd.to_numeric(df[c])
    epsilon = 1e-9

    # 1. Basic Stats
    df['notional'] = df['close'] * df['volume']
    
    # 2. Wick Ratio
    bo = df[['open', 'close']].max(axis=1)
    body = (df['close'] - df['open']).abs()
    upper_wick = df['high'] - bo
    df['wick_ratio'] = upper_wick / (body + epsilon)
    
    # 3. Moving Averages
    df['ma5'] = df['close'].rolling(window=5).mean()
    df['ma20'] = df['close'].rolling(window=20).mean()
    df['ma60'] = df['close'].rolling(window=60).mean()
    
    # 4. Volume Features
    df['vol_ma20'] = df['volume'].rolling(window=20).mean()
    df['vol_ma3'] = df['volume'].rolling(window=3).mean()
    df['vol_spike'] = df['volume'] / (df['vol_ma20'] + epsilon)
    
    # 5. Returns
    df['ret_1d'] = df['close'].pct_change()
    
    # 6. Silence Strategy
    df['atr'] = calculate_atr(df, 14)
    df['atr_ratio'] = df['atr'] / (df['close'] + epsilon)
    df['close_loc'] = (df['close'] - df['low']) / (df['high'] - df['low'] + epsilon)
    
    vol_ma3_min21 = df['vol_ma3'].rolling(window=21).min()
    is_vol_calm = (df['vol_ma3'] <= vol_ma3_min21 * 1.5)
    
    atr_min21 = df['atr_ratio'].rolling(window=21).min()
    is_volatility_low = (df['atr_ratio'] <= atr_min21 * 1.2)
    
    df['is_silent_candidate'] = is_vol_calm & is_volatility_low
    
    # 7. RS & Regime
    if btc_df is not None:
        df['date_str'] = df['datetime'].dt.strftime('%Y-%m-%d')
        # Map BTC data (Assume btc_df has same daily frequency)
        # To avoid reindex errors, use dictionary mapping or merge
        # Simple map:
        btc_ret_map = btc_df.set_index('date_str')['ret_1d'].to_dict()
        btc_ma60_map = btc_df.set_index('date_str')['ma60'].to_dict()
        btc_close_map = btc_df.set_index('date_str')['close'].to_dict()
        
        df['btc_ret'] = df['date_str'].map(btc_ret_map)
        df['btc_ma60'] = df['date_str'].map(btc_ma60_map)
        df['btc_close'] = df['date_str'].map(btc_close_map)
        
        df['rs'] = df['ret_1d'] - df['btc_ret']
        df['is_bear'] = df['btc_close'] < df['btc_ma60']
        
        df.drop(columns=['date_str', 'btc_ret', 'btc_ma60', 'btc_close'], errors='ignore', inplace=True)
    
    return df

async def process_symbol(exchange_name, symbol, btc_df, sem, progress_callback=None):
    ticker_name = symbol.split('/')[0]
    norm_symbol = f"{exchange_name.upper()}_KRW-{ticker_name}"
    file_path = os.path.join(DATA_DIR, f"{norm_symbol}.parquet")
    
    existing_df = None
    since_ts = None
    
    # Incremental Logic
    if os.path.exists(file_path):
        try:
            existing_df = pd.read_parquet(file_path)
            if not existing_df.empty:
                last_time = existing_df.iloc[-1]['datetime']
                since_ts = int(last_time.timestamp() * 1000) + 1
        except:
            pass

    # Fetch (Threaded Snyc)
    new_df = await fetch_ohlcv_async(exchange_name, symbol, sem, since=since_ts)
    
    if new_df.empty:
        if existing_df is not None:
             final_df = existing_df
        else:
            return None
    else:
        if existing_df is not None:
            final_df = pd.concat([existing_df, new_df]).drop_duplicates(subset=['timestamp']).sort_values('timestamp')
        else:
            final_df = new_df
            
    # Re-calculate features
    final_df = calculate_features(final_df, btc_df)
    
    # Save
    final_df.to_parquet(file_path)
    return norm_symbol

async def main_async(progress_callback=None):
    # Create Semaphore inside the running loop
    sem = asyncio.Semaphore(CONCURRENCY_LIMIT)
    
    start_time = time.time()
    
    if progress_callback: progress_callback(0.0, "Initializing Sync-Threaded Update...")
    
    # 1. Fetch BTC Reference
    btc_df = await fetch_ohlcv_async('upbit', 'BTC/KRW', sem, limit=500)
    
    if btc_df.empty:
        # Fallback Bithumb
        btc_df = await fetch_ohlcv_async('bithumb', 'BTC/KRW', sem, limit=500)
        
    if btc_df.empty:
        if progress_callback: progress_callback(0.0, "Error: BTC Fetch Failed (Sync)")
        print("BTC Fetch Failed")
        return
        
    btc_df = calculate_features(btc_df)
    btc_df['date_str'] = btc_df['datetime'].dt.strftime('%Y-%m-%d')
    btc_df.to_parquet(os.path.join(DATA_DIR, "GLOBAL_BTC.parquet"))
    
    if progress_callback: progress_callback(0.1, "Fetching Ticker Lists...")
    
    # 2. Get Tickers
    # These are already async-wrapped threads
    upbit_tickers = await fetch_tickers('upbit')
    bithumb_tickers = await fetch_tickers('bithumb')
    
    total_symbols = len(upbit_tickers) + len(bithumb_tickers)
    if progress_callback: progress_callback(0.15, f"Processing {total_symbols} pairs...")
    
    # 3. Process Symbols Batching
    process_tasks = []
    
    for t in upbit_tickers:
        process_tasks.append(process_symbol('upbit', t, btc_df, sem))
    for t in bithumb_tickers:
        process_tasks.append(process_symbol('bithumb', t, btc_df, sem))
        
    # Rate Limiting is less precise with threads spawning new instances
    # But Semaphore limits active threads to 5.
    
    completed = 0
    for f in asyncio.as_completed(process_tasks):
        res = await f
        completed += 1
        
        # UI callback
        prog = 0.15 + (completed / total_symbols * 0.85)
        if progress_callback:
            if completed % 5 == 0:
                msg = f"Updated: {res} ({completed}/{total_symbols})" if res else f"Skipped ({completed}/{total_symbols})"
                progress_callback(prog, msg)
        else:
            # if completed % 10 == 0: print(f"Progress: {completed}/{total_symbols}")
            pass
            
    if progress_callback: progress_callback(1.0, f"Done! ({time.time() - start_time:.1f}s)")

def update_data(progress_callback=None):
    """Entry point for synchronous callers"""
    # Use standard run; if loop checks differ on windows, standard run usually handles new loop
    asyncio.run(main_async(progress_callback))

def load_data_map():
    """Load all parquet files from DATA_DIR into a dict"""
    import glob
    data_map = {}
    files = glob.glob(os.path.join(DATA_DIR, "*.parquet"))
    for f in files:
        sym = os.path.basename(f).replace(".parquet", "")
        # Skip small files
        try:
            df = pd.read_parquet(f)
            if not df.empty and len(df) > 100:
                data_map[sym] = df
        except:
            pass
    return data_map

if __name__ == "__main__":
    update_data()
