
import os
import sys
import time
try:
    import msvcrt  # Windows only
except ImportError:  # pragma: no cover - non-Windows fallback
    msvcrt = None
from datetime import datetime
from typing import Dict, List, Any

# Adjust path if run directly
if __name__ == "__main__":
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .adapter_upbit import UpbitAdapter
from .adapter_bithumb import BithumbAdapter
from .capital_ledger import CapitalLedger

class DashboardCLI:
    def __init__(self, upbit: UpbitAdapter, bithumb: BithumbAdapter, 
                 ledger_upbit: CapitalLedger, ledger_bithumb: CapitalLedger):
        self.upbit = upbit
        self.bithumb = bithumb
        self.ledger_upbit = ledger_upbit
        self.ledger_bithumb = ledger_bithumb
        self.running = True
        self.refresh_rate = 1.0 # sec

        # Cache for display
        self.status_cache = {
            'upbit': {'health': 'INIT', 'pos_count': 0, 'order_count': 0},
            'bithumb': {'health': 'INIT', 'pos_count': 0, 'order_count': 0}
        }

    def _clear_screen(self):
        os.system('cls' if os.name == 'nt' else 'clear')

    def _fetch_data(self):
        """
        Fetches latest data from Adapters and Ledgers.
        In a real scenario, this might run in a thread or be async.
        For Stage 5 MVP, we do it synchronously but safely.
        """
        # Upbit
        try:
            h = self.upbit.health()
            self.status_cache['upbit']['health'] = f"{h.get('status')} ({h.get('latency_ms',0)}ms)"
        except:
            self.status_cache['upbit']['health'] = "ERROR"

        # Bithumb
        try:
            h = self.bithumb.health()
            self.status_cache['bithumb']['health'] = f"{h.get('status')} ({h.get('latency_ms',0)}ms)"
        except:
            self.status_cache['bithumb']['health'] = "ERROR"

        # Update Ledgers (Mock update for now, or real if connected)
        # Real update would rely on Balance fetching, which is costly.
        # For Dashboard visualization, we assume Ledgers are updated by Controller.
        # Here we just read them.

    def _render_header(self):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"================================================================================")
        print(f" [AUTO TRADING MONITOR] {now} | MODE: LIVE-TEST")
        print(f"================================================================================")

    def _render_panels(self):
        # Format: Exchange | Status | Seed | Equity | PnL | Pos/Ord
        print(f" {'EXCHANGE':<10} | {'STATUS':<15} | {'SEED(KRW)':<12} | {'EQUITY':<12} | {'PnL':<8} | {'POS/ORD':<8}")
        print("-" * 80)
        
        for name, adapter, ledger, key in [
            ("UPBIT", self.upbit, self.ledger_upbit, 'upbit'),
            ("BITHUMB", self.bithumb, self.ledger_bithumb, 'bithumb')
        ]:
            state = ledger.get_state()
            status = self.status_cache[key]['health']
            
            pnl_str = f"{state['pnl_cycle']:+.0f}"
            equity_str = f"{state['equity']:,.0f}"
            seed_str = f"{state['baseline_seed']:,.0f}"
            
            # Mock counts (TODO: Real get from adapter if cheap, or cache)
            # Safe call
            try:
                # Limit calls to avoid rate limit spam in loop
                # In real app, Controller updates these. 
                # For this Dashboard MVP, we assume cached values or cheap calls?
                # Let's leave placeholders or simple fetch if latency low.
                pass 
            except: pass

            pos_n = "0" # Placeholder
            ord_n = "0" # Placeholder
            
            print(f" {name:<10} | {status:<15} | {seed_str:<12} | {equity_str:<12} | {pnl_str:<8} | {pos_n}/{ord_n}")

    def _render_tables(self):
        print(f"\n [ACTIVE POSITIONS]")
        print("-" * 80)
        print(f" No active positions.") # Placeholder logic

        print(f"\n [ACTIVE ORDERS]")
        print("-" * 80)
        print(f" No open orders.") # Placeholder logic
        
        print(f"\n [RECENT FILLS]")
        print("-" * 80)
        print(f" No recent fills.")

    def run(self):
        print("Starting Dashboard... Press 'Q' to Quit, 'R' to Refresh.")
        while self.running:
            # Input Check (Non-blocking)
            if msvcrt is not None and msvcrt.kbhit():
                key = msvcrt.getch().decode('utf-8').upper()
                if key == 'Q':
                    self.running = False
                    break
                elif key == 'R':
                    pass # Just continues to render

            # Update & Render
            self._fetch_data()
            self._clear_screen()
            self._render_header()
            self._render_panels()
            self._render_tables()
            
            print(f"\n [CTRL] Press 'Q' to Quit. Last Refresh: {datetime.now().strftime('%H:%M:%S')}")
            
            time.sleep(self.refresh_rate)

if __name__ == "__main__":
    # If run directly as script (not module)
    pass
