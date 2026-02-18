# 증거 기반 8항목 보고서 (v1)

- 작성시각(KST): 2026-02-19
- 작업경로(절대): `/mnt/f/SafeBot/openclaw-news-workspace/python`
- 산출물: `backtest/evidence_report_v1.md`
- 비교 기준(Pre/Post):
  - **Pre** = `backtest/out_at/runner_summary.json`
  - **Post** = `backtest/out_at_rerun/runner_summary.json`

---

## 1) Pre/Post 핵심 비교표 (R0~R4 + R3 포함)

> 요청 포맷 우선 반영: **숫자표**로 `oos_pf / oos_mdd / GO count` 비교
> 
> 주의: 본 저장물에는 `oos_pf`, `oos_mdd`의 **연속값(실수 지표)** 이 직접 저장되어 있지 않아, runner_summary의 체크 기준(`abs_oos_pf`, `abs_oos_mdd`) **통과 건수**로 수치화함.

| Group | Runs | Pre oos_pf(pass) | Post oos_pf(pass) | Pre oos_mdd(pass) | Post oos_mdd(pass) | Pre GO count | Post GO count |
|---|---:|---:|---:|---:|---:|---:|---:|
| R0 | 3 | 3 | 0 | 3 | 3 | 0 | 0 |
| R1 | 6 | 6 | 0 | 6 | 6 | 0 | 0 |
| R2 | 2 | 2 | 0 | 2 | 2 | 0 | 0 |
| R3 | 3 | 3 | 0 | 3 | 3 | 0 | 0 |
| R4 | 1 | 1 | 0 | 1 | 1 | 0 | 0 |
| **합계** | **15** | **15** | **0** | **15** | **15** | **0** | **0** |

---

## 2) R3 세부군(스트레스) 확인

| Run ID | Pre abs_oos_pf | Post abs_oos_pf | Pre abs_oos_mdd | Post abs_oos_mdd | Pre GO | Post GO |
|---|---:|---:|---:|---:|---:|---:|
| R3_FEE_X2 | 1 | 0 | 1 | 1 | 0 | 0 |
| R3_SLIP_X2 | 1 | 0 | 1 | 1 | 0 | 0 |
| R3_BOTH_X2 | 1 | 0 | 1 | 1 | 0 | 0 |

판독: R3 전 케이스에서 `abs_oos_pf`는 Pre→Post 악화(3→0), `abs_oos_mdd` 및 GO는 변화 없음.

---

## 3) 데이터 출처(증거 파일)

1. `backtest/out_at/runner_summary.json`  
2. `backtest/out_at_rerun/runner_summary.json`  
3. 참고 교차검증: `METRICS.md`의 "R0~R4 Gate Change Table"

---

## 4) 계산 규칙(재현 가능)

- 그룹 구분: `run_id` 접두(`R0`~`R4`) 기준 집계
- `oos_pf(pass)`: `checks.abs_oos_pf == true` 건수
- `oos_mdd(pass)`: `checks.abs_oos_mdd == true` 건수
- `GO count`: `go_no_go == "GO"` 건수

재현용 1줄 요약: runner_summary 두 파일을 JSON 로드 후 그룹별 boolean 합산.

---

## 5) 핵심 변화 요약

- `abs_oos_pf` 통과건수: **15 → 0** (전량 하락)
- `abs_oos_mdd` 통과건수: **15 → 15** (변화 없음)
- `GO count`: **0 → 0** (변화 없음, 전 구간 NO_GO 유지)

---

## 6) 제출 판단(증거 기반)

- 현재 증거 기준 결론: **Paper Trading 제출 불가(유지)**
- 근거: GO count가 Post에서도 0이며, oos_pf 통과가 전량 소실.

---

## 7) 미확인 항목(요청 규칙 반영)

아래 항목은 현재 파일셋에서 직접 확인되지 않아 **미확인**으로 표기:

- `oos_pf`의 원시 실수값(예: PF=1.23 형태): **미확인**
- `oos_mdd`의 원시 실수값(예: -12.5% 형태, OOS 분리값): **미확인**
- 사용자 지정 "증거 기반 8항목 포맷"의 원문 템플릿(정의 파일): **미확인**

---

## 8) 후속 보완 제안(선택)

1. OOS 원시 지표(PF/MDD) 저장 소스를 명시(예: run_summary schema 확장).
2. `backtest/core/report_writer.py`에 8항목 템플릿 고정 출력 추가.
3. Pre/Post 대상 디렉터리 명명 규칙을 문서화(`out_at`/`out_at_rerun` 등).

---

## 부록 A) 집계 스냅샷

- Pre(`out_at`):
  - R0: n=3, pf_pass=3, mdd_pass=3, go=0
  - R1: n=6, pf_pass=6, mdd_pass=6, go=0
  - R2: n=2, pf_pass=2, mdd_pass=2, go=0
  - R3: n=3, pf_pass=3, mdd_pass=3, go=0
  - R4: n=1, pf_pass=1, mdd_pass=1, go=0
- Post(`out_at_rerun`):
  - R0: n=3, pf_pass=0, mdd_pass=3, go=0
  - R1: n=6, pf_pass=0, mdd_pass=6, go=0
  - R2: n=2, pf_pass=0, mdd_pass=2, go=0
  - R3: n=3, pf_pass=0, mdd_pass=3, go=0
  - R4: n=1, pf_pass=0, mdd_pass=1, go=0
