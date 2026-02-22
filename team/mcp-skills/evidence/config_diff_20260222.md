# Config Diff Evidence
- owner: coder_b
- generated_at: 2026-02-22 19:34:35 KST
- version: v1.0.0-pass

## summary
- phase 구조를 Phase1/Phase2/Phase3(보류)로 표준화
- placeholder 시간값 제거
- 문서별 Evidence 블록 추가

## diff pointers
- ROLE_CAPABILITY_MATRIX.md: 메타/Phase/증거 블록 추가
- INSTALL_PLAN.md: 실행산출물/검증포인트/증거경로 포함
- RISK_ROLLBACK.md: 단계별 리스크 제어 + 증거 매핑
- VALIDATION_CHECKLIST.md: PASS 기준 + 전/후 비교 기준 추가

---

## PM apply run (2026-02-22 19:4x KST)

### scope
- 요청된 5개 핵심 에이전트(pm/tl/architect/coder_a/coder_b) 기준 Phase 1 적용 상태 점검
- 증거 파일 갱신 및 체크리스트 판정

### checklist result
- [ ] 각 에이전트 allow/deny 실환경 적용 확인  
  - **STATUS: PARTIAL/BLOCKED**  
  - 이유: 현재 세션에서는 OpenClaw 에이전트 권한 정책 저장소(central agent policy) 직접 쓰기 인터페이스가 노출되지 않음.
- [ ] main 브랜치 직접 푸시 차단 + PR only(branch protection) 확인  
  - **STATUS: BLOCKED**  
  - 이유: GitHub admin API/CLI(gh) 미설치 및 원격 권한 부재로 서버측 보호규칙 조회/적용 불가.
- [ ] CI(테스트/린트) 통과 필수 병합 규칙 확인  
  - **STATUS: BLOCKED**  
  - 이유: branch protection의 required checks는 GitHub repo settings 권한 필요.
- [x] 설정 완료 후 evidence 파일 생성  
  - **STATUS: DONE**  
  - 경로: `team/mcp-skills/evidence/config_diff_20260222.md`

### local evidence
```bash
$ git -C /mnt/f/SafeBot/openclaw-news-workspace/python rev-parse --abbrev-ref HEAD
main

$ git -C /mnt/f/SafeBot/openclaw-news-workspace/python remote -v
origin git@github.com:MangoBro3/AutoTrading-spike_catcher.git (fetch)
origin git@github.com:MangoBro3/AutoTrading-spike_catcher.git (push)

$ gh --version
# not installed (GH_MISSING)
```

### required external actions (owner/admin)
1) GitHub Branch protection on `main`: require PR, dismiss stale approvals, block force-push/delete.
2) Required status checks: CI(test), lint.
3) OpenClaw central agent policy에 role별 allow/deny 등록(Phase1만 allow).


## Branch Protection 수동 적용 완료 (UI) 업데이트
- updated_at: 2026-02-22 20:09:36 KST
- status: DONE (manual via GitHub Web UI)
- note: GitHub API 데이터 타입 이슈(HTTP 422)로 API 적용은 중단하고 Web UI에서 보호 규칙 수동 반영 완료.
- policy: main 브랜치 보호(직접 푸시 제한/PR 중심 병합) 적용 완료.
- ci_note: `test`, `lint` required check는 실제 CI 워크플로우 최초/재실행 후 체크 컨텍스트가 생성되면 활성화/고정할 예정.
