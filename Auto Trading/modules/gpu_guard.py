
import os
import subprocess
import logging
from contextlib import contextmanager

logger = logging.getLogger("GPUGuard")

def get_power_limit(gpu_id=0):
    """
    Reads current power limit using nvidia-smi.
    Returns None if failed.
    """
    try:
        # nvidia-smi -i 0 --query-gpu=power.limit --format=csv,noheader,nounits
        result = subprocess.run(
            ["nvidia-smi", "-i", str(gpu_id), "--query-gpu=power.limit", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True
        )
        return float(result.stdout.strip())
    except Exception as e:
        logger.warning(f"[GPUGuard] Failed to read PL: {e}")
        return None

def set_power_limit(gpu_id, watts):
    """
    Sets power limit using nvidia-smi -pl.
    """
    try:
        # nvidia-smi -i 0 -pl 240
        subprocess.run(
            ["nvidia-smi", "-i", str(gpu_id), "-pl", str(watts)],
            capture_output=True, text=True, check=True
        )
        logger.info(f"[GPUGuard] Set GPU {gpu_id} Power Limit to {watts}W")
        return True
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.strip() if e.stderr else "Unknown error (likely Permission Denied/Admin required)"
        logger.warning(f"[GPUGuard] Failed to set PL to {watts}W: {err_msg}")
        return False
    except Exception as e:
        logger.warning(f"[GPUGuard] Error setting PL: {e}")
        return False

@contextmanager
def temporary_power_limit(target_watts=240, gpu_id=0):
    """
    Context Manager to temporarily lower GPU power limit.
    Ensures restoration in finally.
    """
    original_watts = get_power_limit(gpu_id)
    limit_set = False
    
    # 1. Attempt to Set Limit
    if original_watts is not None:
        try:
            if original_watts != target_watts:
                if set_power_limit(gpu_id, target_watts):
                    limit_set = True
        except Exception as e:
            logger.warning(f"[GPUGuard] unexpected error setting limit: {e}")

    # 2. YIELD CONTROL (Critical)
    try:
        yield
    finally:
        # 3. Restore Limit
        if limit_set and original_watts:
            try:
                logger.info(f"[GPUGuard] Restoring original Power Limit ({original_watts}W)...")
                set_power_limit(gpu_id, original_watts)
            except Exception as e:
                logger.warning(f"[GPUGuard] Failed to restore PL: {e}")
