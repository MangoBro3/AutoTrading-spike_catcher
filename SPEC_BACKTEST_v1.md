# SPEC_BACKTEST_v1

## 0) 목적
Hybrid Spec v1.2 전략을 비학습형(rule-based)으로 검증한다.

검증 목표:
1. AGG 발동 실효성
2. 참여율/강세 수익 개선
3. 횡보장 비용 누수 통제
4. Kill zone 가드 반응
5. Scout 실효성
6. RateLimit 필요성 검증

---

## 1) 고정 원칙
- ML/AI 자가학습 금지
- 조건식/임계값 기반 상태 전이만 허용
- 최상위 계약: `x_total <= x_cap`
- 위반 주문은 반드시 Reject

---

## 2) 기간/해상도
- Full Cycle: 2020-01-01 ~ 2024-12-31 (1d)
- IS: 2020-01-01 ~ 2022-12-31 (1d)
- OOS: 2023-01-01 ~ 2024-12-31 (1d, 튜닝 금지)
- Sideways Hell: 2023-01-01 ~ 2023-12-31 (1d)
- Kill Zones: 지정 구간 5m
  - Covid Crash: 2020-03-12 ~ 2020-03-13
  - May 2021 Crash: 2021-05-19 ~ 2021-05-20
  - Luna Cascade: 2022-05-07 ~ 2022-05-13
  - FTX Collapse: 2022-11-06 ~ 2022-11-12

---

## 3) RUN 매트릭스
### R0 Baseline
- Always DEF
- Always AGG
- Hybrid(Spec)

### R1 AB
- Hybrid Scout ON vs OFF
- Hybrid ATR_IGNORE_OK ON vs OFF
- Hybrid RateLimit ON vs OFF

### R2 Trigger Path
- AGG_ON 멀티조건 vs 단순조건(데이터 부족 시 단순조건만)

### R3 비용 스트레스
- fee ×2
- slippage ×2
- fee ×2 + slippage ×2

### R4 Kill Zone(5m)
- Hybrid만 실행
- Guard 반응/손실 억제 검증

---

## 4) 체결/비용/리밸런싱 고정
- fee/slippage는 각 RUN 내 고정값
- 리밸런싱: 하루 1회(고정 시각), 괴리 1% 이상 시 실행
- Intraday Guard 발동 시:
  - 신규 진입 금지
  - 감축만 허용
- SafetyLatch:
  - `x_total > x_cap`면 주문 Reject(소수 오차 허용)

---

## 5) 필수 산출물
1. `daily_state.csv`
2. `switches.csv`
3. `guards.csv`
4. `trades.csv`
5. `summary.json`
6. `metrics_total.json`
7. `metrics_by_mode.json`

---

## 6) Go / No-Go 기준
### 절대 기준
- OOS PF >= 1.2
- OOS MDD <= 0.20
- 강세구간 TCR >= 0.90
- 비용 2배 스트레스에서 구조 붕괴 없음

### 상대 우위 기준
- OOS Hybrid CAGR >= 1.15 × DEF CAGR
- Bull 구간에서 Hybrid 수익 >= 1.30 × DEF 수익
  - 대체 기준: Bull TCR +0.10p 이상

### Kill Zone 기준
- CE_OFF/캡 보수화 실제 발동(로그 증빙)
- Hybrid 손실이 Always AGG 대비 유의미하게 낮아야 함

---

## 7) 구현 파일 계약(초기)
- `backtest/splits/splits_v1.json`
- `backtest/config/run_matrix.py`
- `backtest/core/evaluator.py`
- `backtest/core/report_writer.py`

---

## 8) 보고 규칙
- 작업 진행 중 + 변경 발생 시만 보고
- Busy 상태에서만 주기 보고 사용
- 완료/대기 상태에서는 1회 보고 후 대기
