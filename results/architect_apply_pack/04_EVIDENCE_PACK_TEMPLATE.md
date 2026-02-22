# 산출물 4) Evidence Pack 템플릿 + 최종 정리

## 1) 실행 커맨드 기록 템플릿

```bash
cd /mnt/f/SafeBot/openclaw-news-workspace/python
mkdir -p results/architect_apply_pack/evidence

echo "[1] backup" | tee -a results/architect_apply_pack/evidence/run.log
cp user_config.json user_config.json.bak
cp results/runtime_status.json results/runtime_status.json.bak
cp results/daily_risk_state.json results/daily_risk_state.json.bak
cp results/logs/health.log results/logs/health.log.bak
cp results/outbox/telegram_outbox.json results/outbox/telegram_outbox.json.bak

echo "[2] validate json" | tee -a results/architect_apply_pack/evidence/run.log
python -m json.tool user_config.json > /tmp/user_config.pretty.json
python -m json.tool results/runtime_status.json > /tmp/runtime_status.pretty.json
python -m json.tool results/daily_risk_state.json > /tmp/daily_risk.pretty.json
python -m json.tool results/outbox/telegram_outbox.json > /tmp/outbox.pretty.json

echo "[3] health check" | tee -a results/architect_apply_pack/evidence/run.log
tail -n 50 results/logs/health.log > results/architect_apply_pack/evidence/health_tail.log
```

## 2) 변경 위치(파일/설정키) 체크리스트
- `user_config.json`: `max_entries`, `max_pos`, `loss_limit`, `crash_loss_limit`
- `results/runtime_status.json`: `status`, `updated_at`
- `results/daily_risk_state.json`: `daily_loss_pct`, `mdd_pct`, `halt_new_entry`
- `results/logs/health.log`: 최근 에러 패턴
- `results/outbox/telegram_outbox.json`: 큐 구조/파싱 가능 여부

## 3) 검증 방법 체크리스트
- JSON 파싱 성공 여부(4개 파일)
- 핵심 키 값 출력 확인
- health.log 최근 50줄 내 ERROR/CRITICAL 빈도 확인
- outbox JSON 구조 확인

## 4) 롤백 방법 체크리스트
```bash
cp user_config.json.bak user_config.json
cp results/runtime_status.json.bak results/runtime_status.json
cp results/daily_risk_state.json.bak results/daily_risk_state.json
cp results/logs/health.log.bak results/logs/health.log
cp results/outbox/telegram_outbox.json.bak results/outbox/telegram_outbox.json
```

## 5) Evidence 섹션 (필수)

### A. 설정 diff 템플릿
```diff
# file: user_config.json
- "max_pos": 6
+ "max_pos": 5
```

### B. 설치 로그 템플릿
```text
[INSTALL LOG]
python --version
python -m pip --version
python -m pip list > results/architect_apply_pack/evidence/pip_list.log
```

### C. 검증 전후 비교 포맷 템플릿
```markdown
# Verification Before/After
| 항목 | Before | After | 결과 |
|---|---|---|---|
| user_config.max_pos |  |  | PASS/WARN/FAIL |
| runtime_status.status |  |  | PASS/WARN/FAIL |
| daily_risk_state.halt_new_entry |  |  | PASS/WARN/FAIL |
| health_error_count(last50) |  |  | PASS/WARN/FAIL |
| outbox_json_parse |  |  | PASS/WARN/FAIL |
```

## 6) 최종 보고 템플릿 (60분 SLA)
```markdown
- SLA 시작시각:
- SLA 종료시각:
- 총 소요(분):
- Top5 완료율: x/5
- 실패/보류 항목:
- 즉시 조치 필요 항목:
- 승인 요청자/시각:
```
