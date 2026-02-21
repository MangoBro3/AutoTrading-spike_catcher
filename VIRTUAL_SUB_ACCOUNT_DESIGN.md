# Virtual Sub-Account 기능 설계서

## 0. 목적
실제 업비트/빗썸은 **단일 실계좌**를 사용하되, 전략별로 `capital_cap_krw`(전용 운용금)만 사용하도록 제한하고,
성과(PnL/MDD)도 **가상 원장(virtual ledger)** 기준으로 독립 추적한다.

---

## 1. 핵심 개념

- **실계좌(Real Account):** 거래소의 실제 KRW/코인 잔고.
- **가상 서브계좌(Virtual Sub-Account):** 전략 전용 내부 원장.
- **전용 운용금(`capital_cap_krw`):** 전략이 사용할 수 있는 최대 KRW 한도.
- **가상 순자산(`virtual_equity_krw`):**
  - `virtual_equity_krw = starting_capital_krw + cumulative_realized_pnl_krw + unrealized_pnl_krw - cumulative_fees_krw`
- **주문 가능금액(`available_to_trade_krw`):**
  - `min(capital_cap_krw, virtual_equity_krw) - reserved_margin_krw - open_order_hold_krw`

---

## 2. 동작 원칙

1. **진입 제한:** 새 주문 전 `available_to_trade_krw >= required_notional_krw` 검증.
2. **실계좌 보호:** 실제 주문은 실계좌에서 나가지만, 내부에서는 가상 원장에만 배정/차감.
3. **PnL 귀속:** 체결로 발생한 손익/수수료는 해당 전략의 virtual ledger에만 반영.
4. **초과 방지:** 실계좌 잔고가 충분해도 `capital_cap_krw`를 초과하는 주문은 거부.
5. **리스크 우선:** 손실/드로우다운 한도 위반 시 신규 진입 차단.

---

## 3. 데이터 모델 (최소)

### 3.1 `strategy_virtual_account`
- `id` (PK)
- `strategy_id` (UNIQUE)
- `exchange` (`upbit`|`bithumb`)
- `quote_currency` (`KRW`)
- `starting_capital_krw` (BIGINT)
- `capital_cap_krw` (BIGINT)
- `cumulative_realized_pnl_krw` (BIGINT, default 0)
- `cumulative_fees_krw` (BIGINT, default 0)
- `high_watermark_krw` (BIGINT)
- `current_mdd_pct` (DECIMAL(6,3), default 0)
- `status` (`ACTIVE`|`HALTED`|`ARCHIVED`)
- `created_at`, `updated_at`

### 3.2 `virtual_ledger_entry`
- `id` (PK)
- `virtual_account_id` (FK)
- `ts`
- `entry_type` (`DEPOSIT`|`WITHDRAW`|`REALIZED_PNL`|`UNREALIZED_MARK`|`FEE`|`ADJUSTMENT`)
- `amount_krw` (signed BIGINT)
- `ref_type` (`ORDER`|`TRADE`|`SYSTEM`|`MANUAL`)
- `ref_id` (nullable)
- `memo`

### 3.3 `risk_limit_profile`
- `virtual_account_id` (FK)
- `daily_loss_limit_pct` (예: 3.0)
- `max_mdd_limit_pct` (예: 10.0)
- `max_trades_per_day` (예: 120)
- `max_position_notional_pct` (예: 30.0)
- `max_symbol_exposure_pct` (예: 40.0)

### 3.4 `daily_virtual_snapshot`
- `virtual_account_id` (FK)
- `date_kst` (PK 일부)
- `start_equity_krw`
- `end_equity_krw`
- `daily_realized_pnl_krw`
- `daily_unrealized_pnl_krw`
- `daily_pnl_pct`
- `daily_max_mdd_pct`
- `trades_count`

---

## 4. 계산식

## 4.1 기본
- `cumulative_pnl_krw = cumulative_realized_pnl_krw + unrealized_pnl_krw - cumulative_fees_krw`
- `virtual_equity_krw = starting_capital_krw + cumulative_pnl_krw`
- `roi_pct = (virtual_equity_krw - starting_capital_krw) / starting_capital_krw * 100`

