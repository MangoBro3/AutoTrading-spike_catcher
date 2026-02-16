"""Loader for backtest/splits/splits_v1.json."""

from __future__ import annotations

import json
from pathlib import Path


def load_splits(path: str | Path = "backtest/splits/splits_v1.json") -> dict:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))
