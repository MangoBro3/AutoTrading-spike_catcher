# Evidence Ops Pack (Task D: 항목 2/6/7/8)

- 기준 경로: `/mnt/f/SafeBot/openclaw-news-workspace/python`
- 작성 시각(KST): 2026-02-19 02:24 기준
- 증거 소스: `git log/show`, `backtest/out_at_continuous_failure_table.md`, `backtest/core/evaluator.py`, 파일 `stat/find`

---

## 2) 최근 커밋 3개 (hash | purpose | files[])

> 목적(purpose)은 커밋 메시지 + 변경 파일명 기반 요약(증거: `git show --name-only`)

1. `d38483e5a85c1c2184859db435a5d978e89fcb74`
   - purpose: auto periodic backup + auto trading adapter/evaluator/runner 관련 변경 백업
   - files[]:
     - `Auto Trading/results/daily_risk_state.json`
     - `backtest/core/autotrading_adapter.py`
     - `backtest/core/evaluator.py`
     - `backtest/core/runner.py`

2. `08c134e306e489046973b450c8acf2ae2164f485`
   - purpose: auto periodic backup + hybrid alloc/simulator/state-machine/runner 동기 변경 백업
   - files[]:
     - `alloc/hybrid_alloc.py`
     - `backtest/core/hybrid_simulator.py`
     - `backtest/core/runner.py`
     - `engine/state_machine.py`
     - `results/daily_risk_state.json`

3. `aeebe6c207ee3b6206f04c484ea11a8e07b199d4`
   - purpose: auto periodic backup + continuous verify 문서/실패표/adapter 반영 백업
   - files[]:
     - `backtest/E6_continuous_verify_integrity_report.md`
     - `backtest/E6_post_design_apply_checklist_10.txt`
     - `backtest/E6_rerun_template_commands.sh`
     - `backtest/core/autotrading_adapter.py`
     - `backtest/out_at_continuous_failure_table.md`

---

## 6) 현재 실패항목 (fail_name | 현재값 | 기준값 | 격차)

> 기준식 증거: `backtest/core/evaluator.py`
> - `abs_oos_pf`: 현재 `oos_pf >= 1.2` 필요
> - `abs_oos_mdd`: 현재 `oos_mdd <= 0.20` 필요
> - `rel_oos_cagr`: `oos_cagr_hybrid >= (1.15*oos_cagr_def if def>0 else 0)`
> - `rel_bull_return`: `bull_return_hybrid >= (1.30*bull_return_def if def>0 else 0)`
>
> 현재값 증거: `backtest/out_at_continuous/R0_HYB/metrics_total.json` 및 `backtest/out_at_continuous_failure_table.md`

| fail_name | 현재값 | 기준값 | 격차(현재-기준) |
|---|---:|---:|---:|
| abs_oos_pf | 1.000000 | >= 1.200000 | -0.200000 |
| abs_oos_mdd | 0.291039 | <= 0.200000 | +0.091039 (초과) |
| rel_oos_cagr | -0.237068 | >= 0.000000 *(def=0이므로)* | -0.237068 |
| rel_bull_return | -0.237068 | >= 0.000000 *(def=0이므로)* | -0.237068 |

- 메모: `out_at_continuous_failure_table.md` 기준, 15개 run 전부 `NO_GO`, abs 실패(`abs_oos_pf`,`abs_oos_mdd`)는 공통 발생.

---

## 7) 최근 30분 산출물 2개 (경로 + 생성시각 + 1줄)

1. 경로: `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_laneA_patch/runner_summary.json`
   - 생성시각: `2026-02-19 02:12:54.745412200 +0900`
   - 1줄 요약: `runs=15, NO_GO=15, GO=0`

2. 경로: `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/E6_continuous_verify_integrity_report.md`
   - 생성시각: `2026-02-19 02:02:09.359296500 +0900`
   - 1줄 요약: `# E6 Continuous Verify Guardrail - 기준 파일셋 정합성 점검`

---

## 8) 2시간 계획 (30분 단위, 완료조건/산출물경로)

| 시간블록 (KST) | 작업 | 완료조건 | 산출물경로 |
|---|---|---|---|
| T+0:00 ~ T+0:30 | Gate 실패 정량 재집계(abs/rel) 자동 스크립트 실행 | 15개 run의 fail 빈도/격차 표가 재생성되고 수치 일치 | `backtest/out_laneA_patch/failure_gap_table.md` |
| T+0:30 ~ T+1:00 | abs 우선 개선안 1차(DD/PF 동시개선 파라미터) 실험 1회 | 신규 out 디렉토리 생성 + runner_summary에 최소 1개 체크 개선 | `backtest/out_laneA_patch_try1/runner_summary.json` |
| T+1:00 ~ T+1:30 | rel 실패 원인분해(HYB 음수 CAGR/수익률) 리포트 | HYB vs DEF 비교 원인 3개 이상과 근거 지표 기록 | `backtest/out_laneA_patch_try1/regime_extension_report.json` |
| T+1:30 ~ T+2:00 | 재실행 결과 검증 + 결론 업데이트 | GO 수 변화/주요 격차 변화가 표로 정리되고 다음 액션 결정 | `backtest/E6_continuous_verify_integrity_report.md` (append) |

- 실행 원칙: 모든 판단은 `summary.json.checks` + `metrics_total.json` + `evaluator.py` 기준식으로만 판정.
