#!/usr/bin/env bash
set -euo pipefail

# E6 / Continuous Verify Guardrail - 동일 커맨드 재실행 템플릿
# 작업 루트(절대경로): /mnt/f/SafeBot/openclaw-news-workspace/python
# 코드 로직 변경 없이, 동일 실행 커맨드만 재현하기 위한 템플릿

ROOT="/mnt/f/SafeBot/openclaw-news-workspace/python"
cd "$ROOT"

PY="python3"

# run_summary 기준(현재 기준셋에서 관측된 값)
RUN_SUMMARY_FIX="Auto Trading/results/runs/20260204_142438_backtest_LABS_SIM_launcher_demo/run_summary.json"
RUN_SUMMARY_FINAL_CONT="Auto Trading/results/runs/20260219_014300_backtest_LABS_SIM_laneB_guard_patch/run_summary.json"

OUT_FIX="backtest/out_at_fix"
OUT_FINAL="backtest/out_at_final"
OUT_CONT="backtest/out_at_continuous"

# 0) 기존 산출물 백업(선택)
# cp -a "$OUT_FIX" "${OUT_FIX}_bak_$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
# cp -a "$OUT_FINAL" "${OUT_FINAL}_bak_$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true
# cp -a "$OUT_CONT" "${OUT_CONT}_bak_$(date +%Y%m%d_%H%M%S)" 2>/dev/null || true

# 1) clean recreate
rm -rf "$OUT_FIX" "$OUT_FINAL" "$OUT_CONT"

# 2) out_at_fix 재생성 (기준 run_summary: FIX)
$PY run_backtest.py \
  --adapter auto_trading \
  --run-summary "$RUN_SUMMARY_FIX" \
  --out "$OUT_FIX"

# 3) out_at_final 재생성 (기준 run_summary: FINAL/CONT)
$PY run_backtest.py \
  --adapter auto_trading \
  --run-summary "$RUN_SUMMARY_FINAL_CONT" \
  --out "$OUT_FINAL"

# 4) out_at_continuous 재생성 (동일 입력 재실행)
$PY run_backtest.py \
  --adapter auto_trading \
  --run-summary "$RUN_SUMMARY_FINAL_CONT" \
  --out "$OUT_CONT"

# 5) 파일셋/해시 비교(즉시 검증)
$PY - <<'PY'
import hashlib, os
bases=['backtest/out_at_fix','backtest/out_at_final','backtest/out_at_continuous']

def fmap(base):
    m={}
    for r,_,fs in os.walk(base):
        for f in fs:
            p=os.path.join(r,f)
            rel=os.path.relpath(p,base)
            m[rel]=hashlib.sha256(open(p,'rb').read()).hexdigest()
    return m

maps={b:fmap(b) for b in bases}
for b in bases:
    print(f'{b}: files={len(maps[b])}')

pairs=[(bases[0],bases[1]),(bases[0],bases[2]),(bases[1],bases[2])]
for a,b in pairs:
    only_a=set(maps[a])-set(maps[b])
    only_b=set(maps[b])-set(maps[a])
    diff=[k for k in set(maps[a])&set(maps[b]) if maps[a][k]!=maps[b][k]]
    print(f'[{a} vs {b}] only_a={len(only_a)} only_b={len(only_b)} hash_diff={len(diff)}')
PY

echo "[DONE] E6 rerun template completed"
