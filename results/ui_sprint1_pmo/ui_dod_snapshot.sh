#!/usr/bin/env bash
set -euo pipefail

ROOT="/mnt/f/SafeBot/openclaw-news-workspace/python"
LOG="$ROOT/results/ui_sprint1_pmo/ui_dod_snapshot.log"
TS="$(date '+%Y-%m-%d %H:%M:%S %:z')"

UI_HTML_COUNT=0
UI_DIR_COUNT=0
UI_TEST_LINES=0

if [ -d "$ROOT/tools/agent-dashboard/public" ]; then
  UI_HTML_COUNT=$(find "$ROOT/tools/agent-dashboard/public" -type f -name '*.html' 2>/dev/null | wc -l | tr -d ' ')
fi

if [ -d "$ROOT" ]; then
  UI_DIR_COUNT=$(find "$ROOT" -maxdepth 3 -type d | while read -r d; do
    if [[ "$d" =~ agent-dashboard|ui|front|web|dashboard ]]; then
      echo "$d"
    fi
  done | wc -l | tr -d ' ')
fi

if [ -x "$ROOT/.venv/bin/python" ]; then
  UI_TEST_LINES=$("$ROOT/.venv/bin/python" -m pytest -q -k ui --collect-only >/tmp/ui_pyo.out 2>/tmp/ui_pyo.err || true
  )
  if [ -s /tmp/ui_pyo.out ]; then
    UI_TEST_LINES=$(cat /tmp/ui_pyo.out | wc -l | tr -d ' ')
  fi
fi

{
  echo "[${TS}] UI DoD Snapshot"
  echo "HTML files: $UI_HTML_COUNT"
  echo "UI-like dirs: $UI_DIR_COUNT"
  echo "Pytest ui-collect output lines: $UI_TEST_LINES"
  echo "---"
  echo "Artifacts:" 
  if [ -d "$ROOT/tools" ]; then
    find "$ROOT/tools" -maxdepth 4 -type f \( -name '*.tsx' -o -name '*.ts' -o -name '*.jsx' -o -name '*.js' -o -name '*.html' -o -name '*.css' -o -name '*.vue' \) 2>/dev/null
  fi
  echo "---"
} | tee -a "$LOG"

rm -f /tmp/ui_pyo /tmp/ui_pyo.out /tmp/ui_pyo.err
