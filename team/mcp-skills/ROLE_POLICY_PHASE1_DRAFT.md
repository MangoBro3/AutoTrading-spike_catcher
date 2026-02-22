# ROLE_POLICY_PHASE1_DRAFT.md

- version: v0.1-draft
- phase: Phase 1 (저위험/무중단)
- scope: pm, tl, architect, coder_a, coder_b (+ optional: main, mango)
- principle: 최소권한(Least Privilege), 기본 deny, 업무필수 allow만 개방

## 1) 공통 정책 (Global)

### Allow (공통)
- read-only 작업: 파일/문서 조회, 상태 조회, 로그 조회(민감정보 마스킹 전제)
- 보고/증빙 산출물 작성: `team/mcp-skills/`, `results/`, `evidence/` 하위 문서

### Deny (공통)
- main 직접 push/force-push
- 비승인 외부 전송(메시지/웹훅/이메일 등)
- 비인가 시스템 설정 변경(운영 OS/네트워크/시크릿)
- destructive command(`rm -rf`, 데이터 영구삭제) 기본 금지

---

## 2) 역할별 Phase 1 권한 초안

## PM
- 핵심작업: 백로그/우선순위, 수용기준, 리스크 커뮤니케이션
- MCP Allow:
  - `github` (read-only: 이슈/PR 조회)
- Skills Allow:
  - `read_issues`
  - `read_pull_requests`
- Deny:
  - PR 승인/머지
  - 코드 수정/푸시
  - 외부 알림 전송(Phase 2 전까지)
- 적용 난이도: 낮음

## TL
- 핵심작업: 태스크 분해, 리뷰 기준, Go/No-Go
- MCP Allow:
  - `github` (review scope)
- Skills Allow:
  - `read_issues`
  - `review_pr`
  - `approve_pr` (조건부)
- Deny:
  - 코드 직접 push
  - main 직접 변경
- 적용 난이도: 낮음

## Architect
- 핵심작업: ADR, 인터페이스 계약, 구조 기준
- MCP Allow:
  - `file_system` (read/write 제한)
  - `github` (read-only)
- Skills Allow:
  - `read_files` (repo 전체 읽기)
  - `write_files` (허용 경로 한정)
- Write Allow Path:
  - `docs/**`
  - `adr/**`
  - `team/mcp-skills/**`
- Deny:
  - `src/**` 코드 수정
  - 실행 커맨드/배포 커맨드
- 적용 난이도: 중간

## Coder_A
- 핵심작업: 기능 구현, 단위테스트, 리팩터링
- MCP Allow:
  - `file_system` (코드 영역)
  - `command` (제한)
- Skills Allow:
  - `read_files`
  - `edit_files`
  - `run_test`
  - `run_lint`
- Write Allow Path:
  - `src/**`, `tests/**`, 설정파일 일부
- Command Allow:
  - `pytest`, `ruff`, `flake8`, `python -m ...` (검증 중심)
- Deny:
  - 운영 인프라 변경 명령
  - 배포/프로덕션 파괴성 명령
- 적용 난이도: 중간

## Coder_B
- 핵심작업: 통합검증, 충돌해결, 코드-문서 동기화
- MCP Allow:
  - `file_system`
  - `command` (통합검증 범위)
- Skills Allow (Phase 1):
  - `read_files`
  - `edit_files`
- Skills Reserve (Phase 2):
  - `run_integration_test`
- Deny:
  - main 직접 배포/직접 푸시
  - 외부 시스템 설정 변경
- 적용 난이도: 중간

## (Optional) main
- 역할: 운영 채널 응대/요약
- Phase 1 Allow:
  - read-only status/report
- Phase 1 Deny:
  - 코드 수정/승인/배포

## (Optional) mango
- 역할: 오너 세션 운영 확인/의사결정
- Phase 1 Allow:
  - 결과 조회/승인
- Phase 1 Deny:
  - 자동 실행권한 위임(명시 승인 전)

---

## 3) 적용 템플릿 (초안)

각 에이전트 정책은 아래 형식으로 등록:

```yaml
agent: <pm|tl|architect|coder_a|coder_b>
phase: phase1
default: deny
allow:
  mcp: [ ... ]
  skills: [ ... ]
  paths: [ ... ]
  commands: [ ... ]
deny:
  mcp: [ ... ]
  skills: [ ... ]
  paths: [ ... ]
  commands: [ ... ]
notes:
  - rationale: 업무필수 최소권한
  - rollback: phase1 이전 정책으로 즉시 복귀
```

## 4) 검증 체크 (Phase 1)
- [ ] pm이 이슈/PR 조회는 가능하고, 리뷰/코드수정은 불가
- [ ] tl이 리뷰/승인은 가능하고, push는 불가
- [ ] architect가 docs/adr만 수정 가능하고 src 수정 불가
- [ ] coder_a가 src/tests 수정 + test/lint 실행 가능
- [ ] coder_b가 통합 전 단계 수정 가능, integration 실행은 Phase 2까지 보류
- [ ] main 보호 규칙(직접 push 차단/PR 기반)과 정책 충돌 없음

## 5) 롤백
- 정책 충돌/과권한 발견 시: 해당 에이전트 `default: deny`로 즉시 전환
- 마지막 정상 정책 스냅샷으로 복원
- 복원 후 최소 1회 재검증 수행
