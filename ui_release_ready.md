# UI Release Ready Note (Core)
- 작성일: 2026-02-19 15:59 KST
- 기준 경로: `/mnt/f/SafeBot/openclaw-news-workspace/python`
- 범위: UI Core 1페이지 요약 (완료 기능/검증/제한/다음 스프린트)

## 1) 완료 기능 (UI Core)
1. **UI 산출물 경로/기본 자산 확인 완료**
   - 정적 화면 자산 확인: `Auto Trading/ui/public/index.html`
   - 스캔 근거 로그:
     - `results/ui_sprint1_pmo/01_ui_artifact_scan.log`
     - `results/ui_sprint1_pmo/02_ui_dir_scan.log`
2. **UI 증적 수집 체계 구축 완료**
   - 스냅샷 스크립트 작성/운영: `results/ui_sprint1_pmo/ui_dod_snapshot.sh`
   - 누적 로그: `results/ui_sprint1_pmo/ui_dod_snapshot.log`
3. **UI DoD 추적판 운영 시작**
   - 상태판: `UI_DOD_TRACKER.md`
   - 완료/진행/막힘 항목을 증거 경로 기반으로 관리 가능

## 2) 검증 커맨드 (재현용)
```bash
# 1) UI 자산 존재 확인
ls -l 'Auto Trading/ui/public/index.html'

# 2) UI 관련 산출물 스캔(근거 로그 재생성)
find . -maxdepth 4 -iname '*ui*' > results/ui_sprint1_pmo/01_ui_artifact_scan.log
find tools -maxdepth 4 -type d > results/ui_sprint1_pmo/02_ui_dir_scan.log

# 3) UI DoD 스냅샷 1회 갱신
bash results/ui_sprint1_pmo/ui_dod_snapshot.sh

# 4) UI 테스트 수집 현황 확인(현재 기준)
.venv/bin/python -m pytest -q -k ui --collect-only | tee results/ui_sprint1_pmo/03_ui_pytest_collect.log
```

## 3) 알려진 제한 (Known Limitations)
1. **UI 전용 자동화 테스트 부재**
   - `pytest -k ui` 기준 실질 실행 테스트가 부족(수집 중심)
2. **실행 화면 증적(스크린샷/동영상) 미흡**
   - 정적 파일 존재 증거는 있으나, 브라우저 렌더링 E2E 증거가 부족
3. **백엔드 의존 연동 검증 미완료**
   - UI 단위 기준 산출물/경로 검증은 완료했으나 API 연계 플로우 증빙은 다음 단계 필요

## 4) 다음 스프린트 항목 (UI Sprint2 제안)
1. **Playwright 기반 스크린샷 자동화 도입**
   - 목표: 핵심 화면 3~5개 자동 캡처 + 아티팩트 저장
2. **UI E2E 최소 시나리오 3종 구현**
   - 예: 상태 조회, 실행 시작 요청, 실행 중지/오류 표시
3. **UI-Backend 계약 스키마 고정 반영**
   - Start/Confirm/Stop 응답 필드 동결 후 UI 표시값 매핑
4. **릴리즈 증적 표준화**
   - `results/ui_sprint2/` 하위에 테스트 로그/스크린샷/요약 리포트 자동 생성

---
### 결론
- **UI Core는 ‘자산/증적 체계 준비’ 관점에서 Release Ready(초기) 상태**.
- 다만 **자동화 E2E 테스트와 실행 화면 증적 확보**가 정식 릴리즈(운영 배포) 전 필수 게이트이다.
