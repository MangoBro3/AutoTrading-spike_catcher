# Auto Trading UI

독립 실행형 정적 UI + 서버 엔트리.

## 실행

### 1) Backend (FastAPI, 8765)
```bash
cd "/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading"
BACKEND_PORT=8765 ./.venv/bin/python fastapi_backend.py
```

### 2) UI (18890)
```bash
cd "/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/ui"
node server.mjs
```

브라우저: `http://127.0.0.1:18890`

## E2E 증적 생성
```bash
cd "/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/ui"
npm install
npm run e2e:evidence
```
- 산출 경로: `Auto Trading/ui/evidence/ui-final-1/`

## 기본 연동 설정
- `WORKER_API_BASE_URL` 기본값: `http://127.0.0.1:8765/api/v1`
- `WORKER_POLL_MS` 기본값: `1000`
