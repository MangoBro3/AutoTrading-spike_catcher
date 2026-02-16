
import sys
import time
import threading
from unittest.mock import MagicMock
import random

# Path setup
sys.path.append(r"c:\Users\nak\Desktop\DHR 런처\python\Auto Trading")

from modules.dashboard_cli import DashboardCLI
from modules.adapter_upbit import UpbitAdapter
from modules.adapter_bithumb import BithumbAdapter
from modules.capital_ledger import CapitalLedger

def manual_test():
    # 1. Mock Adapters
    print("Initializing Mock Adapters...")
    upbit_mock = MagicMock(spec=UpbitAdapter)
    bithumb_mock = MagicMock(spec=BithumbAdapter)
    
    # 2. Mock Ledgers
    ledger_upbit = CapitalLedger("UPBIT", 100000)
    ledger_bithumb = CapitalLedger("BITHUMB", 500000)

    # 3. Dynamic Mock Behavior
    # We update mock return values in a background thread to simulate changes
    def update_mocks():
        while True:
            # Latency Jitter
            upbit_lat = random.randint(10, 50)
            bithumb_lat = random.randint(30, 200)
            
            upbit_mock.health.return_value = {'status': 'ok', 'latency_ms': upbit_lat}
            bithumb_mock.health.return_value = {'status': 'ok', 'latency_ms': bithumb_lat}
            
            # PnL Jitter (Simulate Ledger Updates)
            ledger_upbit.update(100000 + random.randint(-1000, 1000))
            ledger_bithumb.update(500000 + random.randint(-5000, 5000))
            
            time.sleep(2)

    t = threading.Thread(target=update_mocks, daemon=True)
    t.start()

    # 4. Launch Dashboard
    dashboard = DashboardCLI(upbit_mock, bithumb_mock, ledger_upbit, ledger_bithumb)
    try:
        dashboard.run()
    except KeyboardInterrupt:
        print("Dashboard stopped.")

if __name__ == "__main__":
    manual_test()
