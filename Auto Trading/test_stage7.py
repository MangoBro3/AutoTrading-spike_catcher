
import unittest
import pandas as pd
import sys
from unittest.mock import MagicMock, patch

# Path setup
sys.path.append(r"c:\Users\nak\Desktop\DHR 런처\python\Auto Trading")

from modules.run_controller import RunController
from modules.capital_ledger import CapitalLedger
from modules.watch_engine import WatchEngine

class TestStage7(unittest.TestCase):
    def setUp(self):
        self.adapter = MagicMock()
        self.ledger = MagicMock(spec=CapitalLedger)
        self.ledger.get_state.return_value = {'baseline_seed': 100000, 'equity': 100000}
        
        self.watch = MagicMock(spec=WatchEngine)
        self.watch.current_regime = "NEUTRAL"
        
        self.notifier = MagicMock()
        
        self.controller = RunController(
            self.adapter, self.ledger, self.watch, self.notifier, mode="PAPER"
        )

    def test_startup_alert(self):
        print("\n=== [Stage 7] Startup Alert Test ===")
        # Start (Paper mode auto-confirms)
        self.controller.start()
        
        # Check Notifier (allow optional runtime metadata like PID)
        self.notifier.emit_event.assert_called()
        args = self.notifier.emit_event.call_args[0]

        self.assertEqual(args[0], "SYSTEM")
        self.assertEqual(args[1], "ALL")
        self.assertEqual(args[2], "BOT STARTED")
        self.assertIn("🚀 **RUN START**", args[3])
        self.assertIn("- Mode: PAPER", args[3])
        self.assertIn("- Equity: 100,000 KRW", args[3])
        self.assertIn("- BTC Regime: NEUTRAL", args[3])

        print(" -> [RUN_START] event correctly emitted.")

    def test_degrade_logic_critical(self):
        print("\n=== [Stage 7] Circuit Breaker (Critical) Test ===")
        self.controller.mode = "LIVE" # Simulate LIVE
        
        # Create Losing History (DD > 15%)
        # -10%, -10% -> 0.9 * 0.9 = 0.81 (-19% DD)
        df_loss = pd.DataFrame({
            'pnl_pct': [-0.10, -0.10, 0.01, 0.01],
            'dt': pd.date_range("2025-01-01", periods=4)
        })
        
        res = self.controller.check_performance_degrade(df_loss)
        
        print(f" -> Result: {res}")
        self.assertEqual(res['level'], "CRITICAL")
        self.assertEqual(res['size_mult'], 0.0)
        
        # Verify Downgrade to PAPER
        self.assertEqual(self.controller.mode, "PAPER")
        print(" -> Mode downgraded to PAPER.")
        
        # Verify Risk Alert
        self.notifier.emit_event.assert_called()
        call_args = self.notifier.emit_event.call_args
        args = call_args[0]
        kwargs = call_args[1]
        
        self.assertEqual(args[0], "RISK") # event_type
        self.assertIn("CIRCUIT BREAKER", args[2]) # title
        
        # Severity might be positional or kwarg
        severity = kwargs.get('severity')
        if not severity and len(args) > 4:
            severity = args[4]
            
        self.assertEqual(severity, "CRITICAL") # severity

    def test_degrade_logic_warning(self):
        print("\n=== [Stage 7] Auto-Degrade (Warning) Test ===")
        # Win Rate < 30%
        # 4 trades: 1 Win, 3 Losses => 25% Win Rule
        df_bad_win = pd.DataFrame({
            'pnl_pct': [0.05, -0.01, -0.01, -0.01],
            'dt': pd.date_range("2025-01-01", periods=4)
        })
        
        res = self.controller.check_performance_degrade(df_bad_win)
        print(f" -> Result: {res}")
        
        self.assertEqual(res['level'], "WARNING")
        self.assertEqual(res['size_mult'], 0.5)

if __name__ == '__main__':
    unittest.main()
