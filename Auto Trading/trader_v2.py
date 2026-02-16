import os
import time
import ccxt
import dotenv
from datetime import datetime
import pandas as pd

# Load Env
dotenv.load_dotenv()

# Modules
from config_v2 import *
from modules.budget_manager import BudgetManager
from modules.risk_manager import RiskCalculator
from modules.execution_engine import ExecutionEngine
from modules.notifier import TelegramNotifier
from modules.logger_utils import get_run_id

# Existing logic imports (Assumed to be in same dir)
import data_loader
from strategy import Strategy

import json
import glob

def load_best_params():
    """Find and load the latest best_params.json from autotune_runs"""
    base_dir = "autotune_runs"
    if not os.path.exists(base_dir): 
        print(f"[Config] No {base_dir} found. Using defaults.")
        return {}
        
    # Find all run folders
    runs = sorted([d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))], reverse=True)
    
    for run in runs:
        path = os.path.join(base_dir, run, "best_params.json")
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    params = json.load(f)
                    print(f"✅ Loaded Optimized Params from: {run}")
                    return params
            except Exception as e:
                print(f"⚠️ Failed to load params from {run}: {e}")
                
    print("[Config] No best_params.json found in recent runs. Using defaults.")
    return {}

def _legacy_mode_allowed() -> bool:
    return str(os.getenv("ALLOW_LEGACY", "0")).strip().lower() in {"1", "true", "yes", "on"}


def _is_entry_signal(last_row: pd.Series) -> bool:
    """Accept both legacy/new signal fields safely."""
    candidates = [
        "signal_confirm_A",  # legacy expectation
        "signal_A",          # strategy output
        "signal_buy_exec",   # shifted execution-safe output
        "signal_buy",        # pre-shift signal
    ]
    for key in candidates:
        try:
            if bool(last_row.get(key, False)):
                return True
        except Exception:
            continue
    return False


def _build_signal_payload(origin_symbol: str, last_row: pd.Series) -> dict:
    symbol_normalized = origin_symbol.replace("UPBIT_", "").replace("BITHUMB_", "").replace("_KRW", "/KRW")
    payload = {
        'symbol': symbol_normalized,
        'origin_symbol': origin_symbol,
        'score': float(last_row.get('score_exec', last_row.get('score', 0)) or 0),
        'target_money': BUDGET_KRW / 3,
        'spread_bp': float(last_row.get('spread_bp', 20) or 20),
        'ask_depth_sum': float(last_row.get('ask_depth_sum', 100_000_000) or 100_000_000),
        'chase_pct': float(last_row.get('chase_pct', 0.5) or 0.5),
    }

    # Minimal schema gate (P0): fail closed on malformed signal.
    required = ['symbol', 'score', 'target_money', 'spread_bp', 'ask_depth_sum', 'chase_pct']
    for k in required:
        if k not in payload:
            raise ValueError(f"Missing signal field: {k}")
    if payload['target_money'] <= 0:
        raise ValueError("target_money must be > 0")

    return payload


