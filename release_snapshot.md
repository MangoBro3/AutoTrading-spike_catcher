# Release Snapshot (Final)
- 실행 커맨드: `python run_backtest.py --adapter auto_trading --run-summary models/_archive/run_20260212_173603_42/run_summary.json --out backtest/out_recover_v2_verify`
- 입력경로: `/mnt/f/SafeBot/openclaw-news-workspace/python/models/_archive/run_20260212_173603_42/run_summary.json`
- 출력경로: `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest/out_recover_v2_verify/runner_summary.json`
- GO-NOGO: **GO** (TL_GATE_RESULT=GO, TL_GATE_GO_COUNT=15/15, R2_RE_GATE_GO_COUNT=2/2)
- pytest 커맨드: `.venv/bin/python -m pytest -q "Auto Trading/test_stage7.py" "Auto Trading/test_stage10.py" "Auto Trading/test_stage11_integration.py"`
- pytest 결과: **9 passed in 11.71s** (2026-02-19 실행)
- 기준 작업경로: `/mnt/f/SafeBot/openclaw-news-workspace/python`