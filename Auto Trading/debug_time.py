import ccxt
import time
import requests

def check_time_sync():
    print("=== Bithumb Time Sync Check ===")
    
    # 1. Local Time
    local_ts = int(time.time() * 1000)
    print(f"Local Time:  {local_ts}")
    
    # 2. Server Time (Public API)
    try:
        # Bithumb public API for time/server status isn't standard in CCXT always, 
        # but we can check ticker timestamp
        ex = ccxt.bithumb()
        ticker = ex.fetch_ticker('BTC/KRW')
        server_ts = ticker['timestamp']
        print(f"Server Time: {server_ts}")
        
        diff = local_ts - server_ts
        print(f"Difference:  {diff} ms")
        
        if abs(diff) > 3000:
            print("❌ WARNING: Time difference > 3 seconds.")
            print("   Bithumb requires strict time sync.")
            print("   Please 'Sync Windows Time' in Settings.")
        else:
            print("✅ Time Sync looks OK.")
            
    except Exception as e:
        print(f"Error fetching server time: {e}")

if __name__ == "__main__":
    check_time_sync()
