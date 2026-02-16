# HYBRID_SPEC_v1.2

## 0) 목적
비학습형(rule-based) 자본 배분 스위치 전략으로, 시장 상태에 따라 총 익스포저(`x_cap`)와 CE 비중(`w_ce`)을 동적으로 조절한다.

핵심 목표:
- 추세 구간 참여율(TCR) 개선
- 횡보/급락 구간 손실 및 비용 누수 통제
- 운영 리스크(API/슬리피지/리컨 불일치) 즉시 방어

---

## 1) 불변 계약(절대 규칙)
1. **ML/AI 자가학습 금지** (조건식/임계값 기반만 허용)
2. **최상위 안전식:** `x_total <= x_cap`
3. 위반 주문은 반드시 Reject
4. Guard 발동 시 신규 진입 제한(또는 차단), 감축 우선

---

## 2) 상태 모델

### 2.1 시장 레짐
- `DEFENSIVE`
- `AGGRESSIVE`
- `RANGE`
- `TREND`
- `BEAR`
- `SUPER_TREND` (옵션)

### 2.2 운영 상태
- `NORMAL`
- `CE_OFF`
- `OPS_KILL`

---

## 3) 배분 변수
- `x_cap`: 총 익스포저 상한
- `x_cd`: CD 레그 익스포저
- `x_ce`: CE 레그 익스포저
- `w_ce`: CE 가중치 (`x_ce / x_total`)
- `x_total = x_cd + x_ce`

기본 정책:
- 보수 레짐(DEF/RANGE/BEAR): `x_cap` 축소, `w_ce` 축소
- 공격 레짐(AGG/TREND/SUPER_TREND): `x_cap` 확대, `w_ce` 점진 확대

---

## 4) 전이 규칙(개념)
AGG_ON 확인은 멀티 조건 기반(데이터 부족 시 단순 조건 fallback 허용).

예시 확인 신호:
- 추세/모멘텀 확인
- 거래량 확인
- 비용/슬리피지 상태 정상
- DD/ATR guard 미발동

전이 제약:
- 최소 유지시간(min-hold)
- 쿨다운(cooldown)
- 연속 토글 방지 히스테리시스

---

## 5) Guard 규칙

### 5.1 Intraday Guard
- 조건: 급격한 변동성 확대, 체결 이상, 리컨 불일치 등
- 조치:
  - 신규 진입 금지
  - 감축 주문만 허용
  - 필요 시 `CE_OFF`

### 5.2 Drawdown Ladder
- DD 구간별 `x_cap` 단계 축소
- 임계 DD 초과 시 하드스탑(운영 중지)

### 5.3 Ops Kill
다음 중 하나라도 충족 시 `OPS_KILL`:
- API 오류 임계 초과
- 슬리피지 이상치 연속
- 계정/포지션 리컨 불일치 지속

조치:
- 신규 주문 차단
- 필요 시 강제 감축/정리

---

## 6) Scout
Scout는 소형 탐색 익스포저로 신호 실효성만 검증하며, 본 익스포저 확대 전 단계로 사용.

원칙:
- 최대 비중 제한(작게)
- 가드 우선
- 본 포지션 전환 조건 명시

---

## 7) 실행 제약
- 리밸런싱: 하루 1회 고정 시각 + 괴리 임계 이상일 때
- 비용/슬리피지 추정은 실행 시점 고정 파라미터 사용
- 모든 주문은 Safety Latch 통과 후 제출

---

## 8) 로그/관측 포인트
필수 기록:
- 상태 전이(이유 포함)
- `x_cap`, `w_ce`, `x_cd`, `x_ce`, `x_total`
- Guard 발동 시각/원인/조치
- 주문 Reject 사유(특히 `x_total > x_cap`)

---

## 9) 수용 기준(요약)
- OOS 구간에서 PF/MDD 기준 충족
- 비용 2배 스트레스에서 구조 붕괴 없음
- Kill zone에서 Guard 반응 로그가 실제로 증빙됨

---

## 10) 구현 연결 포인트
- `engine/`: 상태 전이
- `alloc/`: `x_cap`, `w_ce`, scout, CE_OFF, DD ladder
- `guards/`: intraday/ops kill/safety latch
- `backtest/`: splits, run matrix, evaluator, report writer
