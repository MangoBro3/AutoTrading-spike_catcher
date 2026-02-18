# evidence_report_final

## Scope
- base_path: `/mnt/f/SafeBot/openclaw-news-workspace/python`
- report_type: `final_docs_closeout_draft`

## Input Paths
- `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_at/runner_summary.json`
- `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_at_rerun/runner_summary.json`
- `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage7.py`
- `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage10.py`
- `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage11_integration.py`

## Numeric Snapshot
- pytest_passed: `9`
- rerun_generated_runs: `15`
- r0_r4_go_count: `0/15`
- abs_oos_pf_pass_before_after: `15/15 -> 0/15`
- kz_guard_fired_pass_before_after: `0/15 -> 1/15`

## TL Final Gate Placeholder
- TL_GATE_RESULT: `[PENDING_INPUT]`
- TL_GATE_TIMESTAMP_KST: `[PENDING_INPUT]`
- TL_GATE_SOURCE_PATH: `[PENDING_INPUT]`
- TL_GATE_NOTE_ID: `[PENDING_INPUT]`

## re-gate R2 pending slot
- R2_RE_GATE_RESULT: `[PENDING_INPUT]`  <!-- allowed: GO | NO_GO -->
- R2_RE_GATE_RUNS: `[PENDING_INPUT]`    <!-- example: 2 -->
- R2_RE_GATE_GO_COUNT: `[PENDING_INPUT]` <!-- example: 0/2 -->
- R2_ABS_OOS_PF_PASS_BEFORE_AFTER: `[PENDING_INPUT]` <!-- example: 2/2 -> 0/2 -->
- R2_KZ_GUARD_FIRED_PASS_BEFORE_AFTER: `[PENDING_INPUT]` <!-- example: 0/2 -> 0/2 -->
- R2_RE_GATE_TIMESTAMP_KST: `[PENDING_INPUT]`
- R2_RE_GATE_SOURCE_PATH: `[PENDING_INPUT]`
- R2_RE_GATE_NOTE: `[PENDING_INPUT]`
