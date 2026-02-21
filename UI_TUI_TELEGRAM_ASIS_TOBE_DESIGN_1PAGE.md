# 구현 설계서 1장 (AS-IS / TO-BE 매핑)
- 대상 경로: `/mnt/f/SafeBot/openclaw-news-workspace/python`
- 범위: **Web UI Zone1~4**, **TUI 로깅/ANSI/포맷**, **Telegram debounce + rich snapshot 템플릿**
- 우선순위: **운영 신뢰성 > 기능 추가** (canonical truth 단일 소스, 모드 표시 일관, 알림 중복 방지)

---

## 0) 핵심 원칙 (Reliability First)
1. **Canonical Truth 단일 소스**
   - 상태판단 기준은 `GET /api/v1/status`(+lock)에서 정규화한 `truth`만 사용.
   - UI/TUI/Telegram은 모두 `truth(mode, phase, running, lock_exists, reason_code)` 기반으로 렌더.
2. **Mode 표시 일관성**
   - 표시 우선순위 고정: `truth.mode > status.mode > controller_mode`.
   - `LIVE/PAPER` 외 문자열은 강제 정규화(UNKNOWN 금지).
3. **중복 알림 방지 상태키**
   - 알림 dedupe 키를 이벤트 문자열이 아닌 **상태키(state key)**로 통일.
   - 예: `mode:{MODE}|phase:{PHASE}|reason:{REASON}|exchange:{EX}`

---

## 1) AS-IS / TO-BE 매핑

### A. Web UI Zone 1~4
| Zone | AS-IS | TO-BE |
|---|---|---|
| Zone1 (상단 Truth/KPI) | `ui/public/index.html` + `ui/server.mjs`에서 truth/모드 계산 중복 존재 | **truth selector 공통화**(단일 함수), stale runtimeStatus는 보조정보로만 표기 |
| Zone2 (모드/ONOFF/거래소 토글) | 버튼 이벤트별 분기 구현, 실패 시 에러 표기만 통일 부족 | 모드 전환/confirm/stop를 **state machine 기반 UI 액션 핸들러**로 통합 |
| Zone3 (모니터링/리뷰/그래프) | fallback 소스 다중, 소스 우선순위가 코드 분산 | `overview`에서 source priority 명시 후 UI는 렌더 전용으로 단순화 |
| Zone4 (위험 액션: panic/order cancel/manual roundtrip) | 개별 API 호출/응답 포맷 상이 | 위험 액션 공통 응답 envelope(`ok, action, truth_after, audit_id`)로 표준화 |

**수용기준(검증 포인트)**
- `/api/overview` 응답에 `truth` 필드 항상 존재 + 유효값(`LIVE|PAPER`, `RUNNING|STOPPED|WAITING_*`).
- UI 상단 Truth badge와 Mode 버튼 상태가 100회 폴링에서도 불일치 0건.
- Zone4 액션( panic/stop/cancel ) 수행 후 2초 내 truth 반영(관측 실패율 <1%).

**파일별 변경 계획**
- `Auto Trading/ui/server.mjs`
  - `normalizeTruth/deriveModeInfo`를 **단일 canonical selector**로 정리.
  - `/api/overview` 응답에 `truth_version`, `truth_ts`, `truth_source` 추가.
- `Auto Trading/ui/public/index.html`
  - mode/truth 렌더 함수 통합(`resolveDisplayMode` + badge + control sync).
  - Zone별 렌더 진입점 분리(`renderZone1~4`)로 엮임 제거.
- (선택) `Auto Trading/ui/worker-monitor.mjs`
  - 스냅샷 필드 누락 시 canonical fallback 계약 강화.

---

### B. TUI 로깅 / ANSI / 포맷
| 항목 | AS-IS | TO-BE |
|---|---|---|
| ANSI clear | `fastapi_backend.py`, `launcher.py` 각각 독립 구현 | ANSI 처리 공통 유틸(tty 여부 + clear 정책)로 통일 |
| 상태 포맷 | TUI별 라인/라벨 표준 다름 | `truth` 기준 공통 헤더 템플릿(Mode/Phase/Lock/Traffic) 적용 |
| 로깅 일관성 | print/log 혼재 | `logger` 중심 + 사용자 표시 문자열 분리(표시/로그 이원화) |

**수용기준(검증 포인트)**
- TUI 2종(`--tui`, launcher) 모두 `TRUTH=...` 라인 동일 포맷 출력.
- TTY가 아닐 때 ANSI escape 출력 0건.
- 동일 상태에서 10분 구동 시 출력 흔들림(포맷 깨짐) 0건.

**파일별 변경 계획**
- `Auto Trading/fastapi_backend.py`
  - `BackendStatusTUI`에 formatter 주입(공통 템플릿 사용).
- `Auto Trading/launcher.py`
  - `\033[H\033[J` 직접 호출 제거, 공통 clear 함수 사용.
- `Auto Trading/modules/logger_utils.py` (확장)
  - `format_truth_line()`, `safe_clear_screen()` 추가.

---

### C. Telegram debounce + Rich Snapshot 템플릿
| 항목 | AS-IS | TO-BE |
|---|---|---|
| Debounce | `notifier_telegram` dedupe + `fastapi_backend` mode alert debounce 이원화 | **단일 debounce 상태키 저장소**로 통합 (`results/outbox/telegram_alert_state.json`) |
| 메시지 포맷 | title/message 자유형 | 운영용 **rich snapshot 템플릿** 고정 (mode/phase/lock/reason/equity/pnl/exchange) |
| 중복 방지 기준 | dedupe_key 호출자 책임 | 키 생성 책임을 notifier 내부로 이동(호출자는 event_type만 지정) |

**수용기준(검증 포인트)**
- 동일 상태 반복(예: LIVE RUNNING 유지) 60초 내 중복 알림 0건.
- 상태 변화(예: RUNNING→STOPPED)는 1회 즉시 알림.
- 알림 본문에 canonical truth + 핵심 수치 6개 필수 포함률 100%.

**파일별 변경 계획**
- `Auto Trading/modules/notifier_telegram.py`
  - `build_state_key(truth, context)` 추가.
  - debounce 저장소 로드/저장(`telegram_alert_state.json`) 추가.
  - `emit_rich_snapshot(truth, runtime)` 템플릿 메서드 추가.
- `Auto Trading/fastapi_backend.py`
  - `_build_mode_alert/_maybe_emit_mode_alert`를 notifier 공용 API 호출로 변경.
- `Auto Trading/web_backend.py` (필요 시)
  - panic/critical 알림도 동일 state key 체계로 이관.

---

## 2) 검증 시나리오 (최소)
1. **Mode consistency**: PAPER→LIVE(승인)→STOP 3단계 수행, UI/TUI/Telegram 모두 truth 일치.
2. **Debounce**: 동일 phase 유지 5분 동안 알림 1회만 발송.
3. **Duplicate guard**: 프로세스 재시작 후 같은 상태 재감지 시 중복 알림 미발송.
4. **Panic path**: panic 실행 시 `truth.reason_code` 반영 + CRITICAL snapshot 1회 발송.

---

## 3) 롤아웃 순서
1) server.mjs + index.html (canonical truth 일원화)  
2) fastapi_backend/launcher TUI 포맷 통일  
3) notifier debounce/state-key 통합  
4) 운영 리허설(실제/모의 각각 1회) 후 기본값 활성화
