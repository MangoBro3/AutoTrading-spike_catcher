#!/usr/bin/env bash
set -euo pipefail

REPO="/mnt/f/SafeBot/openclaw-news-workspace/python"
cd "$REPO"

# SSH 키 준비 (cron 환경용)
export GIT_SSH_COMMAND="ssh -F /home/mangobro3/.ssh/config"

# 변경 없으면 종료
if git diff --quiet && git diff --cached --quiet; then
echo "[auto_git_push] no changes"
exit 0
fi

git add -A
git commit -m "chore(auto): periodic backup commit $(date '+%Y-%m-%d %H:%M:%S')" || true
git push origin main
echo "[auto_git_push] pushed"
