
import sys
import os

# Add relevant paths
sys.path.append(r"c:\Users\nak\Desktop\DHR 런처\python\Auto Trading")

print("Attempting to import modules...")
try:
    from autotune import AutoTuner
    print("✅ autotune imported successfully")
except Exception as e:
    print(f"❌ autotune import failed: {e}")

try:
    from backtester import Backtester
    print("✅ backtester imported successfully")
except Exception as e:
    print(f"❌ backtester import failed: {e}")

try:
    from tqdm import tqdm
    print("✅ tqdm is available")
except ImportError:
    print("⚠️ tqdm is NOT available (Backtester will use fallback)")

print("Verification complete.")
