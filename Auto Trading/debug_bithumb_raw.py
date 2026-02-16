import ccxt
import os
import json
from dotenv import load_dotenv

load_dotenv()

def debug_bithumb_raw():
    print("=== Bithumb Raw JSON Debug ===")
    key = os.getenv("BITHUMB_KEY")
    secret = os.getenv("BITHUMB_SECRET")
    
    if not key:
        print("Error: No BITHUMB_KEY in .env")
        return

    # Initialize with verbose=True to print raw HTTP requests/responses
    # But to capture it for the user cleanly, we can also look at the exception or result.
    ex = ccxt.bithumb({
        'apiKey': key,
        'secret': secret,
        'enableRateLimit': True,
        'options': {'adjustForTimeDifference': True}
    })
    
    try:
        print("\nSending 'fetch_balance' request...")
        bal = ex.fetch_balance()
        
        # If successful, print the 'info' field which is the raw response from exchange
        print("\n✅ Success! Raw Response (ex.last_json or info):")
        print(json.dumps(bal['info'], indent=4, ensure_ascii=False))
        
    except Exception as e:
        print("\n❌ Error Occurred!")
        print(f"Error Message: {e}")
        
        # Try to print raw response if attached to exception
        # CCXT errors often contain the raw response text
        print("\n--- Raw Error Details ---")
        # In python, we can inspect the exception object
        print(str(e))

if __name__ == "__main__":
    debug_bithumb_raw()
