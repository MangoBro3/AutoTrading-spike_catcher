import os

# --- V2.1 Constants ---
BUDGET_KRW = 100000
RESERVE_KRW = 5000 # Fee reserve

# Gates
MAX_SPREAD_BP = 50
MIN_DEPTH_RATIO = 2.0
MAX_CHASE_PCT = 3.0

# Risk
RISK_UNIT_WINDOW = 60 # sec

# System
RUN_ID_PREFIX = "RUN_V2"
LOG_DIR_BASE = "live_runs"

# Exchange
BITHUMB_FEE = 0.0025

# --- Environment ---
# Loaded via dotenv in main script

# --- STAGE 0: POLICY & GATES ---
SPOT_ONLY = True
TRADE_MARKET = "KRW"
BTC_TRADE_DISABLED = True
BTC_AS_REGIME_INDICATOR = True
WEB_UI_DISABLED = True
SEED_KRW_DEFAULT = 100000

def validate_config(seed_krw):
    """
    Stage 0 Validation
    Enforces policies before system start.
    """
    if not isinstance(seed_krw, (int, float)):
        raise ValueError("[Config Error] Seed KRW must be a number.")
    
    if seed_krw <= 0:
        raise ValueError(f"[Config Error] Invalid Seed: {seed_krw}. Must be > 0.")
        
    # Verify Constants (Self-Integrity Check)
    if not SPOT_ONLY:
        raise ValueError("[Config Error] Only SPOT trading is allowed in this version.")
    if TRADE_MARKET != "KRW":
        raise ValueError("[Config Error] Only KRW market is allowed.")
    if not BTC_TRADE_DISABLED:
        raise ValueError("[Config Error] BTC Trading must be disabled (Indicator Only).")
        
    return True
