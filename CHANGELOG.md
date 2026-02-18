# CHANGELOG

## [2026-02-18] Round 1
- What:
  - Initialized Artifact-Driven Squad workflow files (`SPEC.md`, `TASKS.md`, `CHANGELOG.md`).
  - Added first contract reference ticket `T-001`.
- Why:
  - Enforce state-over-chat execution and contract-first development.
- Risk:
  - Low. Documentation/control-plane update only.
- Migration/Notes:
  - All implementation must start only after `contracts/T-001.contract.v1.json` approval.

## [2026-02-18] Round 2
- What:
  - Implemented capital allocation module (`alloc/hybrid_alloc.py`) with `x_cap`, `w_ce`, `scout`, DD ladder and `x_total <= x_cap` invariant handling.
  - Implemented guard engine (`guards/guard_engine.py`) for intraday / ops_kill / safety_latch.
  - Replaced runner mock path with Hybrid simulator engine (`backtest/core/hybrid_simulator.py`) and wired into `engine_interface` + `runner`.
  - Added GO/NO_GO + checks into per-run `summary.json` and regenerated R0~R4 artifacts (`backtest/out_mock`, `backtest/out_at`).
  - Updated `backtest/README.md` to reflect simulator-based execution.
- Why:
  - Complete Hybrid Spec v1.2 executable core and standardized backtest outputs.
- Risk:
  - Medium. Simulator is deterministic and contract-compliant but still synthetic (not production market feed).
- Migration/Notes:
  - `python -m pytest -q` is currently blocked because pytest is not installed in `.venv`.
