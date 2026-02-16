
import unittest
import sys
import os

sys.path.append(r"c:\Users\nak\Desktop\DHR 런처\python\Auto Trading")
import config_v2

class TestConfigValidation(unittest.TestCase):
    def test_valid_seed(self):
        self.assertTrue(config_v2.validate_config(100000))

    def test_invalid_seed_zero(self):
        with self.assertRaises(ValueError):
            config_v2.validate_config(0)
            
    def test_invalid_seed_negative(self):
        with self.assertRaises(ValueError):
            config_v2.validate_config(-100)

    def test_constants(self):
        self.assertTrue(config_v2.SPOT_ONLY)
        self.assertTrue(config_v2.BTC_TRADE_DISABLED)
        self.assertTrue(config_v2.WEB_UI_DISABLED)
        self.assertEqual(config_v2.TRADE_MARKET, "KRW")

if __name__ == '__main__':
    unittest.main()
