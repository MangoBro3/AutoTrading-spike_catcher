
import unittest
import sys
import logging

# Path setup
sys.path.append(r"c:\Users\nak\Desktop\DHR 런처\python\Auto Trading")
from modules.capital_ledger import CapitalLedger

# Configure logging to stdout for visual verification
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(message)s')

class TestStage4(unittest.TestCase):
    def test_ledger_scenario(self):
        print("\n=== [Stage 4] Capital Ledger Verification Scenario ===")
        
        # 1. Initialize with 100k
        ledger = CapitalLedger("UPBIT", 100000)
        state = ledger.get_state()
        print(f"1. Init: Seed={state['baseline_seed']}, Equity={state['equity']}")
        self.assertEqual(state['baseline_seed'], 100000)
        self.assertEqual(state['withdrawable_profit'], 0)

        # 2. Simulate Profit (Equity -> 120k)
        # Bot manages positions and reports total value = 120k
        ledger.update(120000)
        state = ledger.get_state()
        print(f"2. Profit: Equity={state['equity']}, PnL={state['pnl_cycle']}, Withdrawable={state['withdrawable_profit']}")
        self.assertEqual(state['pnl_cycle'], 20000)
        self.assertEqual(state['withdrawable_profit'], 20000)
        self.assertEqual(state['roi_pct'], 20.0)

        # 3. Try Reset while holding positions (Should Fail)
        print("\n3. Attempting Reset with 1 Active Position...")
        success, reason = ledger.reset_seed(100000, open_positions_count=1)
        print(f"   Result: {success}, Reason: {reason}")
        self.assertFalse(success)
        self.assertIn("Active positions", reason)

        # 4. Simulate Withdrawal logic (User takes 20k profit)
        # Note: Ledger doesn't inherently move money, it tracks state.
        # If user withdraws 20k, remaining equity becomes 100k.
        print("\n4. Simulate Withdrawal of 20k (Equity 120k -> 100k)")
        ledger.update(100000)
        state = ledger.get_state()
        # Now PnL Cycle is 0 (since equity returned to baseline)
        # But 'Realized' Profit concept is usually tracked by accumulation.
        # Simple Ledger Metric: Current PnL = Equity - Baseline.
        self.assertEqual(state['pnl_cycle'], 0)
        print(f"   State after withdrawal: Equity={state['equity']}")

        # 5. Reset Seed (Flat) -> Success
        print("\n5. Resetting Seed (Flat State)...")
        success, summary = ledger.reset_seed(200000, open_positions_count=0)
        print(f"   Result: {success}")
        if success:
            print(f"   Archived Cycle Summary: {summary}")
            
        self.assertTrue(success)
        
        # Verify New State
        new_state = ledger.get_state()
        print(f"6. New Cycle: Seed={new_state['baseline_seed']}, Equity={new_state['equity']}")
        self.assertEqual(new_state['baseline_seed'], 200000)
        self.assertEqual(new_state['equity'], 200000)

if __name__ == '__main__':
    unittest.main()
