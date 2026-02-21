# COCKPIT_SPEC_v1.2

- 버전: v1.2 (LOCKED)
- 상태: **고정 사양(변경 금지, 명시적 개정 없이는 수정 불가)**
- 적용 경로(절대): `/mnt/f/SafeBot/openclaw-news-workspace/python`
- 문서 위치: `Auto Trading/ui/COCKPIT_SPEC_v1.2.md`

---

## 1) 목적
본 문서는 **Cockpit UI 사양 v1.2**를 단일 기준 문서(SSOT)로 고정한다.
또한 UI/기능 구조에서 **"완전 분리" 원칙**을 강제하고, 과거 **Agent Dashboard 잔재 요소를 금지 항목**으로 명시한다.

---

## 2) 범위
- 대상: Auto Trading 프로젝트의 Cockpit 화면 및 연관 UI 컴포넌트
- 비대상: Agent Dashboard 계열 화면/컴포넌트/네이밍/상태모델

---

## 3) Spec Lock (고정 규칙)
1. 본 문서는 Cockpit UI의 유일한 기준 문서다.
2. 명시적 버전 상향(v1.3 이상) 없이 내용 변경 금지.
3. 구현/리팩토링/디자인 조정 시 본 문서와 불일치하면 **구현이 잘못된 것**으로 간주.
4. 예외가 필요하면 별도 개정안 문서 작성 후 버전업으로만 반영.

---

## 4) Cockpit UI v1.2 핵심 정의

### 4.1 화면 정체성
- Cockpit은 **트레이딩 운영 콘솔**이다.
- 목적: 시장/전략/주문/리스크 상태를 **즉시 판단 가능한 형태**로 제공.
- 대시보드형 나열보다, 운영 의사결정 우선의 배치/시각화 사용.

### 4.2 필수 정보 영역
- Market Snapshot: 심볼/가격/변동/거래량 등 실시간 요약
- Strategy Status: 전략 상태(ON/OFF/PAUSE), 시그널, 최근 실행 결과
- Position & Orders: 포지션, 미체결, 체결 이력 핵심 지표
- Risk Guard: 손실 한도, 익스포저, 긴급 정지 상태
- System Health: 데이터 피드 지연, API 상태, 에러 알림

### 4.3 인터랙션 원칙
- 고위험 액션(매수/매도/전략 중지/긴급정지)은 명확한 확인 단계 필요
- 경고/오류는 색상+텍스트+아이콘으로 중복 표현(접근성/가독성)
- 실시간 갱신은 사용성 저해 없는 범위에서 안정적으로 반영

---

## 5) "완전 분리" 조항 (강제)
Cockpit UI는 Agent Dashboard와 **완전히 분리**되어야 한다.

### 5.1 분리 대상
- 화면 구조(Layout)
- UI 컴포넌트 계층
- 상태 저장소(State)
- 라우팅 경로(Route)
- 스타일 토큰/테마 의존성
- 데이터 어댑터 및 ViewModel

### 5.2 분리 기준
- Cockpit 코드에서 Agent Dashboard 모듈 import 금지
- 공용 컴포넌트는 중립 네이밍만 허용(Agent 전용 네임스페이스 금지)
- 라우팅/메뉴/브레드크럼 상호 참조 금지
- 상태(store/context) 공유 금지
- 기능 플래그로 임시 연결하는 방식 금지

### 5.3 운영 기준
- Cockpit 관련 이슈/작업은 Cockpit 스코프로만 처리
- Agent Dashboard 이슈를 Cockpit에서 우회 해결 금지

---

## 6) 금지 항목 (Agent Dashboard 잔재)
아래 항목은 Cockpit UI v1.2에서 **명시적으로 금지**한다.

1. `AgentDashboard*` 접두/접미 컴포넌트 재사용
2. `legacy-panel`, `agent_panel` 등 레거시 route/path 유지
3. Agent 전용 store/context를 Cockpit에서 직접 구독
4. "Agent", "Assistant", "Worker" 중심 메뉴/카드/위젯 노출
5. Dashboard 전용 KPI 카드 레이아웃 복제
6. Agent Dashboard용 CSS class/token 네이밍 재사용
7. Dashboard 잔재 문구(예: Agent Status, Worker Queue) 노출
8. Cockpit 화면에서 Agent 작업 제어 버튼 제공
9. Dashboard API 응답 스키마에 직접 결합된 UI 바인딩
10. 마이그레이션 명목의 임시 브릿지 코드 상시화

---

## 7) 검증 체크리스트 (릴리즈 전)
- [ ] Cockpit 소스에 Agent Dashboard import가 없는가?
- [ ] 라우트 트리에 Dashboard 경로 참조가 없는가?
- [ ] 상태관리 계층(store/context) 공유가 없는가?
- [ ] UI 문구/아이콘/레이아웃에 Dashboard 잔재가 없는가?
- [ ] 고위험 액션 확인 플로우가 동작하는가?
- [ ] Risk/System 경고가 명확히 표시되는가?

---

## 8) 변경 절차
- 본 문서 변경은 버전업 기반(`v1.2 -> v1.3`)으로만 허용
- 변경 시 반드시 아래를 함께 기록:
  - 변경 배경
  - 영향 범위
  - 마이그레이션 계획
  - 롤백 기준

---

## 9) 부칙
- 본 문서가 다른 산출물과 충돌할 경우, 본 문서를 우선한다.
- 본 문서는 작성 시점부터 즉시 효력을 가진다.
