# ROLE_CAPABILITY_MATRIX

- 작성시각: 2026-02-22 19:34:35 KST
- 문서버전: v1.0.0-pass
- 상태: PASS
- 책임자: coder_b
- 범위: `pm`, `tl`, `architect`, `coder_a`, `coder_b` (옵션: `main`, `mango`)

## 1) 우선순위 Top 5 (공통)
1. 요구사항/결정 로그 표준화
2. 아키텍처 의사결정(ADR) + 인터페이스 계약 고정
3. 코드 품질 게이트 자동화(테스트/린트/타입체크)
4. 릴리즈 전 검증 체크리스트 운영
5. 권한분리(읽기/쓰기/배포 분리) + 감사로그 확보

## 2) 역할별 Capability 매트릭스 (요약)

> 난이도: L(낮음) / M(중간) / H(높음)

- **pm (M)**: 백로그/우선순위/수용기준/리스크 커뮤니케이션, 읽기 중심 권한
- **tl (M)**: 태스크 분해/리뷰 기준/Go-NoGo 판단, 리뷰 승인 권한(조건부)
- **architect (H)**: ADR/계약/구조 기준 수립, 설계 문서 중심 권한
- **coder_a (M)**: 구현/단위테스트/리팩터링, 기능 브랜치 수정 + 테스트 권한
- **coder_b (M)**: 통합테스트/문서 동기화/충돌관리, 기능 브랜치 수정 + 통합 검증 권한
- **(옵션) main (H)**: 오케스트레이션/최종 승인, 직접 구현·운영변경 금지
- **(옵션) mango (L~M)**: 운영 보조/요약/알림 집계, 조회·요약 중심 권한

## 3) 표준 Phase 구조 (문서 공통)

### Phase 1 (저위험 3개)
1. 역할별 최소권한 템플릿 적용(기본 deny)
2. P1 Skills만 활성화(문서/이슈/테스트/린트 보조)
3. PR 보호 규칙 강제(main direct push 금지, 리뷰+CI 필수)

- 실행 산출물: 권한 프로파일 초안, P1 활성 목록, 브랜치 보호 설정표
- 검증 포인트: 권한위반 0건, 신규 PR 100% 보호규칙 경유
- 증거 경로: `./evidence/config_diff_20260222.md`, `./evidence/install_execution_log_20260222.log`

### Phase 2 (중위험 4개)
1. P2 Skills 단계 활성화(트렌드/리포팅/통합테스트 보강)
2. 실패 대응 루프 적용(권한거부/게이트 실패 케이스)
3. 주간 리스크 리뷰(오남용 징후 점검)
4. 역할 KPI 베이스라인 고정

- 실행 산출물: P2 활성 매트릭스, 실패대응 기록, KPI 베이스라인 표
- 검증 포인트: 리드타임·실패율 측정 가능, 실패케이스 재현/복구 확인
- 증거 경로: `./evidence/validation_before_after_20260222.md`, `./evidence/install_execution_log_20260222.log`

### Phase 3 (보류)
- 보류 조건: 2주 이상 안정 운영 데이터 축적 전까지 자동화 고도화(P3) 미적용
- 재개 조건: 품질게이트 안정 + 오남용 탐지 임계치 검증 완료

- 실행 산출물(재개 시): P3 파일럿 범위 문서, 중단조건 문서
- 검증 포인트: Human-in-the-loop 준수, 임계치 초과 알림 동작
- 증거 경로: `./evidence/artifact_manifest_20260222.md`

## 4) Evidence 블록
- 설정 diff: `./evidence/config_diff_20260222.md`
- 설치/실행 로그: `./evidence/install_execution_log_20260222.log`
- 검증 전/후 비교: `./evidence/validation_before_after_20260222.md`
- 산출물 경로/책임자/시각/버전: `./evidence/artifact_manifest_20260222.md`
