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
    """Fallback adapter until real engine binding is implemented."""
    from backtest.core.runner import simulate_run

    run = {"run_id": request.run_id, "mode": request.mode, **request.options}
    return simulate_run(run, request.split)
