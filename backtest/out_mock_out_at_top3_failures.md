# out_mock + out_at 비교표 (Top3 실패항목)

기준: `backtest/out_mock/*/summary.json` 15건 + `backtest/out_at/*/summary.json` 15건 (총 30건)
업데이트 시각: 2026-02-19 01:28 KST 기준 재집계

| 순위 | 실패항목(check) | out_mock (건수/비율) | out_at (건수/비율) | 합계 (건수/비율) |
|---|---|---:|---:|---:|
| 1 | `kz_guard_fired` | 14 / 93.3% | 15 / 100.0% | 29 / 96.7% |
| 2 | `kz_loss_improved` | 1 / 6.7% | 15 / 100.0% | 16 / 53.3% |
| 3 | `abs_bull_tcr` | 0 / 0.0% | 15 / 100.0% | 15 / 50.0% |

메모: `rel_oos_cagr`, `rel_bull_return`는 각각 2 / 30 (6.7%)로 Top3 밖.

TASKS/CHANGELOG/METRICS 반영 초안(3줄):
1. TASKS.md: “AT 집중 실패 3종(`kz_guard_fired`,`kz_loss_improved`,`abs_bull_tcr`) 원인분해 + 임계값/규칙 재설계”를 다음 실행 라운드 필수 태스크로 등록.
2. CHANGELOG.md: “2026-02-19 비교 재집계(30런) 결과와 후속 액션 링크”를 단일 항목으로 기록해 의사결정 근거를 고정.
3. METRICS.md(신규): `top3_fail_rate_combined`, `family_gap(out_at-out_mock)`, `kz_guard_fired_rate` 3개 KPI를 라운드별 누적 표로 관리.
