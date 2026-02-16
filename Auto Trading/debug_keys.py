import ccxt
import os
import requests
from dotenv import load_dotenv

# Load .env
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, ".env")
print(f"Loading .env from: {env_path}")
load_dotenv(env_path, override=True)

def get_my_ip():
    try:
        ip = requests.get('https://api.ipify.org').text
        return ip
    except:
        return "Unknown"

def test_bithumb():
    print("\n[Testing Bithumb]")
    print(f"Loading .env from: {os.environ.get('BITHUMB_KEY')[:5]}...") # Just proving it's loaded
    key = os.getenv("BITHUMB_KEY")
    secret = os.getenv("BITHUMB_SECRET")
    
    if not key or not secret:
        print("❌ Keys not found in .env")
        return

    print(f"Key loaded: {key[:5]}...{key[-5:]} (Length: {len(key)})")
    print(f"Secret loaded: {secret[:5]}...{secret[-5:]} (Length: {len(secret)})")
    
    try:
        ex = ccxt.bithumb({
            'apiKey': key,
            'secret': secret,
            'enableRateLimit': True,
            'options': {'adjustForTimeDifference': True}
        })
        bal = ex.fetch_balance()
        print("✅ Connection Success!")
        print(f"Total Assets found: {len(bal['total'])}")
        
    except Exception as e:
        print(f"❌ Connection Failed: {e}")
        print("💡 Possible Fixes:")
        print("1. Check if IP Address is registered in Bithumb API Management.")
        print(f"   Your Current IP: {get_my_ip()}")
        print("2. Check if you copied 'Connect Key' instead of 'API Key' or vice versa.")

def test_upbit():
    print("\n[Testing Upbit]")
    key = os.getenv("UPBIT_ACCESS_KEY")
    secret = os.getenv("UPBIT_SECRET_KEY")
    
    if not key or not secret:
        print("❌ Keys not found in .env")
        return
        
    print(f"Key loaded: {key[:4]}...{key[-4:]}")
    
    try:
        ex = ccxt.upbit({
            'apiKey': key,
            'secret': secret,
            'enableRateLimit': True
        })
        bal = ex.fetch_balance()
        print("✅ Connection Success!")
        print(f"Total KRW: {bal['KRW']['total']:,.0f}")
        
    except Exception as e:
        print(f"❌ Connection Failed: {e}")
        print("💡 Check IP Allowlist in Upbit Open API Settings.")
        print(f"   Your Current IP: {get_my_ip()}")

if __name__ == "__main__":
    print("=== API Key Debugger ===")
    test_bithumb()
    test_upbit()
