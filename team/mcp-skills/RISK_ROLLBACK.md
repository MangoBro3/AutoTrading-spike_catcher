# RISK_ROLLBACK

- 작성시각: 2026-02-22 19:34:35 KST
- 문서버전: v1.0.0-pass
- 상태: PASS
- 책임자: coder_b

## 리스크 원칙
사전 차단(Prevent) + 조기 탐지(Detect) + 즉시 복구(Rollback)

## 표준 Phase 구조

### Phase 1 (저위험 3개)
1. 과도 권한 부여 차단(기본 deny/최소 allow)
2. 품질게이트 우회 차단(CI/리뷰 강제)
3. 문서-코드 불일치 차단(PR 템플릿 동기화 필수)

- 실행 산출물: 권한 제한표, 게이트 강제 설정, 문서동기화 체크 항목
- 검증 포인트: 권한위반/우회 시도 탐지 여부, 차단 로그 존재
- 증거 경로: `./evidence/config_diff_20260222.md`, `./evidence/install_execution_log_20260222.log`

### Phase 2 (중위험 4개)
1. 자동화 오남용 탐지 임계치 적용(파일수/라인수)
2. 역할 충돌 탐지(리드타임/대기시간 지표)
3. 롤백 레벨(Level 0~3) 실행 절차 리허설
4. 승인 체계 고정(Level별 승인자)

- 실행 산출물: 임계치 설정표, 역할 충돌 리포트, 롤백 리허설 기록
- 검증 포인트: 임계치 초과 알림 발동, Level별 승인/복구 재현
- 증거 경로: `./evidence/validation_before_after_20260222.md`, `./evidence/install_execution_log_20260222.log`

### Phase 3 (보류)
- 보류 범위: P3 자동화 전면 확장
- 재개 조건: 롤백 드릴 통과 + 24시간 무사고 + 체크리스트 재통과

- 실행 산출물(재개 시): P3 확장 승인서, 중단/복귀 트리거 표
- 검증 포인트: 전역 중단 후 P1 최소운영 복귀 가능
- 증거 경로: `./evidence/artifact_manifest_20260222.md`

## 롤백 레벨
- Level 0: 개별 Skill 비활성화
- Level 1: 특정 역할 write/execute 회수(read-only)
- Level 2: PR 병합 일시 중지 + 핫픽스 전환
- Level 3: P2/P3 중단 + P1 최소운영 복귀

## Evidence 블록
- 설정 diff: `./evidence/config_diff_20260222.md`
- 설치/실행 로그: `./evidence/install_execution_log_20260222.log`
- 검증 전/후 비교: `./evidence/validation_before_after_20260222.md`
- 산출물 경로/책임자/시각/버전: `./evidence/artifact_manifest_20260222.md`
