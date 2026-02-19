import unittest
from pathlib import Path

WEB_BACKEND_PATH = Path(__file__).resolve().parent / "web_backend.py"


class TestUIBuildBSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = WEB_BACKEND_PATH.read_text(encoding="utf-8")

    def test_frontend_features(self):
        self.assertIn("Live Mode Start Confirm", self.payload)
        self.assertIn("Panic Exit", self.payload)
        self.assertIn("startPanicHold", self.payload)
        self.assertIn("Orders", self.payload)
        self.assertIn("/api/orders", self.payload)

    def test_backend_endpoints_present(self):
        for path in [
            '"/api/panic"',
            '"/api/orders"',
            '"/api/orders/cancel"',
            '"/api/restart"',
            '"_notify_openclaw_emergency"',
            '"_cancel_open_orders"',
        ]:
            self.assertIn(path, self.payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
