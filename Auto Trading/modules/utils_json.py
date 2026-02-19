import json
import os
from pathlib import Path
from datetime import datetime, date
import shutil
import numpy as np
from typing import Any, Callable, Iterable, Optional

SCHEMA_VERSION_FIELD = "_schema_version"


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


def _fsync_directory(parent: Path):
    """Force directory entry fsync for stronger crash consistency."""
    try:
        fd = os.open(str(parent), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except Exception:
        # Directory fsync is a best-effort durability feature; keep write path resilient.
        pass


def safe_json_dump(
    data: Any,
    file_path,
    indent: int = 4,
    *,
    schema_version: Optional[int] = None,
) -> None:
    """
    Atomically writes JSON data to file_path.

    Steps:
    1) Write data to <target>.tmp
    2) Flush + fsync temp file descriptor
    3) Replace target with temp file
    4) fsync target directory
    """
    target_path = Path(file_path)
    tmp_path = target_path.with_suffix(target_path.suffix + ".tmp")

    if schema_version is not None:
        if isinstance(data, dict):
            data = dict(data)
            data.setdefault(SCHEMA_VERSION_FIELD, schema_version)
        else:
            data = {
                SCHEMA_VERSION_FIELD: schema_version,
                "value": data,
            }

    # Ensure parent directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, cls=CustomJSONEncoder, indent=indent, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, target_path)
        _fsync_directory(target_path.parent)
    except Exception as e:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        raise IOError(f"Failed to write JSON cleanly to {file_path}: {e}")


def safe_json_load(
    file_path,
    *,
    default: Any = None,
    schema_version: Optional[int] = None,
    schema_migrations: Optional[Iterable[Callable[[Any], Any]]] = None,
    repair: bool = False,
):
    """
    Loads JSON with optional schema version guard and migration.

    - If the file does not exist, returns `default`.
    - If corrupted/unreadable, optionally backs up corrupted file as `.corrupt` and returns default.
    - If schema_version is provided and file has `_schema_version`, migration steps can be
      supplied in schema_migrations list ordered by old-version index.
      Each migration receives the loaded object and should return new object.
    """
    path = Path(file_path)
    if not path.exists():
        return default

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw else default
    except Exception:
        if repair:
            backup = path.with_suffix(path.suffix + ".corrupt")
            try:
                shutil.move(str(path), str(backup))
            except Exception:
                pass
        return default

    if data is None:
        return default

    if schema_version is None:
        return data

    # Legacy data (no schema_version) starts at version 1
    current = data.get(SCHEMA_VERSION_FIELD, 1) if isinstance(data, dict) else 1

    # Best-effort migrations between versions.
    if not isinstance(schema_migrations, list):
        schema_migrations = []

    if isinstance(current, int):
        while current < schema_version:
            idx = int(current) - 1
            if 0 <= idx < len(schema_migrations):
                try:
                    data = schema_migrations[idx](data)
                except Exception:
                    if repair:
                        if data is not None:
                            backup = path.with_suffix(path.suffix + f".corrupt_v{current}")
                            try:
                                shutil.move(str(path), str(backup))
                            except Exception:
                                pass
                    return default
            else:
                # No migration available; keep best-effort using current structure.
                break
            current += 1
        return data

    return data
