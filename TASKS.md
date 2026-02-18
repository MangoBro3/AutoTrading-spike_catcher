| ID | Status | Owner | Description | Dependency | Ownership | Contract Ref | Blocker | Fail Count |
|---:|:---:|:---:|:---|:---:|:---|:---|:---|:---:|
| T-001 | IN_PROGRESS | PM | Hybrid v1.2 core + backtest runner integration (Phase 1) | None | A:engine/**,alloc/** B:guards/**,backtest/**,run_backtest.py | contracts/T-001.contract.v1.json | None (2026-02-19 stage7/10/11 pytest + auto_trading rerun 검증 완료) | 0/3 |

### Sync Checkpoint (2026-02-18 18:11 KST, Lane B)
- 기준 로그: `team/usage/activity_log.jsonl` 최신 task 관련 이벤트 확인
- DONE 후보: 없음 (T-001 완료/검증 완료 이벤트 없음)
- Blocker 태그 정리안:
  - 현재 Blocker는 유지하되, 로그 미기록 상태이므로 `[REVIEW]`로 명시
  - 추후 `task_blocked` 또는 동등 이벤트 추가 시 `[ACTIVE_BLOCKER]`로 승격
  - blocker 해소 이벤트 기록 시 Blocker 칼럼을 `None`으로 정리

### Sync Checkpoint (2026-02-19 01:41 KST, Verify & Integrate)
- 검증 경로: `/mnt/f/SafeBot/openclaw-news-workspace/python`
- pytest: `Auto Trading/test_stage7.py`, `test_stage10.py`, `test_stage11_integration.py` → **9 passed**
- rerun: `python run_backtest.py --adapter auto_trading --run-summary models/_archive/run_20260212_173603_42/run_summary.json --out backtest/out_at_rerun`
- 산출물: `backtest/out_at_rerun/runner_summary.json` 재생성 확인
- R0~R4 gate 변화: GO 건수 변화 없음(전/후 모두 0), 체크 단위로는 `abs_oos_pf` 15건 `True→False`, `kz_guard_fired` 1건(`R4`) `False→True`
