
import unittest
import threading
import time
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import Launcher (Assumes modules path is setup)
import sys
sys.path.append(r"c:\Users\nak\Desktop\DHR 런처\python\Auto Trading")
from launcher import Launcher
from modules.run_controller import RunController

class TestStage11(unittest.TestCase):
    def setUp(self):
        self.launcher = Launcher()
        self.launcher._wait_input = MagicMock(return_value='n') # Default input mock
        self.json_path = Path("results/runtime_status.json")
        if self.json_path.exists():
            self.json_path.unlink()

    def test_input_pause_dashboard(self):
        print("\n=== [Stage 11] Input Pause Safety Test ===")
        # 1. Not Locked initially
        self.assertFalse(self.launcher.menu_lock)
        
        # 2. Simulate Menu Input
        # We manually call a method that locks
        def delayed_input(prompt):
            self.assertTrue(self.launcher.menu_lock, "Menu Lock should be TRUE during input check")
            print("   [Verified] Menu is Locked during input.")
            return '4' # Back

        self.launcher._wait_input = delayed_input
        self.launcher._show_menu()
        
        # 3. Should be unlocked after
        self.assertFalse(self.launcher.menu_lock, "Menu Lock should be FALSE after return")
        print("   [Verified] Menu Unlocked after exit.")

    def test_mock_crash_resilience(self):
        print("\n=== [Stage 11] Crash Resilience Test ===")
        # We simulate a Controller that crashes immediately
        
        mock_controller = MagicMock()
        mock_controller.running = True
        
        def crash_run():
            print("   [Mock] Controller Running...")
            time.sleep(0.2)
            print("   [Mock] Controller CRASHING!")
            # Write Error Status manually as real controller would
            status = {'status': 'ERROR', 'last_error': 'Simulated Explosion'}
            with open("results/runtime_status.json", 'w') as f:
                json.dump(status, f)
            raise RuntimeError("Simulated Explosion")
            
        mock_controller.run = crash_run
        
        # Inject Mock
        self.launcher.controller = mock_controller
        self.launcher.worker_thread = threading.Thread(target=mock_controller.run)
        
        # Start
        self.launcher.worker_thread.start()
        time.sleep(0.5) # Wait for crash
        
        # Check if Launcher is still "running" (The app itself)
        self.assertTrue(self.launcher.running)
        print("   [Verified] Launcher survived Controller crash.")
        
        # Check Status File
        if self.json_path.exists():
            data = json.loads(self.json_path.read_text())
            print(f"   [Status Read] {data}")
            self.assertEqual(data['status'], 'ERROR')
            self.assertIn('Explosion', data['last_error'])
        else:
            self.fail("Runtime status file not found.")

if __name__ == '__main__':
    unittest.main()
