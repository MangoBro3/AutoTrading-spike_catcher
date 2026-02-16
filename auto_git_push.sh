#!/usr/bin/env bash
set -euo pipefail

REPO="/mnt/f/SafeBot/openclaw-news-workspace/python"
cd "$REPO"

# 동시 실행 방지
LOCKFILE="/tmp/auto_git_push.lock"
exec 9>"$LOCKFILE"
flock -n 9 || exit 0

# 변경 없으면 종료
git add -A
if git diff --cached --quiet; then
exit 0
fi

# 자동 커밋 + 푸시
MSG="chore(auto): sync $(date -u +'%Y-%m-%d %H:%M:%S UTC')"
git commit -m "$MSG" || exit 0
git push origin main
