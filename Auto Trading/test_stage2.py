
import unittest
import shutil
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
            file_name="outbox_test.json"
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
        self.assertEqual(self.notifier.outbox[0]['status'], 'SENT')
        self.assertEqual(self.notifier._send_telegram.call_count, 1)
        
        # 2. Second Emit (Within cooldown) -> Ignored
        self.notifier.emit_event("SYSTEM", "ALL", "Hello", "Again", dedupe_key=key, cooldown_min=1)
        self.assertEqual(len(self.notifier.outbox), 1) # Count unchanged
        self.assertEqual(self.notifier._send_telegram.call_count, 1) # Sends unchanged
        
        print("\n[Dedupe] Duplicate event ignored successfully.")

    def test_retry_logic(self):
        """Verify retry behavior and status updates"""
        
        # Simulate Failure
        self.notifier._send_telegram.side_effect = Exception("Network Down")
        
        # Emit
        self.notifier.emit_event("RISK", "UPBIT", "Crash", "Help")
        
        # Check PENDING and Retry Count
        evt = self.notifier.outbox[0]
        self.assertEqual(evt['status'], 'PENDING')
        self.assertEqual(evt['retry_count'], 1)
        self.assertGreater(evt['next_retry_ts'], time.time())
        print(f"\n[Retry] Event caught error: {evt['last_error']}. Retry Count: {evt['retry_count']}")
        
        # Simulate Time Pass (Force reset next_retry_ts)
        evt['next_retry_ts'] = time.time() - 1 
        
        # Simulate Recovery
        self.notifier._send_telegram.side_effect = None # Remove Error
        
        # Process manually
        self.notifier.process_outbox()
        
        # Check SENT
        evt = self.notifier.outbox[0]
        self.assertEqual(evt['status'], 'SENT')
        print(f"[Retry] Event recovered and SENT.")

    def test_file_persistence(self):
        """Verify reload from disk"""
        self.notifier.emit_event("WATCH", "BITHUMB", "Eye", "See")
        
        # Create new instance
        new_notifier = TelegramNotifier(
            bot_token="TEST_TOKEN", 
            chat_id="TEST_CHAT",
            storage_dir=str(self.test_dir),
            file_name="outbox_test.json"
        )
        
        self.assertEqual(len(new_notifier.outbox), 1)
        self.assertEqual(new_notifier.outbox[0]['message'], "See")
        print(f"[Persistence] Loaded {len(new_notifier.outbox)} items from disk.")

if __name__ == '__main__':
    unittest.main()
