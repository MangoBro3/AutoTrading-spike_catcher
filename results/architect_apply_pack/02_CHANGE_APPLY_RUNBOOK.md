# 산출물 2) 변경 적용 Runbook (기본옵션)

## 1. 변경 대상

### 항목 A: 운영 설정 기준선
- 변경 위치(파일/설정키): `user_config.json`
  - `max_entries`, `max_pos`, `loss_limit`, `crash_loss_limit`
- 적용 커맨드:
```bash
cd /mnt/f/SafeBot/openclaw-news-workspace/python
cp user_config.json user_config.json.bak
python -m json.tool user_config.json > /tmp/user_config.pretty.json
```
- 검증 방법:
```bash
python - <<'PY'
import json
j=json.load(open('user_config.json'))
for k in ['max_entries','max_pos','loss_limit','crash_loss_limit']:
    print(k, j.get(k))
PY
```
- 롤백 방법:
```bash
cp user_config.json.bak user_config.json
```

### 항목 B: 런타임 상태 기준선
- 변경 위치(파일/설정키): `results/runtime_status.json` (`status`, `updated_at`)
- 적용 커맨드:
```bash
cp results/runtime_status.json results/runtime_status.json.bak
python -m json.tool results/runtime_status.json > /tmp/runtime_status.pretty.json
```
- 검증 방법:
```bash
python - <<'PY'
import json
j=json.load(open('results/runtime_status.json'))
print('status=', j.get('status'))
print('updated_at=', j.get('updated_at'))
PY
```
- 롤백 방법:
```bash
cp results/runtime_status.json.bak results/runtime_status.json
```

## 2. Evidence 섹션

### 설정 diff 템플릿
```diff
# file: results/runtime_status.json
- "status": "degraded"
+ "status": "ok"
```

### 설치 로그 템플릿
```text
[INSTALL/ENV]
python --version
python -m pip --version
python -m pip list (saved)
```

### 검증 전후 비교 포맷 템플릿
```markdown
| 체크항목 | Before | After | 결과 |
|---|---|---|---|
| user_config.loss_limit |  |  | PASS/WARN/FAIL |
| runtime_status.status |  |  | PASS/WARN/FAIL |
```