def main():
    print("=== Auto Trading System V2.1 Hiring... ===")

    # P0 safety: legacy loop is blocked by default.
    if not _legacy_mode_allowed():
        raise RuntimeError(
            "Legacy trader_v2.py is blocked by default. "
            "Use RunController for production path, or set ALLOW_LEGACY=1 explicitly."
        )
    
    # 1. Setup
    # 1. Setup
    bithumb_key = os.getenv("BITHUMB_KEY")
    bithumb_secret = os.getenv("BITHUMB_SECRET")
    upbit_key = os.getenv("UPBIT_ACCESS_KEY")
    upbit_secret = os.getenv("UPBIT_SECRET_KEY")
    
    tele_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    notifier = TelegramNotifier(tele_token, chat_id)
    run_id = get_run_id()
    log_dir = os.path.join(LOG_DIR_BASE, run_id)
    os.makedirs(log_dir, exist_ok=True)
    
    # 2. Exchange Connection & Budget Managers
    # Store exchanges in a dict for easy access
    exchanges = {}
    budget_managers = {}
    exec_engines = {}
    
    # --- Bithumb ---
    if bithumb_key and bithumb_secret:
        try:
            ex_bit = ccxt.bithumb({
                'apiKey': bithumb_key, 
                'secret': bithumb_secret,
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'}
            })
            exchanges['Bithumb'] = ex_bit
            budget_managers['Bithumb'] = BudgetManager("Bithumb", budget_krw=BUDGET_KRW, reserve_krw=RESERVE_KRW)
            exec_engines['Bithumb'] = ExecutionEngine(run_id, log_dir, budget_managers['Bithumb'])
            print("✅ Bithumb Connected")
        except Exception as e:
            print(f"❌ Bithumb Connection Failed: {e}")
            
    # --- Upbit ---
    if upbit_key and upbit_secret:
        try:
            ex_up = ccxt.upbit({
                'apiKey': upbit_key, 
                'secret': upbit_secret,
                'enableRateLimit': True,
                'options': {'defaultType': 'spot'}
            })
            exchanges['Upbit'] = ex_up
            budget_managers['Upbit'] = BudgetManager("Upbit", budget_krw=BUDGET_KRW, reserve_krw=RESERVE_KRW)
            exec_engines['Upbit'] = ExecutionEngine(run_id, log_dir, budget_managers['Upbit'])
            print("✅ Upbit Connected")
        except Exception as e:
             print(f"❌ Upbit Connection Failed: {e}")

    if not exchanges:
        print("❌ No exchanges connected. Check .env")
        return

    # 4. Baseline Initialization (CRITICAL security step)
    print("Locked & Loaded. Fetching Balance for Baseline...")
    
    msg_body = f"✅ **Bot Started (V2.1)**\nRunID: `{run_id}`\nBudget per Ex: `{BUDGET_KRW:,.0f} KRW`"
    
    # robust iteration to allow deletion
    exchange_names = list(exchanges.keys())
    
    for name in exchange_names:
        ex = exchanges[name]
        try:
            bal = ex.fetch_balance()
            current_assets = bal['total']
            budget_managers[name].initialize_baseline(current_assets)
            msg_body += f"\n- **{name}**: Baseline Locked (Assets: {len(current_assets)})"
        except Exception as e:
            print(f"❌ Failed to init baseline for {name}: {e}")
            del exchanges[name]
            print(f"⚠️ Removed {name} from active list due to error.")

    if not exchanges:
        print("❌ All exchanges failed. Stop.")
        return
            
    # Notify
    import asyncio
    asyncio.run(notifier.send_msg(msg_body))

    # 5. Main Loop
    strategy = Strategy()
    best_params = load_best_params()
    
    # Merge defaults with best_params
    # Default as defined in strategy or here
    base_params = {'trigger_vol_A': 2.0} 
    current_params = base_params.copy()
    current_params.update(best_params)
    
    print(f"🚀 Starting Logic Loop... Params: {current_params}")
    
    while True:
        try:
            # A. Update Data
            # Note: For V2.1 "Race Horse" mode, we might need faster loop than standard data_loader
            # But adhering to existing structure for now.
            data_loader.update_data()
            
            # B. Analyze
            # Load data from parquet (Simulation for V2 structure using existing loader)
            # In real high-frequency V2, this should be in-memory. 
            # Assuming data_loader saves to disk and we read back.
            data_map = {} # Load logic same as trader.py
            import glob
            files = glob.glob("data/*.parquet")
            for f in files:
                sym = os.path.basename(f).replace(".parquet", "")
                data_map[sym] = pd.read_parquet(f)
                
            # C. Generate Signals
            signals = []
            for sym, df in data_map.items():
                if df.empty:
                    continue
                # Run Strat
                res = strategy.analyze(df, params=current_params)
                last = res.iloc[-1]

                # Check Signal (legacy + new fields)
                if _is_entry_signal(last):
                    try:
                        sig = _build_signal_payload(sym, last)
                        signals.append(sig)
                    except Exception as e:
                        print(f"[SignalSchema] Skip malformed signal for {sym}: {e}")
            
            # D. Execute
            # Iterate through signals and route to appropriate exchange/engine
            
            for sig in signals:
                # Determine Exchange (Simple logic based on symbol prefix or config)
                # Current sig['symbol'] is like "KRW-BTC" or "BTC/KRW"
                # Need to know which exchange provided the data/signal.
                # In V1 data_loader, symbols are prefixed: UPBIT_KRW-BTC, BITHUMB_BTC_KRW
                # Sig generation earlier should preserve this or route.
                
                # Let's assume Signal carries 'exchange' or we try both if symbol exists.
                # For V2.1 MVP, let's map by prefix if available, or try all.
                
                target_ex_names = []
                symbol_clean = sig['symbol']
                
                # Heuristic routing
                if "UPBIT" in sig.get('origin_symbol', ''):
                    target_ex_names.append('Upbit')
                elif "BITHUMB" in sig.get('origin_symbol', ''):
                    target_ex_names.append('Bithumb')
                else:
                    # Default to both if not specified? Or check market existence?
                    # Safer: Try All connected
                    target_ex_names = list(exchanges.keys())

                for ex_name in target_ex_names:
                    if ex_name not in exchanges: continue
                    
                    engine = exec_engines[ex_name]
                    ex_api = exchanges[ex_name]
                    
                    # Prepare Market Data for Gate
                    current_market = {
                        'balance': engine.budget_mgr.bot_cash, 
                        'price': 0 
                    }
                    
                    # Fetch fresh ticker
                    try:
                        ticker = ex_api.fetch_ticker(symbol_clean)
                        current_market['price'] = ticker['last']
                        
                        # Execute
                        engine.execute_entry(sig, current_market, exchange_api=ex_api)
                        
                    except Exception as e:
                        print(f"[{ex_name}] Ticker/Exec Error for {symbol_clean}: {e}")
                
            time.sleep(60) # 1 min Interval
            
        except KeyboardInterrupt:
            print("Stop.")
            break
        except Exception as e:
            print(f"Loop Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
