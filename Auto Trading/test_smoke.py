
import unittest
import pandas as pd
import sys
import os

# Add path to import backtester
sys.path.append(r"c:\Users\nak\Desktop\DHR 런처\python\Auto Trading")
from backtester import Backtester

class TestBacktesterCost(unittest.TestCase):
    def setUp(self):
        self.bt = Backtester()

    def test_apply_cost_buy(self):
        """Test BUY cost application (Price should increase)"""
        raw_price = 100.0
        cost_rate = 0.002 # 0.2%
        
        exec_price = self.bt.apply_cost(raw_price, "BUY", cost_rate)
        expected = 100.0 * (1 + 0.002)
        
        print(f"\n[Test Buy] Raw: {raw_price}, Cost: {cost_rate}, Exec: {exec_price}, Expected: {expected}")
        self.assertAlmostEqual(exec_price, expected)
        self.assertGreater(exec_price, raw_price)

    def test_apply_cost_sell(self):
        """Test SELL cost application (Price should decrease)"""
        raw_price = 100.0
        cost_rate = 0.002 # 0.2%
        
        exec_price = self.bt.apply_cost(raw_price, "SELL", cost_rate)
        expected = 100.0 * (1 - 0.002)
        
        print(f"\n[Test Sell] Raw: {raw_price}, Cost: {cost_rate}, Exec: {exec_price}, Expected: {expected}")
        self.assertAlmostEqual(exec_price, expected)
        self.assertLess(exec_price, raw_price)

    def test_tax_scenario(self):
        """
        Smoke Test A (The 'Tax' Test)
        Situation: Buy Raw = 100, Sell Raw = 100 (No market move)
        Cost: 0.2% each side
        Expectation: PnL < 0
        """
        raw_entry = 100.0
        raw_exit = 100.0
        cost_rate = 0.002
        
        entry_price = self.bt.apply_cost(raw_entry, "BUY", cost_rate)
        exit_price = self.bt.apply_cost(raw_exit, "SELL", cost_rate)
        
        # PnL Calculation (Standard: (Exit - Entry)/Entry)
        pnl_pct = (exit_price - entry_price) / entry_price
        
        print(f"\n[Tax Test] Raw Entry/Exit: 100/100")
        print(f"  -> Exec Entry: {entry_price}")
        print(f"  -> Exec Exit:  {exit_price}")
        print(f"  -> PnL: {pnl_pct*100:.4f}%")
        
        self.assertLess(pnl_pct, 0, "PnL must be negative due to costs")
        
        # Calculation Check
        # Entry = 100.2
        # Exit = 99.8
        # PnL = (99.8 - 100.2) / 100.2 = -0.4 / 100.2 ~= -0.003992 (-0.4%)
        # Note: Denominator is higher, so % loss is slightly dampened vs raw basis, but absolute is correct.
        
        expected_pnl = (99.8 - 100.2) / 100.2
        self.assertAlmostEqual(pnl_pct, expected_pnl)

if __name__ == '__main__':
    unittest.main()
