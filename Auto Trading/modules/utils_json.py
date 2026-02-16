import json
import os
import shutil
import numpy as np
from datetime import datetime, date
from pathlib import Path

class CustomJSONEncoder(json.JSONEncoder):
    """
    JSON Encoder that handles:
    - datetime/date -> ISO format string
    - pathlib.Path -> string
    - numpy types -> native Python types (int, float, list)
    """
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        if isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

def safe_json_dump(data, file_path, indent=4):
    """
    Atomically writes data to file_path in JSON format.
    1. Dump to file_path.tmp
    2. os.replace(tmp, target)
    """
    target_path = Path(file_path)
    tmp_path = target_path.with_suffix(".tmp")
    
    # Ensure parent directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, cls=CustomJSONEncoder, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno()) # Force write to disk
            
        os.replace(tmp_path, target_path)
    except Exception as e:
        if tmp_path.exists():
            try: os.remove(tmp_path)
            except: pass
        raise IOError(f"Failed to write JSON cleanly to {file_path}: {e}")
