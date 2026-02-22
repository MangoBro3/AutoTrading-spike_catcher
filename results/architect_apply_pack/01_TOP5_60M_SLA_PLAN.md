# 산출물 1) Top5 우선순위 + 60분 SLA 실행안 (기본옵션)

기준: architect 초안 반영용 운영 실행안(실제 적용 가능한 기본 명령만 사용)
대상 경로: `/mnt/f/SafeBot/openclaw-news-workspace/python`

## Top5 우선순위 표

| 우선순위 | 항목 | 변경 위치(파일/설정키) | 적용 커맨드(기본옵션) | 검증 방법 | 롤백 방법 |
|---|---|---|---|---|---|
| P1 | 런타임 상태 기준선 고정 | `results/runtime_status.json` | `python -m json.tool results/runtime_status.json > /tmp/runtime_status.pretty.json` | pretty 출력 성공 + `status`/`updated_at` 키 존재 확인 | `cp results/runtime_status.json.bak results/runtime_status.json` |
| P2 | 일일 리스크 상태 기준선 고정 | `results/daily_risk_state.json` | `python -m json.tool results/daily_risk_state.json > /tmp/daily_risk.pretty.json` | `daily_loss_pct`/`mdd_pct`/`halt_new_entry` 키 확인 | `cp results/daily_risk_state.json.bak results/daily_risk_state.json` |
| P3 | 운영 설정값 기준선 점검 | `user_config.json` (`max_entries`,`max_pos`,`loss_limit`,`crash_loss_limit`) | `python -m json.tool user_config.json > /tmp/user_config.pretty.json` | 핵심 키 4개 값 출력/비정상(음수, null) 여부 점검 | `cp user_config.json.bak user_config.json` |
| P4 | 백엔드 헬스 로그 가용성 확인 | `results/logs/health.log` | `tail -n 50 results/logs/health.log` | 최근 타임스탬프 존재 + error 폭증 여부 확인 | 로그성 파일이므로 롤백 대신 `cp results/logs/health.log.bak results/logs/health.log` |
| P5 | 알림 송신 버퍼 정상 확인 | `results/outbox/telegram_outbox.json` | `python -m json.tool results/outbox/telegram_outbox.json > /tmp/outbox.pretty.json` | JSON 파싱 성공 + queue 항목 구조 확인 | `cp results/outbox/telegram_outbox.json.bak results/outbox/telegram_outbox.json` |

## 60분 SLA 대응 플랜

| 구간(분) | 작업 | 완료 기준(DoD) | 산출물 |
|---:|---|---|---|
| 0~10 | 사전 백업 | 대상 파일 5개 `.bak` 생성 | `results/architect_apply_pack/evidence/backup_manifest.txt` |
| 10~25 | 설정/상태 파일 유효성 점검 | JSON 4개 파싱 성공 | `.../evidence/validate_json.log` |
| 25~40 | 운영 로그/아웃박스 확인 | health/outbox 점검 결과 기록 | `.../evidence/ops_check.log` |
| 40~50 | 검증 전후 비교 작성 | Before/After 템플릿 채움 | `.../evidence/before_after_compare.md` |
| 50~60 | 결과 요약/승인 대기 | Top5 상태(PASS/WARN/FAIL) 확정 | `.../FINAL_SUMMARY.md` |

## Evidence 섹션

### A. 설정 diff 템플릿
```diff
# file: user_config.json
- "loss_limit": 2.0
+ "loss_limit": 1.8
```

### B. 설치/환경 로그 템플릿
```bash
# 기본옵션 환경 확인 로그
python --version
python -m pip --version
python -m pip list > results/architect_apply_pack/evidence/pip_list.log
```

### C. 검증 전후 비교 템플릿
```markdown
## Before
- runtime_status.updated_at:
- daily_risk_state.halt_new_entry:
- user_config.loss_limit:

## After
- runtime_status.updated_at:
- daily_risk_state.halt_new_entry:
- user_config.loss_limit:

## 판정
- PASS/WARN/FAIL:
- 근거 파일:
```
