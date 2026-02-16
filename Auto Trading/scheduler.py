import time
import schedule
from datetime import datetime
import data_loader

def job():
    print(f"\n[Scheduler] Starting Update at {datetime.now().strftime('%H:%M:%S')}...")
    try:
        # Use existing sync entry point
        data_loader.update_data() 
        print(f"[Scheduler] Update Completed at {datetime.now().strftime('%H:%M:%S')}")
    except Exception as e:
        print(f"[Scheduler] Error during update: {e}")

import os
import atexit

PID_FILE = "scheduler.pid"

def cleanup_pid():
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)

def main():
    # Write PID
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    
    atexit.register(cleanup_pid)
    
    print("=== Auto Trading Data Scheduler ===")
    print(f"Started (PID: {os.getpid()})")
    print("Runs every 15 minutes.")
    
    # Run immediately on start
    job()
    
    # Schedule
    schedule.every(15).minutes.do(job)
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")
        cleanup_pid()

if __name__ == "__main__":
    try:
        # Try to import schedule
        import schedule
    except ImportError:
        print("Installing schedule library...")
        import os
        os.system("pip install schedule")
        import schedule
        
    main()
