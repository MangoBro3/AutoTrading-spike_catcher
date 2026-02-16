
import os
import pandas as pd
import glob
from strategy import Strategy

def load_data():
    data_dir = "data"
    files = glob.glob(os.path.join(data_dir, "*.parquet"))
    data_map = {}
    for f in files:
        basename = os.path.basename(f).replace(".parquet", "")
        try:
            df = pd.read_parquet(f)
            if not df.empty:
                data_map[basename] = df
        except: pass
    return data_map

def debug_strategy():
    print("=== Signal Debugger ===")
    data_map = load_data()
    print(f"Loaded {len(data_map)} symbols.")
    
    if not data_map:
        print("No data found in 'data/' folder.")
        return

    strat = Strategy()
    
    # Aggressive Test Params (User's defaults)
    params = {
        'trigger_vol_A': 1.5,
        'breakout_days_A': 5,
        'close_confirm_pct_A': 0.002,
        'use_regime_filter_A': False, # Force check without regime
        'rsi_ceiling_A': 85
    }
    
    print(f"\nTest Params: {params}\n")
    
    analyzed_count = 0
    signal_count = 0
    
    # Sort by recent Date to check freshness
    latest_dates = []
    
    for sym, df in data_map.items():
        if "USDT" in sym: continue
        
        # Check freshness
        if 'datetime' in df.columns:
            last_dt = df['datetime'].iloc[-1]
            latest_dates.append(last_dt)
        
        res = strat.analyze(df, params=params)
        last = res.iloc[-1]
        
        # Debug Print for a few symbols
        if analyzed_count < 5: 
            print(f"--- {sym} ---")
            print(f"Length: {len(df)}")
            print(f"Date Type: {df['datetime'].dtype}")
            if not df.empty:
                print(f"Sample Date: {df['datetime'].iloc[0]}")
            print(f"Date: {last.get('datetime')}")
            print(f"Close: {last['close']}")
            print(f"Vol Spike: {last.get('vol_spike', 0):.2f} (Req: {params['trigger_vol_A']})")
            print(f"BO Level: {last.get('bo_level_A', 0):.2f}")
            print(f"Is Confirm: {last['close'] >= last.get('bo_level_A', 0) * 1.002}")
            print(f"RSI: {last.get('rsi', 0):.1f}")
            print(f"Signal A: {last.get('signal_A')}")
            print("----------------")
            
        analyzed_count += 1
        if last.get('signal_A'):
            signal_count += 1
            print(f"!!! SIGNAL FOUND: {sym} !!!")

    print(f"\nStats:")
    print(f"Total Analyzed: {analyzed_count}")
    print(f"Total Signals: {signal_count}")
    
    if latest_dates:
        print(f"Data Date Range: {min(latest_dates)} ~ {max(latest_dates)}")
        
if __name__ == "__main__":
    debug_strategy()
