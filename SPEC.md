# SPEC

## Goals
- Implement Hybrid Spec v1.2 as rule-based, artifact-driven development.
- Deliver a validated backtest pipeline (R0~R4) with Go/No-Go evaluation.

## Scope
- In:
  - `engine/**`, `alloc/**`, `guards/**`, `backtest/**`, `run_backtest.py`
  - Artifact workflow (`SPEC.md`, `TASKS.md`, `CHANGELOG.md`, `contracts/*`)
- Out:
  - Live deployment changes to production exchange execution settings
  - Non-contract code modifications

## Constraints (Must / Must-not)
- Must follow Task Contract v1 before coding.
- Must enforce strict ownership and single merger (TL only).
- Must use `anchor_replace_block` as default coder output.
- Must-not modify `/contracts/*` or `shared/*` by coders.

## Acceptance Criteria (Global)
- Hybrid core components are implemented per contract.
- Backtest outputs required artifacts for each run.
- TL executes full `test_plan` on integrated codebase successfully.
- PM receives checkpoint-only reports.

## Test Plan (Global)
- `python -m pytest -q`
- `python run_backtest.py --adapter mock --out backtest/out_mock`
- `python run_backtest.py --adapter auto_trading --out backtest/out_at`

## Decisions
- Team mode uses Artifact-Driven Squad Final v1.0.
- PM is sole user-facing reporting channel for team checkpoints.

## Risks
- Merge conflict churn if ownership boundaries are violated.
- Contract drift if artifacts are not updated each round.
