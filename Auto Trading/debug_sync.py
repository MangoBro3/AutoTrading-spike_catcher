
import requests

try:
    print("Testing requests to Upbit...")
    r = requests.get("https://api.upbit.com/v1/market/all", timeout=5)
    print(f"Status: {r.status_code}")
except Exception as e:
    print(f"Sync Failed: {e}")