### 4.2 MDD
- `high_watermark_krw = max(previous_high_watermark_krw, virtual_equity_krw)`
- `drawdown_pct = (high_watermark_krw - virtual_equity_krw) / high_watermark_krw * 100`
- `current_mdd_pct = max(previous_current_mdd_pct, drawdown_pct)`

### 4.3 일일 PnL
- `daily_pnl_krw = end_equity_krw - start_equity_krw`
- `daily_pnl_pct = daily_pnl_krw / start_equity_krw * 100`

> 요구 핵심 반영: **시작원금 + 누적PnL** 구조를 기준 원장으로 사용.

---

## 5. 리스크 한도 / 가드

### 하드 가드(자동 차단)
1. `daily_pnl_pct <= -daily_loss_limit_pct` → `HALT_NEW_ENTRY`
2. `current_mdd_pct >= max_mdd_limit_pct` → `STRATEGY_HALT`
3. `trades_today > max_trades_per_day` → 당일 신규진입 금지
4. `new_position_notional > max_position_notional_pct * virtual_equity_krw` → 주문 거부

### 소프트 가드(경고)
- 경고 임계치(예: 하드가드의 70~80%) 도달 시 운영자 알림

---

## 6. 주문/정산 플로우

1. 시그널 발생
2. Pre-trade check
   - 계정상태 ACTIVE
   - `available_to_trade_krw` 검증
   - 리스크 한도 검증
3. 실거래소 주문 전송
4. 체결 수신
   - `virtual_ledger_entry`에 REALIZED_PNL/FEE 반영
   - 포지션 평가손익 업데이트(UNREALIZED_MARK)
5. 스냅샷/알림
   - 임계치 체크 → WARN/CRITICAL 발송

---

## 7. UI 스키마 (화면 요소)

### 7.1 전략 상세 > Virtual Account 카드
- Starting Capital (KRW)
- Capital Cap (KRW)
- Virtual Equity (KRW)
- Available to Trade (KRW)
- Daily PnL (%/KRW)
- Current MDD (%)
- Status (ACTIVE/HALTED)

### 7.2 설정 모달
- `capital_cap_krw` 입력
- 리스크 한도 입력 (`daily_loss_limit_pct`, `max_mdd_limit_pct`, `max_trades_per_day`)
- 저장 시 즉시 검증(음수/0/비정상 퍼센트 차단)

### 7.3 원장 탭
- 일자/타입/금액/참조주문/메모 필터
- CSV 내보내기

---

## 8. API 스키마 (제안)

### 8.1 조회
- `GET /api/v1/strategies/{strategy_id}/virtual-account`
```json
{
  "strategy_id": "strat_001",
  "exchange": "upbit",
  "starting_capital_krw": 5000000,
  "capital_cap_krw": 3000000,
  "virtual_equity_krw": 3124500,
  "available_to_trade_krw": 1250000,
  "daily_pnl_pct": -0.82,
  "current_mdd_pct": 4.13,
  "status": "ACTIVE"
}
```

### 8.2 설정 변경
- `PATCH /api/v1/strategies/{strategy_id}/virtual-account`
```json
{
  "capital_cap_krw": 3500000,
  "risk_limit_profile": {
    "daily_loss_limit_pct": 3.0,
    "max_mdd_limit_pct": 10.0,
    "max_trades_per_day": 120,
    "max_position_notional_pct": 30.0,
    "max_symbol_exposure_pct": 40.0
  }
}
```

### 8.3 원장 이력
- `GET /api/v1/strategies/{strategy_id}/virtual-ledger?from=2026-02-01&to=2026-02-21&type=REALIZED_PNL`

### 8.4 운영 액션
- `POST /api/v1/strategies/{strategy_id}/halt`
- `POST /api/v1/strategies/{strategy_id}/resume` (권한/사유 필수)

---

## 9. 마이그레이션 최소안 (Low-Risk)

### Phase 1 (DB only)
- 신규 테이블 4개 생성:
  - `strategy_virtual_account`
  - `virtual_ledger_entry`
  - `risk_limit_profile`
  - `daily_virtual_snapshot`
- 기존 주문/체결 테이블 수정 없음

### Phase 2 (Read-path)
- 기존 체결 이벤트 소비 시, 병렬로 virtual ledger 적재(Shadow mode)
- UI는 읽기 전용으로 PnL/MDD 표시

