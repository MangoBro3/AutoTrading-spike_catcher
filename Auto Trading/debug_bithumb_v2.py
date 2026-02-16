import ccxt
import os
import requests
from dotenv import load_dotenv

load_dotenv()

def debug_bithumb_v2():
    print("=== Bithumb API 2.0 / Connect Spec Check ===")
    
    # 1. Check CCXT Spec
    ex = ccxt.bithumb()
    print(f"CCXT Version: {ccxt.__version__}")
    print(f"Bithumb API URL: {ex.urls['api']}") if 'api' in ex.urls else print("No explicit api url?")
    
    key = os.getenv("BITHUMB_KEY")
    secret = os.getenv("BITHUMB_SECRET")
    
    if not key: return

    print(f"Loaded Key: {key[:4]}**** (Length: {len(key)})")
    
    print("\n[Attempt 1: Standard CCXT]")
    ex.apiKey = key
    ex.secret = secret
    ex.options['adjustForTimeDifference'] = True
    
    try:
        ex.load_markets() # Public
        print("Markets loaded (Public API OK)")
        
        bal = ex.fetch_balance() # Private
        print("✅ Standard Fetch Balance: Success")
        print(bal['total'])
    except Exception as e:
        print(f"❌ Standard Fetch Failed: {e}")
        
    print("\n[Attempt 2: Manual V2 Endpoint Test (Connect API)]")
    # Some users report 'Connect Key' uses different logic or endpoints (e.g. /v1/ vs /v2/ in some exchanges)
    # Bithumb 'Connect' usually relies on OAuth2 or specific headers? 
    # But usually standard API keys work on standard endpoints if activated.
    
    # Let's check if the Key Format gives a clue.
    if len(key) == 32:
        print("Key Length: 32 (Looks like standard API Key)")
    elif len(key) > 60:
        print("Key Length > 60 (Could be OAuth Access Token?)")
    else:
        print(f"Key Length: {len(key)} (Unknown format)")

if __name__ == "__main__":
    debug_bithumb_v2()
