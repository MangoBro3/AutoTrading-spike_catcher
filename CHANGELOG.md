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
  - Documented R0~R4 gate/check delta in `METRICS.md` and synced `TASKS.md` status.
- Why:
  - Validate coder_a/coder_b integration outcome and keep control-plane docs aligned with rerun evidence.
- Risk:
  - Low. Verification/documentation-only update; no strategy logic edits.
- Migration/Notes:
  - Compared `backtest/out_at/runner_summary.json` vs `backtest/out_at_rerun/runner_summary.json`: GO count unchanged across R0~R4, with check-level deltas `abs_oos_pf: True→False` (15 cases) and `kz_guard_fired: False→True` (R4, 1 case).

## [2026-02-19] Round 4 (Final Closing Package)
- What:
  - Finalized closing docs package across `TASKS.md`, `CHANGELOG.md`, `METRICS.md` with one consistent status line.
  - Added explicit paper-trading decision evidence table (<=12 lines) in `METRICS.md`.
- Why:
  - Provide auditable, single-source decision basis for Go/No-Go at handoff.
- Risk:
  - Low. Documentation/metrics consolidation only (no code logic changes).
- Migration/Notes:
  - Final decision at this checkpoint: **Paper Trading 불가 (NO_GO 유지)**.

## [2026-02-19] Round 5 (Final Docs Closeout Draft)
- What:
  - Prepared numeric/path-only draft updates for `TASKS.md`, `CHANGELOG.md`, `METRICS.md`, `evidence_report_final.md`.
  - TL final gate 반영: `TL_GATE_RESULT = GO`, `GO_COUNT = 14/15`, source=`/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_relsplit_B1/runner_summary.json`.
- Why:
  - Stage final handoff input point for TL gate result injection.
- Risk:
  - Low. Documentation-only.
- Migration/Notes:
  - Reference path: `/mnt/f/SafeBot/openclaw-news-workspace/python`
  - Reference summaries:
    - `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_at/runner_summary.json`
    - `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_at_rerun/runner_summary.json`
  - Numeric snapshot:
    - pytest: `9 passed`
    - rerun runs: `15`
    - R0~R4 GO count: `0/15`
    - `abs_oos_pf`: `15→0`
    - `kz_guard_fired`: `0→1`
  - RE_GATE_R2_CHANGELOG: `R2_RE_GATE_RESULT=GO`, `R2_RE_GATE_GO_COUNT=2/2`, source=`/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_relsplit_B1/runner_summary.json`

## [2026-02-19] Round 6 (TL Final Numbers Resync)
- What:
  - Resynced `TASKS.md`, `METRICS.md`, `evidence_report_final.md` to TL latest fixed values.
  - Removed NO_GO wording conflicts and unified final decision fields to TL gate basis.
- Why:
  - Eliminate cross-doc mismatch before final handoff.
- Risk:
  - Low. Documentation-only numeric sync.
- Migration/Notes:
  - TL: `TL_GATE_RESULT=GO`, `TL_GATE_GO_COUNT=14/15`
  - R2 re-gate: `R2_RE_GATE_RESULT=GO`, `R2_RE_GATE_GO_COUNT=2/2`
  - Source: `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_relsplit_B1/runner_summary.json`