### Phase 3 (Enforcement)
- 주문 전 Pre-trade check에 `capital_cap_krw` + 리스크 가드 적용
- 차단 이벤트 알림 활성화

### Rollback
- 플래그(`virtual_account_enforcement=false`)로 즉시 비활성화 가능
- 원장 적재는 계속 유지하여 데이터 유실 방지

---

## 10. 수용 기준 (Acceptance)
- 실계좌 잔고가 충분해도 `capital_cap_krw` 초과 주문이 100% 차단됨
- 전략별 PnL/MDD가 실계좌 총손익과 독립적으로 재현 가능
- 일일 스냅샷이 KST 기준으로 누락 없이 생성됨
- 경고/중지 알림이 임계치 조건에서 정확히 1회 이상 발생

---

## 11. 오픈 이슈
- 복수 전략이 동일 심볼 동시 매매 시 체결 귀속 규칙(FIFO vs tag-based)
- 수수료/슬리피지 배부 방식(정확배부 vs 비율배부)
- 입출금/수동거래 발생 시 원장 보정 운영정책

---

## 12. v1.1 추가 확정 사항

### 12.1 '어제의 트레이딩 리뷰' UI/데이터 스키마

#### UI (일자별 카드)
- 기준: KST `D-1`(어제) 일자 단위 카드
- 카드 필드:
  - 시작자금 (`start_equity_krw`)
  - 종료자금 (`end_equity_krw`)
  - 일일손익 (`daily_pnl_krw`, `daily_pnl_pct`)
  - 거래수 (`trades_count`)
  - 승률 (`win_rate_pct`)
  - 최대손실 (`max_loss_trade_krw`)
  - 코멘트 (`review_comment`)

#### 데이터 스키마 확장 (`daily_virtual_snapshot`)
- 기존 필드 유지 + 아래 필드 추가:
  - `win_trades_count` (INT, default 0)
  - `loss_trades_count` (INT, default 0)
  - `win_rate_pct` (DECIMAL(6,3), 계산/저장 가능)
  - `max_loss_trade_krw` (BIGINT, default 0)
  - `review_comment` (VARCHAR(500), nullable)

#### 계산 규칙
- `win_rate_pct = (win_trades_count / nullif(trades_count, 0)) * 100`
- 거래가 0건이면 `win_rate_pct = 0`
- `max_loss_trade_krw`는 해당 일자 체결 기준 최저(가장 음수) 거래손익의 절대값/음수표기 중 택1로 UI 정책 통일

### 12.2 전용 운용금 복리 규칙 (virtual_equity 기반)

#### 목적
일일 손익을 다음 주문 가능 운용금에 자동 반영하여, 전략 자금을 `virtual_equity` 기준으로 복리 운용한다.

#### 규칙 정의
1. **기준 자금:** 다음 주문 기준자금(`next_order_base_krw`)은 `virtual_equity_krw`를 사용
2. **상한 적용:** 실제 주문 가능금은 항상
   - `effective_order_cap_krw = min(capital_cap_krw, virtual_equity_krw)`
3. **자동 갱신 시점:** 체결/수수료 반영으로 `virtual_equity_krw` 변경 시 즉시 재계산
4. **주문 금액 산식:**
   - `order_notional_krw = strategy_risk_fraction * effective_order_cap_krw`
   - 이후 최소주문금액/호가단위/거래소 제약으로 라운딩
5. **손실 구간 축소:** 손실로 `virtual_equity_krw`가 감소하면 다음 주문자금도 동일 비율로 자동 축소
6. **이익 구간 확대:** 이익으로 `virtual_equity_krw`가 증가하면 다음 주문자금도 동일 비율로 자동 확대
7. **안전 바닥:** `virtual_equity_krw <= 0` 또는 리스크 하드가드 위반 시 신규진입 차단(`HALT_NEW_ENTRY`)

#### 구현 메모
- 기존 `available_to_trade_krw` 산식과 충돌 없이, 주문 직전 `effective_order_cap_krw`를 우선 계산
- UI에는 "현재 복리 기준자금"(= `effective_order_cap_krw`)을 노출하여 운영자가 즉시 확인 가능하게 함

버전: v1.1
