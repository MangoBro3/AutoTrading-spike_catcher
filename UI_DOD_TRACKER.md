# UI Sprint1 PMO - DoD 추적판 (최종 판정 업데이트)
- 생성일: 2026-02-19 14:50 KST
- 기준 경로: `/mnt/f/SafeBot/openclaw-news-workspace/python`
- 목적: 항목별 `완료/진행/막힘` 상태 + 근거 커맨드/로그(또는 스크린샷) 경로 관리

## 최종 판정(2026-02-19 18:05)
- **결론: NOT_READY**
- **근거(증적 재판정):** E2E 조건(Playwright UI 렌더링 스크린샷 3장 + 로그) 미충족. 현재 `results/ui_sprint1_pmo` 내 PNG/JPG/JPEG 산출물은 0장이라 `NOT_READY` 유지.
- **근거 경로(4개):**
  1) `/mnt/f/SafeBot/openclaw-news-workspace/python/results/ui_sprint1_pmo/03_ui_pytest_collect.log`
  2) `/mnt/f/SafeBot/openclaw-news-workspace/python/results/ui_sprint1_pmo/04_ui_build_smoke.log`
  3) `/mnt/f/SafeBot/openclaw-news-workspace/python/results/ui_sprint1_pmo/ui_dod_snapshot.log`
  4) `/mnt/f/SafeBot/openclaw-news-workspace/python/results/ui_sprint1_pmo/07_e2e_screenshot_count.log`

## Build A/B 반영 + 테스트 근거

| 구분 | 상태 | 근거(명령/근거파일) | 증적 경로 |
|---|:---:|---|---|
| Build A: Worker API 연동(대시보드) | 완료 | Sprint1 API 연동 엔트리(`GET /health`, `/state`, `/orders`, `/api/worker`, `/api/worker/control/:action`) 확인 | `/mnt/f/SafeBot/openclaw-news-workspace/python/tools/agent-dashboard/README.md`
`/mnt/f/SafeBot/openclaw-news-workspace/python/tools/agent-dashboard/server.mjs`
`/mnt/f/SafeBot/openclaw-news-workspace/python/tools/agent-dashboard/worker-monitor.mjs` |
| Build B: UI Smoke(기능/엔드포인트 문자열 기반) | 완료 | `TestUIBuildBSmoke` 2건 모두 통과 | `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/test_ui_sprint1_smoke.py`
`/mnt/f/SafeBot/openclaw-news-workspace/python/results/ui_sprint1_pmo/04_ui_build_smoke.log` |
| Backend 스모크 | 완료 | `test_smoke.py` 3/3 통과 | `/mnt/f/SafeBot/openclaw-news-workspace/python/results/ui_sprint1_pmo/06_smoke_backend.log` |
| Worker-monitor 단위테스트 | 완료 | Node 테스트 5/5 통과 | `/mnt/f/SafeBot/openclaw-news-workspace/python/results/ui_sprint1_pmo/05_worker_monitor_unit.log` |

## 항목별 DoD

| 항목 | 상태 | 근거(명령/근거파일) | 근거 경로 |
|---|:---:|---|---|
| 1) UI 경로 탐색(기본 산출물 존재 확인) | 완료 | `find` 기반 스캔 로그 | `/mnt/f/SafeBot/openclaw-news-workspace/python/results/ui_sprint1_pmo/01_ui_artifact_scan.log`
`/mnt/f/SafeBot/openclaw-news-workspace/python/results/ui_sprint1_pmo/02_ui_dir_scan.log` |
| 2) UI 화면 정적 자산 존재 (`index.html`) | 완료 | `tools/agent-dashboard/public/index.html` 존재 확인 | `/mnt/f/SafeBot/openclaw-news-workspace/python/tools/agent-dashboard/public/index.html` |
| 3) UI 실행/동작 테스트(프레임워크 기준) | 진행 | 이전 `pytest -k ui` 수집 결과로 한계가 있었으나 Build B 스모크 추가 통과 | `/mnt/f/SafeBot/openclaw-news-workspace/python/results/ui_sprint1_pmo/03_ui_pytest_collect.log`
`/mnt/f/SafeBot/openclaw-news-workspace/python/results/ui_sprint1_pmo/04_ui_build_smoke.log` |
| 4) UI-Sprint 증적 저장 경로 정비 | 완료 | 증적 스냅샷 스크립트 작성/로그 누적
실행 예: `bash results/ui_sprint1_pmo/ui_dod_snapshot.sh` | `/mnt/f/SafeBot/openclaw-news-workspace/python/results/ui_sprint1_pmo/ui_dod_snapshot.sh`
`/mnt/f/SafeBot/openclaw-news-workspace/python/results/ui_sprint1_pmo/ui_dod_snapshot.log` |
| 5) 근거 커맨드 실시간 갱신 체계 | 완료 | 30초 주기 샘플 갱신 커맨드 제공 | `results/ui_sprint1_pmo/ui_dod_snapshot.sh` (수동/주기 실행) |

## 미완료(정확히 1건)
1) 브라우저 기반 UI 렌더링 증적(Playwright/스크린샷 기반 E2E) 미구현 → 실제 화면 상태 전환, 버튼/요청/표시 연동 검증 부재

## 실시간 갱신 지침
- 수동 갱신: 
  - `bash /mnt/f/SafeBot/openclaw-news-workspace/python/results/ui_sprint1_pmo/ui_dod_snapshot.sh`
- 반복 갱신(예시 30초):
  - `while true; do bash /mnt/f/SafeBot/openclaw-news-workspace/python/results/ui_sprint1_pmo/ui_dod_snapshot.sh; sleep 30; done`
- 최신 기록은 모두 `ui_dod_snapshot.log`에 누적됩니다.
