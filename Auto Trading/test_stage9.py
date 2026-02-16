
import unittest
import sys
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

# Path setup
sys.path.append(r"c:\Users\nak\Desktop\DHR 런처\python\Auto Trading")

from modules.labs_backtest import LabsBacktester
from modules.labs_ml import LabsML

class TestStage9(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("test_labs9_output")
        self.backtester = LabsBacktester(base_dir=str(self.test_dir))
        self.ml = LabsML(base_dir=str(self.test_dir))

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    @patch('builtins.input', return_value='N') # Simulate User saying No to charts
    def test_backtest_chart_saving(self, mock_input):
        print("\n=== [Stage 9] Backtest & Chart Saving Test ===")
        
        run_id = self.backtester.run(
            strategy_class=None, 
            universe=[], 
            params={}, 
            tag="TestGraph"
        )
        
        # Verify Files
        run_dir = self.test_dir / "runs" / run_id
        charts_dir = run_dir / "charts"
        
        self.assertTrue((run_dir / "equity.csv").exists())
        self.assertTrue((run_dir / "trades.csv").exists())
        self.assertTrue((charts_dir / "equity_curve.png").exists())
        self.assertTrue((charts_dir / "drawdown.png").exists())
        self.assertTrue((run_dir / "run_summary.json").exists())
        
        print("\n[Verify] Charts & CSVs created successfully.")

    def test_ml_skeleton(self):
        print("\n=== [Stage 9] ML Skeleton Test ===")
        
        run_id = self.ml.run_ml_pipeline("train", epochs=10, lr=0.001)
        
        run_dir = self.test_dir / "runs" / run_id
        summary_path = run_dir / "run_summary.json"
        
        self.assertTrue(summary_path.exists())
        
        # Check Index
        index_path = self.test_dir / "index" / "runs_index.csv"
        self.assertTrue(index_path.exists())
        
        print("\n[Verify] ML Summary & Index updated.")

if __name__ == '__main__':
    unittest.main()
