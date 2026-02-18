
import unittest
import sys
import os
import shutil
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# Path setup
sys.path.append(r"c:\Users\nak\Desktop\DHR 런처\python\Auto Trading")

from modules.run_controller import RunController
from modules.adapter_upbit import UpbitAdapter
from modules.capital_ledger import CapitalLedger

class TestStage10(unittest.TestCase):
    def setUp(self):
        self.adapter = MagicMock(spec=UpbitAdapter)
        self.ledger = MagicMock(spec=CapitalLedger)
        self.ledger.get_state.return_value = {'baseline_seed': 100000, 'equity': 100000, 'roi_pct': 0.0}
        
        self.notifier = MagicMock()
        self.watch = MagicMock()
        self.watch.current_regime = "NEUTRAL"
        
        # Clean locks
        self.lock_dir = Path("results/locks")
        if self.lock_dir.exists():
            shutil.rmtree(self.lock_dir)

        self.controller = RunController(
            self.adapter, self.ledger, self.watch, self.notifier, mode="PAPER"
        )
        self.controller.lock_file = self.lock_dir / "bot.lock" # Redirect lock for test

    def test_pid_lock(self):
        print("\n=== [Stage 10] PID Lock Test (Strict) ===")
        
        # 1. Acquire First Lock
        print("1. Acquiring first lock...")
        success = self.controller._acquire_lock()
        self.assertTrue(success)
        self.assertTrue(self.controller.lock_file.exists())
        print("   Lock file created.")

        # 2. Simulate Body Double (Should Fail even if PID is different)
        print("2. Simulating collision...")
        controller2 = RunController(self.adapter, self.ledger, self.watch, None, mode="PAPER")
        controller2.lock_file = self.controller.lock_file
        
        # In Strict Mode, this MUST fail even without checking PID
        success2 = controller2._acquire_lock()
        self.assertFalse(success2)
        print("   Collision correctly detected (Strict Policy).")
        
        # 3. Release
        self.controller._release_lock()
        self.assertFalse(self.controller.lock_file.exists())
        print("   Lock released.")
        
    def test_degraded_blocking(self):
        print("\n=== [Stage 10] Circuit Breaker Blocking Test ===")
        adapter = UpbitAdapter(use_env=False)
        adapter.status = "DEGRADED"

        # Test must be key/network independent: inject dummy creds + mock exchange call
        adapter.client.apiKey = "DUMMY"
        adapter.client.secret = "DUMMY"
        adapter.client.create_order = MagicMock(return_value={"id": "mock-reduce-only"})
        
        # 1. Try Normal Buy (Entry) -> Should be Blocked
        print("1. Attempting Buy in DEGRADED mode...")
        order = adapter.create_order("KRW-BTC", "limit", "buy", 0.1, 50000)
        self.assertIsNone(order)
        print("   Buy Order Blocked.")
        
        # 2. Try Reduce-only (Exit) -> Should be Allowed
        # (Assuming we pass reduce_only param)
        print("2. Attempting Reduce-Only in DEGRADED mode...")
        order = adapter.create_order("KRW-BTC", "limit", "sell", 0.1, 50000, params={'reduce_only': True})
        self.assertIsNotNone(order)
        adapter.client.create_order.assert_called_once()
        print("   Reduce-Only Order Allowed.")

    def test_risk_limits(self):
        print("\n=== [Stage 10] Risk Limits Test ===")
        self.controller.mode = "LIVE"
        
        # Mock Heavy Loss (-6%)
        # Limit is 5%
        self.ledger.get_state.return_value = {
            'baseline_seed': 100000, 
            'equity': 94000, 
            'roi_pct': -6.0
        }
        
        # Reset daily risk baseline for deterministic test
        self.controller.daily_risk_state = {
            "day": self.controller._today_key_local(),
            "daily_start_equity": 100000.0,
            "intraday_peak_equity": 100000.0,
            "hard_stop_triggered": False,
            "last_trigger_reason": None,
            "updated_at": time.time(),
        }

        # Trigger Check
        print("1. Injecting -6% ROI (Limit is 5%)")
        ok = self.controller.check_risk_limits()
        
        self.assertFalse(ok)
        self.assertEqual(self.controller.mode, "PAPER")
        print("   Risk Triggered -> Downgraded to PAPER.")
        
        # Check Notifier
        self.notifier.emit_event.assert_called()
        args = self.notifier.emit_event.call_args
        # args[0] might be kwargs or tuple
        # emit_event("RISK", ...)
        # Check if first arg is RISK or title
        # My implementation: emit_event(type, exchange, title, msg, severity...)
        # kwargs check is safer
        # But here I know I called it with positional triggers in _trigger_emergency_stop
        
        # Let's just check call count > 0 is enough for "Alert sent" verify
        print("   Alert sent to Notifier.")

    def test_circuit_breaker(self):
        print("\n=== [Stage 10] Circuit Breaker Test (UpbitAdapter) ===")
        # Need real instance logic, but mocked client
        adapter = UpbitAdapter(use_env=False)
        adapter.logger = MagicMock() # Silence logs
        
        # Simulate 4 errors
        print("1. Simulating 4 consecutive errors...")
        for i in range(4):
            adapter._handle_error(Exception("Test Error"))
            
        print(f"   Status: {adapter.status}")
        self.assertEqual(adapter.status, "DEGRADED")
        
        # Verify Recovery
        print("2. Simulating Success (Health Check)...")
        # Mock client fetch ticker success
        with patch.object(adapter.client, 'fetch_ticker', return_value={'close': 100}):
            adapter.health()
            
        # Error count should decrease by 1 each success
        # 4 -> 3 (Still degraded? Check logic: if count == 0 -> OK)
        # _reset_error_stats decrements by 1.
        
        print(f"   Status after 1 success: {adapter.status}, Errors: {adapter.error_count}")
        self.assertEqual(adapter.error_count, 3)
        self.assertEqual(adapter.status, "DEGRADED")
        
        # Recover fully
        for i in range(3):
             with patch.object(adapter.client, 'fetch_ticker', return_value={'close': 100}):
                adapter.health()

        print(f"   Status after full recovery: {adapter.status}, Errors: {adapter.error_count}")
        self.assertEqual(adapter.status, "OK")


if __name__ == '__main__':
    unittest.main()
