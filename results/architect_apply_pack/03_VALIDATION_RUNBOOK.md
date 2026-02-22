# 산출물 3) 검증 Runbook (기본옵션)

## 1. 검증 대상

### 항목 C: 일일 리스크 상태
- 변경 위치(파일/설정키): `results/daily_risk_state.json`
  - `daily_loss_pct`, `mdd_pct`, `halt_new_entry`
- 적용 커맨드:
```bash
cd /mnt/f/SafeBot/openclaw-news-workspace/python
cp results/daily_risk_state.json results/daily_risk_state.json.bak
python -m json.tool results/daily_risk_state.json > /tmp/daily_risk.pretty.json
```
- 검증 방법:
```bash
python - <<'PY'
import json
j=json.load(open('results/daily_risk_state.json'))
for k in ['daily_loss_pct','mdd_pct','halt_new_entry']:
    print(k, j.get(k))
PY
```
- 롤백 방법:
```bash
cp results/daily_risk_state.json.bak results/daily_risk_state.json
```

### 항목 D: 로그/아웃박스
- 변경 위치(파일/설정키):
  - `results/logs/health.log`
  - `results/outbox/telegram_outbox.json`
- 적용 커맨드:
```bash
cp results/logs/health.log results/logs/health.log.bak
cp results/outbox/telegram_outbox.json results/outbox/telegram_outbox.json.bak
tail -n 50 results/logs/health.log
python -m json.tool results/outbox/telegram_outbox.json > /tmp/outbox.pretty.json
```
- 검증 방법:
```bash
grep -E "ERROR|CRITICAL" -n results/logs/health.log | tail -n 20
python - <<'PY'
import json
j=json.load(open('results/outbox/telegram_outbox.json'))
print(type(j).__name__)
PY
```
- 롤백 방법:
```bash
cp results/logs/health.log.bak results/logs/health.log
cp results/outbox/telegram_outbox.json.bak results/outbox/telegram_outbox.json
```

## 2. Evidence 섹션

### 설정 diff 템플릿
```diff
# file: results/daily_risk_state.json
- "halt_new_entry": false
+ "halt_new_entry": true
```

### 설치 로그 템플릿
```text
[VERIFY ENV]
python --version
python -m pip --version
```

### 검증 전후 비교 포맷 템플릿
```markdown
## Risk State Compare
- Before: daily_loss_pct= , mdd_pct= , halt_new_entry=
- After : daily_loss_pct= , mdd_pct= , halt_new_entry=
- Verdict: PASS/WARN/FAIL

## Health/Outbox Compare
- Before: health_error_count= , outbox_json_parse=
- After : health_error_count= , outbox_json_parse=
- Verdict: PASS/WARN/FAIL
```
