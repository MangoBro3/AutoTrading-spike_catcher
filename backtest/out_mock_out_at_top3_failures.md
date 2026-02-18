# out_mock + out_at 비교표 (Top3 실패항목)

기준: `backtest/out_mock/*/summary.json` 15건 + `backtest/out_at/*/summary.json` 15건 (총 30건)

| 순위 | 실패항목(check) | out_mock (건수/비율) | out_at (건수/비율) | 합계 (건수/비율) |
|---|---|---:|---:|---:|
| 1 | `kz_guard_fired` | 14 / 93.3% | 15 / 100.0% | 29 / 96.7% |
| 2 | `kz_loss_improved` | 1 / 6.7% | 15 / 100.0% | 16 / 53.3% |
| 3 | `abs_bull_tcr` | 0 / 0.0% | 15 / 100.0% | 15 / 50.0% |

메모: `rel_oos_cagr`, `rel_bull_return`는 각각 2 / 30 (6.7%)로 Top3 밖.

TASKS/CHANGELOG 반영 제안(3줄):
1. TASKS.md: “AT 시나리오 Top3 실패항목(`kz_guard_fired`,`kz_loss_improved`,`abs_bull_tcr`) 원인분해 및 임계값 재설계” 작업 추가.
2. TASKS.md: “out_mock/out_at 체크 실패율 자동 집계 스크립트 + CI 리포트 생성”을 반복 업무로 등록.
3. CHANGELOG.md: 금회 비교 결과(Top3 건수/비율, 총 30런 기준)와 후속 액션 아이템 링크를 한 단락으로 기록.
