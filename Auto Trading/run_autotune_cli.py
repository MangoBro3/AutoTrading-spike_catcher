
import argparse
import sys
import os
import json
import pandas as pd
import glob
from autotune import AutoTuner
from backtester import Backtester # Import for class check if needed

# Add current path to sys.path to find modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def load_data():
    """Load all parquet files (Borrowed from app.py)"""
    data_dir = "data"
    files = glob.glob(os.path.join(data_dir, "*.parquet"))
    
    data_map = {}
    print(f"Loading data from {data_dir}...")
    for f in files:
        basename = os.path.basename(f).replace(".parquet", "")
        try:
            data_map[basename] = pd.read_parquet(f)
        except: pass
    print(f"Loaded {len(data_map)} files.")
    return data_map

def load_config():
    CONFIG_FILE = "user_config.json"
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def main():
    parser = argparse.ArgumentParser(description="AutoTune CLI Runner")
    parser.add_argument("--group", type=str, default="A", help="Target Group (A/B/C)")
    parser.add_argument("--trials", type=int, default=20, help="Number of trials")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--output", type=str, default="autotune_runs", help="Output directory")
    
    args = parser.parse_args()
    
    # 1. Load Data
    data_map = load_data()
    if not data_map:
        print("Error: No data found in 'data' folder.")
        return

    # 2. Load Config & Params
    user_config = load_config()
    
    # Default Params (Synced with app.py defaults)
    base_params = {
        'enable_strategy_A': user_config.get('enable_A', True),
        'enable_strategy_B': user_config.get('enable_B', True),
        # Strategy A
        'trigger_vol_A': user_config.get('trig_vol_A', 2.0),
        'breakout_days_A': user_config.get('bo_days_A', 7),
        'close_confirm_pct_A': user_config.get('confirm_pct_A', 0.5), # app.py multiplies by 100 on save? No, load_config reads what is saved.
        # Wait, app.py: confirm_pct_A = slider / 100. Save logic: confirm_pct_A * 100.
        # So json has 50.0 (if 0.5 * 100 = 50).
        # We need to be careful.
        # Let's assume user_config.json stores the RAW UI value (e.g. 0.5 * 100 = 50).
        # But app.py logic when saving: 'confirm_pct_A': confirm_pct_A * 100.
        # So json has 50.
        # But strat expects decimal?
        # app.py strat_params: 'close_confirm_pct_A': confirm_pct_A (which is 0.5/100 = 0.005)
        # So if loading from json: json=50 -> we need 0.5 -> /100?
        # Actually in app.py: `confirm_pct_A = st.slider(...) / 100`.
        # If config has 50, slider loads 50.
        # So here we need to divide by 100 if the key is typically percentage.
        # Let's check keys: 'close_confirm_pct_A', 'daily_loss_limit_pct'.
        
        # NOTE: To avoid mismatch, we should ideally reuse the exact transformation logic.
        # For Phase 1 CLI, let's use the values as is, assuming user wants to tune FROM them.
        # BUT AutoTune generates NEW values.
        # The base_params only matter for "Static" params that are NOT being tuned.
        # If we tune Group A, we overwrite A params.
        # If we tune Group B, we overwrite B params.
        
        'rsi_ceiling_A': user_config.get('rsi_cap_A', 75),
        'entry_delay_bars_A': user_config.get('delay_A', 1),
        
        # Strategy B
        'trend_ma_fast_B': user_config.get('ma_fast_B', 20),
        'trend_ma_slow_B': user_config.get('ma_slow_B', 60),
        'rsi_entry_B': user_config.get('rsi_B', 45),
        
        # Portfolio
        'allocation_A_pct': user_config.get('alloc_A', 60),
        'allocation_B_pct': 100 - user_config.get('alloc_A', 60),
        'max_entries_per_day': user_config.get('max_entries', 2),
        'max_open_positions': user_config.get('max_pos', 3),
        'cooldown_days_after_sl': user_config.get('cooldown', 5),
        'daily_loss_limit_pct': user_config.get('loss_limit', 2.0), # json has 2.0
        'min_turnover_krw': user_config.get('min_turnover', 10_000_000),
        'universe_top_n': user_config.get('universe_top_n', 0),
        
        # Exits
        'sl_atr_mult_A': user_config.get('sl_mul_A', 1.8),
        'trail_atr_mult_A': user_config.get('trail_mul_A', 2.5),
        'partial_tp_r_A': user_config.get('tp_r_A', 1.2),
        'time_stop_days_A': user_config.get('time_A', 3),
        
        'sl_atr_mult_B': user_config.get('sl_mul_B', 1.4),
        'partial_tp_r_B': user_config.get('tp_r_B', 1.0),
        'max_hold_days_B': user_config.get('max_hold_B', 5)
    }
    
    # Correction for percentages if needed (app.py divides by 100 for some)
    # daily_loss_limit_pct is used as % in params?
    # Backtester: p_loss_limit = params.get(...) / 100
    # So param should be 2.0. Good.
    
    # config.get('close_confirm_pct_A') -> app.py divides by 100.
    # In app.py: `confirm_pct_A = st.slider(...) / 100` -> `strat_params['close_confirm_pct_A'] = confirm_pct_A`
    # So strat expects 0.005.
    # User config has 0.5 (from slider default) or 50 (if saved?).
    # let's assume raw value.
    if base_params['close_confirm_pct_A'] > 0:
        base_params['close_confirm_pct_A'] /= 100.0

    print(f"\n🚀 Starting AutoTune CLI")
    print(f"   Group: {args.group}")
    print(f"   Trials: {args.trials}")
    print(f"   Seed: {args.seed}")
    print(f"   Output: {args.output}\n")
    
    try:
        tuner = AutoTuner(data_map, base_params, output_dir=args.output)
        
        # Callback for progress bar
        # AutoTune runs tasks: N trials * 4 folds.
        # We can use TQDM for the Whole Process if we want.
        # But autotune.py already logs "Trial X/Y".
        # Let's just pass a simple printer or use tqdm manually if we modify autotune?
        # Autotune accepts a callback(prog, msg).
        
        from tqdm import tqdm
        pbar = tqdm(total=100, desc="Overall Optimization", unit="%")
        
        last_p = 0
        def progress_handler(p, msg):
            nonlocal last_p
            # p is 0.0 to 1.0
            current_pct = int(p * 100)
            diff = current_pct - last_p
            if diff > 0:
                pbar.update(diff)
                last_p = current_pct
            pbar.set_postfix_str(msg)
            
        run_dir = tuner.run_process(args.group, num_trials=args.trials, seed=args.seed, callback=progress_handler)
        
        pbar.update(100 - last_p)
        pbar.close()
        
        print(f"\n✅ Done! Check {run_dir}")
        
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
