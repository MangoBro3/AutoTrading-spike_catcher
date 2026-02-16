
import unittest
import pandas as pd
import numpy as np
import sys
from unittest.mock import MagicMock

# Path setup
sys.path.append(r"c:\Users\nak\Desktop\DHR 런처\python\Auto Trading")

from modules.watch_engine import WatchEngine

class TestStage6(unittest.TestCase):
    def setUp(self):
        self.notifier = MagicMock()
        self.engine = WatchEngine(self.notifier)

    def _create_dummy_df(self, start_price, trend, length=50):
        dates = pd.date_range(start="2025-01-01", periods=length, freq="D")
        prices = [start_price + (i * trend) for i in range(length)]
        return pd.DataFrame({'close': prices}, index=dates)

    def test_regime_logic(self):
        print("\n=== [Stage 6] Regime Logic Test ===")
        
        # 1. RISK_ON Scenario (Uptrend)
        # Price 100 -> 150 (SMA20 will be approx 140, Close 150 > SMA)
        df_uptrend = self._create_dummy_df(100, 1.0, 50) 
        regime = self.engine.update_regime(df_uptrend)
        
        print(f"1. Uptrend Regime: {regime}")
        self.assertEqual(regime, "RISK_ON")
        
        # Check Notifier called
        self.notifier.emit_event.assert_called()
        
        guide = self.engine.get_action_guide()
        self.assertTrue(guide['can_enter'])
        self.assertEqual(guide['size_mult'], 1.0)

        # 2. RISK_OFF Scenario (Downtrend)
        # Sudden drop: Append bearish candles
        last_price = df_uptrend['close'].iloc[-1]
        df_downtrend = self._create_dummy_df(last_price, -5.0, 30) # Fast drop
        # Concatenate is needed only if tracking history, 
        # but update_regime just takes a DF. Let's pass the strictly bearish DF.
        
        regime = self.engine.update_regime(df_downtrend)
        print(f"2. Downtrend Regime: {regime}")
        self.assertEqual(regime, "RISK_OFF")
        
        guide = self.engine.get_action_guide()
        self.assertFalse(guide['can_enter'])
        self.assertEqual(guide['size_mult'], 0.0)

    def test_scoring_logic(self):
        print("\n=== [Stage 6] Scoring Logic Test ===")
        
        # Setup 3 assets
        # Asset A: Strong Uptrend (Score High)
        # Asset B: Flat (Score Low)
        # Asset C: Downtrend (Score Negative)
        
        data = {
            "KRW-A": self._create_dummy_df(100, 2.0, 30),
            "KRW-B": self._create_dummy_df(100, 0.1, 30),
            "KRW-C": self._create_dummy_df(100, -1.0, 30),
            "KRW-BTC": self._create_dummy_df(1000, 10.0, 30) # Should be ignored
        }
        
        top = self.engine.score_candidates(data, top_n=2)
        
        print(f"Top Candidate: {top[0]}")
        print(f"Second Candidate: {top[1]}")
        
        self.assertEqual(top[0][0], "KRW-A")
        self.assertEqual(top[1][0], "KRW-B")
        self.assertEqual(len(top), 2)
        
        # Verify BTC excluded
        symbols = [x[0] for x in top]
        self.assertNotIn("KRW-BTC", symbols)

if __name__ == '__main__':
    unittest.main()
