| ID | Status | Owner | Description | Dependency | Ownership | Contract Ref | Blocker | Fail Count |
|---:|:---:|:---:|:---|:---:|:---|:---|:---|:---:|
| T-001 | IN_PROGRESS | PM | Hybrid v1.2 core + backtest runner integration (Phase 1) | None | A:engine/**,alloc/** B:guards/**,backtest/**,run_backtest.py | contracts/T-001.contract.v1.json | **PAPER_TRADING_BLOCKED (R0~R4 GO=0/15, NO_GO 유지)** | 0/3 |

### Final Sync Checkpoint (2026-02-19 01:49 KST, Lane B / Start Now)
- 작업 경로: `/mnt/f/SafeBot/openclaw-news-workspace/python`
- 검증 상태: `Auto Trading/test_stage7.py test_stage10.py test_stage11_integration.py` → **9 passed**
- 재실행 상태: `run_backtest.py --adapter auto_trading ... --out backtest/out_at_rerun` → **15 runs 생성**
- 산출물 일관성: `TASKS.md / CHANGELOG.md / METRICS.md` 마감 패키지 동기화 완료
- 최종 판단: **현재는 Paper Trading 불가(NO_GO)**
- 근거 위치: `METRICS.md`의 "Paper Trading 판단 근거표(12줄 이내)"

### Final Docs Closeout Draft (for TL Gate)
- 기준 경로: `/mnt/f/SafeBot/openclaw-news-workspace/python`
- 기준 산출물:
  - `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_at/runner_summary.json`
  - `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_at_rerun/runner_summary.json`
- 수치:
  - pytest: `9 passed`
  - rerun 생성 건수: `15`
  - R0~R4 GO count: `0/15`
  - `abs_oos_pf` pass: `15→0`
  - `kz_guard_fired` pass: `0→1` (R4 1건)
- TL 최종 게이트 결과(자리표시): `TL_GATE_RESULT = [PENDING_INPUT]`
- RE_GATE_R2_APPLY_SLOT: `[PENDING_INPUT]` (R2 재게이트 결과 수신 즉시 반영용)
