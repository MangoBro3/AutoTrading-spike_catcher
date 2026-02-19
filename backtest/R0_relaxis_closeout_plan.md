# R0 전용 마무리안 (단일안 확정)

대상: `R0_DEF / R0_AGG / R0_HYB` 남은 NO_GO 3건
목표: **rel 축 이슈만 최소 변경으로 해소**하고, 기준선 고정 + 오버피팅 방지 조건을 명시

## 1) 최소 변경(코드/로직)

### 변경안 A (단일 채택)
- `backtest/core/runner.py`의 `eval_scope`를 유지:
  - `rel_deadband_enabled = (run_id == "R0_HYB")`
  - `rel_deadband_eps = 1e-9` (고정값)
- 의미:
  - R0에서 rel 평가는 HYB 비교축에만 제한 적용(DEF/AGG는 rel로 흔들지 않음)
  - DEF 기준값이 0 근처일 때 생기는 부호/스케일 왜곡(0 대비 비율비교)만 deadband로 완충

> 즉, 전략/신호/포지션 로직은 건드리지 않고 **판정축의 수치적 불안정만 국소 보정**.

---

## 2) 기준선 고정(Baseline Lock)

- 고정 기준선: **동일 실행 배치의 `R0_DEF`**
- 비교 대상: `R0_HYB` (rel), `R0_AGG`(abs 기준 참조)
- 실행 규칙:
  1. 같은 run batch에서 산출된 `R0_DEF`만 baseline으로 사용
  2. `rel_deadband_eps`는 전 구간/전 실험 동일 상수(1e-9)
  3. 보고서에는 `R0_DEF, R0_HYB`의 raw metric과 rel check(raw/final) 동시 표기

---

## 3) 오버피팅 방지 조건 (필수)

1. **단일 파라미터 고정**: deadband epsilon 튜닝 금지 (`1e-9` 고정)
2. **게이트 완화 금지**: abs gate 임계값(`oos_pf>=1.2`, `oos_mdd<=0.20`) 변경 금지
3. **적용 범위 고정**: deadband는 `R0_HYB` rel check에만 적용 (R1~R4 확장 금지)
4. **판정 분리 유지**: rel 축 해소 후에도 최종 GO/NO_GO는 abs/kz 포함 동일 규칙으로 판정

---

## 4) 기대 결과(해석 기준)

- 이번 마무리안은 **rel 축 노이즈 제거용**이므로,
  - R0_HYB의 rel 실패 원인은 제거 가능
  - 단, R0 3건의 NO_GO 지속 여부는 abs(`oos_pf`, `oos_mdd`)에 의해 결정됨
- 즉, 이번 안의 성공 기준은 **"rel 축 해소 + 기준 일관성 확보"**이며,
  **NO_GO 자체를 억지로 GO로 바꾸는 안이 아님**.

---

## 결론 (확정안)

- **확정안: 변경안 A 단일 채택**
- 요약: `R0_HYB rel deadband(1e-9)만 적용` + `R0_DEF baseline 고정` + `게이트/파라미터 튜닝 금지`
- 장점: 최소 변경, 설명 가능성 높음, 과최적화 유인 낮음
