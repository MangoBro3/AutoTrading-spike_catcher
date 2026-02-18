# out_at_continuous run별 실패원인 테이블

- 기준 경로: `backtest/out_at_continuous/*`
- 산출 시각: 2026-02-19 (Asia/Seoul)
- 판정 소스: 각 run의 `summary.json.checks` (abs/rel 실패 체크) + `metrics_total.json` 핵심값

| run_id | go_no_go | abs 실패체크 | rel 실패체크 | oos_pf | oos_mdd | oos_cagr_hybrid | oos_cagr_def | bull_return_hybrid | bull_return_def |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| R0_AGG | NO_GO | abs_oos_pf, abs_oos_mdd | - | 1.000000 | 0.291039 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| R0_DEF | NO_GO | abs_oos_pf, abs_oos_mdd | - | 1.000000 | 0.291039 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |
| R0_HYB | NO_GO | abs_oos_pf, abs_oos_mdd | rel_oos_cagr, rel_bull_return | 1.000000 | 0.291039 | -0.237068 | 0.000000 | -0.237068 | 0.000000 |
| R1_ATR_IGN_OFF | NO_GO | abs_oos_pf, abs_oos_mdd | rel_oos_cagr, rel_bull_return | 1.000000 | 0.291039 | -0.237068 | 0.000000 | -0.237068 | 0.000000 |
| R1_ATR_IGN_ON | NO_GO | abs_oos_pf, abs_oos_mdd | rel_oos_cagr, rel_bull_return | 1.000000 | 0.291039 | -0.237068 | 0.000000 | -0.237068 | 0.000000 |
| R1_RATE_OFF | NO_GO | abs_oos_pf, abs_oos_mdd | rel_oos_cagr, rel_bull_return | 1.000000 | 0.291039 | -0.237068 | 0.000000 | -0.237068 | 0.000000 |
| R1_RATE_ON | NO_GO | abs_oos_pf, abs_oos_mdd | rel_oos_cagr, rel_bull_return | 1.000000 | 0.291039 | -0.237068 | 0.000000 | -0.237068 | 0.000000 |
| R1_SCOUT_OFF | NO_GO | abs_oos_pf, abs_oos_mdd | rel_oos_cagr, rel_bull_return | 1.000000 | 0.291039 | -0.237068 | 0.000000 | -0.237068 | 0.000000 |
| R1_SCOUT_ON | NO_GO | abs_oos_pf, abs_oos_mdd | rel_oos_cagr, rel_bull_return | 1.000000 | 0.291039 | -0.237068 | 0.000000 | -0.237068 | 0.000000 |
| R2_MULTI | NO_GO | abs_oos_pf, abs_oos_mdd | rel_oos_cagr, rel_bull_return | 1.000000 | 0.291039 | -0.237068 | 0.000000 | -0.237068 | 0.000000 |
| R2_SIMPLE | NO_GO | abs_oos_pf, abs_oos_mdd | rel_oos_cagr, rel_bull_return | 1.000000 | 0.291039 | -0.237068 | 0.000000 | -0.237068 | 0.000000 |
| R3_BOTH_X2 | NO_GO | abs_oos_pf, abs_oos_mdd | rel_oos_cagr, rel_bull_return | 1.000000 | 0.291039 | -0.237068 | 0.000000 | -0.237068 | 0.000000 |
| R3_FEE_X2 | NO_GO | abs_oos_pf, abs_oos_mdd | rel_oos_cagr, rel_bull_return | 1.000000 | 0.291039 | -0.237068 | 0.000000 | -0.237068 | 0.000000 |
| R3_SLIP_X2 | NO_GO | abs_oos_pf, abs_oos_mdd | rel_oos_cagr, rel_bull_return | 1.000000 | 0.291039 | -0.237068 | 0.000000 | -0.237068 | 0.000000 |
| R4_KILL | NO_GO | abs_oos_pf, abs_oos_mdd | rel_oos_cagr, rel_bull_return | 1.000000 | 0.291039 | -0.237068 | 0.000000 | -0.237068 | 0.000000 |

## 요약
- 총 run: 15 / NO_GO: 15
- abs 실패는 전 run 공통으로 `abs_oos_pf`, `abs_oos_mdd` 발생
- rel 실패는 `R0_AGG`, `R0_DEF` 제외 run에서 공통으로 `rel_oos_cagr`, `rel_bull_return` 발생

## 다음 수정 우선순위 (3줄)
1. abs 게이트 우선: `oos_pf`/`oos_mdd`를 동시에 개선하는 손실구간(DD) 축소 로직의 설계 검증 케이스를 먼저 확정.
2. rel 게이트 2순위: HYB/변형 run의 `oos_cagr_hybrid`, `bull_return_hybrid` 음수 구간 원인(포지션/전환 타이밍) 분해 리포트 추가.
3. 기준선 고정: `R0_AGG`/`R0_DEF`를 baseline으로 두고 변경안은 동일 지표셋(abs+rel+핵심 metrics)으로 A/B 비교 자동화.
