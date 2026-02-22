# INSTALL_PLAN

- 작성시각: 2026-02-22 19:34:35 KST
- 문서버전: v1.0.0-pass
- 상태: PASS
- 책임자: coder_b

## 목적
역할 기반 MCP/Skills를 신규 인프라 없이 현재 저장소/CI/문서 체계에서 즉시 적용하고, 검증 가능한 증거를 남긴다.

## 표준 Phase 구조

### Phase 1 (저위험 3개)
1. 최소권한 프로파일 적용(allow/deny 고정)
2. P1 Skills 활성화(문서/이슈/테스트/린트)
3. PR 품질게이트 강제(리뷰 1+, 테스트/린트/타입체크)

- 실행 산출물: 권한 정책 파일, P1 활성 설정, PR 규칙 스냅샷
- 검증 포인트: main 직접 푸시 0건, 신규 PR 게이트 통과율 확인
- 증거 경로: `./evidence/config_diff_20260222.md`, `./evidence/install_execution_log_20260222.log`

### Phase 2 (중위험 4개)
1. P2 Skills 점진 활성화(리포팅/통합테스트 보강)
2. 실패 케이스 대응 루프 운영(우회/권한거부/검증실패)
3. ADR/결정로그 표준 적용률 100% 확보
4. 주간 리스크 리뷰 정례화

- 실행 산출물: P2 적용 목록, 실패 대응 이력, ADR 준수 리포트
- 검증 포인트: 실패 케이스 복구 가능성, 문서-코드 정합성
- 증거 경로: `./evidence/validation_before_after_20260222.md`, `./evidence/install_execution_log_20260222.log`

### Phase 3 (보류)
- 보류 정책: P3(영향분석/자동수정/고도화 자동화)는 안정성 데이터 확보 전 보류
- 재개 조건: 2주 이상 무중대사고 + 품질지표 개선 + 롤백 드릴 통과

- 실행 산출물(재개 시): P3 파일럿 운영계획서, 중단조건 표준서
- 검증 포인트: 오남용 탐지 임계치 및 즉시 중단 경로
- 증거 경로: `./evidence/artifact_manifest_20260222.md`

## 즉시 적용 기본옵션
- 문서 템플릿(요구사항/ADR/릴리즈노트)
- CI 품질게이트(테스트/린트/타입체크)
- 브랜치 보호룰(main direct push 차단)
- 역할별 실행 규칙(read/write/execute 경계)

## Evidence 블록
- 설정 diff: `./evidence/config_diff_20260222.md`
- 설치/실행 로그: `./evidence/install_execution_log_20260222.log`
- 검증 전/후 비교: `./evidence/validation_before_after_20260222.md`
- 산출물 경로/책임자/시각/버전: `./evidence/artifact_manifest_20260222.md`
