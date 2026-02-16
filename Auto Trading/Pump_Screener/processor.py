import pandas as pd
import numpy as np
import os
import glob
from concurrent.futures import ProcessPoolExecutor
import logging

# Configuration
DATA_DIR = "data/raw"
PROCESSED_DIR = "data/processed"
BTC_FILE = os.path.join(DATA_DIR, "KRW-BTC.parquet")
MIN_NOTIONAL = 100_000_000 # 1억 KRW
LIQ_RATIO = 0.7 # Notional / MA20 >= 0.7

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def load_btc_data():
    if not os.path.exists(BTC_FILE):
        raise FileNotFoundError(f"BTC file not found: {BTC_FILE}")
    df = pd.read_parquet(BTC_FILE)
    df['candle_date_time_kst'] = pd.to_datetime(df['candle_date_time_kst']) # Use KST or UTC
    # Standardize time column
    if 'candle_date_time_utc' in df.columns:
        df['date'] = pd.to_datetime(df['candle_date_time_utc'])
    else:
        df['date'] = pd.to_datetime(df['candle_date_time_kst'])
    
    # Ensure Numeric
    df['trade_price'] = pd.to_numeric(df['trade_price'], errors='coerce')
    
    df = df.sort_values('date').set_index('date')
    df['btc_ret_1d'] = df['trade_price'].pct_change()

    df['btc_ret_7d'] = df['trade_price'].pct_change(7)
    df['btc_ma60'] = df['trade_price'].rolling(60).mean()
    df['btc_bear'] = (df['trade_price'] < df['btc_ma60']).astype(int)
    return df[['btc_ret_1d', 'btc_ret_7d', 'btc_bear']]

