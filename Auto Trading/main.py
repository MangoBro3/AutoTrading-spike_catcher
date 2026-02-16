import os
import sys
import json
import time

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_banner():
    clear_screen()
    print("==========================================")
    print("       AUTO TRADING SYSTEM V2.1")
    print("==========================================")
    print("")

def load_best_params():
    base_dir = "autotune_runs"
    if not os.path.exists(base_dir): return None
    runs = sorted([d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))], reverse=True)
    for run in runs:
        path = os.path.join(base_dir, run, "best_params.json")
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    return json.load(f), run
            except: pass
    return None, None

def menu_start_trading():
    print("\n[1] Starting Auto Trader (V2)...")
    print("--------------------------------")
    os.system("python trader_v2.py")
    input("\n[Trader Stopped] Press Enter to return...")

def menu_view_params():
    print("\n[2] Current Best Parameters")
    print("--------------------------------")
    params, run_id = load_best_params()
    if params:
        print(f"Source Run: {run_id}\n")
        print(json.dumps(params, indent=4))
    else:
        print("❌ No optimized parameters found. Using defaults.")
    
    input("\nPress Enter to return...")

def menu_optimize():
    print("\n[3] Run Optimization (AutoTune)")
    print("--------------------------------")
    print("This will run a quick optimization (Group A, 20 trials).")
    print("For detailed UI control, please use 'Run_Lab.bat'.")
    confirm = input("Start Optimization? (y/n): ")
    if confirm.lower() == 'y':
        # Need a CLI wrapper for autotune. 
        # Since autotune is a class, we can create a small runner script or call via python -c
        # Creating a temporary runner script is safer.
        cmd = 'python -c "import sys; print(\'\\n[1/3] Loading Modules...\'); from autotune import AutoTuner; from strategy import Strategy; import data_loader; strat=Strategy(); print(\'[2/3] Updating Market Data (This may take time)...\'); data_loader.update_data(); data_map=data_loader.load_data_map(); print(\'[3/3] Starting AutoTune (Group A, 20 Trials)...\'); tuner=AutoTuner(data_map, strat.default_params); tuner.run_process(\'A\', 20, callback=lambda p, m: print(f\'   >> {m}\'));print(\'\\n[Done] Optimization Complete! results saved in autotune_runs/\');"'
        try:
             os.system(cmd)
        except Exception as e:
             print(f"Error: {e}")
    
    input("\nPress Enter to return...")

def menu_backtest():
    print("\n[4] Run Backtest (Quick)")
    print("--------------------------------")
    print("Running backtest with CURRENT best parameters...")
    # Using python -c to run quick backtest
    params, _ = load_best_params()
    if not params:
        print("No params found, using defaults.")
    
    # We can invoke backtester.py directly if it has a __main__ or use python -c
    # Let's assume we want to run a check.
    cmd = 'python -c "from backtester import Backtester; from strategy import Strategy; import data_loader; import json; params=Strategy().default_params; bt=Backtester(); data_loader.update_data(); data_map=data_loader.load_data_map(); res=bt.run_portfolio(data_map, params, verbose=True); print(\'Total Return: {:.2f}%\'.format(res[\'total_return\']));"' 
    # Simplified cmd for demo. Real implementation might need robust argument passing.
    # For now, let's just run backtester.py if it has a main, or just print "Use Lab".
    print("\n⚠️ For detailed visual backtest, please use the 'Run_Lab.bat' (Streamlit UI).")
    print("CLI Backtest is currently a placeholder for V2.2.")
    
    input("\nPress Enter to return...")

def main():
    while True:
        print_banner()
        print("1. ⚔️  Start Auto Trading")
        print("2. 📊 View Current Parameters")
        print("3. 🧠 Run Optimization (AutoTune)")
        print("4. 📉 Run Backtest")
        print("0. Exit")
        print("")
        
        choice = input("Select >> ")
        
        if choice == '1': menu_start_trading()
        elif choice == '2': menu_view_params()
        elif choice == '3': menu_optimize()
        elif choice == '4': menu_backtest()
        elif choice == '0': sys.exit()

if __name__ == "__main__":
    main()
