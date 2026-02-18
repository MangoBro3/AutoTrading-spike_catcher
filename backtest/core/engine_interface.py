"""Engine/data interface contract for replacing mock runner logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class RunRequest:
    run_id: str
    mode: str
    split: dict
    options: dict


class EngineAdapter(Protocol):
    def run(self, request: RunRequest) -> dict:
        """Return payload compatible with report_writer.write_reports()."""


def default_mock_adapter(request: RunRequest) -> dict:
    """Default local simulator adapter for Hybrid v1.2 backtests."""
    from backtest.core.hybrid_simulator import simulate_hybrid_run

    return simulate_hybrid_run(request)
