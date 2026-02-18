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

## [2026-02-19] Round 3 (Verify & Integrate)
- What:
  - Verified patch on absolute path `/mnt/f/SafeBot/openclaw-news-workspace/python` with stage-specific pytest (`test_stage7.py`, `test_stage10.py`, `test_stage11_integration.py`) → **9 passed**.
  - Re-ran backtest with auto_trading adapter and regenerated `backtest/out_at_rerun/runner_summary.json`.
  - Documented R0~R4 gate delta in `METRICS.md` and synced `TASKS.md` blocker status.
- Why:
  - Validate coder_b patch outcome and keep control-plane docs aligned with rerun evidence.
- Risk:
  - Low. Verification/documentation-only update; no strategy logic edits.
- Migration/Notes:
  - Compared `backtest/out_at/runner_summary.json` vs `backtest/out_at_rerun/runner_summary.json`: GO count unchanged across R0~R4, while `abs_oos_pf` switched `True→False` on all rerun cases.
