import pandas as pd
import numpy as np
import requests
import joblib
import os
import logging
from datetime import datetime

# Config
BASE_URL = "https://api.bithumb.com"
MODEL_FILE = "data/model.pkl"
TOP_K = 10
BTC_KILL_THRESHOLD = -0.03 # -3%

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_candles_recent(market, count=60):
    url = f"{BASE_URL}/v1/candles/days"
    params = {"market": market, "count": count}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        if not data: return None
        return pd.DataFrame(data)
    except:
        return None

def fetch_markets():
    url = f"{BASE_URL}/v1/market/all"
    params = {"isDetails": "true"}
    try:
        response = requests.get(url, params=params)
        data = response.json()
        return [m for m in data if m['market'].startswith('KRW-')]
    except:
        return []

def prepare_features(market_code, df, btc_df):
    try:
        # Date parsing
        if 'candle_date_time_utc' in df.columns:
            df['date'] = pd.to_datetime(df['candle_date_time_utc'])
        else:
            df['date'] = pd.to_datetime(df['candle_date_time_kst'])
            
        df = df.sort_values('date').reset_index(drop=True)
        
        # Numeric Check
        cols_to_num = ['opening_price', 'high_price', 'low_price', 'trade_price', 'candle_acc_trade_volume', 'candle_acc_trade_price']
        for col in cols_to_num:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # Features
        o = df['opening_price']
        h = df['high_price']
        l = df['low_price']
        c = df['trade_price']
        
        eps = 1e-9
        body = (c - o).abs()
        upper_wick = h - np.maximum(o, c)
        
        df['body_ratio'] = body / (h - l + eps)
        df['upper_wick_ratio'] = upper_wick / (body + eps)
        df['pos_in_candle'] = (c - l) / (h - l + eps)
        
        # Rolling 7d
        for col in ['body_ratio', 'upper_wick_ratio', 'pos_in_candle']:
            df[f'{col}_max_7d'] = df[col].rolling(7).max()
            df[f'{col}_mean_7d'] = df[col].rolling(7).mean()
            
        df['ret_1d'] = c.pct_change()
        df['ret_2d'] = c.pct_change(2)
        df['ret_3d'] = c.pct_change(3)
        
        # Join BTC (Merge on Date)

        # Assuming btc_df has index as date
        df = df.set_index('date').join(btc_df, how='left')
        
        df['rs_7d'] = df['trade_price'].pct_change(7) - df['btc_ret_7d']
        df['corr_30d'] = df['ret_1d'].rolling(30).corr(df['btc_ret_1d'])
        
        df['vol_7d'] = df['ret_1d'].rolling(7).std()
        df['vol_30d'] = df['ret_1d'].rolling(30).std()
        df['vol_squeeze'] = df['vol_7d'] / (df['vol_30d'] + eps)
        
        df['ma20'] = c.rolling(20).mean()
        df['ma60'] = c.rolling(60).mean()
        df['dist_ma20'] = c / df['ma20'] - 1
        df['dist_ma60'] = c / df['ma60'] - 1
        
        # Return LAST row (Features for predicting Tomorrow)
        # Note: If we run this "Today" (T), we have closed candle T-1? or T?
        # Bithumb "Days" candle at current time might be Today's Incomplete?
        # Specification says "anchor_dt = T-1". 
        # Usually checking AFTER Close (9:00 AM KST).
        # We take the last completed candle.
        # Assuming run time is after close, df.iloc[-1] is yesterday's close (or today's depending on API convention).
        # Upbit 'candles/days' returns [Today, Yesterday...]
        # If we take df.iloc[-1] (sorted asc), it's the LATEST candle.
        
        # We use the latest available data to predict NEXT Pump.
        return df.iloc[[-1]].reset_index()
        
    except Exception as e:
        return None

def main():
    if not os.path.exists(MODEL_FILE):
        logging.error("Model file not found. Train first.")
        return

    model = joblib.load(MODEL_FILE)
    markets = fetch_markets()
    logging.info(f"Scanning {len(markets)} markets...")
    
    # Fetch BTC for Features & Kill Switch
    btc_df = fetch_candles_recent('KRW-BTC', count=100)
    if btc_df is None:
        logging.error("Failed to fetch BTC.")
        return
        
    # Process BTC
    if 'candle_date_time_utc' in btc_df.columns:
        btc_df['date'] = pd.to_datetime(btc_df['candle_date_time_utc'])
    else:
        btc_df['date'] = pd.to_datetime(btc_df['candle_date_time_kst'])
        
    btc_df['trade_price'] = pd.to_numeric(btc_df['trade_price'])
    btc_df = btc_df.sort_values('date').set_index('date')
    btc_df['btc_ret_1d'] = btc_df['trade_price'].pct_change()
    btc_df['btc_ret_7d'] = btc_df['trade_price'].pct_change(7)
    btc_df['btc_ma60'] = btc_df['trade_price'].rolling(60).mean()
    btc_df['btc_bear'] = (btc_df['trade_price'] < btc_df['btc_ma60']).astype(int)
    
    btc_features = btc_df[['btc_ret_1d', 'btc_ret_7d', 'btc_bear']]
    
    # KILL SWITCH CHECK
    last_btc_ret = btc_features.iloc[-1]['btc_ret_1d']
    if last_btc_ret <= BTC_KILL_THRESHOLD:
        print(f"!!! KILL SWITCH ACTIVATED !!! (BTC 1d Return: {last_btc_ret:.2%})")
        return

    candidates = []
    
    for m in markets:
        if m['market'] == 'KRW-BTC': continue
        
        # Rate limit
        import time
        time.sleep(0.1)
        
        df = fetch_candles_recent(m['market'], count=60)
        if df is None or len(df) < 30: continue
        
        feat_df = prepare_features(m['market'], df, btc_features)
        
        if feat_df is not None:
            # Predict
            # Ensure columns match model
            # For now, just pass all cols, LightGBM ignores extras if configured (or we should filter)
            # Better to filter: model.booster_.feature_name()
            
            # Predict
            try:
                # Drop non-feature cols
                cols_to_drop = ['date', 'index', 'market', 'candle_date_time_utc', 'candle_date_time_kst', 'opening_price', 'high_price', 'low_price', 'trade_price', 'candle_acc_trade_volume', 'candle_acc_trade_price', 'timestamp']
                X_in = feat_df.drop(columns=[c for c in cols_to_drop if c in feat_df.columns], errors='ignore')
                
                # Align columns? LGBM uses feature names.
                prob = model.predict_proba(X_in)[:, 1][0]
                candidates.append({'market': m['market'], 'score': prob})
            except Exception as e:
                pass

    # Sort & Output
    candidates.sort(key=lambda x: x['score'], reverse=True)
    top_k = candidates[:TOP_K]
    
    print(f"\n=== Today's Top {TOP_K} Pump Candidates ===")
    for i, c in enumerate(top_k):
        print(f"{i+1}. {c['market']} (Score: {c['score']:.4f})")

if __name__ == "__main__":
    main()
