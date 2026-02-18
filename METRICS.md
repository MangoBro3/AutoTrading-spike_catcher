# METRICS

## 2026-02-19 Verify & Integrate (auto_trading rerun)

### Verification Commands
- `cd '/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading' && pytest -q test_stage7.py test_stage10.py test_stage11_integration.py`
  - Result: **9 passed in 11.53s**
- `cd /mnt/f/SafeBot/openclaw-news-workspace/python && python run_backtest.py --adapter auto_trading --run-summary models/_archive/run_20260212_173603_42/run_summary.json --out backtest/out_at_rerun`
  - Result: **generated runs: 15**

### R0~R4 Gate Change Table (before: `out_at` → after: `out_at_rerun`)

| Gate Group | Runs | GO Count (Before→After) | abs_oos_pf pass | abs_oos_mdd pass | abs_bull_tcr pass | abs_stress_no_break pass | rel_oos_cagr pass | rel_bull_return pass | kz_guard_fired pass | kz_loss_improved pass |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R0 | 3 | 0→0 | 3→0 | 3→3 | 0→0 | 3→3 | 3→3 | 3→3 | 0→0 | 3→3 |
| R1 | 6 | 0→0 | 6→0 | 6→6 | 0→0 | 6→6 | 6→6 | 6→6 | 0→0 | 6→6 |
| R2 | 2 | 0→0 | 2→0 | 2→2 | 0→0 | 2→2 | 2→2 | 2→2 | 0→0 | 2→2 |
| R3 | 3 | 0→0 | 3→0 | 3→3 | 0→0 | 3→3 | 3→3 | 3→3 | 0→0 | 3→3 |
| R4 | 1 | 0→0 | 1→0 | 1→1 | 0→0 | 1→1 | 1→1 | 1→1 | 0→1 | 1→1 |

### Paper Trading 판단 근거표 (12줄 이내)
| 항목 | 근거 | 판정 |
|---|---|---|
| 테스트 안정성 | stage7/10/11 pytest 9 passed | 통과 |
| 실행 재현성 | rerun 15건 생성, summary 재생성 확인 | 통과 |
| TL 최종 게이트 | TL_GATE_GO_COUNT = 14/15 (`out_relsplit_B1`) | 통과 |
| R2 re-gate | R2_RE_GATE_GO_COUNT = 2/2 | 통과 |
| 안전 가드 | R2_KZ_GUARD_FIRED_PASS 0/2→2/2 | 통과 |
| 최종 결론 | TL 최신 확정 수치 기준 | **Paper Trading GO** |

### Summary
- TL 최신 확정 기준: `TL_GATE_RESULT=GO`, `TL_GATE_GO_COUNT=14/15`.
- RE_GATE_R2: `R2_RE_GATE_RESULT=GO`, `R2_RE_GATE_GO_COUNT=2/2`.
- 코드 로직 파일 수정 없이 문서 수치 동기화만 수행.

## Final Docs Closeout Draft (Numeric/Path Only)
- 기준 경로: `/mnt/f/SafeBot/openclaw-news-workspace/python`
- 입력 파일:
  - `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_at/runner_summary.json`
  - `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_at_rerun/runner_summary.json`
- 수치 스냅샷 (TL 최신 확정):
  - `pytest_passed = 9`
  - `rerun_generated_runs = 15`
  - `TL_GATE_RESULT = GO`
  - `TL_GATE_GO_COUNT = 14/15`
  - `R2_RE_GATE_RESULT = GO`
  - `R2_RE_GATE_GO_COUNT = 2/2`
- TL 최종 게이트 결과:
  - `TL_GATE_TIMESTAMP_KST = 2026-02-19 08:30:52`
  - `TL_GATE_SOURCE_PATH = /mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_relsplit_B1/runner_summary.json`
- RE_GATE_R2_METRICS:
  - `R2_RE_GATE_RUNS = 2`
  - `R2_ABS_OOS_PF_PASS_BEFORE_AFTER = 0/2 -> 2/2`
  - `R2_KZ_GUARD_FIRED_PASS_BEFORE_AFTER = 0/2 -> 2/2`
  - `R2_RE_GATE_SOURCE_PATH = /mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_relsplit_B1/runner_summary.json`
