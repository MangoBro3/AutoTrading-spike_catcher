
import sys
import time
import threading
import json
import logging
import signal
import urllib.request
import urllib.error
from pathlib import Path

# Module Imports
from modules.adapter_upbit import UpbitAdapter
from modules.capital_ledger import CapitalLedger
from modules.watch_engine import WatchEngine
from modules.run_controller import RunController
from modules.notifier_telegram import TelegramNotifier
from modules.dashboard_cli import DashboardCLI

# Configure centralized logging (Launcher Level)
Path("results/logs").mkdir(parents=True, exist_ok=True)
Path("results/locks").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename='results/logs/launcher.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
console = logging.StreamHandler()
console.setLevel(logging.WARNING) # Console only clean errors
logging.getLogger('').addHandler(console)

class Launcher:
    def __init__(self):
        self.controller = None # The Worker Thread Object
        self.worker_thread = None
        self.running = True
        self.menu_lock = False # Prevents dashboard refresh collision during input
        self.use_api = True
        self.api_base = "http://127.0.0.1:8765"
        
        # Cleanup Stale IPC Status
        try:
            Path("results/runtime_status.json").unlink(missing_ok=True)
        except:
            pass
        
    def _load_config(self):
        # In MVP, hardcode or basic env check
        # For Stage 11, we verify keys exist
        pass

    def _api_request(self, method, path, payload=None):
        url = f"{self.api_base}{path}"
        data = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    def _api_get(self, path):
        return self._api_request("GET", path)

    def _api_post(self, path, payload=None):
        return self._api_request("POST", path, payload)

    def _wait_input(self, prompt_text):
        """
        Thread-Safe Input Wrapper.
        Pauses Dashboard refresh while waiting for user input.
        """
        self.menu_lock = True
        try:
            # Clear line if possible or just print newline
            print(f"\n{prompt_text}", end='', flush=True)
            return sys.stdin.readline().strip()
        finally:
            self.menu_lock = False

    def start_trading_thread(self, mode="PAPER", seed=1000000, disable_strategy=False, confirm_phrase=None):
        if self.worker_thread and self.worker_thread.is_alive():
            print(" [!] Bot is already running.")
            return

        print(f" [Launcher] Initializing {mode} Mode...")

        if self.use_api:
            try:
                # Update backend settings
                self._api_post("/api/settings", {
                    "mode": mode,
                    "seed_krw": seed
                })
                payload = {}
                if confirm_phrase:
                    payload["confirm"] = confirm_phrase
                res = self._api_post("/api/start", payload)
                print(f" [Launcher] {res.get('message', 'Started via backend')}")
            except Exception as e:
                print(f" [ERROR] Backend start failed: {e}")
            return

        # 1. Initialize Modules
        try:
            # Detect Exchange (Hardcoded Upbit for now as per Context)
            adapter = UpbitAdapter(use_env=True)
            notifier = TelegramNotifier() 
            
            # Fix: CapitalLedger(exchange_name, initial_seed)
            ledger = CapitalLedger(exchange_name="UPBIT", initial_seed=seed)
            # WatchEngine expects notifier (not adapter). Use notifier for regime-change alerts.
            watch = WatchEngine(notifier)
            
            # 2. Controller
            self.controller = RunController(
                adapter,
                ledger,
                watch,
                notifier,
                mode=mode,
                disable_strategy=disable_strategy
            )
            
            # 3. Pre-flight
            if not self.controller.perform_preflight_check():
                print(" [ABORT] Pre-flight Check Failed.")
                return

            # 4. Start Thread
            self.worker_thread = threading.Thread(target=self.controller.run, daemon=True)
            self.worker_thread.start()
            print(" [Launcher] Trading Thread Started.")
            
        except Exception as e:
            print(f" [ERROR] Initialization Failed: {e}")
            logging.error("Init Failed", exc_info=True)

    def stop_trading_thread(self):
        if self.use_api:
            try:
                res = self._api_post("/api/stop")
                print(f" [Launcher] {res.get('message', 'Stopped via backend')}")
            except Exception as e:
                print(f" [WARN] Backend stop failed: {e}")
            return

        if self.controller and self.controller.running:
            print(" [Launcher] Stopping Controller...")
            self.controller.stop()
            self.worker_thread.join(timeout=5)
            if self.worker_thread.is_alive():
                 print(" [WARN] Controller thread stuck. Force killing not supported in Python threads.")
            print(" [Launcher] Stopped.")
        else:
            print(" [!] Not running.")

    def run_dashboard_loop(self):
        import msvcrt
        
        print(" [Launcher] Entering Dashboard Loop. Press 'm' for Menu, 'q' to Quit.")
        last_refresh = 0
        current_status = "STARTING"
        
        while self.running:
            # 1. Refresh Dashboard 
            # If ERROR, we slow down refresh to 5s and DO NOT clear screen aggressively
            refresh_interval = 5.0 if current_status == "ERROR" else 1.0
            
            if not self.menu_lock and (time.time() - last_refresh > refresh_interval):
                current_status = self._render_dashboard(previous_status=current_status)
                last_refresh = time.time()
            
            # 2. Check Input (Non-blocking)
            if msvcrt.kbhit():
                try:
                    # Fix UnicodeDecodeError: Ignore non-utf8 inputs (e.g. KR keys)
                    key = msvcrt.getch().decode('utf-8', errors='ignore').lower()
                except:
                    key = ''
                    
                if key == 'm':
                    self._show_menu()
                elif key == 'q':
                    if self._confirm_exit():
                        self.running = False
                        break
            
            time.sleep(0.1)
        
        # Cleanup
        self.stop_trading_thread()
        print(" [Launcher] Bye.")

    def _render_dashboard(self, previous_status=None):
        def safe_fmt(value, fmt=',.0f', default="N/A"):
            """Safe formatting for dashboard fields"""
            try:
                if isinstance(value, (int, float)):
                    return f"{value:{fmt}}"
                return default
            except:
                return default

        if self.use_api:
            try:
                data = self._api_get("/api/status")
                runtime = data.get("runtime") or {}
                status = data.get("controller_state", "UNKNOWN")
                if status != "ERROR":
                    sys.stdout.write("\033[H\033[J")

                print("="*50)
                print(f" DHR TRADING BOT (API Mode) - {safe_fmt(time.time(), '.1f')}")
                print(f" STATUS: {status} | MODE: {data.get('controller_mode', 'N/A')}")

                equity = safe_fmt(runtime.get('equity'), ',.0f', '0')
                pnl = safe_fmt((runtime.get('pnl_pct', 0) or 0) * 100, '.2f', '0.00')
                regime = runtime.get('regime', 'N/A')
                btc = safe_fmt(runtime.get('btc_price', 0), ',.0f', '0')

                print(f" EQUITY: {equity} KRW | PnL: {pnl}%")
                print(f" REGIME: {regime:<10} | BTC: {btc} KRW")

                last_tick = runtime.get("last_tick_ts")
                if last_tick:
                    print(f" LAST TICK: {last_tick:.0f}")
                if runtime.get("last_error"):
                    print("\n [!] CRITICAL ERROR DETECTED")
                    print(f" Reason: {runtime.get('last_error')}")
                    print(" (Check results/logs/crash_log.txt for full traceback)")

                print("="*50)
                print(" [m] Menu | [q] Quit")
                return status
            except Exception as e:
                print(f" [Launcher Error] Backend Status: {e}")
                return "ERROR"

        # Read IPC JSON
        try:
            path = Path("results/runtime_status.json")
            if not path.exists():
                if previous_status != "STARTING":
                    print(" [Launcher] Waiting for Controller Status...")
                return "STARTING"

            text_content = path.read_text()
            if not text_content: # Empty file check
                return "STARTING"
                
            data = json.loads(text_content)
            status = data.get('status', 'UNKNOWN')
            
            # Check for ERROR state
            if status == "ERROR":
                # Do not clear screen on Error to keep traceback visible
                pass
            else:
                sys.stdout.write("\033[H\033[J") # ANSI Clear 
            
            print("="*50)
            print(f" DHR TRADING BOT (Failed to Fail) - {safe_fmt(data.get('ts'), '.1f')}")
            print(f" STATUS: {status} | MODE: {data.get('mode', 'N/A')}")
            
            equity = safe_fmt(data.get('equity'), ',.0f', '0')
            pnl = safe_fmt(data.get('pnl_pct', 0) * 100, '.2f', '0.00')
            
            regime = data.get('regime', 'N/A')
            btc = safe_fmt(data.get('btc_price', 0), ',.0f', '0')
            
            print(f" EQUITY: {equity} KRW | PnL: {pnl}%")
            print(f" REGIME: {regime:<10} | BTC: {btc} KRW")
            
            if status == "ERROR":
                print("\n [!] CRITICAL ERROR DETECTED")
                print(f" Reason: {data.get('last_error', 'Unknown')}")
                print(" (Check results/logs/crash_log.txt for full traceback)")
                print("="*50)
                return "ERROR"
            
            print("="*50)
            print(" [m] Menu | [q] Quit")
            return status
            
        except Exception as e:
            # Launcher itself has issues reading JSON?
            # Do NOT crash. Just print error.
            print(f" [Launcher Error] Reading Dashboard: {e}")
            return "ERROR"
        return "UNKNOWN"

    def _show_menu(self):
        self.menu_lock = True
        time.sleep(0.5) # Wait for display to settle
        print("\n" + "="*30)
        print("       MAIN MENU")
        print("="*30)
        print(" 1. [LIVE] Start Auto Trading")
        print(" 2. [PAPER] Start Simulation")
        print(" 3. [LABS] Run Backtest")
        print(" 4. [LABS] Auto Tuning")
        print(" 5. [VIEW] Open Dashboard")
        print(" Q. Quit")
        print("="*30)
        
        choice = self._wait_input(" Select Option >> ").lower()
        self._handle_menu_selection(choice)
        
        print(" Returning to Dashboard...")
        time.sleep(1)
        self.menu_lock = False

    def _handle_menu_selection(self, choice):
        if choice == '1':
             confirm = self._wait_input(" Type 'LIVE UPBIT SEED=1000000' to confirm: ")
             if confirm == "LIVE UPBIT SEED=1000000":
                self.start_trading_thread(mode="LIVE", seed=1000000, confirm_phrase=confirm)
             else:
                print(" [!] Confirmation Failed.")
                time.sleep(1)
        elif choice == '2':
            self.start_trading_thread(mode="PAPER")
        elif choice == '3':
            self._run_labs_backtest()
        elif choice == '4':
            self._run_labs_autotune()
        elif choice == '5':
            pass # Just return
        elif choice == 'q':
            if self._confirm_exit():
                self.running = False

    def _run_labs_backtest(self):
        print("\n [LABS] Initializing Backtester...")
        try:
            if self.use_api:
                res = self._api_post("/api/labs/run_backtest")
                print(f" [LABS] {res.get('message', 'Backtest started via backend')}")
            else:
                from modules.labs_backtest import LabsBacktester
                # Dummy Params for Demo
                universe = ["KRW-BTC"]
                params = {} 
                labs = LabsBacktester()
                labs.run(None, universe, params, tag="launcher_demo")
            self._wait_input(" Press Enter to continue...")
        except Exception as e:
            print(f" [ERROR] Backtest Failed: {e}")
            self._wait_input(" Press Enter to continue...")

    def _run_labs_autotune(self):
        print("\n [LABS] Initializing Auto Tuner (Green Mode)...")
        try:
            if self.use_api:
                res = self._api_post("/api/labs/run_evolution")
                print(f" [LABS] {res.get('message', 'Evolution started via backend')}")
            else:
                from modules.labs_autotune import AutoTuner
                config = {
                    'green_watts': 240,
                    'gpu_id': 0,
                    'simulate_crash': False
                }
                tuner = AutoTuner(config)
                tuner.run_optimization(n_trials=5, n_workers=2)
            self._wait_input(" Press Enter to continue...")
        except Exception as e:
            print(f" [ERROR] AutoTune Failed: {e}")
            self._wait_input(" Press Enter to continue...")

    def _confirm_exit(self):
        self.menu_lock = True
        ans = self._wait_input(" Quit? (y/n): ")
        self.menu_lock = False
        return ans.lower() == 'y'

    def run_self_test(self, seconds=5):
        """
        Minimal self-test: start controller in PAPER mode without strategy execution,
        allow IPC/status updates, then stop.
        """
        print(f" [Launcher] Self-test start ({seconds}s).")
        if self.use_api:
            try:
                status = self._api_get("/api/status")
                print(" [Self-test] Backend OK:", bool(status))
                health = self._api_post("/api/health_all")
                print(" [Self-test] Health:", health.get("overall", health.get("status")))
            except Exception as e:
                print(f" [Self-test] Failed: {e}")
            return
        self.start_trading_thread(mode="PAPER", seed=1000000, disable_strategy=True)
        time.sleep(max(1, seconds))
        self.stop_trading_thread()
        print(" [Launcher] Self-test complete.")

if __name__ == "__main__":
    # Windows ANSI Helper
    import os
    import argparse
    os.system('cls')
    
    # Create Results Dirs
    Path("results/logs").mkdir(parents=True, exist_ok=True)
    Path("results/locks").mkdir(parents=True, exist_ok=True)

    parser = argparse.ArgumentParser(description="DHR Launcher")
    parser.add_argument("--self-test", action="store_true", help="Run a short self-test and exit")
    parser.add_argument("--self-test-seconds", type=int, default=5, help="Self-test duration (seconds)")
    args, _ = parser.parse_known_args()

    app = Launcher()
    try:
        if args.self_test:
            app.run_self_test(seconds=args.self_test_seconds)
        else:
            app.run_dashboard_loop()
    except KeyboardInterrupt:
        app.stop_trading_thread()
        print("\n [Force Exit]")
