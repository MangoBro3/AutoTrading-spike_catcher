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
| 게이트 성과 | R0~R4 GO count = 0/15 (전후 동일) | 미통과 |
| 수익성 체크 | abs_oos_pf pass 15→0 (전량 악화) | 미통과 |
| 안전 가드 | kz_guard_fired R4: 0→1 (발화 증가) | 주의 |
| 최종 결론 | 핵심 게이트 미충족(NO_GO 유지) | **Paper Trading 불가** |

### Summary
- GO/NO_GO 결론은 R0~R4 전체에서 변화 없음 (**모두 NO_GO 유지**).
- 체크 변화: `abs_oos_pf` 15건 `True→False`, `kz_guard_fired` 1건(`R4`) `False→True`.
- 코드 로직 파일 수정 없이 검증/재실행/문서 반영만 수행.

## Final Docs Closeout Draft (Numeric/Path Only)
- 기준 경로: `/mnt/f/SafeBot/openclaw-news-workspace/python`
- 입력 파일:
  - `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_at/runner_summary.json`
  - `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_at_rerun/runner_summary.json`
- 수치 스냅샷:
  - `pytest_passed = 9`
  - `rerun_generated_runs = 15`
  - `r0_r4_go_count = 0/15`
  - `abs_oos_pf_pass_before_after = 15/15 -> 0/15`
  - `kz_guard_fired_pass_before_after = 0/15 -> 1/15`
- TL 최종 게이트 결과(자리표시):
  - `TL_GATE_RESULT = [PENDING_INPUT]`
  - `TL_GATE_TIMESTAMP_KST = [PENDING_INPUT]`
  - `TL_GATE_SOURCE_PATH = [PENDING_INPUT]`
