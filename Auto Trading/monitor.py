import time
import os
import pandas as pd
from datetime import datetime
import data_loader
from strategy import Strategy
from telegram_bot import send_telegram_message
import glob

def load_and_analyze():
    data_dir = "data"
    files = glob.glob(os.path.join(data_dir, "*.parquet"))
    
    data_map = {}
    for f in files:
        basename = os.path.basename(f).replace(".parquet", "")
        try:
            data_map[basename] = pd.read_parquet(f)
        except: pass
            
    return data_map

def run_cycle():
    print(f"\n[Monitor] Starting Scan Cycle at {datetime.now()}")
    
    # 1. Update Data
    print("[Monitor] Updating Data...")
    try:
        data_loader.update_data() # This saves parquets
    except Exception as e:
        print(f"[Monitor] Data Update Failed: {e}")
        send_telegram_message(f"⚠️ **Error**: Data Update Failed\n`{e}`")
        return

    # 2. Load & Analyze
    data_map = load_and_analyze()
    strat = Strategy()
    
    # Find BTC context
    btc_df = None
    for k in ['GLOBAL_BTC', 'UPBIT_KRW-BTC']:
        if k in data_map: 
             btc_df = data_map[k]
             break
             
    # Params (Standard)
    params = {
        'trigger_vol': 2.5,
        'breakout_days': 7,
        'beast_vol': 10.0,
        'beast_ret': 0.15,
        'use_regime': True
    }
    
    triggers = []
    beasts = []
    
    print("[Monitor] Analyzing Candidates...")
    for symbol, df in data_map.items():
        if "BTC" in symbol: continue
        if df.empty: continue
        
        df_res = strat.analyze(df, params=params)
        last = df_res.iloc[-1]
        
        item = {
            'symbol': symbol,
            'price': last['close'],
            'vol': last['vol_spike'],
            'ret': last['ret_1d'],
            'score_silence': last.get('score_silence', 0)
        }
        
        if last.get('signal_beast', False):
            beasts.append(item)
        elif last.get('signal_action', False): # Trigger
             triggers.append(item)
             
    # 3. Send Alerts
    msg_lines = []
    if beasts:
        msg_lines.append(f"🔥 **BEAST MODE DETECTED** ({len(beasts)})")
        for b in beasts:
            msg_lines.append(f"- {b['symbol']}: {b['ret']:.1%} (Vol {b['vol']:.1f}x)")
            
    if triggers:
        if msg_lines: msg_lines.append("")
        msg_lines.append(f"🟢 **BUY SIGNAL** ({len(triggers)})")
        for t in triggers:
            msg_lines.append(f"- {t['symbol']}: {t['price']:,} (Vol {t['vol']:.1f}x)")
            
    if msg_lines:
        final_msg = "\n".join(msg_lines)
        print("[Monitor] Sending Alert...")
        print(final_msg)
        send_telegram_message(f"🐯 **Quant Alert**\n{final_msg}")
    else:
        print("[Monitor] No signals found.")

def main_loop(interval_minutes=30):
    send_telegram_message(f"🤖 **Auto Monitor Started**\nInterval: {interval_minutes} min")
    
    while True:
        try:
            run_cycle()
        except Exception as e:
            print(f"Cycle Error: {e}")
            send_telegram_message(f"⚠️ Monitor Error: {e}")
            
        print(f"[Monitor] Sleeping for {interval_minutes} min...")
        time.sleep(interval_minutes * 60)

if __name__ == "__main__":
    # Default 60 min loop
    main_loop(60)
