
import unittest
import os
import sys
from dotenv import load_dotenv

# Path setup
sys.path.append(r"c:\Users\nak\Desktop\DHR 런처\python\Auto Trading")

from modules.adapter_upbit import UpbitAdapter
from modules.adapter_bithumb import BithumbAdapter

# Load Env
load_dotenv(r"c:\Users\nak\Desktop\DHR 런처\python\Auto Trading\.env")

class TestStage3(unittest.TestCase):
    def setUp(self):
        self.upbit_key = os.getenv("UPBIT_ACCESS")
        self.upbit_secret = os.getenv("UPBIT_SECRET")
        self.bithumb_key = os.getenv("BITHUMB_ACCESS")
        self.bithumb_secret = os.getenv("BITHUMB_SECRET")
        
        # Mock keys if missing (to verify structure logic at least)
        if not self.upbit_key: self.upbit_key="MOCK"; self.upbit_secret="MOCK"
        if not self.bithumb_key: self.bithumb_key="MOCK"; self.bithumb_secret="MOCK"

        # Initialize Adapters
        # Note: If keys are invalid, CCXT might error on private methods, but public (health) might work?
        # Actually health() often uses public time/ticker.
        
        # We wrap init in try/catch to allow partial tests if network fails
        try:
            self.upbit = UpbitAdapter(self.upbit_key, self.upbit_secret)
        except Exception as e:
            print(f"Upbit Init Failed: {e}")
            self.upbit = None
            
        try:
            self.bithumb = BithumbAdapter(self.bithumb_key, self.bithumb_secret)
        except Exception as e:
            print(f"Bithumb Init Failed: {e}")
            self.bithumb = None

    def test_health_structure(self):
        """Verify health() returns {'status':..., 'latency_ms':...}"""
        if self.upbit:
            h = self.upbit.health()
            print(f"\n[Upbit Health] {h}")
            self.assertIn('status', h)
            
        if self.bithumb:
            h = self.bithumb.health()
            print(f"[Bithumb Health] {h}")
            self.assertIn('status', h)

    def test_balance_normalization(self):
        """Verify Balance keys (Free/Total) match standard"""
        # If real keys are missing, we can't test real return, 
        # but we can check if method exists.
        
        if self.upbit and "MOCK" not in self.upbit_key:
            bal = self.upbit.get_balances()
            print(f"\n[Upbit Balances] {bal.keys()}")
            if 'KRW' in bal:
                self.assertIn('total', bal['KRW'])
                self.assertIn('free', bal['KRW'])
                
        if self.bithumb and "MOCK" not in self.bithumb_key:
            bal = self.bithumb.get_balances()
            print(f"[Bithumb Balances] {bal.keys()}")
            if 'KRW' in bal:
                self.assertIn('total', bal['KRW'])
                self.assertIn('free', bal['KRW'])

    def test_symbol_normalization(self):
        """Unit test for symbol conversion"""
        if self.upbit:
            norm = self.upbit._normalize_symbol("BTC/KRW")
            self.assertEqual(norm, "KRW-BTC")
            
        if self.bithumb:
            norm = self.bithumb._normalize_symbol("ETH/KRW")
            self.assertEqual(norm, "KRW-ETH")
            print(f"\n[Normalization Check] BTC/KRW -> {norm} (Expected KRW-ETH)")

if __name__ == '__main__':
    unittest.main()
