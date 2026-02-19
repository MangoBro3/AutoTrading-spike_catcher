# evidence_report_final

## Scope
- base_path: `/mnt/f/SafeBot/openclaw-news-workspace/python`
- report_type: `final_docs_closeout_draft`

## Input Paths
- `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_at/runner_summary.json`
- `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_recover_v2_verify/runner_summary.json`
- `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage7.py`
- `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage10.py`
- `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage11_integration.py`

## Numeric Snapshot (TL Latest Fixed)
- pytest_status: `PASS`
- rerun_generated_runs: `15`
- TL_GATE_RESULT: `GO`
- TL_GATE_GO_COUNT: `15/15`
- R0_GATE_DELTA: `0/3 -> 3/3`
- R2_RE_GATE_RESULT: `GO`
- R2_RE_GATE_GO_COUNT: `2/2`

## TL Final Gate
- TL_GATE_RESULT: `GO`
- TL_GATE_TIMESTAMP_KST: `2026-02-19 08:30:52`
- TL_GATE_SOURCE_PATH: `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_recover_v2_verify/runner_summary.json`
- TL_GATE_NOTE_ID: `TL_FINAL_VERIFY_20260219_083052`
- TL_GATE_GO_COUNT: `15/15`

## re-gate R2
- R2_RE_GATE_RESULT: `GO`
- R2_RE_GATE_RUNS: `2`
- R2_RE_GATE_GO_COUNT: `2/2`
- R2_ABS_OOS_PF_PASS_BEFORE_AFTER: `0/2 -> 2/2`
- R2_KZ_GUARD_FIRED_PASS_BEFORE_AFTER: `0/2 -> 2/2`
- R2_RE_GATE_TIMESTAMP_KST: `2026-02-19 08:30:52`
- R2_RE_GATE_SOURCE_PATH: `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_recover_v2_verify/runner_summary.json`
- R2_RE_GATE_NOTE: `R2_MULTI,R2_SIMPLE both GO`

## PTP_once 후보 반영 전/후표 (AC3/AC4/AC6 + MDD/stress/GO/PF)

- 기준: `backtest/out/baseline`(Pre) vs `backtest/out/candidate_ptp_once_per_position`(Post)
- 출처: `report_exit_ptp_once_expanded_recomputed.json`

| 항목 | Pre | Post | 변화 |
|---|---:|---:|---:|
| AC3_partial_tp_count | 511 | 255 | -50.20% |
| AC4_top10_realized_median_pct | 16.4637 | 26.9978 | +10.5341 |
| AC6_min_pf | 3.205522 | 3.205522 | 0.000000 |
| MDD(max) | 0.037069 | 0.037069 | 0.000000 |
| stress(any_stress_break) | false | false | 동일 |
| GO(go_rate) | 1.000000 | 1.000000 | 동일 |
| PF(min_pf) | 3.205522 | 3.205522 | 0.000000 |

## Backend Sprint1 PASS 근거 동기화 (수치/경로)
- `smoke`=`3/3` → `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_smoke.py`
- `lock`=`3/3` → `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/modules/single_instance_lock.py`
- `safestart`=`4/4` → `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/modules/safe_start.py`
- `tests`=`19/19` → `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage1.py`, `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage2.py`, `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage7.py`, `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage10.py`, `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage11_integration.py`
- sync: `/mnt/f/SafeBot/openclaw-news-workspace/python/results/evidence_backend_sprint1_pass.json`
- TL: `GO`, `15/15` → `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_recover_v2_verify/runner_summary.json`
