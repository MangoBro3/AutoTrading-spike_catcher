# METRICS

## 2026-02-19 Verify & Integrate (auto_trading rerun)

### Verification Commands
- `cd '/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading' && pytest -q test_stage7.py test_stage10.py test_stage11_integration.py`
  - Result: **9 passed in 11.53s**
- `cd /mnt/f/SafeBot/openclaw-news-workspace/python && python run_backtest.py --adapter auto_trading --run-summary models/_archive/run_20260212_173603_42/run_summary.json --out backtest/out_recover_v2_verify`
  - Result: **generated runs: 15**

### R0~R4 Gate Change Table (before: `out_at` → after: `out_recover_v2_verify`)

| Gate Group | Runs | GO Count (Before→After) | abs_oos_pf pass | abs_oos_mdd pass | abs_bull_tcr pass | abs_stress_no_break pass | rel_oos_cagr pass | rel_bull_return pass | kz_guard_fired pass | kz_loss_improved pass |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R0 | 3 | 0→3 | 3→0 | 3→3 | 0→0 | 3→3 | 3→3 | 3→3 | 0→0 | 3→3 |
| R1 | 6 | 0→0 | 6→0 | 6→6 | 0→0 | 6→6 | 6→6 | 6→6 | 0→0 | 6→6 |
| R2 | 2 | 0→0 | 2→0 | 2→2 | 0→0 | 2→2 | 2→2 | 2→2 | 0→0 | 2→2 |
| R3 | 3 | 0→0 | 3→0 | 3→3 | 0→0 | 3→3 | 3→3 | 3→3 | 0→0 | 3→3 |
| R4 | 1 | 0→0 | 1→0 | 1→1 | 0→0 | 1→1 | 1→1 | 1→1 | 0→1 | 1→1 |

### Paper Trading 판단 근거표 (12줄 이내)
| 항목 | 근거 | 판정 |
|---|---|---|
| 테스트 안정성 | stage7/10/11 pytest PASS | 통과 |
| 실행 재현성 | rerun 15건 생성, summary 재생성 확인 | 통과 |
| TL 최종 게이트 | TL_GATE_GO_COUNT = 15/15 (`out_recover_v2_verify`) | 통과 |
| R0 전환 | R0 GO_COUNT 0/3 -> 3/3 | 통과 |
| R2 re-gate | R2_RE_GATE_GO_COUNT = 2/2 | 통과 |
| 안전 가드 | R2_KZ_GUARD_FIRED_PASS 0/2→2/2 | 통과 |
| 최종 결론 | TL 최신 확정 수치 기준 | **Paper Trading GO** |

### Summary
- TL 최신 확정 기준: `TL_GATE_RESULT=GO`, `TL_GATE_GO_COUNT=15/15`.
- RE_GATE_R2: `R2_RE_GATE_RESULT=GO`, `R2_RE_GATE_GO_COUNT=2/2`.
- 코드 로직 파일 수정 없이 문서 수치 동기화만 수행.

## Final Docs Closeout Draft (Numeric/Path Only)
- 기준 경로: `/mnt/f/SafeBot/openclaw-news-workspace/python`
- 입력 파일:
  - `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_at/runner_summary.json`
  - `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_recover_v2_verify/runner_summary.json`
- 수치 스냅샷 (TL 최신 확정):
  - `pytest_status = PASS`
  - `rerun_generated_runs = 15`
  - `TL_GATE_RESULT = GO`
  - `TL_GATE_GO_COUNT = 15/15`
  - `R2_RE_GATE_RESULT = GO`
  - `R2_RE_GATE_GO_COUNT = 2/2`
- TL 최종 게이트 결과:
  - `TL_GATE_TIMESTAMP_KST = 2026-02-19 08:30:52`
  - `TL_GATE_SOURCE_PATH = /mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_recover_v2_verify/runner_summary.json`
- RE_GATE_R2_METRICS:
  - `R2_RE_GATE_RUNS = 2`
  - `R2_ABS_OOS_PF_PASS_BEFORE_AFTER = 0/2 -> 2/2`
  - `R2_KZ_GUARD_FIRED_PASS_BEFORE_AFTER = 0/2 -> 2/2`
  - `R2_RE_GATE_SOURCE_PATH = /mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_recover_v2_verify/runner_summary.json`

## Backend Sprint1 PASS 근거 (수치/경로)
- 기준 경로: `/mnt/f/SafeBot/openclaw-news-workspace/python`
- `test_smoke.py`: `3/3` (`/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_smoke.py`)
- `single_instance_lock`: `3/3` (`/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/modules/single_instance_lock.py`)
- `safe_start`: `4/4` (`/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/modules/safe_start.py`)
- stage/stability tests: `19/19` (`/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_smoke.py`, `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage1.py`, `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage2.py`, `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage7.py`, `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage10.py`, `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage11_integration.py`)
- 근거 통합 파일: `/mnt/f/SafeBot/openclaw-news-workspace/python/results/evidence_backend_sprint1_pass.json`
- TL 최종 게이트 동기화: `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_recover_v2_verify/runner_summary.json` (`TL_GATE_RESULT=GO`, `TL_GATE_GO_COUNT=15/15`)

### Backend Sprint1 Evidence Sync (Final)
- `smoke`=`3/3` (`/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_smoke.py`)
- `lock`=`3/3` (`/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/modules/single_instance_lock.py`)
- `safestart`=`4/4` (`/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/modules/safe_start.py`)
- `tests`=`19/19` (`/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage1.py`, `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage2.py`, `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage7.py`, `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage10.py`, `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_stage11_integration.py`)
- `sync_file`=`/mnt/f/SafeBot/openclaw-news-workspace/python/results/evidence_backend_sprint1_pass.json`
- `TL_GATE_RESULT`=`GO`, `TL_GATE_GO_COUNT`=`15/15`
- `TL_GATE_PATH`=`/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_recover_v2_verify/runner_summary.json`

## UI Sprint1 PASS Evidence (Numeric/Path)
- `worker_polling_interval_ms`=`1000` (`/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/web_backend.py`)
- `worker_polling_routes_per_cycle`=`3` (`/api/status`,`/api/models`,`/api/orders`) (`/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/web_backend.py`)
- `worker_threads`=`4` (`heartbeat_loop`, `watchlist_scheduler`, `evolution_scheduler`, `data_update_scheduler`) (`/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/web_backend.py`)
- `safety_overlay_exists`=`1` (`liveConfirmBackdrop`) (`/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/web_backend.py`)
- `panic_ready_percent`=`80` (`PANIC_READY_PERCENT`) + `panic_hold_ms`=`3000` (`PANIC_HOLD_MS`) (`/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/web_backend.py`)
- `order_cancel_endpoints`=`1` (`/api/orders/cancel`) + `order_cancel_handlers`=`2` (`cancelOrder`, `cancelAllOrders`) (`/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/web_backend.py`)
- `panic_input_debounce`=`80 ms` progress timer interval + `clear` guards on pointer up/leave (`/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/web_backend.py`)
- `ui_sprint1_smoke`=`2/2` (`/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_ui_sprint1_smoke.py`)
