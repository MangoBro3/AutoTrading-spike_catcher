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

### Summary
- GO/NO_GO 결론은 R0~R4 전체에서 변화 없음 (**모두 NO_GO 유지**).
- 체크 변화: `abs_oos_pf` 15건 `True→False`, `kz_guard_fired` 1건(`R4`) `False→True`.
- 코드 로직 파일 수정 없이 검증/재실행/문서 반영만 수행.
