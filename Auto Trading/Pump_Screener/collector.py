import requests
import pandas as pd
import time
import os
import json
import logging
from datetime import datetime, timedelta

# Configuration
BASE_URL = "https://api.bithumb.com" # Using Bithumb API
DATA_DIR = "data/raw"
CHECKPOINT_FILE = "data/checkpoint.json"
RATE_LIMIT_DELAY = 0.1  # 10 requests per second (Safe limit)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_checkpoint(checkpoint):
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump(checkpoint, f, indent=4)

def fetch_markets():
    """
    Fetches all markets and filters for KRW markets.
    Using Bithumb Public API v1 (Assuming compatibility with v1/market/all)
    If Bithumb standard API, it's public/ticker/ALL_KRW etc.
    But implementing requested 'v1/market/all' style.
    """
    url = f"{BASE_URL}/v1/market/all"
    params = {"isDetails": "true"}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        # Filter KRW markets
        krw_markets = [m for m in data if m['market'].startswith('KRW-')]
        
        # Also fetch BTC market for features
        btc_market = [m for m in data if m['market'] == 'KRW-BTC']
        
        logging.info(f"Fetched {len(krw_markets)} KRW markets.")
        return krw_markets
    except Exception as e:
        logging.error(f"Failed to fetch markets: {e}")
        return []

def fetch_candles_chunk(market, to=None, count=200):
    url = f"{BASE_URL}/v1/candles/days"
    params = {
        "market": market,
        "count": count
    }
    if to:
        params["to"] = to
        
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"Error fetching candles for {market}: {e}")
        return None

def collect_market_data(market_code, checkpoint):
    logging.info(f"Starting collection for {market_code}...")
    
    all_candles = []
    
    # Check if we have existing data to resume? 
    # For now, implementing simplistic full-history logic or resume from 'next_to'
    
    # However, standard practice for "Full History" with paging backward:
    # Start from NOW (or None) -> Go back until no results.
    
    current_to = checkpoint.get(market_code, {}).get('next_to', None)
    is_done = checkpoint.get(market_code, {}).get('done', False)
    
    if is_done:
        logging.info(f"Market {market_code} is already fully collected.")
        return

    while True:
        candles = fetch_candles_chunk(market_code, to=current_to)
        
        if not candles:
            logging.info(f"No more candles found for {market_code}.")
            break
            
        # Parse and append
        # API returns: [{"market": "KRW-BTC", "candle_date_time_utc": "...", ...}, ...]
        # We need to sort or handle them. 'candles' list is usually desc or asc.
        # Upbit/Bithumb v1 usually returns latest first (descending).
        
        all_candles.extend(candles)
        
        # Update cursor (latest timestamp in the chunk or the last one?)
        # With 'to' (exclusive), use the OLDEST timestamp in the batch as the next 'to'.
        # Since response is usually Descending order (New -> Old):
        # The last item is the oldest.
        
        last_candle_time = candles[-1]['candle_date_time_etc'] if 'candle_date_time_etc' in candles[-1] else candles[-1]['candle_date_time_kst']
        # Note: Bithumb v1 might use 'candle_date_time_utc' or 'kst'.
        # Let's inspect the first response structure if possible, but assuming standard v1.
        # Fallback to 'candle_date_time_utc'
        
        timestamp_key = 'candle_date_time_utc' # Standard
        
        if timestamp_key not in candles[0]:
            logging.error(f"Unknown timestamp key in response: {candles[0].keys()}")
            break
            
        oldest_in_batch = candles[-1][timestamp_key]
        
        current_to = oldest_in_batch
        
        logging.info(f"Fetched {len(candles)} candles. Next cursor: {current_to}")
        
        # Checkpoint update
        checkpoint[market_code] = {'next_to': current_to, 'done': False}
        save_checkpoint(checkpoint) # Frequent save might be slow, but safer.
        
        time.sleep(RATE_LIMIT_DELAY)
        
        # Stop condition? 
        # If count < requested? usually means end of history.
        if len(candles) < 200:
            break

    # Save to file
    if all_candles:
        df = pd.DataFrame(all_candles)
        save_path = os.path.join(DATA_DIR, f"{market_code}.parquet")
        
        # If file exists, merge? or Overwrite?
        # User said "Full-history". Let's overwrite for now or Append if smart.
        # Simpler: Load existing, append new, drop duplicates, save.
        
        if os.path.exists(save_path):
            existing_df = pd.read_parquet(save_path)
            df = pd.concat([existing_df, df])
        
        df = df.drop_duplicates(subset=['candle_date_time_utc']).sort_values('candle_date_time_utc')
        df.to_parquet(save_path, index=False)
        logging.info(f"Saved {len(df)} rows to {save_path}")

    # Mark as done
    checkpoint[market_code]['done'] = True
    save_checkpoint(checkpoint)

def main():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
        
    checkpoint = load_checkpoint()
    markets = fetch_markets()
    
    if not markets:
        logging.error("No markets found. Exiting.")
        return

    # Prioritize BTC first for features
    btc_market = next((m for m in markets if m['market'] == 'KRW-BTC'), None)
    if btc_market:
        collect_market_data(btc_market['market'], checkpoint)
    
    for market in markets:
        if market['market'] == 'KRW-BTC': continue
        collect_market_data(market['market'], checkpoint)

if __name__ == "__main__":
    main()