def process_market(file_path, btc_df):
    try:
        df = pd.read_parquet(file_path)
        market_code = os.path.basename(file_path).replace('.parquet', '')
        
        # Date parsing
        if 'candle_date_time_utc' in df.columns:
            df['date'] = pd.to_datetime(df['candle_date_time_utc'])
        else:
            df['date'] = pd.to_datetime(df['candle_date_time_kst'])
            
        df = df.sort_values('date').reset_index(drop=True)
        
        # Ensure Numeric
        cols_to_num = ['opening_price', 'high_price', 'low_price', 'trade_price', 'candle_acc_trade_volume', 'candle_acc_trade_price']
        for col in cols_to_num:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # Basic Price Features
        o = df['opening_price']
        h = df['high_price']
        l = df['low_price']
        c = df['trade_price']
        v = df['candle_acc_trade_volume']
        notional = df['candle_acc_trade_price']

        
        # Returns
        df['ret_1d'] = c.pct_change()
        df['ret_2d'] = c.pct_change(2)
        df['ret_3d'] = c.pct_change(3)
        
        # --- LABELING ---
        # Pump Event: 1D > 20% OR (2D or 3D > 50%)
        # Look ahead: Label at T depends on T+1 return (so we predict at T)
        # Or Label at T (Pump Day) -> The SAMPLE is T-1.
        
        # Let's verify input: "Positive: y=1, anchor_dt = T-1". 
        # So we identify Pump Day P. Then row P-1 is the Positive Sample.
        
        # Identify Pump Days
        is_pump_1d = (df['ret_1d'] >= 0.20)
        # For multi-day, simple approximation using sliding window max return
        # But ret_2d > 0.5 means from T-2 to T is > 50%.
        # If today is T, did it pump?
        is_pump_multi = (df['ret_2d'] >= 0.50) | (df['ret_3d'] >= 0.50)
        
        pump_mask = is_pump_1d | is_pump_multi
        
        # To create samples, we shift the mask BACKWARDS?
        # No, if T is Pump, we want to label T-1 as "Will Pump".
        # So label column 'target' at row T-1 should be 1.
        # We shift the pump_mask BACK by 1 (-1 shift).
        
        df['is_pump_event'] = pump_mask
        df['target'] = df['is_pump_event'].shift(-1).fillna(False).astype(int) # Looks at NEXT day
        # For multi-day, the pump starts at T. So T-1 should predict T.
        
        # --- DECLUSTERING ---
        # Keep only the FIRST pump day in a 10-day window.
        # Logic: If row i is target=1, and row i-k (k<10) was target=1, set row i target=0.
        
        # Find indices where target=1
        target_indices = df.index[df['target'] == 1].tolist()
        valid_indices = []
        
        if target_indices:
            last_idx = -999
            for idx in target_indices:
                if idx - last_idx >= 10:
                    valid_indices.append(idx)
                    last_idx = idx
        
        # Overwrite target
        df['target'] = 0
        df.loc[valid_indices, 'target'] = 1
        
        # --- FILTERING ---
        # Liquidity Floor (anchor T)
        ma20_notional = notional.rolling(20).mean()
        liq_cond = (notional >= MIN_NOTIONAL) & ((notional / ma20_notional) >= LIQ_RATIO)
        # We only keep rows that satisfy this at T (the prediction time)
        
        # --- FEATURES ---
        # 1. Wick & Body
        # eps to avoid zero div
        eps = 1e-9
        body = (c - o).abs()
        upper_wick = h - np.maximum(o, c)
        lower_wick = np.minimum(o, c) - l
        
        df['body_ratio'] = body / (h - l + eps)
        df['upper_wick_ratio'] = upper_wick / (body + eps)
        df['pos_in_candle'] = (c - l) / (h - l + eps)
        
        # Rolling Stats (7d)
        for col in ['body_ratio', 'upper_wick_ratio', 'pos_in_candle']:
            df[f'{col}_max_7d'] = df[col].rolling(7).max()
            df[f'{col}_mean_7d'] = df[col].rolling(7).mean()
        
        # 2. Relative Strength
        # Join BTC
        df = df.set_index('date').join(btc_df, how='left')
        
        df['rs_7d'] = df['trade_price'].pct_change(7) - df['btc_ret_7d']
        # Correlation 30d
        df['corr_30d'] = df['ret_1d'].rolling(30).corr(df['btc_ret_1d'])
        
        # 3. Volatility
        df['vol_7d'] = df['ret_1d'].rolling(7).std()
        df['vol_30d'] = df['ret_1d'].rolling(30).std()
        df['vol_squeeze'] = df['vol_7d'] / (df['vol_30d'] + eps)
        
        # 4. Trend
        df['ma20'] = c.rolling(20).mean()
        df['ma60'] = c.rolling(60).mean()
        df['dist_ma20'] = c / df['ma20'] - 1
        df['dist_ma60'] = c / df['ma60'] - 1
        
        # Select Features requires T-1 availability. 
        # All columns computed with rolling/shift(0) are available at T.
        # But we are predicting T+1. So at row T, we predict T+1.
        # Correct. 'target' is shift(-1).
        
        # Apply Filters
        # Only rows where we have enough history (e.g. 60 days) and Liq condition met
        # Relaxed for debugging
        valid_mask = (df.index >= df.index[0] + pd.Timedelta(days=1)) 
        
        df_valid = df[valid_mask].copy()
        
        # --- SAMPLING ---
        # Positives
        positives = df_valid[df_valid['target'] == 1]
        n_pos = len(positives)
        # logging.info(f"{market_code}: {n_pos} pumps found.")
        
        if n_pos == 0:
            return None
            
        negatives = df_valid[df_valid['target'] == 0]
        # Relax sampling ratio
        if len(negatives) > n_pos * 10:
            negatives = negatives.sample(n_pos * 10, random_state=42)
            
        final_df = pd.concat([positives, negatives])
        final_df['market'] = market_code
        return final_df

        
    except Exception as e:
        # logging.error(f"Error processing {file_path}: {e}")
        return None

def main():
    if not os.path.exists(PROCESSED_DIR):
        os.makedirs(PROCESSED_DIR)
        
    logging.info("Loading BTC data...")
    try:
        btc_df = load_btc_data()
    except Exception as e:
        logging.error(e)
        return

    logging.info("Processing markets...")
    files = glob.glob(os.path.join(DATA_DIR, "*.parquet"))
    # Filter out BTC from processing list (it's the reference)
    files = [f for f in files if "KRW-BTC" not in f]
    
    # Use standard loop for debug (ProcessPool sometimes hard in snippets)
    results = []
    
    # Limit for quick test if needed, but running all is fine ~400 files
    count = 0
    for f in files:
        res = process_market(f, btc_df)
        if res is not None:
            results.append(res)
        count += 1
        if count % 50 == 0:
            logging.info(f"Processed {count}/{len(files)} files...")

    if not results:
        logging.warning("No data generated.")
        return

    full_df = pd.concat(results)
    save_path = os.path.join(PROCESSED_DIR, "train_dataset.parquet")
    full_df.to_parquet(save_path)
    logging.info(f"Dataset saved to {save_path}. Shape: {full_df.shape}")
    
    # Class balance check
    vc = full_df['target'].value_counts()
    logging.info(f"Class Balance:\n{vc}")

if __name__ == "__main__":
    main()
