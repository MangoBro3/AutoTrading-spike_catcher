# Agent Team Dashboard

간단한 로컬 대시보드입니다.

## 실행

```bash
cd /mnt/f/SafeBot/openclaw-news-workspace/python/tools/agent-dashboard
node server.mjs
```

브라우저: http://127.0.0.1:18890

## 표시 내용
- Gateway/Channels 상태 (`openclaw status --all --json` 기반)
- 에이전트 목록 (`openclaw agents list --json` 기반)
- 세션 요약
- PM 체크포인트 파일 (옵션)
  - 경로: `/mnt/f/SafeBot/openclaw-news-workspace/python/team/checkpoints/latest.json`

## 체크포인트 파일 예시

```json
{
  "status": "Yellow",
  "blockers": ["contract path mismatch"],
  "next_actions": ["align canonical path"],
  "user_decision_needed": "Yes",
  "fail_count": "1/3",
  "last_failed_step": "runtime"
}
```
