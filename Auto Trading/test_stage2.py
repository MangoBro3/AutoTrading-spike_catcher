
import unittest
import shutil
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys
sys.path.append(r"c:\Users\nak\Desktop\DHR 런처\python\Auto Trading")

from modules.notifier_telegram import TelegramNotifier


class TestStage2(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("test_results_stage2")
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

        # Initialize Notifier with mock token
        self.notifier = TelegramNotifier(
            bot_token="TEST_TOKEN",
            chat_id="TEST_CHAT",
            storage_dir=str(self.test_dir),
            file_name="outbox_test.json",
        )

        # Mock the physical send method to simulate network
        self.notifier._send_telegram = MagicMock()

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_deduplication(self):
        """Verify duplicate events are ignored within cooldown"""
        key = "MSG_001"

        # 1. First Emit (Success)
        self.notifier.emit_event("SYSTEM", "ALL", "Hello", "World", dedupe_key=key, cooldown_min=1)
        self.assertEqual(len(self.notifier.outbox), 1)
        self.assertEqual(self.notifier.outbox[0]["status"], "filled")
        self.assertEqual(self.notifier._send_telegram.call_count, 1)

        # 2. Second Emit (Within cooldown) -> Ignored
        self.notifier.emit_event("SYSTEM", "ALL", "Hello", "Again", dedupe_key=key, cooldown_min=1)
        self.assertEqual(len(self.notifier.outbox), 1)
        self.assertEqual(self.notifier._send_telegram.call_count, 1)

        print("\n[Dedupe] Duplicate event ignored successfully.")

    def test_outbox_state_machine(self):
        """Verify requested->accepted->filled/canceled transition path"""
        self.notifier._send_telegram.side_effect = [Exception("Network Down"), None]

        self.notifier.emit_event("RISK", "UPBIT", "Crash", "Help")
        evt = self.notifier.outbox[0]
        self.assertEqual(evt["status"], "requested")
        self.assertEqual(evt["retry_count"], 1)
        self.assertGreater(evt["next_retry_ts"], time.time())

        # Retry from requested state after waiting
        evt["next_retry_ts"] = time.time() - 1
        self.notifier.process_outbox()

        evt = self.notifier.outbox[0]
        self.assertEqual(evt["status"], "filled")
        print(f"[Outbox FSM] {evt['status']} after retry")

    def test_file_persistence(self):
        """Verify reload from disk with schema wrapper and recovery"""
        self.notifier.emit_event("WATCH", "BITHUMB", "Eye", "See")

        # Create new instance (simulate restart)
        new_notifier = TelegramNotifier(
            bot_token="TEST_TOKEN",
            chat_id="TEST_CHAT",
            storage_dir=str(self.test_dir),
            file_name="outbox_test.json",
        )

        self.assertEqual(len(new_notifier.outbox), 1)
        self.assertEqual(new_notifier.outbox[0]["message"], "See")

        # Confirm schema version is stored
        saved = json.loads((self.test_dir / "outbox_test.json").read_text(encoding="utf-8"))
        self.assertEqual(saved.get("_schema_version"), 2)
        self.assertIn("events", saved)

    def test_legacy_outbox_compat(self):
        """Verify legacy list-form outbox loads with migration."""
        legacy = [
            {
                "id": "legacy_1",
                "ts": "2026-01-01T00:00:00",
                "event_type": "SYSTEM",
                "exchange": "ALL",
                "severity": "INFO",
                "title": "[ALL] [SYSTEM] TEST",
                "message": "legacy",
                "dedupe_key": "legacy_key",
                "status": "PENDING",
                "retry_count": 0,
                "next_retry_ts": time.time(),
                "last_error": None,
            }
        ]
        (self.test_dir / "outbox_test.json").write_text(json.dumps(legacy), encoding="utf-8")

        migrated = TelegramNotifier(
            bot_token="TEST_TOKEN",
            chat_id="TEST_CHAT",
            storage_dir=str(self.test_dir),
            file_name="outbox_test.json",
        )

        self.assertEqual(len(migrated.outbox), 1)
        self.assertEqual(migrated.outbox[0]["status"], "requested")


if __name__ == '__main__':
    unittest.main()
