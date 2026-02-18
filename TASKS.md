| ID | Status | Owner | Description | Dependency | Ownership | Contract Ref | Blocker | Fail Count |
|---:|:---:|:---:|:---|:---:|:---|:---|:---|:---:|
| T-001 | IN_PROGRESS | PM | Hybrid v1.2 core + backtest runner integration (Phase 1) | None | A:engine/**,alloc/** B:guards/**,backtest/**,run_backtest.py | contracts/T-001.contract.v1.json | [REVIEW] pytest 미설치로 full test_plan 1단계 보류 (activity_log에 blocker 이벤트 미기록) | 0/3 |

### Sync Checkpoint (2026-02-18 18:11 KST, Lane B)
- 기준 로그: `team/usage/activity_log.jsonl` 최신 task 관련 이벤트 확인
- DONE 후보: 없음 (T-001 완료/검증 완료 이벤트 없음)
- Blocker 태그 정리안:
  - 현재 Blocker는 유지하되, 로그 미기록 상태이므로 `[REVIEW]`로 명시
  - 추후 `task_blocked` 또는 동등 이벤트 추가 시 `[ACTIVE_BLOCKER]`로 승격
  - blocker 해소 이벤트 기록 시 Blocker 칼럼을 `None`으로 정리
