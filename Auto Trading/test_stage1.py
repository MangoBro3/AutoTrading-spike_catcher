
import unittest
import shutil
import numpy as np
from datetime import datetime
from pathlib import Path
import json
import csv
import sys
import os

# Ensure modules are importable
sys.path.append(r"c:\Users\nak\Desktop\DHR 런처\python\Auto Trading")

from modules.utils_json import CustomJSONEncoder, safe_json_dump
from modules.results_writer import ResultsWriter

class TestStage1(unittest.TestCase):
    def setUp(self):
        # Create a temp results dir for testing
        self.test_dir = Path("test_results_stage1")
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.writer = ResultsWriter(base_dir=str(self.test_dir))

    def tearDown(self):
        # Cleanup
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_json_util(self):
        """Verify CustomJSONEncoder handles numpy and datetime"""
        data = {
            "dt": datetime(2025, 5, 20, 12, 0, 0),
            "np_int": np.int64(42),
            "np_float": np.float64(3.14),
            "np_arr": np.array([1, 2, 3]),
            "path": Path("some/path")
        }
        
        dump_path = self.test_dir / "dump_test.json"
        safe_json_dump(data, dump_path)
        
        self.assertTrue(dump_path.exists())
        
        with open(dump_path, 'r') as f:
            loaded = json.load(f)
            
        print(f"\n[JSON check] Loaded: {loaded}")
        
        self.assertEqual(loaded['np_int'], 42)
        self.assertEqual(loaded['np_float'], 3.14)
        self.assertEqual(loaded['np_arr'], [1, 2, 3])
        self.assertEqual(loaded['path'], "some\\path" if os.name=='nt' else "some/path")
        # ISO format check
        self.assertIn("2025-05-20", loaded['dt'])

    def test_results_writer(self):
        """Verify Run Dir creation, Summary Write, Index Update"""
        run_id, run_path = self.writer.create_run_dir("backtest", "UPBIT", "test_tag")
        
        print(f"\n[Writer Check] Created Run: {run_id}")
        self.assertTrue(run_path.exists())
        self.assertIn("backtest_UPBIT_test_tag", run_id)
        
        summary = {
            "run_type": "backtest",
            "exchange": "UPBIT",
            "tag": "test_tag",
            "metrics": {
                "total_return": 15.5,
                "win_rate": 60.0,
                "trades": 100
            }
        }
        
        json_path = self.writer.write_summary(run_id, summary)
        self.assertTrue(json_path.exists())
        
        # Verify Index
        self.writer.update_index(summary)
        
        index_file = self.test_dir / "index" / "runs_index.csv"
        self.assertTrue(index_file.exists())
        
        with open(index_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row['run_id'], run_id)
            self.assertEqual(row['roi_pct'], "15.5")
            print(f"[Index Check] CSV Row: {row}")

if __name__ == '__main__':
    unittest.main()
