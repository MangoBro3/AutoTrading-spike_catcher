import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import pandas as pd

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

# Ensure project root is current working dir for consistent relative paths
AUTO_DIR = Path(__file__).resolve().parent
ROOT_DIR = AUTO_DIR.parent
sys.path.append(str(AUTO_DIR))
os.chdir(str(ROOT_DIR))

from modules.adapter_upbit import UpbitAdapter
from modules.adapter_bithumb import BithumbAdapter
from modules.capital_ledger import CapitalLedger
from modules.watch_engine import WatchEngine
from modules.run_controller import RunController
from modules.notifier_telegram import TelegramNotifier
from modules.model_manager import ModelManager
from modules.oos_tuner import (
    build_split_windows,
    evaluate_params,
    latest_data_timestamp,
    run_tuning_cycle,
    select_universe,
)

RESULTS_DIR = ROOT_DIR / "results"
LOCK_PATH = RESULTS_DIR / "locks" / "bot.lock"
RUNTIME_STATUS_PATH = RESULTS_DIR / "runtime_status.json"
RUNTIME_STATE_PATH = RESULTS_DIR / "runtime_state.json"
BACKEND_STATUS_PATH = RESULTS_DIR / "backend_status.json"
SETTINGS_PATH = AUTO_DIR / "ui_settings.json"
LABS_DIR = RESULTS_DIR / "labs"
LABS_STATUS_PATH = LABS_DIR / "last_status.json"
LABS_PENDING_LIVE_PATH = LABS_DIR / "pending_live_params.json"
LABS_LAST_RESULT_PATH = LABS_DIR / "last_result.json"
LABS_LAST_BASELINE_PATH = LABS_DIR / "last_baseline.json"
DATA_STATUS_PATH = LABS_DIR / "data_status.json"

OPENCLAW_PANIC_EMERGENCY_DEBOUNCE_MIN = 5

DEFAULT_SETTINGS = {
    "mode": "PAPER",
    "exchange": "UPBIT",
    "seed_krw": 1000000,
    "watchlist": ["KRW-BTC", "KRW-ETH"],
    "watch_refresh_sec": 60,
    "watch_score_min": 1.0,
    "watch_alert_score": 2.0,
    "watch_highlight_top": 3,
    "watch_alert_cooldown_min": 60,
    "auto_buy_score_min_100": 100,
    "watch_exclude_symbols": ["USDT", "USDC"],
    "auto_data_update_enabled": False,
    "auto_data_update_interval_min": 60,
    "evolution_enabled": True,
    "evolution_interval_hours": 24,
    "evolution_anchor_time": "09:00",
    "evolution_lookback_days": 180,
    "evolution_trials_per_group": 20,
    "evolution_min_improve_pct": 5,
    "evolution_min_trades": 50,
    "evolution_max_dd": 0.2,
    "evolution_require_sharpe": True,
    # OOS tuning policy (weekly deterministic cycle)
    "tuning_seed": 42,
    "tuning_trials": 30,
    "tuning_train_days": 180,
    "tuning_oos_days": 28,
    "tuning_embargo_days": 2,
    "tuning_oos_min_trades": 20,
    "tuning_mdd_cap": -0.15,
    "tuning_delta_min": 0.01,
    "tuning_promotion_cooldown_hours": 24,
    "tuning_min_symbols_for_watchlist": 5,
    "tuning_watchlist_fallback_to_market": True,
    "tuning_fallback_top_n": 80,
    "tuning_cadence_days": 7,
    "trainer_cooldown_minutes_on_boot": 15,
}

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>DHR Control Center (Local)</title>
  <style>
    :root {
      --bg: #0f141a;
      --panel: #151b22;
      --panel-2: #1b232c;
      --text: #e6eef7;
      --muted: #8aa0b6;
      --good: #2ecc71;
      --warn: #f1c40f;
      --bad: #e74c3c;
      --accent: #4aa3ff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Tahoma, sans-serif;
      background: radial-gradient(1200px 800px at 20% -10%, #1b2a3a 0%, var(--bg) 55%);
      color: var(--text);
    }
    header {
      padding: 20px 24px;
      border-bottom: 1px solid #202834;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    header h1 { margin: 0; font-size: 20px; letter-spacing: 0.3px; }
    header .hint { color: var(--muted); font-size: 12px; }
    main { display: grid; gap: 16px; padding: 16px 24px 28px; }
    .grid-2 { display: grid; gap: 16px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .grid-3 { display: grid; gap: 12px; grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .card {
      background: linear-gradient(180deg, var(--panel) 0%, var(--panel-2) 100%);
      border: 1px solid #202834;
      border-radius: 10px;
      padding: 14px 16px;
      box-shadow: 0 8px 30px rgba(0,0,0,0.2);
    }
    .card h3 { margin: 0 0 8px; font-size: 14px; color: var(--muted); font-weight: 600; }
    .stat {
      font-size: 20px;
      font-weight: 700;
      letter-spacing: 0.2px;
    }
    .pill {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 4px 10px; border-radius: 999px; font-size: 12px;
      background: #1f2a36; color: var(--muted);
    }
    .pill.good { color: #0a1; background: rgba(46, 204, 113, 0.15); border: 1px solid rgba(46, 204, 113, 0.3); }
    .pill.warn { color: #d9a800; background: rgba(241, 196, 15, 0.15); border: 1px solid rgba(241, 196, 15, 0.3); }
    .pill.bad { color: #ff6b5f; background: rgba(231, 76, 60, 0.15); border: 1px solid rgba(231, 76, 60, 0.3); }
    .pill.live { color: #ff8d82; background: rgba(231, 76, 60, 0.18); border: 1px solid rgba(231, 76, 60, 0.45); }
    .pill.paper { color: #8cc6ff; background: rgba(74, 163, 255, 0.18); border: 1px solid rgba(74, 163, 255, 0.45); }
    .row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .muted { color: var(--muted); font-size: 12px; }
    label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 6px; }
    input, select, textarea {
      width: 100%; background: #10161d; color: var(--text);
      border: 1px solid #243041; border-radius: 6px;
      padding: 8px 10px; font-size: 13px;
    }
    .checkbox-group { display: grid; gap: 6px; }
    .checkbox-group label { display: flex; align-items: center; gap: 8px; margin: 0; }
    .checkbox-group input[type="checkbox"] { width: auto; }
    textarea { min-height: 70px; resize: vertical; }
    button {
      background: var(--accent); color: white; border: none; border-radius: 6px;
      padding: 8px 12px; font-size: 13px; cursor: pointer;
    }
    button.secondary { background: #2a3545; }
    button.danger { background: #b03a2e; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; }
    .log { font-family: Consolas, monospace; font-size: 12px; color: var(--muted); }
    .progress-wrap {
      width: 100%;
      height: 10px;
      background: #0f151c;
      border: 1px solid #243041;
      border-radius: 999px;
      overflow: hidden;
      margin: 8px 0 6px;
    }
    .progress-fill {
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, #4aa3ff, #2ecc71);
      transition: width 180ms ease;
    }
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin: 8px 0;
    }
    .kpi {
      border: 1px solid #243041;
      border-radius: 8px;
      padding: 6px 8px;
      background: #111923;
    }
    .kpi .k { color: var(--muted); font-size: 11px; }
    .kpi .v { color: var(--text); font-size: 13px; font-weight: 700; }
    .compare-win { color: #7bed9f; }
    .compare-lose { color: #ff9f8f; }
    .compare-tie { color: #ffd54f; }
    .watchlist { display: flex; flex-wrap: wrap; gap: 6px; }
    .watchlist-table { display: grid; gap: 6px; }
    .watch-row {
      display: grid;
      grid-template-columns: 36px 1fr 70px 80px 1fr;
      gap: 8px;
      align-items: center;
      padding: 6px 8px;
      border-radius: 8px;
      background: #141b23;
      border: 1px solid #202834;
      font-size: 12px;
    }
    .watch-row.hot {
      border-color: rgba(46, 204, 113, 0.6);
      background: rgba(46, 204, 113, 0.1);
    }
    .watch-row.auto {
      box-shadow: 0 0 0 1px rgba(255, 215, 0, 0.4) inset;
    }
    .watch-row.blocked {
      border-color: rgba(231, 76, 60, 0.6);
      background: rgba(231, 76, 60, 0.08);
    }
    .watch-row.reentry {
      border-color: rgba(74, 163, 255, 0.6);
      background: rgba(74, 163, 255, 0.08);
    }
    .watch-row.selected {
      box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.22) inset;
    }
    .grade {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 24px;
      padding: 2px 6px;
      border-radius: 999px;
      font-weight: 700;
      font-size: 11px;
      margin-left: 6px;
    }
    .grade.s { background: rgba(255, 215, 0, 0.2); color: #ffd54f; border: 1px solid rgba(255, 215, 0, 0.5); }
    .grade.a { background: rgba(46, 204, 113, 0.2); color: #7bed9f; border: 1px solid rgba(46, 204, 113, 0.5); }
    .grade.b { background: rgba(74, 163, 255, 0.2); color: #8cc6ff; border: 1px solid rgba(74, 163, 255, 0.5); }
    .grade.c { background: rgba(149, 165, 166, 0.2); color: #b0bec5; border: 1px solid rgba(149, 165, 166, 0.5); }
    .badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 2px 6px;
      border-radius: 6px;
      font-size: 10px;
      font-weight: 700;
      margin-left: 6px;
      background: rgba(255, 215, 0, 0.15);
      color: #ffd54f;
      border: 1px solid rgba(255, 215, 0, 0.5);
    }
    .watch-rank { font-weight: 700; color: var(--muted); }
    .watch-score { font-weight: 700; }
    .watch-tag { color: var(--muted); }
    .watch-sub { color: #7f92a8; font-size: 11px; }
    .watch-filterbar {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-bottom: 8px;
    }
    .watch-filter-btn {
      background: #202a36;
      color: var(--muted);
      border: 1px solid #2a3647;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 11px;
      cursor: pointer;
    }
    .watch-filter-btn.active {
      color: #d9ebff;
      border-color: #4aa3ff;
      background: rgba(74, 163, 255, 0.2);
    }
    .delta-up { color: #7bed9f; }
    .delta-down { color: #ff9f8f; }
    .delta-flat { color: #9fb3c8; }
    .watch-detail {
      margin-top: 8px;
      border: 1px solid #243041;
      border-radius: 8px;
      background: #101922;
      padding: 8px 10px;
    }
    .watch-detail-title {
      color: #d9ebff;
      font-size: 12px;
      font-weight: 700;
      margin-bottom: 6px;
    }
    .watch-detail-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px 8px;
      font-size: 11px;
      color: #9fb3c8;
    }
    .watch-detail-grid b {
      color: #dcecff;
      font-weight: 700;
    }
    .watch-detail-note {
      margin-top: 6px;
      font-size: 11px;
      color: #9fb3c8;
    }
    .status-pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      margin-left: 6px;
      padding: 2px 6px;
      border-radius: 999px;
      font-size: 10px;
      font-weight: 700;
      border: 1px solid transparent;
    }
    .status-pill.buy {
      color: #7bed9f;
      background: rgba(46, 204, 113, 0.18);
      border-color: rgba(46, 204, 113, 0.45);
    }
    .status-pill.reentry {
      color: #8cc6ff;
      background: rgba(74, 163, 255, 0.18);
      border-color: rgba(74, 163, 255, 0.45);
    }
    .status-pill.blocked {
      color: #ff9f8f;
      background: rgba(231, 76, 60, 0.18);
      border-color: rgba(231, 76, 60, 0.45);
    }
    .chip { padding: 4px 8px; border-radius: 999px; background: #212b37; font-size: 12px; }
    .chart {
      width: 100%;
      height: 140px;
      border: 1px solid #243041;
      border-radius: 8px;
      background: #0f151c;
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--muted);
      font-size: 12px;
    }
    .tabbar {
      display: flex;
      gap: 8px;
      margin-bottom: 10px;
    }
    .tab-btn {
      background: #202a36;
      color: var(--muted);
      border: 1px solid #2a3647;
      border-radius: 6px;
      padding: 6px 10px;
      font-size: 12px;
      cursor: pointer;
    }
    .tab-btn.active {
      color: #d9ebff;
      border-color: #4aa3ff;
      background: rgba(74, 163, 255, 0.2);
    }
    .tab-pane { display: none; }
    .tab-pane.active { display: block; }
    .history-wrap {
      width: 100%;
      max-height: 300px;
      overflow: auto;
      border: 1px solid #243041;
      border-radius: 8px;
      background: #0f151c;
    }
    .history-table {
      width: 100%;
      min-width: 1100px;
      border-collapse: collapse;
      font-size: 12px;
    }
    .history-table th, .history-table td {
      border-bottom: 1px solid #202834;
      padding: 6px 8px;
      text-align: left;
      white-space: nowrap;
    }
    .history-table th {
      position: sticky;
      top: 0;
      background: #111923;
      color: var(--muted);
      z-index: 1;
    }
    .decision-promote { color: #7bed9f; font-weight: 700; }
    .decision-keep { color: #ffd54f; font-weight: 700; }
    .decision-archived { color: #ffcc80; font-weight: 700; }
    .decision-fail { color: #ff9f8f; font-weight: 700; }
    .pill.archive { color: #ffcc80; background: rgba(255, 183, 77, 0.18); border: 1px solid rgba(255, 183, 77, 0.45); }
    .labs-note-error { color: #ff9f8f; font-weight: 700; }
    .labs-note-archived { color: #ffd54f; font-weight: 700; }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(2, 6, 12, 0.72);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 30;
      padding: 16px;
    }
    .modal-backdrop.active {
      display: flex;
    }
    .modal {
      width: min(560px, 100%);
      background: #141b23;
      border: 1px solid #2a3647;
      border-radius: 10px;
      padding: 14px;
      box-shadow: 0 14px 50px rgba(0, 0, 0, 0.35);
    }
    .modal h3 {
      margin-top: 0;
      color: #d9ebff;
      font-size: 16px;
    }
    .orders-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    .orders-table th,
    .orders-table td {
      border-bottom: 1px solid #202834;
      padding: 6px 4px;
      text-align: left;
      white-space: nowrap;
    }
    .orders-table th {
      color: var(--muted);
      position: sticky;
      top: 0;
      background: #111923;
      z-index: 1;
    }
    .order-list-wrap {
      max-height: 220px;
      overflow: auto;
      border: 1px solid #243041;
      border-radius: 8px;
      background: #0f151c;
      padding: 4px;
    }
    .panic-progress {
      margin: 6px 0;
      color: var(--muted);
      font-size: 11px;
    }
    @media (max-width: 980px) {
      .grid-2, .grid-3 { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>DHR Control Center (Local)</h1>
    <div class="hint">Local only: 127.0.0.1</div>
  </header>
  <main>
    <div class="grid-3">
      <div class="card">
        <h3>Backend</h3>
        <div class="row">
          <div class="stat" id="backendStatus">-</div>
          <span class="pill" id="backendPill">?</span>
        </div>
        <div class="muted" id="backendMeta">-</div>
      </div>
      <div class="card">
        <h3>Controller</h3>
        <div class="row">
          <div class="stat" id="controllerStatus">-</div>
          <span class="pill" id="controllerPill">?</span>
        </div>
        <div class="muted" id="controllerMeta">-</div>
      </div>
      <div class="card">
        <h3>Mode / PnL / Position</h3>
        <div class="row">
          <div class="stat" id="modeIndicator">-</div>
          <span class="pill" id="modePill">?</span>
        </div>
        <div class="muted" id="pnlMeta">-</div>
        <div class="muted" id="positionMeta">-</div>
        <div class="muted" id="runtimeMeta">-</div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <h3>Quick Actions</h3>
        <div class="actions">
          <button onclick="requestStart()">Start</button>
          <button class="danger" onclick="stopBot()">Stop</button>
          <button onclick="manualRestart()">Manual Restart</button>
          <button class="danger" id="panicBtn" onpointerdown="startPanicHold()" onpointerup="cancelPanicHold()" onpointerleave="cancelPanicHold()" oncontextmenu="return false;">Panic Exit</button>
          <button class="danger" onclick="shutdownBackend()">Shutdown Backend</button>
          <button class="secondary" onclick="checkHealth()">Check APIs</button>
          <button class="secondary" onclick="refresh()">Refresh</button>
        </div>
        <div class="muted" id="panicStatus">Hold to panic: move slider to READY and press 3 seconds.</div>
        <div class="muted" style="margin-top: 6px;">Panic slider</div>
        <input id="panicSlider" type="range" min="0" max="100" value="0" style="width: 100%;" oninput="updatePanicSliderLabel()" />
        <div class="muted" id="panicSliderValue">Panic slider: 0%</div>
        <div class="muted" id="actionMsg">-</div>
        <div class="muted">Backend shutdown requires manual restart.</div>
      </div>
      <div class="card">
        <h3>Current Watchlist</h3>
        <div class="watch-filterbar">
          <button id="watchFilterAll" class="watch-filter-btn" onclick="setWatchFilter('all')">All</button>
          <button id="watchFilterActionable" class="watch-filter-btn active" onclick="setWatchFilter('actionable')">Actionable</button>
          <button id="watchFilterBlocked" class="watch-filter-btn" onclick="setWatchFilter('blocked')">Blocked</button>
          <button id="watchFilterReentry" class="watch-filter-btn" onclick="setWatchFilter('reentry')">ReEntry</button>
          <button id="watchPinActionable" class="watch-filter-btn active" onclick="toggleWatchPinActionable()">Pin Actionable: ON</button>
        </div>
        <div class="watchlist-table" id="watchlistTable"></div>
        <div class="watch-detail" id="watchDetailPanel">
          <div class="watch-detail-title" id="watchDetailTitle">Entry Plan</div>
          <div class="watch-detail-note" id="watchDetailBody">Select a symbol row to inspect plan.</div>
        </div>
        <div class="muted" id="watchlistMeta">-</div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <h3>Open Orders</h3>
        <div class="muted" id="ordersMeta">-</div>
        <div class="order-list-wrap">
          <table class="orders-table">
            <thead>
              <tr><th>Symbol</th><th>Side</th><th>Type</th><th>Qty</th><th>Price</th><th>Remaining</th><th>Created</th><th>Action</th></tr>
            </thead>
            <tbody id="ordersTableBody">
              <tr><td colspan="8" class="muted">No data.</td></tr>
            </tbody>
          </table>
        </div>
        <div class="actions" style="margin-top:8px;">
          <button class="secondary" onclick="refreshOrders()">Refresh Orders</button>
          <button class="danger" onclick="cancelAllOrders()">Cancel All</button>
        </div>
        <div class="muted" id="ordersMsg">-</div>
      </div>
      <div class="card">
        <h3>Data Update</h3>
        <div class="actions">
          <button onclick="runDataUpdate()">Update Data</button>
        </div>
        <div class="muted" id="dataMsg">-</div>
        <div class="log" id="dataStatus">-</div>
      </div>
      <div class="card">
        <h3>Labs Result</h3>
        <div class="tabbar">
          <button id="labsTabBtnLatest" class="tab-btn active" onclick="switchLabsTab('latest')">Latest Result</button>
          <button id="labsTabBtnHistory" class="tab-btn" onclick="switchLabsTab('history')">Training History</button>
        </div>
        <div id="labsTabLatest" class="tab-pane active">
          <div class="chart" id="labsChart">No chart yet.</div>
          <div class="log" id="labsCompareHeadline">-</div>
          <div class="kpi-grid" id="labsKpiGrid"></div>
          <div class="log" id="labsSummary">-</div>
        </div>
        <div id="labsTabHistory" class="tab-pane">
          <div class="muted" id="modelHistoryMeta">-</div>
          <div class="history-wrap">
            <table class="history-table">
              <thead>
                <tr>
                  <th>Created</th>
                  <th>Run ID</th>
                  <th>Bucket</th>
                  <th>Decision</th>
                  <th>Score C/A</th>
                  <th>Delta</th>
                  <th>ROI</th>
                  <th>MDD</th>
                  <th>Trades</th>
                  <th>CostDrop</th>
                  <th>Weeks(+/-)</th>
                  <th>Worst Week</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody id="modelHistoryTableBody">
                <tr><td colspan="13" class="muted">No history yet.</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <h3>Health & Tick</h3>
        <div class="row">
          <div class="stat" id="healthStatus">-</div>
          <span class="pill" id="healthPill">?</span>
        </div>
        <div class="muted" id="healthMeta">-</div>
        <div class="muted" id="tickMeta">-</div>
        <div class="muted" id="errorMeta">-</div>
      </div>
      <div class="card">
        <h3>Labs / Evolution</h3>
        <div class="actions">
          <button onclick="runBacktest()">Run Backtest</button>
          <button onclick="runEvolution()">Run Evolution</button>
          <button class="secondary" onclick="approveLive()">Approve LIVE Params</button>
        </div>
        <div class="row">
          <div class="muted" id="labsRunState">-</div>
          <span class="pill" id="labsRunPill">?</span>
        </div>
        <div class="muted" id="labsMsg">-</div>
        <div class="progress-wrap"><div class="progress-fill" id="labsProgressBar"></div></div>
        <div class="muted" id="labsProgressText">-</div>
        <div class="log" id="labsStatus">-</div>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <h3>Settings</h3>
        <div style="display:grid; gap:10px;">
          <div>
            <label for="mode">Mode</label>
            <select id="mode">
              <option value="PAPER">PAPER</option>
              <option value="LIVE">LIVE</option>
            </select>
          </div>
          <div>
            <label>Exchange</label>
            <div class="checkbox-group">
              <label><input id="exchange_upbit" type="checkbox" /> UPBIT</label>
              <label><input id="exchange_bithumb" type="checkbox" /> BITHUMB</label>
            </div>
          </div>
          <div>
            <label for="seed">Seed (KRW)</label>
            <input id="seed" type="number" min="1" step="1" />
          </div>
          <div>
            <label for="watchlist">Watchlist (comma separated)</label>
            <textarea id="watchlist"></textarea>
          </div>
          <div>
            <label for="watch_refresh_sec">Watch Refresh (sec)</label>
            <input id="watch_refresh_sec" type="number" min="10" step="5" />
          </div>
          <div>
            <label for="watch_score_min">Watch Score Min</label>
            <input id="watch_score_min" type="number" min="0" step="0.1" />
          </div>
          <div>
            <label for="watch_alert_score">Alert Score Threshold</label>
            <input id="watch_alert_score" type="number" min="0" step="0.1" />
          </div>
          <div>
            <label for="watch_highlight_top">Highlight Top N</label>
            <input id="watch_highlight_top" type="number" min="1" step="1" />
          </div>
          <div>
            <label for="watch_alert_cooldown_min">Alert Cooldown (min)</label>
            <input id="watch_alert_cooldown_min" type="number" min="5" step="5" />
          </div>
          <div>
            <label for="auto_buy_score_min_100">Auto Buy Score (0-100)</label>
            <input id="auto_buy_score_min_100" type="number" min="0" max="200" step="1" />
          </div>
          <div>
            <label for="watch_exclude_symbols">Exclude Symbols (comma separated)</label>
            <input id="watch_exclude_symbols" type="text" placeholder="USDT, USDC" />
          </div>
          <div>
            <label><input id="auto_data_update_enabled" type="checkbox" /> Auto Data Update</label>
          </div>
          <div>
            <label for="auto_data_update_interval_min">Auto Update Interval (min)</label>
            <input id="auto_data_update_interval_min" type="number" min="5" step="5" />
          </div>
          <div>
            <label><input id="evolution_enabled" type="checkbox" /> Evolution Mode (Auto Optimize)</label>
          </div>
          <div>
            <label for="evolution_interval_hours">Evolution Interval (hours)</label>
            <input id="evolution_interval_hours" type="number" min="1" step="1" />
          </div>
          <div>
            <label for="evolution_anchor_time">Evolution Anchor Time (HH:MM, local)</label>
            <input id="evolution_anchor_time" type="text" placeholder="09:00" />
          </div>
          <div>
            <label for="evolution_lookback_days">Evolution Lookback (days)</label>
            <input id="evolution_lookback_days" type="number" min="30" step="1" />
          </div>
          <div>
            <label for="evolution_trials_per_group">Trials per Group (A/B/C)</label>
            <input id="evolution_trials_per_group" type="number" min="5" step="1" />
          </div>
          <div>
            <label for="evolution_min_improve_pct">Min Improve (%)</label>
            <input id="evolution_min_improve_pct" type="number" min="1" step="1" />
          </div>
          <div>
            <label for="evolution_min_trades">Min Trades</label>
            <input id="evolution_min_trades" type="number" min="10" step="1" />
          </div>
          <div>
            <label for="evolution_max_dd">Max Drawdown (e.g. 0.2 = 20%)</label>
            <input id="evolution_max_dd" type="number" min="0.05" max="1" step="0.01" />
          </div>
          <div>
            <label><input id="evolution_require_sharpe" type="checkbox" /> Require Sharpe Improve</label>
          </div>
          <div>
            <label for="tuning_train_days">OOS Train Window (days)</label>
            <input id="tuning_train_days" type="number" min="30" step="1" />
          </div>
          <div>
            <label for="tuning_oos_days">OOS Window (days)</label>
            <input id="tuning_oos_days" type="number" min="7" step="1" />
          </div>
          <div>
            <label for="tuning_embargo_days">Embargo (days)</label>
            <input id="tuning_embargo_days" type="number" min="0" step="1" />
          </div>
          <div>
            <label for="tuning_trials">Tuning Trials</label>
            <input id="tuning_trials" type="number" min="1" step="1" />
          </div>
          <div>
            <label for="tuning_oos_min_trades">OOS Min Trades</label>
            <input id="tuning_oos_min_trades" type="number" min="1" step="1" />
          </div>
          <div>
            <label for="tuning_mdd_cap">OOS MDD Cap (e.g. -0.15 = -15%)</label>
            <input id="tuning_mdd_cap" type="number" max="0" step="0.01" />
          </div>
          <div>
            <label for="tuning_delta_min">OOS Delta Min (score)</label>
            <input id="tuning_delta_min" type="number" step="0.001" />
          </div>
          <div>
            <label for="tuning_seed">Tuning Seed</label>
            <input id="tuning_seed" type="number" min="0" step="1" />
          </div>
          <div>
            <label for="trainer_cooldown_minutes_on_boot">Worker Cooldown On Boot (min)</label>
            <input id="trainer_cooldown_minutes_on_boot" type="number" min="0" step="1" />
          </div>
          <div>
            <label for="confirm">LIVE confirm (required for LIVE)</label>
            <input id="confirm" type="text" placeholder="LIVE UPBIT SEED=1000000" />
          </div>
          <div class="actions">
            <button class="secondary" onclick="saveSettings()">Save Settings</button>
          </div>
          <div class="muted" id="settingsMsg">-</div>
        </div>
      </div>
      <div class="card">
        <h3>Debug</h3>
        <div class="log" id="debugLog">-</div>
      </div>
    </div>
    <div id="liveConfirmBackdrop" class="modal-backdrop">
      <div class="modal">
        <h3>Live Mode Start Confirm</h3>
        <p class="muted">LIVE 모드 시작은 2단 확인이 필요합니다.</p>
        <label for="liveConfirmPhrase">Confirm phrase</label>
        <input id="liveConfirmPhrase" type="text" />
        <div class="actions" style="margin-top: 8px;">
          <button onclick="confirmLiveStart()">Confirm and Start</button>
          <button class="secondary" onclick="closeLiveConfirm()">Cancel</button>
        </div>
        <div class="muted" id="liveConfirmMsg">Expected: -</div>
      </div>
    </div>
  </main>
  <script>
    async function fetchJson(url, options) {
      const res = await fetch(url, options || {});
      const data = await res.json();
      if (!res.ok) throw data;
      return data;
    }

    const MODELS_CACHE = {
      ts: 0,
      data: null,
    };
    const WATCHLIST_UI = {
      filter: "actionable",
      pinActionable: true,
      selectedSymbol: null,
      prevScore100: {},
      lastRows: [],
      lastSettings: null,
      lastMaxScore: 0,
    };
    const BLOCK_REASON_DICT = {
      "pump_chase": "급등 직후 추격 구간이라 진입 차단",
      "cooling_wait_rebreak": "쿨링 구간. 박스 재돌파 확인 전까지 대기",
      "guard_no_atr_gap": "ATR 신뢰 부족 + 갭상승 위험으로 차단",
    };

    function setPill(el, state) {
      el.className = "pill " + state;
    }

    function fmtAge(sec) {
      if (sec === null || sec === undefined) return "-";
      return sec.toFixed(1) + "s";
    }

    function fmtPct(v, digits=2) {
      if (v === null || v === undefined || Number.isNaN(Number(v))) return "-";
      return (Number(v) * 100).toFixed(digits) + "%";
    }

    function fmtSigned(v, digits=3) {
      if (v === null || v === undefined || Number.isNaN(Number(v))) return "-";
      const n = Number(v);
      const s = n > 0 ? "+" : "";
      return s + n.toFixed(digits);
    }

    function fmtKrw(v) {
      if (v === null || v === undefined || Number.isNaN(Number(v))) return "-";
      return Number(v).toLocaleString() + " KRW";
    }

    function fmtPrice(v, digits=0) {
      if (v === null || v === undefined || Number.isNaN(Number(v))) return "-";
      return Number(v).toLocaleString(undefined, {
        minimumFractionDigits: 0,
        maximumFractionDigits: digits,
      });
    }

    function _watchStatus(item) {
      return String((item && item.status) || "BUY").toUpperCase();
    }

    function _watchIsActionable(item) {
      return _watchStatus(item) !== "BLOCKED";
    }

    function _watchFilterLabel(key) {
      const k = String(key || "actionable").toLowerCase();
      if (k === "all") return "All";
      if (k === "blocked") return "Blocked";
      if (k === "reentry") return "ReEntry";
      return "Actionable";
    }

    function _watchFilterMatch(item) {
      const status = _watchStatus(item);
      const filter = String(WATCHLIST_UI.filter || "actionable").toLowerCase();
      if (filter === "all") return true;
      if (filter === "blocked") return status === "BLOCKED";
      if (filter === "reentry") return status === "REENTRY";
      return status !== "BLOCKED";
    }

    function _splitReasonCodes(raw) {
      const txt = String(raw || "").trim();
      if (!txt) return [];
      return txt.split(",").map(s => String(s || "").trim()).filter(Boolean);
    }

    function explainBlockReason(raw) {
      const codes = _splitReasonCodes(raw);
      if (codes.length === 0) {
        return { text: "", codes: [] };
      }
      const text = codes.map(c => BLOCK_REASON_DICT[c] || c).join(" + ");
      return { text, codes };
    }

    function applyWatchPinButton() {
      const pinBtn = document.getElementById("watchPinActionable");
      if (!pinBtn) return;
      const on = !!WATCHLIST_UI.pinActionable;
      pinBtn.classList.toggle("active", on);
      pinBtn.textContent = "Pin Actionable: " + (on ? "ON" : "OFF");
    }

    function applyWatchFilterButtons() {
      const key = String(WATCHLIST_UI.filter || "actionable").toLowerCase();
      const map = {
        all: document.getElementById("watchFilterAll"),
        actionable: document.getElementById("watchFilterActionable"),
        blocked: document.getElementById("watchFilterBlocked"),
        reentry: document.getElementById("watchFilterReentry"),
      };
      Object.entries(map).forEach(([k, el]) => {
        if (!el) return;
        el.classList.toggle("active", k === key);
      });
      applyWatchPinButton();
    }

    function toggleWatchPinActionable() {
      WATCHLIST_UI.pinActionable = !WATCHLIST_UI.pinActionable;
      applyWatchPinButton();
      renderWatchlist(WATCHLIST_UI.lastRows, WATCHLIST_UI.lastSettings, WATCHLIST_UI.lastMaxScore);
    }

    function setWatchFilter(key) {
      const k = String(key || "actionable").toLowerCase();
      const normalized = (k === "all" || k === "blocked" || k === "reentry" || k === "actionable")
        ? k
        : "actionable";
      WATCHLIST_UI.filter = normalized;
      applyWatchFilterButtons();
      renderWatchlist(WATCHLIST_UI.lastRows, WATCHLIST_UI.lastSettings, WATCHLIST_UI.lastMaxScore);
    }

    function selectWatchSymbol(sym) {
      const s = String(sym || "").trim();
      if (!s) return;
      WATCHLIST_UI.selectedSymbol = s;
      renderWatchlist(WATCHLIST_UI.lastRows, WATCHLIST_UI.lastSettings, WATCHLIST_UI.lastMaxScore);
    }

    function renderWatchDetail(item) {
      const titleEl = document.getElementById("watchDetailTitle");
      const bodyEl = document.getElementById("watchDetailBody");
      if (!titleEl || !bodyEl) return;
      if (!item) {
        titleEl.textContent = "Entry Plan";
        bodyEl.textContent = "Select a symbol row to inspect plan.";
        return;
      }

      const status = _watchStatus(item);
      const plan = (item && typeof item.entry_plan === "object" && item.entry_plan) ? item.entry_plan : {};
      const current = Number(plan.current_price);
      const anchor = Number(plan.anchor_price);
      const atr = Number(plan.atr_exec);
      const l1 = Number(plan.l1_price);
      const l2 = Number(plan.l2_price);
      const l3 = Number(plan.l3_price);
      const l1w = Number(plan.l1_weight || 0.4);
      const l2w = Number(plan.l2_weight || 0.3);
      const l3w = Number(plan.l3_weight || 0.3);
      const ttl = Number(plan.ttl_days || 1);
      const chaseK = Number(plan.chase_atr_k || 0);
      const chasePx = Number(plan.chase_cancel_price);
      const slK = Number(plan.sl_atr_k || 0);
      const slPx = Number(plan.stop_loss_price);
      const basis = String(plan.basis || "T-1 close + ATR(exec)");
      const validAtr = !!plan.valid_atr;
      const riskAnchorPct = (Number.isFinite(anchor) && anchor > 0 && Number.isFinite(slPx))
        ? ((anchor - slPx) / anchor) * 100.0
        : null;
      const riskCurrentPct = (Number.isFinite(current) && current > 0 && Number.isFinite(slPx))
        ? ((current - slPx) / current) * 100.0
        : null;
      const distL1Pct = (Number.isFinite(current) && current > 0 && Number.isFinite(l1))
        ? ((l1 / current) - 1.0) * 100.0
        : null;
      const distL2Pct = (Number.isFinite(current) && current > 0 && Number.isFinite(l2))
        ? ((l2 / current) - 1.0) * 100.0
        : null;
      const distL3Pct = (Number.isFinite(current) && current > 0 && Number.isFinite(l3))
        ? ((l3 / current) - 1.0) * 100.0
        : null;

      const antiRaw = String(item.anti_chase_reason || "");
      const antiInfo = explainBlockReason(antiRaw);
      const antiText = antiInfo.text || antiRaw || "-";
      const antiCodes = antiInfo.codes.length ? antiInfo.codes.join(", ") : "-";
      const reentryRaw = String(item.reentry_reason || "");
      const reasonText = status === "BLOCKED"
        ? ("Blocked: " + antiText)
        : (reentryRaw ? ("ReEntry: " + reentryRaw) : String(item.reason || "-"));

      titleEl.textContent = `${String(item.symbol || "-")} | ${status} | Entry Plan`;
      bodyEl.innerHTML = `
        <div class="watch-detail-grid">
          <div><b>Basis</b>: ${escHtml(basis)}</div>
          <div><b>Current</b>: ${fmtPrice(current, 2)} KRW</div>
          <div><b>Anchor</b>: ${fmtPrice(anchor, 2)} KRW</div>
          <div><b>ATR(exec)</b>: ${validAtr ? (fmtPrice(atr, 2) + " KRW") : "N/A"}</div>
          <div><b>L1 (40%)</b>: ${fmtPrice(l1, 2)} KRW</div>
          <div><b>L2 (30%)</b>: ${fmtPrice(l2, 2)} KRW</div>
          <div><b>L3 (30%)</b>: ${fmtPrice(l3, 2)} KRW</div>
          <div><b>L1 Dist vs Now</b>: ${distL1Pct === null ? "-" : fmtSigned(distL1Pct, 2) + "%"}</div>
          <div><b>L2 Dist vs Now</b>: ${distL2Pct === null ? "-" : fmtSigned(distL2Pct, 2) + "%"}</div>
          <div><b>L3 Dist vs Now</b>: ${distL3Pct === null ? "-" : fmtSigned(distL3Pct, 2) + "%"}</div>
          <div><b>TTL</b>: ${Number.isFinite(ttl) ? ttl.toFixed(0) : "1"} day</div>
          <div><b>Chase Guard</b>: ${fmtPrice(chasePx, 2)} KRW (k=${Number.isFinite(chaseK) ? chaseK.toFixed(2) : "-"})</div>
          <div><b>Stop Loss</b>: ${fmtPrice(slPx, 2)} KRW (k=${Number.isFinite(slK) ? slK.toFixed(2) : "-"})</div>
          <div><b>Risk (Anchor→SL)</b>: ${riskAnchorPct === null ? "-" : riskAnchorPct.toFixed(2) + "%"}</div>
          <div><b>Risk (Now→SL)</b>: ${riskCurrentPct === null ? "-" : riskCurrentPct.toFixed(2) + "%"}</div>
        </div>
        <div class="watch-detail-note">
          ${escHtml(reasonText)}<br/>
          Block Codes: ${escHtml(antiCodes)} | Score ${Number(item.score_100 || 0).toFixed(1)}/100 (${fmtSigned(item.delta_score_100, 1)})
        </div>
      `;
    }

    function renderWatchlist(wlInput, settingsInput, maxScoreInput) {
      const wl = Array.isArray(wlInput) ? wlInput : [];
      const settings = settingsInput || {};
      const maxScore = Number(maxScoreInput || 0);
      WATCHLIST_UI.lastRows = wl;
      WATCHLIST_UI.lastSettings = settings;
      WATCHLIST_UI.lastMaxScore = maxScore;

      const prevScoreMap = WATCHLIST_UI.prevScore100 || {};
      const nextScoreMap = {};
      wl.forEach((w) => {
        const sym = String(w.symbol || "");
        const score100 = Number(w.score_100 || 0);
        if (!sym) {
          w.delta_score_100 = null;
          return;
        }
        const prev = prevScoreMap[sym];
        w.delta_score_100 = Number.isFinite(prev) ? (score100 - prev) : null;
        nextScoreMap[sym] = score100;
      });
      WATCHLIST_UI.prevScore100 = nextScoreMap;

      const filtered = wl.filter(_watchFilterMatch);
      let ordered = filtered.slice();
      if (WATCHLIST_UI.pinActionable) {
        ordered.sort((a, b) => {
          const pa = _watchIsActionable(a) ? 0 : 1;
          const pb = _watchIsActionable(b) ? 0 : 1;
          if (pa !== pb) return pa - pb;
          const ra = Number(a.rank || 0);
          const rb = Number(b.rank || 0);
          if (ra !== rb) return ra - rb;
          return 0;
        });
      }

      const orderedSymbols = ordered.map(x => String(x.symbol || "")).filter(Boolean);
      if (!WATCHLIST_UI.selectedSymbol || !orderedSymbols.includes(WATCHLIST_UI.selectedSymbol)) {
        WATCHLIST_UI.selectedSymbol = orderedSymbols.length > 0 ? orderedSymbols[0] : null;
      }

      const tableEl = document.getElementById("watchlistTable");
      if (!tableEl) return;
      if (ordered.length === 0) {
        tableEl.innerHTML = "<div class='muted'>No rows for selected filter.</div>";
        renderWatchDetail(null);
      } else {
        const rows = ordered.map(w => {
          const hotClass = w.highlight ? "hot" : "";
          const autoClass = w.auto_buy_ok ? "auto" : "";
          const status = _watchStatus(w);
          const selectedClass = String(w.symbol || "") === String(WATCHLIST_UI.selectedSymbol || "") ? "selected" : "";
          const rowStatusClass = status === "BLOCKED" ? "blocked" : (status === "REENTRY" ? "reentry" : "");
          const statusClass = status === "BLOCKED" ? "blocked" : (status === "REENTRY" ? "reentry" : "buy");
          const statusBadge = `<span class="status-pill ${statusClass}">${status}</span>`;
          const grade = (w.grade || "-").toLowerCase();
          const autoBadge = w.auto_buy_ok ? "<span class='badge'>AUTO</span>" : "";
          const blockReason = String(w.anti_chase_reason || "");
          const blockInfo = explainBlockReason(blockReason);
          const reentryReason = String(w.reentry_reason || "");
          const reasonLine = blockReason
            ? ("Blocked: " + (blockInfo.text || blockReason))
            : (reentryReason ? ("ReEntry: " + reentryReason) : (w.reason || ""));
          const pumpState = String(w.pump_state || "NORMAL").toUpperCase();
          const penalty = Number(w.penalty_factor);
          const detail = String(w.detail || "");
          const delta = Number.isFinite(Number(w.delta_score_100)) ? Number(w.delta_score_100) : null;
          const deltaClass = (delta !== null && delta > 0.05)
            ? "delta-up"
            : ((delta !== null && delta < -0.05) ? "delta-down" : "delta-flat");
          const deltaText = delta === null ? "Δ -" : ("Δ " + fmtSigned(delta, 1));
          const blockCode = blockInfo.codes.length ? (" | Code " + blockInfo.codes.join(",")) : "";
          return `<div class="watch-row ${hotClass} ${autoClass} ${rowStatusClass} ${selectedClass}" data-sym="${escHtml(String(w.symbol || ""))}" title="${escHtml(detail)}">
            <div class="watch-rank">#${w.rank}</div>
            <div>${w.symbol} <span class="grade ${grade}">${(w.grade || "-")}</span>${statusBadge}${autoBadge}</div>
            <div class="watch-score">${(w.score_100 || 0).toFixed(1)} / 100<br/><span class="watch-sub ${deltaClass}">${deltaText}</span></div>
            <div class="watch-tag">${w.tag || "-"}</div>
            <div class="muted">${escHtml(reasonLine)}<br/><span class="watch-sub">${escHtml(pumpState)} | Penalty x${Number.isFinite(penalty) ? penalty.toFixed(2) : "1.00"}${escHtml(blockCode)}</span></div>
          </div>`;
        }).join("");
        tableEl.innerHTML = rows;
        tableEl.querySelectorAll(".watch-row[data-sym]").forEach((el) => {
          el.addEventListener("click", () => {
            const sym = String(el.getAttribute("data-sym") || "");
            if (sym) selectWatchSymbol(sym);
          });
        });
        const selectedItem = wl.find(x => String(x.symbol || "") === String(WATCHLIST_UI.selectedSymbol || ""));
        renderWatchDetail(selectedItem || ordered[0]);
      }

      const autoMin = (settings && settings.auto_buy_score_min_100 !== undefined)
        ? settings.auto_buy_score_min_100
        : 100;
      const blockedCount = wl.filter(x => _watchStatus(x) === "BLOCKED").length;
      const reentryCount = wl.filter(x => _watchStatus(x) === "REENTRY").length;
      const actionableCount = wl.length - blockedCount;
      const shownCount = ordered.length;
      const filterLabel = _watchFilterLabel(WATCHLIST_UI.filter);
      const pinLabel = WATCHLIST_UI.pinActionable ? "ON" : "OFF";
      const metaEl = document.getElementById("watchlistMeta");
      if (metaEl) {
        metaEl.textContent =
          "Filter: " + filterLabel +
          " | Pin Actionable: " + pinLabel +
          " | Shown " + shownCount + "/" + (wl.length || 0) +
          " (Actionable " + actionableCount +
          ", Blocked " + blockedCount +
          ", ReEntry " + reentryCount +
          ") | 100 = alert threshold | Auto-buy >= " + autoMin + "/100 (raw max " + maxScore.toFixed(3) + ")";
      }
    }

    function _labsResultDecision(lastResultObj) {
      const r = lastResultObj || {};
      const decision = String(r.gate_decision || r.decision || "").toUpperCase();
      const state = String(r.state || "").toUpperCase();
      if (state === "PROMOTED" || decision === "PROMOTE" || r.gate_pass === true) {
        return "PROMOTED";
      }
      if (state === "ARCHIVED" || decision === "FAIL" || decision === "KEEP_ACTIVE" || decision === "ARCHIVED") {
        return "ARCHIVED";
      }
      return "UNKNOWN";
    }

    function setLabsProgress(statusObj, lastResultObj=null) {
      const s = statusObj || {};
      const p = Math.max(0, Math.min(100, Number(s.progress_pct || 0)));
      const bar = document.getElementById("labsProgressBar");
      if (bar) bar.style.width = p.toFixed(1) + "%";
      const statusTxt = s.status || "IDLE";
      const stageTxt = s.stage ? ` | ${s.stage}` : "";
      const msgTxt = s.message ? ` | ${s.message}` : "";
      document.getElementById("labsProgressText").textContent = `${p.toFixed(1)}% | ${statusTxt}${stageTxt}${msgTxt}`;

      const runStateEl = document.getElementById("labsRunState");
      const runPillEl = document.getElementById("labsRunPill");
      const msgEl = document.getElementById("labsMsg");
      let runStateText = "IDLE";
      let runPillState = "warn";
      let msgClass = "";

      if (statusTxt === "FAILED") {
        runStateText = "ERROR (runtime failure)";
        runPillState = "bad";
        msgClass = "labs-note-error";
      } else if (statusTxt === "RUNNING") {
        const jobType = s.job_type ? ` (${String(s.job_type).toUpperCase()})` : "";
        runStateText = `RUNNING${jobType}`;
        runPillState = "warn";
      } else if (statusTxt === "DONE") {
        const d = _labsResultDecision(lastResultObj);
        if (d === "PROMOTED") {
          runStateText = "DONE (PROMOTED)";
          runPillState = "good";
        } else if (d === "ARCHIVED") {
          runStateText = "DONE (ARCHIVED / NO PROMOTION)";
          runPillState = "archive";
          msgClass = "labs-note-archived";
        } else {
          runStateText = "DONE";
          runPillState = "good";
        }
      } else {
        runStateText = statusTxt;
        runPillState = "warn";
      }

      if (runStateEl) runStateEl.textContent = runStateText;
      if (runPillEl) setPill(runPillEl, runPillState);
      if (msgEl) msgEl.className = msgClass ? `muted ${msgClass}` : "muted";
    }

    function renderLabsSummary(resultObj) {
      const result = resultObj || {};
      const comparison = result.model_comparison || null;
      const kpiEl = document.getElementById("labsKpiGrid");
      const headlineEl = document.getElementById("labsCompareHeadline");
      if (!comparison) {
        headlineEl.textContent = "No model comparison yet.";
        kpiEl.innerHTML = "";
        document.getElementById("labsSummary").textContent = JSON.stringify(result, null, 2);
        return;
      }

      const winner = String(comparison.winner || "tie").toLowerCase();
      const winnerClass = winner === "candidate" ? "compare-win" : (winner === "active" ? "compare-lose" : "compare-tie");
      const gateDecision = result.gate_decision || (result.gate_pass ? "PROMOTE" : "KEEP_ACTIVE");
      const gateReason = result.gate_reason ? ` | ${result.gate_reason}` : "";
      headlineEl.innerHTML =
        `Winner: <span class="${winnerClass}">${winner.toUpperCase()}</span> | Gate: ${gateDecision}${gateReason} | Rule: ${comparison.evaluation_rule || "-"}`;

      const d = comparison.delta || {};
      const cScore = comparison.candidate && comparison.candidate.score;
      const aScore = comparison.active && comparison.active.score;
      const cTrades = comparison.candidate && comparison.candidate.trades;
      const aTrades = comparison.active && comparison.active.trades;
      const cCostDrop = comparison.candidate && comparison.candidate.cost_drop;
      const aCostDrop = comparison.active && comparison.active.cost_drop;
      kpiEl.innerHTML = `
        <div class="kpi"><div class="k">Delta Score</div><div class="v">${fmtSigned(d.score, 4)}</div></div>
        <div class="kpi"><div class="k">Delta ROI</div><div class="v">${fmtPct(d.roi, 2)}</div></div>
        <div class="kpi"><div class="k">Delta abs(MDD)</div><div class="v">${fmtSigned(d.abs_mdd, 4)}</div></div>
        <div class="kpi"><div class="k">Delta CostDrop</div><div class="v">${fmtSigned(d.cost_drop, 4)}</div></div>
        <div class="kpi"><div class="k">Candidate Score</div><div class="v">${fmtSigned(cScore, 4)}</div></div>
        <div class="kpi"><div class="k">Active Score</div><div class="v">${fmtSigned(aScore, 4)}</div></div>
        <div class="kpi"><div class="k">CostDrop (C/A)</div><div class="v">${fmtSigned(cCostDrop, 4)} / ${fmtSigned(aCostDrop, 4)}</div></div>
        <div class="kpi"><div class="k">Trades (C/A)</div><div class="v">${cTrades ?? "-"} / ${aTrades ?? "-"}</div></div>
      `;

      const c = comparison.candidate || {};
      const a = comparison.active || {};
      const compact = {
        candidate: { score: c.score, roi: c.roi, mdd: c.mdd, cost_drop: c.cost_drop, trades: c.trades, win_rate: c.win_rate },
        active: { score: a.score, roi: a.roi, mdd: a.mdd, cost_drop: a.cost_drop, trades: a.trades, win_rate: a.win_rate },
        delta: d,
      };
      document.getElementById("labsSummary").textContent = JSON.stringify(compact, null, 2);
    }

    function switchLabsTab(tabKey) {
      const latestBtn = document.getElementById("labsTabBtnLatest");
      const historyBtn = document.getElementById("labsTabBtnHistory");
      const latestPane = document.getElementById("labsTabLatest");
      const historyPane = document.getElementById("labsTabHistory");
      const isHistory = tabKey === "history";
      latestBtn.classList.toggle("active", !isHistory);
      historyBtn.classList.toggle("active", isHistory);
      latestPane.classList.toggle("active", !isHistory);
      historyPane.classList.toggle("active", isHistory);
    }

    function escHtml(v) {
      return String(v ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function fmtDate(v) {
      if (!v) return "-";
      const d = new Date(v);
      if (Number.isNaN(d.getTime())) return String(v);
      return d.toLocaleString();
    }

    function _toNum(v, def = null) {
      const n = Number(v);
      return Number.isFinite(n) ? n : def;
    }

    function renderModelHistory(modelsPayload) {
      const p = modelsPayload || {};
      const rows = Array.isArray(p.history) ? p.history : [];
      const tbody = document.getElementById("modelHistoryTableBody");
      const meta = document.getElementById("modelHistoryMeta");
      meta.textContent =
        `Rows: ${rows.length} | Active Model: ${p.active_model_id || "-"} | Staging: ${(p.staging || []).length} | Archive: ${(p.archive || []).length}`;
      if (rows.length === 0) {
        tbody.innerHTML = "<tr><td colspan='13' class='muted'>No history yet.</td></tr>";
        return;
      }
      const html = rows.map((r) => {
        const decision = String(r.decision || (r.gate_pass ? "PROMOTE" : "FAIL")).toUpperCase();
        let decisionClass = "decision-fail";
        if (decision === "PROMOTE") decisionClass = "decision-promote";
        else if (decision === "KEEP_ACTIVE") decisionClass = "decision-keep";
        else if (decision === "ARCHIVED") decisionClass = "decision-archived";
        const score = _toNum(r.score, null);
        const activeScore = _toNum(r.active_score, null);
        const delta = _toNum(r.delta, null);
        const roi = _toNum(r.roi, null);
        const mdd = _toNum(r.mdd, null);
        const trades = _toNum(r.trades, null);
        const costDrop = _toNum(r.cost_drop, null);
        const pWeeks = _toNum(r.positive_weeks, null);
        const nWeeks = _toNum(r.negative_weeks, null);
        const worstWeek = _toNum(r.worst_week, null);
        const reason = String(r.reason || "-");
        return `<tr>
          <td>${escHtml(fmtDate(r.created_at))}</td>
          <td>${escHtml(r.run_id || "-")}</td>
          <td>${escHtml(r.bucket || "-")}</td>
          <td class="${decisionClass}">${escHtml(decision)}</td>
          <td>${score === null ? "-" : fmtSigned(score, 4)} / ${activeScore === null ? "-" : fmtSigned(activeScore, 4)}</td>
          <td>${delta === null ? "-" : fmtSigned(delta, 4)}</td>
          <td>${roi === null ? "-" : fmtPct(roi, 2)}</td>
          <td>${mdd === null ? "-" : fmtPct(mdd, 2)}</td>
          <td>${trades === null ? "-" : String(Math.trunc(trades))}</td>
          <td>${costDrop === null ? "-" : fmtSigned(costDrop, 4)}</td>
          <td>${pWeeks === null ? "-" : String(Math.trunc(pWeeks))} / ${nWeeks === null ? "-" : String(Math.trunc(nWeeks))}</td>
          <td>${worstWeek === null ? "-" : fmtPct(worstWeek, 2)}</td>
          <td title="${escHtml(reason)}">${escHtml(reason.length > 80 ? reason.slice(0, 77) + "..." : reason)}</td>
        </tr>`;
      }).join("");
      tbody.innerHTML = html;
    }

    async function refreshModelHistory(force=false) {
      const now = Date.now();
      if (!force && MODELS_CACHE.data && (now - MODELS_CACHE.ts) < 5000) {
        renderModelHistory(MODELS_CACHE.data);
        return;
      }
      try {
        const models = await fetchJson("/api/models");
        MODELS_CACHE.ts = now;
        MODELS_CACHE.data = models;
        renderModelHistory(models);
      } catch (err) {
        document.getElementById("modelHistoryMeta").textContent =
          "History load failed: " + (err.error || "unknown");
      }
    }

    async function loadSettings() {
      const data = await fetchJson("/api/settings");
      document.getElementById("mode").value = data.mode || "PAPER";
      const ex = (data.exchange || "UPBIT").toUpperCase();
      const upbitEl = document.getElementById("exchange_upbit");
      const bithumbEl = document.getElementById("exchange_bithumb");
      if (upbitEl && bithumbEl) {
        upbitEl.checked = ex === "UPBIT";
        bithumbEl.checked = ex === "BITHUMB";
      }
      document.getElementById("seed").value = data.seed_krw || 1000000;
      document.getElementById("watchlist").value = (data.watchlist || []).join(", ");
      document.getElementById("watch_refresh_sec").value = data.watch_refresh_sec || 60;
      document.getElementById("watch_score_min").value = data.watch_score_min || 1.0;
      document.getElementById("watch_alert_score").value = data.watch_alert_score || 2.0;
      document.getElementById("watch_highlight_top").value = data.watch_highlight_top || 3;
      document.getElementById("watch_alert_cooldown_min").value = data.watch_alert_cooldown_min || 60;
      document.getElementById("auto_buy_score_min_100").value = data.auto_buy_score_min_100 || 100;
      document.getElementById("watch_exclude_symbols").value = (data.watch_exclude_symbols || []).join(", ");
      document.getElementById("auto_data_update_enabled").checked = !!data.auto_data_update_enabled;
      document.getElementById("auto_data_update_interval_min").value = data.auto_data_update_interval_min || 60;
      document.getElementById("evolution_enabled").checked = !!data.evolution_enabled;
      document.getElementById("evolution_interval_hours").value = data.evolution_interval_hours || 24;
      document.getElementById("evolution_anchor_time").value = data.evolution_anchor_time || "09:00";
      document.getElementById("evolution_lookback_days").value = data.evolution_lookback_days || 180;
      document.getElementById("evolution_trials_per_group").value = data.evolution_trials_per_group || 20;
      document.getElementById("evolution_min_improve_pct").value = data.evolution_min_improve_pct || 5;
      document.getElementById("evolution_min_trades").value = data.evolution_min_trades || 50;
      document.getElementById("evolution_max_dd").value = data.evolution_max_dd || 0.2;
      document.getElementById("evolution_require_sharpe").checked = !!data.evolution_require_sharpe;
      document.getElementById("tuning_train_days").value = data.tuning_train_days || 180;
      document.getElementById("tuning_oos_days").value = data.tuning_oos_days || 28;
      document.getElementById("tuning_embargo_days").value = data.tuning_embargo_days || 2;
      document.getElementById("tuning_trials").value = data.tuning_trials || 30;
      document.getElementById("tuning_oos_min_trades").value = data.tuning_oos_min_trades || 20;
      document.getElementById("tuning_mdd_cap").value = data.tuning_mdd_cap ?? -0.15;
      document.getElementById("tuning_delta_min").value = (data.tuning_delta_min ?? 0.01);
      document.getElementById("tuning_seed").value = data.tuning_seed || 42;
      document.getElementById("trainer_cooldown_minutes_on_boot").value = data.trainer_cooldown_minutes_on_boot || 15;
    }

    async function saveSettings() {
      const upbitEl = document.getElementById("exchange_upbit");
      const bithumbEl = document.getElementById("exchange_bithumb");
      const upbitOn = upbitEl ? upbitEl.checked : false;
      const bithumbOn = bithumbEl ? bithumbEl.checked : false;
      if (!upbitOn && !bithumbOn) {
        document.getElementById("settingsMsg").textContent = "Select at least one exchange.";
        return;
      }
      if (upbitOn && bithumbOn) {
        document.getElementById("settingsMsg").textContent = "Select only one exchange (multi-exchange not supported yet).";
        return;
      }
      const selectedExchange = upbitOn ? "UPBIT" : "BITHUMB";
      const payload = {
        mode: document.getElementById("mode").value,
        exchange: selectedExchange,
        seed_krw: parseInt(document.getElementById("seed").value || "0", 10),
        watchlist: document.getElementById("watchlist").value,
        watch_refresh_sec: parseInt(document.getElementById("watch_refresh_sec").value || "60", 10),
        watch_score_min: parseFloat(document.getElementById("watch_score_min").value || "1.0"),
        watch_alert_score: parseFloat(document.getElementById("watch_alert_score").value || "2.0"),
        watch_highlight_top: parseInt(document.getElementById("watch_highlight_top").value || "3", 10),
        watch_alert_cooldown_min: parseInt(document.getElementById("watch_alert_cooldown_min").value || "60", 10),
        auto_buy_score_min_100: parseInt(document.getElementById("auto_buy_score_min_100").value || "100", 10),
        watch_exclude_symbols: document.getElementById("watch_exclude_symbols").value,
        auto_data_update_enabled: document.getElementById("auto_data_update_enabled").checked,
        auto_data_update_interval_min: parseInt(document.getElementById("auto_data_update_interval_min").value || "60", 10),
        evolution_enabled: document.getElementById("evolution_enabled").checked,
        evolution_interval_hours: parseInt(document.getElementById("evolution_interval_hours").value || "24", 10),
        evolution_anchor_time: document.getElementById("evolution_anchor_time").value || "09:00",
        evolution_lookback_days: parseInt(document.getElementById("evolution_lookback_days").value || "180", 10),
        evolution_trials_per_group: parseInt(document.getElementById("evolution_trials_per_group").value || "20", 10),
        evolution_min_improve_pct: parseInt(document.getElementById("evolution_min_improve_pct").value || "5", 10),
        evolution_min_trades: parseInt(document.getElementById("evolution_min_trades").value || "50", 10),
        evolution_max_dd: parseFloat(document.getElementById("evolution_max_dd").value || "0.2"),
        evolution_require_sharpe: document.getElementById("evolution_require_sharpe").checked,
        tuning_train_days: parseInt(document.getElementById("tuning_train_days").value || "180", 10),
        tuning_oos_days: parseInt(document.getElementById("tuning_oos_days").value || "28", 10),
        tuning_embargo_days: parseInt(document.getElementById("tuning_embargo_days").value || "2", 10),
        tuning_trials: parseInt(document.getElementById("tuning_trials").value || "30", 10),
        tuning_oos_min_trades: parseInt(document.getElementById("tuning_oos_min_trades").value || "20", 10),
        tuning_mdd_cap: parseFloat(document.getElementById("tuning_mdd_cap").value || "-0.15"),
        tuning_delta_min: parseFloat(document.getElementById("tuning_delta_min").value || "0.01"),
        tuning_seed: parseInt(document.getElementById("tuning_seed").value || "42", 10),
        trainer_cooldown_minutes_on_boot: parseInt(document.getElementById("trainer_cooldown_minutes_on_boot").value || "15", 10)
      };
      try {
        await fetchJson("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        document.getElementById("settingsMsg").textContent = "Saved.";
      } catch (err) {
        document.getElementById("settingsMsg").textContent = "Save failed: " + (err.error || "unknown");
      }
      await refresh();
    }

    const PANIC_HOLD_MS = 3000;
    let panicHoldTimer = null;
    let panicHoldProgressTimer = null;
    let pendingLiveAction = "start";

    function buildLiveConfirmPhrase(settings = null) {
      const exEl = document.getElementById("exchange") || document.getElementById("exchangeInput");
      const mode = String((settings && settings.mode) || document.getElementById("mode").value || "PAPER").toUpperCase();
      const exchange = String((settings && settings.exchange) || "UPBIT").toUpperCase();
      const seed = String((settings && settings.seed_krw) || document.getElementById("seed").value || "1000000");
      if (mode !== "LIVE") return "";
      return `LIVE ${exchange} SEED=${seed}`;
    }

    async function loadLiveSettings() {
      try {
        return await fetchJson("/api/settings");
      } catch {
        return null;
      }
    }

    async function requestStart() {
      pendingLiveAction = "start";
      const settings = await loadLiveSettings();
      const mode = String((settings && settings.mode) || document.getElementById("mode").value || "PAPER").toUpperCase();
      if (mode !== "LIVE") {
        await doStart("");
        return;
      }

      const expected = buildLiveConfirmPhrase(settings);
      const input = document.getElementById("liveConfirmPhrase");
      if (input) {
        input.value = "";
        input.placeholder = expected || "LIVE <exchange> SEED=<seed>";
        document.getElementById("liveConfirmMsg").textContent = "Expected: " + (expected || "-");
        document.getElementById("liveConfirmBackdrop").classList.add("active");
      }
      document.getElementById("actionMsg").textContent = "LIVE 2차 확인이 필요합니다. confirm 문구를 입력하세요.";
    }

    function closeLiveConfirm() {
      const backdrop = document.getElementById("liveConfirmBackdrop");
      if (backdrop) backdrop.classList.remove("active");
    }

    async function confirmLiveStart() {
      const expected = buildLiveConfirmPhrase(await loadLiveSettings());
      const input = document.getElementById("liveConfirmPhrase");
      const typed = String(input ? input.value : "").trim();
      if (!typed) {
        document.getElementById("liveConfirmMsg").textContent = "Confirm phrase is required for LIVE.";
        return;
      }
      document.getElementById("liveConfirmMsg").textContent = "Confirming...";
      if (pendingLiveAction === "restart") {
        await doRestart(typed);
      } else {
        await doStart(typed, expected);
      }
      closeLiveConfirm();
    }

    async function doStart(confirmValue = "", expected = "") {
      const payload = { confirm: confirmValue };
      try {
        const res = await fetchJson("/api/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (expected && confirmValue && confirmValue !== expected) {
          document.getElementById("actionMsg").textContent = "Confirm mismatch. " + (res.message || "Started.");
        } else {
          document.getElementById("actionMsg").textContent = res.message || "Started.";
        }
      } catch (err) {
        document.getElementById("actionMsg").textContent = "Start failed: " + (err.error || "unknown");
      }
      await refresh();
    }

    function updatePanicSliderLabel() {
      const slider = document.getElementById("panicSlider");
      const pct = slider ? Number(slider.value || 0) : 0;
      document.getElementById("panicSliderValue").textContent = `Panic slider: ${pct}%`;
      const msg = document.getElementById("panicStatus");
      if (!msg) return;
      msg.textContent = pct >= 80 ? "READY: hold 3 seconds to trigger panic." : "Move slider to READY first (80~100).";
    }

    function clearPanicHold() {
      if (panicHoldTimer) {
        clearTimeout(panicHoldTimer);
        panicHoldTimer = null;
      }
      if (panicHoldProgressTimer) {
        clearInterval(panicHoldProgressTimer);
        panicHoldProgressTimer = null;
      }
      const btn = document.getElementById("panicBtn");
      const status = document.getElementById("panicStatus");
      if (btn) btn.textContent = "Panic Exit";
      if (status) status.textContent = "Hold to panic: move slider to READY and press 3 seconds.";
      updatePanicSliderLabel();
    }

    function startPanicHold() {
      const slider = document.getElementById("panicSlider");
      const current = Number(slider ? slider.value : 0);
      if (current < 80) {
        const status = document.getElementById("panicStatus");
        if (status) status.textContent = "Panic slider not ready.";
        return;
      }
      clearPanicHold();
      const btn = document.getElementById("panicBtn");
      if (btn) btn.disabled = true;
      const startedAt = Date.now();
      const finishAt = startedAt + PANIC_HOLD_MS;
      const update = () => {
        const remain = Math.max(0, finishAt - Date.now());
        const status = document.getElementById("panicStatus");
        if (status) status.textContent = `Panic trigger: ${(remain / 1000).toFixed(1)}s`; 
      };
      update();
      panicHoldProgressTimer = setInterval(update, 80);
      panicHoldTimer = setTimeout(async () => {
        clearPanicHold();
        await triggerPanic();
      }, PANIC_HOLD_MS);
    }

    async function cancelPanicHold() {
      clearPanicHold();
    }

    async function triggerPanic() {
      try {
        const slider = Number(document.getElementById("panicSlider").value || 0);
        const res = await fetchJson("/api/panic", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slider })
        });
        document.getElementById("actionMsg").textContent = res.message || "Panic triggered.";
      } catch (err) {
        document.getElementById("actionMsg").textContent = "Panic failed: " + (err.error || "unknown");
      }
      await refresh();
      await refreshOrders();
    }

    async function stopBot() {
      try {
        const res = await fetchJson("/api/stop", { method: "POST" });
        document.getElementById("actionMsg").textContent = res.message || "Stopped.";
      } catch (err) {
        document.getElementById("actionMsg").textContent = "Stop failed: " + (err.error || "unknown");
      }
      await refresh();
      await refreshOrders();
    }

    async function doRestart(confirmValue = "") {
      try {
        const res = await fetchJson("/api/restart", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirm: confirmValue })
        });
        document.getElementById("actionMsg").textContent = res.message || "Restarted.";
      } catch (err) {
        document.getElementById("actionMsg").textContent = "Restart failed: " + (err.error || "unknown");
      }
      await refresh();
      await refreshOrders();
    }

    async function manualRestart() {
      const settings = await loadLiveSettings();
      const mode = String((settings && settings.mode) || document.getElementById("mode").value || "PAPER").toUpperCase();
      if (mode !== "LIVE") {
        await doRestart("");
        return;
      }
      pendingLiveAction = "restart";
      const expected = buildLiveConfirmPhrase(settings);
      const input = document.getElementById("liveConfirmPhrase");
      if (input) {
        input.value = "";
        input.placeholder = expected || "LIVE <exchange> SEED=<seed>";
        document.getElementById("liveConfirmMsg").textContent = "Expected: " + (expected || "-");
        document.getElementById("liveConfirmBackdrop").classList.add("active");
      }
      document.getElementById("actionMsg").textContent = "LIVE restart requires 2차 확인.";
    }
    async function checkHealth() {
      try {
        const res = await fetchJson("/api/health_all", { method: "POST" });
        const up = res.upbit || {};
        const tg = res.telegram || {};
        document.getElementById("healthStatus").textContent = res.overall || "UNKNOWN";
        const bh = res.bithumb || {};
        const hl = res.hyperliquid || {};
        document.getElementById("healthMeta").textContent =
          `Upbit: ${up.status || "-"} (${up.latency_ms ?? "-"} ms) | Bithumb: ${bh.status || "-"} (${bh.latency_ms ?? "-"}) | Telegram: ${tg.status || "-"} | HL: ${hl.status || "-"}`;
        setPill(document.getElementById("healthPill"), res.overall === "OK" ? "good" : "warn");
      } catch (err) {
        document.getElementById("healthStatus").textContent = "ERROR";
        document.getElementById("healthMeta").textContent = err.error || "Health check failed.";
        setPill(document.getElementById("healthPill"), "bad");
      }
    }

    async function runBacktest() {
      try {
        const res = await fetchJson("/api/labs/run_backtest", { method: "POST" });
        document.getElementById("labsMsg").textContent = res.message || "Backtest started.";
        setLabsProgress({ progress_pct: 1, status: "RUNNING", stage: "queued", message: "Backtest queued" });
      } catch (err) {
        document.getElementById("labsMsg").textContent = "Backtest failed: " + (err.error || "unknown");
      }
      await refresh();
    }

    async function runEvolution() {
      try {
        const res = await fetchJson("/api/labs/run_evolution", { method: "POST" });
        document.getElementById("labsMsg").textContent = res.message || "Evolution started.";
        setLabsProgress({ progress_pct: 1, status: "RUNNING", stage: "queued", message: "Evolution queued" });
      } catch (err) {
        document.getElementById("labsMsg").textContent = "Evolution failed: " + (err.error || "unknown");
      }
      await refresh();
    }

    async function runDataUpdate() {
      try {
        const res = await fetchJson("/api/data/update", { method: "POST" });
        document.getElementById("dataMsg").textContent = res.message || "Data update started.";
      } catch (err) {
        document.getElementById("dataMsg").textContent = "Data update failed: " + (err.error || "unknown");
      }
      await refresh();
    }

    function orderStatusText(v) {
      if (v === undefined || v === null || v === "") return "-";
      if (typeof v === "number") return Number.isFinite(v) ? v.toString() : "-";
      return String(v);
    }

    function _escapeAttr(v) {
      return String(v || "")
        .replace(/&/g, "&amp;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }

    function _renderOrdersRows(orders) {
      const tbody = document.getElementById("ordersTableBody");
      if (!tbody) return;
      if (!Array.isArray(orders) || orders.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="muted">No open orders.</td></tr>';
        return;
      }
      tbody.innerHTML = orders.map((o, idx) => {
        const side = orderStatusText(o.side || o.side_type || "-");
        const kind = orderStatusText(o.type || o.order_type || "-");
        const symbol = orderStatusText(o.symbol || o.market || "-");
        const qty = orderStatusText(o.qty || o.amount || 0);
        const price = orderStatusText(o.price || o.avg_price || "-");
        const remaining = orderStatusText(o.remaining || o.remain_qty || 0);
        const created = orderStatusText(o.created_at || o.datetime || o.created || "-");
        const oid = _escapeAttr(String(o.order_id || o.id || `auto-${idx}`));
        const sym = _escapeAttr(String(o.symbol || o.market || ""));
        return `<tr><td>${symbol}</td><td>${side}</td><td>${kind}</td><td>${qty}</td><td>${price}</td><td>${remaining}</td><td>${created}</td><td><button class="danger" onclick="cancelOrder('${oid}', '${sym}')">Cancel</button></td></tr>`;
      }).join("");
    }

    async function refreshOrders() {
      try {
        const data = await fetchJson('/api/orders');
        const orders = data.orders || [];
        document.getElementById("ordersMeta").textContent = `Exchange: ${data.exchange || "-"} | Count: ${orders.length}`;
        _renderOrdersRows(orders);
      } catch (err) {
        document.getElementById("ordersMeta").textContent = "Orders load failed: " + (err.error || "unknown");
        const tbody = document.getElementById("ordersTableBody");
        if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="muted">Load failed.</td></tr>';
      }
    }

    async function cancelOrder(orderId, symbol = "") {
      try {
        const payload = { order_id: orderId, symbol };
        const res = await fetchJson('/api/orders/cancel', {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        document.getElementById("ordersMsg").textContent = res.message || "Cancel requested.";
      } catch (err) {
        document.getElementById("ordersMsg").textContent = "Cancel failed: " + (err.error || "unknown");
      }
      await refreshOrders();
    }

    async function cancelAllOrders() {
      try {
        const res = await fetchJson('/api/orders/cancel', {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ all: true })
        });
        document.getElementById("ordersMsg").textContent = res.message || "Cancel all requested.";
      } catch (err) {
        document.getElementById("ordersMsg").textContent = "Cancel all failed: " + (err.error || "unknown");
      }
      await refreshOrders();
    }

    function renderChart(seriesInput) {
      const el = document.getElementById("labsChart");
      let series = {};
      if (Array.isArray(seriesInput)) {
        series = { candidate: seriesInput };
      } else if (seriesInput && typeof seriesInput === "object") {
        series = seriesInput;
      }
      const candidate = Array.isArray(series.candidate) ? series.candidate : [];
      const active = Array.isArray(series.active) ? series.active : [];
      const hasCandidate = candidate.length >= 2;
      const hasActive = active.length >= 2;
      if (!hasCandidate && !hasActive) {
        el.textContent = "No chart data.";
        return;
      }
      const w = el.clientWidth || 300;
      const h = el.clientHeight || 140;
      const allPoints = [].concat(candidate, active);
      const min = Math.min(...allPoints);
      const max = Math.max(...allPoints);
      const span = (max - min) || 1;
      function toCoords(points) {
        const step = w / (points.length - 1);
        return points.map((p, i) => {
          const x = i * step;
          const y = h - ((p - min) / span) * (h - 10) - 5;
          return `${x.toFixed(1)},${y.toFixed(1)}`;
        }).join(" ");
      }
      const candidateLine = hasCandidate
        ? `<polyline fill="none" stroke="#4aa3ff" stroke-width="2" points="${toCoords(candidate)}" />`
        : "";
      const activeLine = hasActive
        ? `<polyline fill="none" stroke="#f1c40f" stroke-width="2" points="${toCoords(active)}" />`
        : "";
      const legend = `
        <div style="position:absolute;top:8px;right:8px;font-size:11px;color:#9db0c3;">
          ${hasCandidate ? "<span style='color:#4aa3ff;'>candidate</span>" : ""}
          ${hasCandidate && hasActive ? " | " : ""}
          ${hasActive ? "<span style='color:#f1c40f;'>active</span>" : ""}
        </div>
      `;
      el.style.position = "relative";
      el.innerHTML = `${legend}<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
        ${candidateLine}
        ${activeLine}
      </svg>`;
    }

    async function approveLive() {
      try {
        const res = await fetchJson("/api/labs/approve_live", { method: "POST" });
        document.getElementById("labsMsg").textContent = res.message || "LIVE params approved.";
      } catch (err) {
        document.getElementById("labsMsg").textContent = "Approve failed: " + (err.error || "unknown");
      }
      await refresh();
    }

    async function shutdownBackend() {
      if (!confirm("Shutdown backend? UI will disconnect until you manually restart.")) return;
      try {
        const res = await fetchJson("/api/shutdown", { method: "POST" });
        document.getElementById("actionMsg").textContent = res.message || "Backend shutting down.";
      } catch (err) {
        document.getElementById("actionMsg").textContent = "Shutdown failed: " + (err.error || "unknown");
      }
    }

    async function refresh() {
      try {
        const data = await fetchJson("/api/status");
        const b = data.backend || {};
        const r = data.runtime || {};

        document.getElementById("backendStatus").textContent = b.ok ? "OK" : "DOWN";
        document.getElementById("backendMeta").textContent = "PID " + (b.pid || "-") + " | Uptime " + fmtAge(b.uptime_sec);
        setPill(document.getElementById("backendPill"), b.ok ? "good" : "bad");

        document.getElementById("controllerStatus").textContent = data.controller_state || "UNKNOWN";
        document.getElementById("controllerMeta").textContent = "Owner " + (data.controller_owner || "-") + " | Mode " + (data.controller_mode || "-");
        setPill(document.getElementById("controllerPill"), data.controller_state === "RUNNING" ? "good" : "warn");

        const pf = data.portfolio || {};
        const pfPos = pf.position || {};
        const mode = String(pf.mode || data.controller_mode || r.mode || "UNKNOWN").toUpperCase();
        const isRunning = !!pf.running;
        const modeLabel = isRunning ? (mode + " RUNNING") : (mode + " STOPPED");
        document.getElementById("modeIndicator").textContent = modeLabel;
        if (!isRunning) {
          setPill(document.getElementById("modePill"), "warn");
        } else if (mode === "LIVE") {
          setPill(document.getElementById("modePill"), "live");
        } else if (mode === "PAPER") {
          setPill(document.getElementById("modePill"), "paper");
        } else {
          setPill(document.getElementById("modePill"), "good");
        }

        const pnlPct = Number(pf.pnl_pct !== undefined ? pf.pnl_pct : ((r.pnl_pct || 0) * 100));
        const equity = Number(pf.equity_krw !== undefined ? pf.equity_krw : (r.equity || 0));
        document.getElementById("pnlMeta").textContent =
          "Equity " + fmtKrw(equity) + " | Return " + (Number.isFinite(pnlPct) ? pnlPct.toFixed(2) + "%" : "-");

        let positionText = "Position FLAT";
        const qty = Number(pfPos.qty || 0);
        if (pfPos.has_position && qty > 0) {
          const sym = pfPos.symbol || "-";
          const avg = Number(pfPos.avg_entry_price || 0);
          positionText = "Position " + sym + " | Qty " + qty.toFixed(6) + " | Avg " + fmtKrw(avg);
        }
        document.getElementById("positionMeta").textContent = positionText;

        const lastUpdate = r.ts ? new Date(r.ts * 1000).toLocaleTimeString() : "-";
        document.getElementById("runtimeMeta").textContent = "Last update " + lastUpdate + " | Age " + fmtAge(data.runtime_age_sec);

        const lastTick = r.last_tick_ts ? new Date(r.last_tick_ts * 1000).toLocaleTimeString() : "-";
        document.getElementById("tickMeta").textContent = "Last tick " + lastTick;
        let errorMsg = r.last_error ? ("Last error: " + r.last_error) : "No recent error.";
        if (data.recent_errors && data.recent_errors.length > 0) {
          errorMsg = "Crash log: " + data.recent_errors[data.recent_errors.length - 1];
        }
        document.getElementById("errorMeta").textContent = errorMsg;

        if (data.health) {
          const up = data.health.upbit || {};
          const bh = data.health.bithumb || {};
          const tg = data.health.telegram || {};
          const hl = data.health.hyperliquid || {};
          document.getElementById("healthStatus").textContent = data.health.overall || "UNKNOWN";
          document.getElementById("healthMeta").textContent =
            `Upbit: ${up.status || "-"} (${up.latency_ms ?? "-"} ms) | Bithumb: ${bh.status || "-"} (${bh.latency_ms ?? "-"}) | Telegram: ${tg.status || "-"} | HL: ${hl.status || "-"}`;
          setPill(document.getElementById("healthPill"), data.health.overall === "OK" ? "good" : "warn");
        }

        const wl = data.watchlist_ranked || [];
        renderWatchlist(wl, data.settings || {}, data.watchlist_score_max || 0);
        applyWatchFilterButtons();

        if (data.labs) {
          const labsStatus = data.labs.status || {};
          const lastResult = data.labs.last_result || null;
          document.getElementById("labsStatus").textContent = JSON.stringify(labsStatus, null, 2);
          setLabsProgress(labsStatus, lastResult);
          if (labsStatus.message) {
            document.getElementById("labsMsg").textContent = labsStatus.message;
          }

          if (lastResult) {
            const chartSeries = lastResult.equity_curve_compare || lastResult.equity_curve || [];
            renderChart(chartSeries);
            renderLabsSummary(lastResult);
          } else {
            document.getElementById("labsCompareHeadline").textContent = "No labs result yet.";
            document.getElementById("labsKpiGrid").innerHTML = "";
            document.getElementById("labsSummary").textContent = "-";
          }
        }

        if (data.data_status) {
          document.getElementById("dataStatus").textContent = JSON.stringify(data.data_status, null, 2);
        }

        await refreshModelHistory(false);
        await refreshOrders();
        document.getElementById("debugLog").textContent = JSON.stringify(data, null, 2);
      } catch (err) {
        document.getElementById("debugLog").textContent = "Status fetch failed.";
      }
    }

    applyWatchFilterButtons();
    updatePanicSliderLabel();
    loadSettings().then(refresh);
    (function bindExchangeToggles() {
      const upbitEl = document.getElementById("exchange_upbit");
      const bithumbEl = document.getElementById("exchange_bithumb");
      if (!upbitEl || !bithumbEl) return;
      upbitEl.addEventListener("change", () => {
        if (upbitEl.checked) bithumbEl.checked = false;
      });
      bithumbEl.addEventListener("change", () => {
        if (bithumbEl.checked) upbitEl.checked = false;
      });
    })();
    setInterval(refresh, 1000);
  </script>
</body>
</html>
"""


def _safe_read_json(path: Path, default=None):
    try:
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _safe_write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False)
    last_error = None

    # Windows can transiently lock files (indexer/AV/other readers). Retry with
    # unique temp files to avoid tmp-name collisions across concurrent writers.
    for attempt in range(6):
        tmp_path = path.with_name(
            f"{path.stem}.{os.getpid()}.{threading.get_ident()}.{int(time.time() * 1000)}.{attempt}.tmp"
        )
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
            return
        except PermissionError as e:
            last_error = e
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            time.sleep(0.05 * (attempt + 1))
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise

    raise last_error or RuntimeError(f"Failed to write JSON file: {path}")


def load_settings():
    data = _safe_read_json(SETTINGS_PATH, default=None)
    if not data:
        data = {}
    merged = DEFAULT_SETTINGS.copy()
    merged.update(data)
    if not SETTINGS_PATH.exists():
        _safe_write_json(SETTINGS_PATH, merged)
    return merged


def _normalize_hhmm(value, default="09:00"):
    raw = str(value or "").strip()
    try:
        parts = raw.split(":")
        if len(parts) != 2:
            raise ValueError("invalid time format")
        hh = int(parts[0])
        mm = int(parts[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError("invalid time range")
        return f"{hh:02d}:{mm:02d}"
    except Exception:
        return default


def save_settings(data: dict):
    current = load_settings()
    settings = DEFAULT_SETTINGS.copy()
    settings.update(current)

    if "mode" in data:
        settings["mode"] = str(data.get("mode", settings["mode"])).upper()
    if "exchange" in data:
        settings["exchange"] = str(data.get("exchange", settings["exchange"])).upper()
    if "seed_krw" in data:
        settings["seed_krw"] = int(data.get("seed_krw", settings["seed_krw"]))

    if "watchlist" in data:
        watchlist_raw = data.get("watchlist", "")
        if isinstance(watchlist_raw, str):
            watchlist = [x.strip().upper() for x in watchlist_raw.split(",") if x.strip()]
        elif isinstance(watchlist_raw, list):
            watchlist = [str(x).strip().upper() for x in watchlist_raw if str(x).strip()]
        else:
            watchlist = settings["watchlist"]
        settings["watchlist"] = watchlist

    # Evolution settings
    if "evolution_enabled" in data:
        settings["evolution_enabled"] = bool(data.get("evolution_enabled"))
    if "evolution_interval_hours" in data:
        settings["evolution_interval_hours"] = max(
            1,
            int(data.get("evolution_interval_hours", settings["evolution_interval_hours"]))
        )
    if "evolution_anchor_time" in data:
        settings["evolution_anchor_time"] = _normalize_hhmm(
            data.get("evolution_anchor_time", settings.get("evolution_anchor_time", "09:00")),
            default=settings.get("evolution_anchor_time", "09:00"),
        )
    if "evolution_lookback_days" in data:
        settings["evolution_lookback_days"] = int(data.get("evolution_lookback_days", settings["evolution_lookback_days"]))
    if "evolution_trials_per_group" in data:
        settings["evolution_trials_per_group"] = int(data.get("evolution_trials_per_group", settings["evolution_trials_per_group"]))
    if "evolution_min_improve_pct" in data:
        settings["evolution_min_improve_pct"] = int(data.get("evolution_min_improve_pct", settings["evolution_min_improve_pct"]))
    if "evolution_min_trades" in data:
        settings["evolution_min_trades"] = int(data.get("evolution_min_trades", settings["evolution_min_trades"]))
    if "evolution_max_dd" in data:
        settings["evolution_max_dd"] = float(data.get("evolution_max_dd", settings["evolution_max_dd"]))
    if "evolution_require_sharpe" in data:
        settings["evolution_require_sharpe"] = bool(data.get("evolution_require_sharpe"))

    # OOS tuning policy
    if "tuning_seed" in data:
        settings["tuning_seed"] = int(data.get("tuning_seed", settings["tuning_seed"]))
    if "tuning_trials" in data:
        settings["tuning_trials"] = int(data.get("tuning_trials", settings["tuning_trials"]))
    if "tuning_train_days" in data:
        settings["tuning_train_days"] = int(data.get("tuning_train_days", settings["tuning_train_days"]))
    if "tuning_oos_days" in data:
        settings["tuning_oos_days"] = int(data.get("tuning_oos_days", settings["tuning_oos_days"]))
    if "tuning_embargo_days" in data:
        settings["tuning_embargo_days"] = int(data.get("tuning_embargo_days", settings["tuning_embargo_days"]))
    if "tuning_oos_min_trades" in data:
        settings["tuning_oos_min_trades"] = int(data.get("tuning_oos_min_trades", settings["tuning_oos_min_trades"]))
    if "tuning_mdd_cap" in data:
        settings["tuning_mdd_cap"] = min(0.0, float(data.get("tuning_mdd_cap", settings["tuning_mdd_cap"])))
    if "tuning_delta_min" in data:
        settings["tuning_delta_min"] = max(0.0, float(data.get("tuning_delta_min", settings["tuning_delta_min"])))
    if "tuning_promotion_cooldown_hours" in data:
        settings["tuning_promotion_cooldown_hours"] = max(
            0,
            int(data.get("tuning_promotion_cooldown_hours", settings["tuning_promotion_cooldown_hours"]))
        )
    if "tuning_min_symbols_for_watchlist" in data:
        settings["tuning_min_symbols_for_watchlist"] = max(
            1,
            int(data.get("tuning_min_symbols_for_watchlist", settings["tuning_min_symbols_for_watchlist"]))
        )
    if "tuning_watchlist_fallback_to_market" in data:
        settings["tuning_watchlist_fallback_to_market"] = bool(data.get("tuning_watchlist_fallback_to_market"))
    if "tuning_fallback_top_n" in data:
        settings["tuning_fallback_top_n"] = max(
            10,
            int(data.get("tuning_fallback_top_n", settings["tuning_fallback_top_n"]))
        )
    if "tuning_cadence_days" in data:
        settings["tuning_cadence_days"] = int(data.get("tuning_cadence_days", settings["tuning_cadence_days"]))
    if "trainer_cooldown_minutes_on_boot" in data:
        settings["trainer_cooldown_minutes_on_boot"] = int(
            data.get("trainer_cooldown_minutes_on_boot", settings["trainer_cooldown_minutes_on_boot"])
        )

    # Watchlist settings
    if "watch_refresh_sec" in data:
        settings["watch_refresh_sec"] = int(data.get("watch_refresh_sec", settings["watch_refresh_sec"]))
    if "watch_score_min" in data:
        settings["watch_score_min"] = float(data.get("watch_score_min", settings["watch_score_min"]))
    if "watch_alert_score" in data:
        settings["watch_alert_score"] = float(data.get("watch_alert_score", settings["watch_alert_score"]))
    if "watch_highlight_top" in data:
        settings["watch_highlight_top"] = int(data.get("watch_highlight_top", settings["watch_highlight_top"]))
    if "watch_alert_cooldown_min" in data:
        settings["watch_alert_cooldown_min"] = int(data.get("watch_alert_cooldown_min", settings["watch_alert_cooldown_min"]))
    if "auto_buy_score_min_100" in data:
        settings["auto_buy_score_min_100"] = int(data.get("auto_buy_score_min_100", settings["auto_buy_score_min_100"]))
    if "watch_exclude_symbols" in data:
        raw = data.get("watch_exclude_symbols", "")
        if isinstance(raw, str):
            settings["watch_exclude_symbols"] = [x.strip().upper() for x in raw.split(",") if x.strip()]
        elif isinstance(raw, list):
            settings["watch_exclude_symbols"] = [str(x).strip().upper() for x in raw if str(x).strip()]
    if "auto_data_update_enabled" in data:
        settings["auto_data_update_enabled"] = bool(data.get("auto_data_update_enabled"))
    if "auto_data_update_interval_min" in data:
        settings["auto_data_update_interval_min"] = int(data.get("auto_data_update_interval_min", settings["auto_data_update_interval_min"]))

    _safe_write_json(SETTINGS_PATH, settings)
    return settings


USER_CONFIG_PATH = ROOT_DIR / "user_config.json"


def _safe_tail(path: Path, max_lines=20):
    try:
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [line.rstrip("\n") for line in lines[-max_lines:]]
    except Exception:
        return []


def load_user_config():
    if USER_CONFIG_PATH.exists():
        try:
            with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_user_config(cfg: dict):
    with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


def config_to_params(cfg: dict):
    confirm_pct = cfg.get("confirm_pct_A", 0.5)
    # user_config stores percent (e.g. 20 means 0.20)
    if confirm_pct > 1:
        confirm_pct = confirm_pct / 100.0

    alloc_a = cfg.get("alloc_A", 60)
    if alloc_a > 100:
        alloc_a = 60
    alloc_b = 100 - alloc_a

    return {
        'enable_strategy_A': cfg.get('enable_A', True),
        'enable_strategy_B': cfg.get('enable_B', True),
        'trigger_vol_A': cfg.get('trig_vol_A', 2.0),
        'breakout_days_A': cfg.get('bo_days_A', 7),
        'close_confirm_pct_A': confirm_pct,
        'rsi_ceiling_A': cfg.get('rsi_cap_A', 75),
        'entry_delay_bars_A': cfg.get('delay_A', 1),
        'use_regime_filter_A': cfg.get('use_regime_filter_A', True),
        'trend_ma_fast_B': cfg.get('ma_fast_B', 20),
        'trend_ma_slow_B': cfg.get('ma_slow_B', 60),
        'rsi_entry_B': cfg.get('rsi_B', 45),
        'allocation_A_pct': alloc_a,
        'allocation_B_pct': alloc_b,
        'max_entries_per_day': cfg.get('max_entries', 2),
        'max_open_positions': cfg.get('max_pos', 3),
        'cooldown_days_after_sl': cfg.get('cooldown', 5),
        'daily_loss_limit_pct': cfg.get('loss_limit', 2.0),
        'min_turnover_krw': cfg.get('min_turnover', 10_000_000),
        'universe_top_n': cfg.get('universe_top_n', 0),
        'sl_atr_mult_A': cfg.get('sl_mul_A', 1.8),
        'trail_atr_mult_A': cfg.get('trail_mul_A', 2.5),
        'partial_tp_r_A': cfg.get('tp_r_A', 1.2),
        'time_stop_days_A': cfg.get('time_A', 3),
        'sl_atr_mult_B': cfg.get('sl_mul_B', 1.4),
        'partial_tp_r_B': cfg.get('tp_r_B', 1.0),
        'max_hold_days_B': cfg.get('max_hold_B', 5),
        # Anti-chase / re-entry controls
        'pump_high_pct_th': cfg.get('pump_high_pct_th', 0.15),
        'chase_ret_1d_th': cfg.get('chase_ret_1d_th', 0.12),
        'chase_gap_pct_th': cfg.get('chase_gap_pct_th', 0.08),
        'chase_ext_atr_k': cfg.get('chase_ext_atr_k', 1.8),
        'chase_rsi_th': cfg.get('chase_rsi_th', 78),
        'no_atr_gap_block_th': cfg.get('no_atr_gap_block_th', 0.01),
        'cooling_pullback_min': cfg.get('cooling_pullback_min', 0.06),
        'cooling_box_lookback': cfg.get('cooling_box_lookback', 5),
        'reentry_breakout_buffer': cfg.get('reentry_breakout_buffer', 0.002),
        'reentry_vol_mult': cfg.get('reentry_vol_mult', 1.2),
        'reentry_rsi_max': cfg.get('reentry_rsi_max', 72),
        'rearmed_ttl_days': cfg.get('rearmed_ttl_days', 1),
        'reentry_score_boost': cfg.get('reentry_score_boost', 1.15),
    }


def params_to_config(params: dict, base_cfg: dict):
    cfg = dict(base_cfg)
    alloc_a = params.get("allocation_A_pct", cfg.get("alloc_A", 60))
    if alloc_a > 100:
        alloc_a = 60
    cfg.update({
        'trig_vol_A': params.get('trigger_vol_A', cfg.get('trig_vol_A', 2.0)),
        'bo_days_A': params.get('breakout_days_A', cfg.get('bo_days_A', 7)),
        'delay_A': params.get('entry_delay_bars_A', cfg.get('delay_A', 1)),
        'rsi_cap_A': params.get('rsi_ceiling_A', cfg.get('rsi_cap_A', 75)),
        'use_regime_filter_A': params.get('use_regime_filter_A', cfg.get('use_regime_filter_A', True)),
        'ma_fast_B': params.get('trend_ma_fast_B', cfg.get('ma_fast_B', 20)),
        'ma_slow_B': params.get('trend_ma_slow_B', cfg.get('ma_slow_B', 60)),
        'rsi_B': params.get('rsi_entry_B', cfg.get('rsi_B', 45)),
        'alloc_A': alloc_a,
        'max_entries': params.get('max_entries_per_day', cfg.get('max_entries', 2)),
        'max_pos': params.get('max_open_positions', cfg.get('max_pos', 3)),
        'cooldown': params.get('cooldown_days_after_sl', cfg.get('cooldown', 5)),
        'loss_limit': params.get('daily_loss_limit_pct', cfg.get('loss_limit', 2.0)),
        'min_turnover': params.get('min_turnover_krw', cfg.get('min_turnover', 10_000_000)),
        'universe_top_n': params.get('universe_top_n', cfg.get('universe_top_n', 0)),
        'sl_mul_A': params.get('sl_atr_mult_A', cfg.get('sl_mul_A', 1.8)),
        'trail_mul_A': params.get('trail_atr_mult_A', cfg.get('trail_mul_A', 2.5)),
        'tp_r_A': params.get('partial_tp_r_A', cfg.get('tp_r_A', 1.2)),
        'time_A': params.get('time_stop_days_A', cfg.get('time_A', 3)),
        'sl_mul_B': params.get('sl_atr_mult_B', cfg.get('sl_mul_B', 1.4)),
        'tp_r_B': params.get('partial_tp_r_B', cfg.get('tp_r_B', 1.0)),
        'max_hold_B': params.get('max_hold_days_B', cfg.get('max_hold_B', 5)),
        # Anti-chase / re-entry controls
        'pump_high_pct_th': params.get('pump_high_pct_th', cfg.get('pump_high_pct_th', 0.15)),
        'chase_ret_1d_th': params.get('chase_ret_1d_th', cfg.get('chase_ret_1d_th', 0.12)),
        'chase_gap_pct_th': params.get('chase_gap_pct_th', cfg.get('chase_gap_pct_th', 0.08)),
        'chase_ext_atr_k': params.get('chase_ext_atr_k', cfg.get('chase_ext_atr_k', 1.8)),
        'chase_rsi_th': params.get('chase_rsi_th', cfg.get('chase_rsi_th', 78)),
        'no_atr_gap_block_th': params.get('no_atr_gap_block_th', cfg.get('no_atr_gap_block_th', 0.01)),
        'cooling_pullback_min': params.get('cooling_pullback_min', cfg.get('cooling_pullback_min', 0.06)),
        'cooling_box_lookback': params.get('cooling_box_lookback', cfg.get('cooling_box_lookback', 5)),
        'reentry_breakout_buffer': params.get('reentry_breakout_buffer', cfg.get('reentry_breakout_buffer', 0.002)),
        'reentry_vol_mult': params.get('reentry_vol_mult', cfg.get('reentry_vol_mult', 1.2)),
        'reentry_rsi_max': params.get('reentry_rsi_max', cfg.get('reentry_rsi_max', 72)),
        'rearmed_ttl_days': params.get('rearmed_ttl_days', cfg.get('rearmed_ttl_days', 1)),
        'reentry_score_boost': params.get('reentry_score_boost', cfg.get('reentry_score_boost', 1.15)),
    })

    if "close_confirm_pct_A" in params:
        cfg["confirm_pct_A"] = params["close_confirm_pct_A"] * 100
    return cfg


def _compute_sharpe(returns):
    if not returns or len(returns) < 2:
        return 0.0
    import math
    mean = sum(returns) / len(returns)
    var = sum((x - mean) ** 2 for x in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(len(returns))


def _compute_metrics(res):
    trades = res.get("trade_list", []) or []
    returns = [t.get("return", 0.0) for t in trades]
    sharpe = _compute_sharpe(returns)
    max_dd = 0.0
    if trades:
        try:
            max_dd = min([t.get("max_dd", 0.0) for t in trades])
        except Exception:
            max_dd = 0.0
    return {
        "trades": res.get("trades", 0),
        "total_return": res.get("total_return", 0.0),
        "win_rate": res.get("win_rate", 0.0),
        "sharpe": sharpe,
        "max_dd": max_dd
    }


def _compute_equity_curve(trades):
    curve = []
    equity = 1.0
    for t in trades:
        equity *= (1 + (t.get("return", 0.0) or 0.0))
        curve.append(round(equity, 6))
    return curve


def _metric_val(metrics, key, default=0.0):
    if not isinstance(metrics, dict):
        return float(default)
    try:
        return float(metrics.get(key, default) or default)
    except Exception:
        return float(default)


def _build_model_comparison(candidate_metrics, baseline_metrics):
    cand = candidate_metrics or {}
    base = baseline_metrics or {}

    cand_score = _metric_val(cand, "score", 0.0)
    base_score = _metric_val(base, "score", 0.0)
    cand_roi = _metric_val(cand, "roi", 0.0)
    base_roi = _metric_val(base, "roi", 0.0)
    cand_mdd = abs(_metric_val(cand, "mdd", 0.0))
    base_mdd = abs(_metric_val(base, "mdd", 0.0))
    cand_trades = int(_metric_val(cand, "trades", 0))
    base_trades = int(_metric_val(base, "trades", 0))
    cand_win = _metric_val(cand, "win_rate", 0.0)
    base_win = _metric_val(base, "win_rate", 0.0)
    cand_cost_drop = _metric_val(cand, "cost_drop", 0.0)
    base_cost_drop = _metric_val(base, "cost_drop", 0.0)

    delta_score = cand_score - base_score
    delta_roi = cand_roi - base_roi
    delta_mdd = cand_mdd - base_mdd
    delta_trades = cand_trades - base_trades
    delta_win = cand_win - base_win
    delta_cost_drop = cand_cost_drop - base_cost_drop

    winner = "tie"
    if delta_score > 1e-12:
        winner = "candidate"
    elif delta_score < -1e-12:
        winner = "active"
    else:
        # Tie-breakers when score is identical.
        if delta_roi > 1e-12:
            winner = "candidate"
        elif delta_roi < -1e-12:
            winner = "active"
        elif delta_mdd < -1e-12:
            winner = "candidate"
        elif delta_mdd > 1e-12:
            winner = "active"
        elif delta_cost_drop < -1e-12:
            winner = "candidate"
        elif delta_cost_drop > 1e-12:
            winner = "active"

    return {
        "evaluation_rule": "score=ROI-0.5*abs(MDD)-0.2*CostDrop, higher is better",
        "winner": winner,
        "candidate": {
            "score": cand_score,
            "roi": cand_roi,
            "mdd": _metric_val(cand, "mdd", 0.0),
            "cost_drop": cand_cost_drop,
            "trades": cand_trades,
            "win_rate": cand_win,
        },
        "active": {
            "score": base_score,
            "roi": base_roi,
            "mdd": _metric_val(base, "mdd", 0.0),
            "cost_drop": base_cost_drop,
            "trades": base_trades,
            "win_rate": base_win,
        },
        "delta": {
            "score": delta_score,
            "roi": delta_roi,
            "abs_mdd": delta_mdd,
            "cost_drop": delta_cost_drop,
            "trades": delta_trades,
            "win_rate": delta_win,
        },
    }


def _prepare_symbol_dfs(raw_dfs, params):
    from strategy import Strategy
    strat = Strategy()
    analyzed = {}
    for sym, df in raw_dfs.items():
        if df is None or df.empty:
            continue
        if str(sym).upper().startswith("GLOBAL_BTC"):
            continue
        try:
            analyzed[sym] = strat.analyze(df, params=params)
        except Exception:
            continue
    return analyzed


def _run_backtest_with_params(raw_dfs, params, lookback_days: int):
    from backtester import Backtester
    bt = Backtester()
    symbol_dfs = _prepare_symbol_dfs(raw_dfs, params)
    if not symbol_dfs:
        raise RuntimeError("No usable symbol data for backtest.")
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=lookback_days)
    return bt.run_portfolio(symbol_dfs, params, start_date=start_dt, end_date=end_dt, verbose=False)


def _load_data_map():
    from data_loader import load_data_map
    return load_data_map()


LABS_RUNTIME = {
    "running": False,
    "job_type": None,
    "job_id": None
}
LABS_RUNTIME_LOCK = threading.Lock()

HEALTH_CACHE = {
    "ts": 0,
    "data": None
}

DATA_RUNTIME = {
    "running": False,
    "last_msg": None
}
DATA_RUNTIME_LOCK = threading.Lock()

WATCH_CACHE = {
    "ts": 0,
    "list": [],
    "last_alert": {},
    "last_list": {},
    "last_sell_alert": {},
}


def _labs_runtime_snapshot():
    with LABS_RUNTIME_LOCK:
        return {
            "running": bool(LABS_RUNTIME.get("running")),
            "job_type": LABS_RUNTIME.get("job_type"),
            "job_id": LABS_RUNTIME.get("job_id"),
        }


def _reserve_labs_job(job_type: str):
    normalized = str(job_type or "").strip().lower()
    if normalized not in {"evolution", "backtest"}:
        raise ValueError(f"Unsupported labs job type: {job_type}")
    prefix = "evo" if normalized == "evolution" else "bt"
    with LABS_RUNTIME_LOCK:
        if LABS_RUNTIME["running"]:
            return None
        job_id = f"{prefix}_{int(time.time() * 1000)}"
        LABS_RUNTIME["running"] = True
        LABS_RUNTIME["job_type"] = normalized
        LABS_RUNTIME["job_id"] = job_id
        return {"job_type": normalized, "job_id": job_id}


def _release_labs_job():
    with LABS_RUNTIME_LOCK:
        LABS_RUNTIME["running"] = False
        LABS_RUNTIME["job_type"] = None
        LABS_RUNTIME["job_id"] = None


def _is_data_running():
    with DATA_RUNTIME_LOCK:
        return bool(DATA_RUNTIME.get("running"))


def _reserve_data_job():
    with DATA_RUNTIME_LOCK:
        if DATA_RUNTIME["running"]:
            return False
        DATA_RUNTIME["running"] = True
        DATA_RUNTIME["last_msg"] = "RUNNING"
        return True


def _release_data_job(last_msg=None):
    with DATA_RUNTIME_LOCK:
        DATA_RUNTIME["running"] = False
        if last_msg is not None:
            DATA_RUNTIME["last_msg"] = str(last_msg)


def _write_labs_status(payload: dict):
    LABS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _safe_write_json(LABS_STATUS_PATH, payload)
    except Exception as e:
        _log_labs(f"WARN labs status write failed: {e}")


def _read_labs_status():
    return _safe_read_json(LABS_STATUS_PATH, default={})


def _set_labs_status(status: dict, progress_pct=None, stage=None, message=None, **extra):
    if progress_pct is not None:
        try:
            p = float(progress_pct)
        except Exception:
            p = 0.0
        status["progress_pct"] = max(0.0, min(100.0, p))
    if stage is not None:
        status["stage"] = str(stage)
    if message is not None:
        status["message"] = str(message)
    status["updated_at"] = datetime.now().isoformat()
    if extra:
        status.update(extra)
    _write_labs_status(status)


def _log_labs(message: str):
    log_dir = RESULTS_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "labs.log"
    ts = datetime.now().isoformat()
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{ts} {message}\n")


def _notify_labs(title: str, metrics=None):
    try:
        notifier = TelegramNotifier()
        if notifier and notifier.bot_token and notifier.chat_id:
            msg = title
            if metrics:
                msg += f"\nMetrics: {metrics}"
            notifier.emit_event("LABS", "SYSTEM", "EVOLUTION", msg, severity="INFO")
    except Exception:
        pass


def _log_health(message: str):
    log_dir = RESULTS_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "health.log"
    ts = datetime.now().isoformat()
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"{ts} {message}\n")


def _evaluate_candidates(base_params, raw_dfs, settings, seed=42):
    from autotune import AutoTuner

    trials_per_group = int(settings.get("evolution_trials_per_group", 20))
    tuner = AutoTuner(raw_dfs, base_params, output_dir="autotune_runs")

    all_trials = []
    for group in ["A", "B", "C"]:
        trials = tuner.generate_trials(group, trials_per_group, seed=seed)
        for t in trials:
            # Normalize confirm pct if out of expected fractional range
            if t.get("close_confirm_pct_A", 0) > 0.05:
                t["close_confirm_pct_A"] = t["close_confirm_pct_A"] / 100.0
            all_trials.append(t)

    return all_trials


def _resolve_labs_universe(raw_dfs: dict, settings: dict):
    def _latest_turnover(df):
        if df is None or len(df) == 0:
            return 0.0
        try:
            if "turnover_exec" in df.columns:
                s = pd.to_numeric(df["turnover_exec"], errors="coerce")
            elif "turnover" in df.columns:
                s = pd.to_numeric(df["turnover"], errors="coerce")
            elif "close" in df.columns and "volume" in df.columns:
                s = pd.to_numeric(df["close"], errors="coerce") * pd.to_numeric(df["volume"], errors="coerce")
            else:
                return 0.0
            s = s.dropna()
            if len(s) == 0:
                return 0.0
            return float(s.iloc[-1])
        except Exception:
            return 0.0

    requested = settings.get("watchlist") or []
    try:
        min_symbols = max(1, int(settings.get("tuning_min_symbols_for_watchlist", 5)))
    except Exception:
        min_symbols = 5
    fallback_enabled = bool(settings.get("tuning_watchlist_fallback_to_market", True))

    scoped_watch = select_universe(raw_dfs, universe=requested)
    watch_count = len(scoped_watch)
    if watch_count >= min_symbols:
        return {
            "universe": requested,
            "scoped_raw": scoped_watch,
            "mode": "watchlist",
            "fallback": False,
            "reason": None,
            "symbol_count": watch_count,
            "watchlist_count": len(requested),
            "min_symbols": min_symbols,
        }

    if watch_count > 0 and not fallback_enabled:
        return {
            "universe": requested,
            "scoped_raw": scoped_watch,
            "mode": "watchlist",
            "fallback": False,
            "reason": f"fallback_disabled ({watch_count}<{min_symbols})",
            "symbol_count": watch_count,
            "watchlist_count": len(requested),
            "min_symbols": min_symbols,
        }

    scoped_all = select_universe(raw_dfs, universe=None)
    try:
        top_n = max(10, int(settings.get("tuning_fallback_top_n", 80)))
    except Exception:
        top_n = 80
    if len(scoped_all) > top_n:
        ranked = sorted(scoped_all.items(), key=lambda kv: _latest_turnover(kv[1]), reverse=True)
        scoped_all = dict(ranked[:top_n])
    return {
        "universe": None,
        "scoped_raw": scoped_all,
        "mode": "market_top_n",
        "fallback": True,
        "reason": f"watchlist_too_narrow ({watch_count}<{min_symbols}), fallback_top_n={top_n}",
        "symbol_count": len(scoped_all),
        "watchlist_count": len(requested),
        "min_symbols": min_symbols,
    }


def _run_evolution_job(settings: dict, job_id: str):
    status = {
        "job_id": job_id,
        "job_type": "evolution",
        "status": "RUNNING",
        "started_at": datetime.now().isoformat(),
        "message": "Evolution running",
        "stage": "init",
        "progress_pct": 0.0,
        "last_evolution_ts": time.time(),
    }
    _set_labs_status(status, progress_pct=1, stage="init", message="Evolution job started")

    try:
        _set_labs_status(status, progress_pct=5, stage="load_data", message="Loading market data")
        raw_dfs = _load_data_map()
        if not raw_dfs:
            raise RuntimeError("No data available. Run data update first.")

        _set_labs_status(status, progress_pct=10, stage="load_config", message="Loading configs and active model")
        base_cfg = load_user_config()
        base_params = config_to_params(base_cfg)
        model_mgr = ModelManager(base_dir=ROOT_DIR / "models")
        prev_active_params = model_mgr.load_active_params() or dict(base_params)
        universe_info = _resolve_labs_universe(raw_dfs, settings)
        scoped_raw = universe_info.get("scoped_raw") or {}
        if not scoped_raw:
            raise RuntimeError("No symbols left after universe/market filters.")

        if universe_info.get("fallback"):
            _set_labs_status(
                status,
                progress_pct=15,
                stage="tuning",
                message=(
                    "Starting OOS tuning cycle "
                    f"(watchlist->market fallback, symbols={universe_info.get('symbol_count', 0)})"
                ),
            )
            _log_labs(
                "Universe fallback enabled: "
                f"{universe_info.get('reason')} -> mode={universe_info.get('mode')} "
                f"symbols={universe_info.get('symbol_count')}"
            )
        else:
            _set_labs_status(
                status,
                progress_pct=15,
                stage="tuning",
                message=f"Starting OOS tuning cycle (mode={universe_info.get('mode')}, symbols={universe_info.get('symbol_count', 0)})",
            )

        def _on_tuning_progress(pct, stage_name, msg):
            mapped = 20.0 + (max(0.0, min(100.0, float(pct))) * 0.52)
            _set_labs_status(
                status,
                progress_pct=mapped,
                stage=f"tuning:{stage_name}",
                message=f"Tuning - {msg}",
            )

        cycle = run_tuning_cycle(
            raw_dfs=raw_dfs,
            base_params=base_params,
            model_manager=model_mgr,
            strategy_name="KRW_SPOT_LONG_ONLY",
            global_seed=int(settings.get("tuning_seed", 42)),
            universe=universe_info.get("universe"),
            train_days=int(settings.get("tuning_train_days", 180)),
            oos_days=int(settings.get("tuning_oos_days", 28)),
            embargo_days=int(settings.get("tuning_embargo_days", 2)),
            n_trials=int(settings.get("tuning_trials", 30)),
            oos_min_trades=int(settings.get("tuning_oos_min_trades", 20)),
            mdd_cap=float(settings.get("tuning_mdd_cap", -0.15)),
            delta_min=float(settings.get("tuning_delta_min", 0.01)),
            promotion_cooldown_hours=int(settings.get("tuning_promotion_cooldown_hours", 24)),
            progress_cb=_on_tuning_progress,
        )
        _set_labs_status(status, progress_pct=74, stage="tuning_done", message="Tuning done. Running auto backtest")

        windows = cycle.get("windows", {})
        serialized_windows = {k: str(v) for k, v in windows.items()}
        candidate_params = cycle.get("candidate_params") or {}
        best_params = candidate_params if cycle.get("gate_pass") else None
        best_metrics = cycle.get("candidate_oos_metrics")
        base_metrics = cycle.get("active_oos_metrics")
        _safe_write_json(LABS_LAST_BASELINE_PATH, base_metrics or {})

        candidate_bt_metrics = None
        candidate_curve = []
        if candidate_params:
            _set_labs_status(status, progress_pct=82, stage="auto_backtest:candidate", message="Auto backtest candidate model")
            candidate_bt_metrics, candidate_bt_res = evaluate_params(
                scoped_raw,
                candidate_params,
                windows["oos_start"],
                windows["oos_end"],
                include_cost_stress=True,
            )
            candidate_curve = _compute_equity_curve(candidate_bt_res.get("trade_list", []) or [])

        _set_labs_status(status, progress_pct=90, stage="auto_backtest:active", message="Auto backtest previous active model")
        active_bt_metrics, active_bt_res = evaluate_params(
            scoped_raw,
            prev_active_params,
            windows["oos_start"],
            windows["oos_end"],
            include_cost_stress=True,
        )
        active_curve = _compute_equity_curve(active_bt_res.get("trade_list", []) or [])
        comparison = _build_model_comparison(
            candidate_bt_metrics or best_metrics,
            active_bt_metrics or base_metrics,
        )

        if cycle.get("gate_pass") and best_params:
            new_cfg = params_to_config(best_params, base_cfg)
            save_user_config(new_cfg)
            pending = {
                "created_at": datetime.now().isoformat(),
                "params": best_params,
                "metrics": best_metrics,
                "run_id": cycle.get("run_id"),
                "windows": serialized_windows,
            }
            _safe_write_json(LABS_PENDING_LIVE_PATH, pending)

        _set_labs_status(status, progress_pct=96, stage="write_results", message="Writing result artifacts")
        result_payload = {
            "base_metrics": base_metrics,
            "best_metrics": best_metrics,
            "best_params": best_params,
            "applied_to_paper": bool(cycle.get("gate_pass")),
            "pending_live": bool(cycle.get("gate_pass")),
            "equity_curve": candidate_curve or active_curve,
            "equity_curve_compare": {
                "candidate": candidate_curve,
                "active": active_curve,
            },
            "oos_policy": {
                "train_days": int(settings.get("tuning_train_days", 180)),
                "oos_days": int(settings.get("tuning_oos_days", 28)),
                "embargo_days": int(settings.get("tuning_embargo_days", 2)),
                "min_trades": int(settings.get("tuning_oos_min_trades", 20)),
                "mdd_cap": float(settings.get("tuning_mdd_cap", -0.15)),
                "delta_min": float(settings.get("tuning_delta_min", 0.01)),
                "promotion_cooldown_hours": int(settings.get("tuning_promotion_cooldown_hours", 24)),
                "universe_mode": universe_info.get("mode"),
                "symbol_count": int(universe_info.get("symbol_count", 0)),
                "watchlist_fallback": bool(universe_info.get("fallback")),
                "watchlist_fallback_reason": universe_info.get("reason"),
            },
            "windows": serialized_windows,
            "gate_pass": bool(cycle.get("gate_pass")),
            "gate_decision": cycle.get("decision"),
            "gate_reason": cycle.get("decision_reason"),
            "gate_delta": cycle.get("gate_delta"),
            "gate_reasons": cycle.get("gate_reasons", []),
            "weekly_pnl": cycle.get("weekly_pnl", []),
            "positive_weeks": cycle.get("positive_weeks", 0),
            "negative_weeks": cycle.get("negative_weeks", 0),
            "worst_week": cycle.get("worst_week", 0.0),
            "run_id": cycle.get("run_id"),
            "state": cycle.get("state"),
            "auto_backtest": {
                "window": {
                    "oos_start": str(windows.get("oos_start")),
                    "oos_end": str(windows.get("oos_end")),
                    "data_end": str(windows.get("data_end")),
                },
                "candidate_metrics": candidate_bt_metrics,
                "active_metrics": active_bt_metrics,
            },
            "model_comparison": comparison,
        }
        _safe_write_json(LABS_LAST_RESULT_PATH, result_payload)

        status["ended_at"] = datetime.now().isoformat()
        status["status"] = "DONE"
        winner = (comparison or {}).get("winner", "tie").upper()
        if cycle.get("gate_pass"):
            status["message"] = (
                "OOS tuning + auto backtest complete. "
                f"Candidate promoted to ACTIVE. Comparison winner: {winner}."
            )
            _log_labs(f"OOS tuning PASS. run_id={cycle.get('run_id')} promoted.")
            _notify_labs("OOS tuning PASS. Active model updated.", best_metrics)
        else:
            reasons = ", ".join(cycle.get("gate_reasons", [])) or "gate_failed"
            status["message"] = (
                "OOS tuning + auto backtest complete. "
                f"Candidate archived (no promotion): {reasons}. Comparison winner: {winner}."
            )
            _log_labs(f"OOS tuning FAIL. run_id={cycle.get('run_id')} reasons={reasons}")
        status["best_metrics"] = best_metrics
        _set_labs_status(status, progress_pct=100, stage="done")

    except Exception as e:
        status["status"] = "FAILED"
        status["ended_at"] = datetime.now().isoformat()
        status["message"] = f"Evolution failed: {e}"
        status["trace"] = traceback.format_exc()
        _set_labs_status(status, stage="failed")
        _log_labs(f"Evolution failed: {e}")
    finally:
        _release_labs_job()


def _run_backtest_job(settings: dict, job_id: str):
    status = {
        "job_id": job_id,
        "job_type": "backtest",
        "status": "RUNNING",
        "started_at": datetime.now().isoformat(),
        "message": "Backtest running",
        "stage": "init",
        "progress_pct": 0.0,
    }
    _set_labs_status(status, progress_pct=1, stage="init", message="Backtest job started")

    try:
        _set_labs_status(status, progress_pct=10, stage="load_data", message="Loading market data")
        raw_dfs = _load_data_map()
        if not raw_dfs:
            raise RuntimeError("No data available. Run data update first.")

        _set_labs_status(status, progress_pct=20, stage="load_config", message="Loading active model/config")
        base_cfg = load_user_config()
        base_params = config_to_params(base_cfg)
        model_mgr = ModelManager(base_dir=ROOT_DIR / "models")
        active_params = model_mgr.load_active_params() or base_params

        _set_labs_status(status, progress_pct=35, stage="build_universe", message="Applying universe filter")
        universe_info = _resolve_labs_universe(raw_dfs, settings)
        scoped_raw = universe_info.get("scoped_raw") or {}
        if not scoped_raw:
            raise RuntimeError("No symbols left after universe filter.")
        if universe_info.get("fallback"):
            _log_labs(
                "Backtest universe fallback enabled: "
                f"{universe_info.get('reason')} -> mode={universe_info.get('mode')} "
                f"symbols={universe_info.get('symbol_count')}"
            )

        _set_labs_status(status, progress_pct=50, stage="build_windows", message="Computing OOS window")
        data_end = latest_data_timestamp(scoped_raw)
        windows = build_split_windows(
            data_end_ts=data_end,
            train_days=int(settings.get("tuning_train_days", 180)),
            oos_days=int(settings.get("tuning_oos_days", 28)),
            embargo_days=int(settings.get("tuning_embargo_days", 2)),
        )
        _set_labs_status(status, progress_pct=65, stage="evaluate", message="Running OOS backtest")
        metrics, res = evaluate_params(
            scoped_raw,
            active_params,
            windows["oos_start"],
            windows["oos_end"],
            include_cost_stress=True,
        )
        equity_curve = _compute_equity_curve(res.get("trade_list", []) or [])

        _set_labs_status(status, progress_pct=90, stage="write_results", message="Writing result artifacts")
        result_payload = {
            "base_metrics": metrics,
            "best_metrics": None,
            "best_params": active_params,
            "applied_to_paper": False,
            "pending_live": False,
            "equity_curve": equity_curve,
            "window": {
                "oos_start": str(windows["oos_start"]),
                "oos_end": str(windows["oos_end"]),
                "data_end": str(windows["data_end"]),
            },
            "universe_mode": universe_info.get("mode"),
            "universe_symbol_count": int(universe_info.get("symbol_count", 0)),
            "watchlist_fallback": bool(universe_info.get("fallback")),
            "watchlist_fallback_reason": universe_info.get("reason"),
            "active_model_id": model_mgr.active_model_id(),
        }
        _safe_write_json(LABS_LAST_RESULT_PATH, result_payload)
        _safe_write_json(LABS_LAST_BASELINE_PATH, metrics)

        status["status"] = "DONE"
        status["ended_at"] = datetime.now().isoformat()
        status["message"] = "Backtest complete (latest OOS 4-week window)."
        status["best_metrics"] = metrics
        _set_labs_status(status, progress_pct=100, stage="done")
        _log_labs(
            f"Backtest completed for OOS window {windows['oos_start'].date()}~{windows['oos_end'].date()}."
        )

    except Exception as e:
        status["status"] = "FAILED"
        status["ended_at"] = datetime.now().isoformat()
        status["message"] = f"Backtest failed: {e}"
        status["trace"] = traceback.format_exc()
        _set_labs_status(status, stage="failed")
        _log_labs(f"Backtest failed: {e}")
    finally:
        _release_labs_job()


def _write_data_status(payload: dict):
    LABS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _safe_write_json(DATA_STATUS_PATH, payload)
    except Exception as e:
        # Never kill data-update thread due to transient status-file lock.
        _log_labs(f"WARN data status write failed: {e}")


def _run_data_update_job():
    status = {
        "status": "RUNNING",
        "started_at": datetime.now().isoformat(),
        "message": "Data update running"
    }
    _write_data_status(status)

    try:
        from data_loader import update_data

        def _progress(p, msg):
            status["progress"] = float(p)
            status["message"] = msg
            status["updated_at"] = datetime.now().isoformat()
            _write_data_status(status)

        update_data(progress_callback=_progress)

        status["status"] = "DONE"
        status["ended_at"] = datetime.now().isoformat()
        status["message"] = "Data update complete"
        _write_data_status(status)
    except Exception as e:
        status["status"] = "FAILED"
        status["ended_at"] = datetime.now().isoformat()
        status["message"] = f"Data update failed: {e}"
        status["trace"] = traceback.format_exc()
        _write_data_status(status)
    finally:
        _release_data_job(last_msg=status.get("message"))


def _parse_iso_ts(ts):
    try:
        return datetime.fromisoformat(ts).timestamp()
    except Exception:
        return 0.0


def data_update_scheduler():
    while True:
        try:
            settings = load_settings()
            if not settings.get("auto_data_update_enabled", False):
                time.sleep(10)
                continue

            if _is_data_running():
                time.sleep(10)
                continue

            interval_min = int(settings.get("auto_data_update_interval_min", 60))
            status = build_data_payload()
            last_ts = 0.0
            for key in ("ended_at", "updated_at", "started_at"):
                if status.get(key):
                    last_ts = _parse_iso_ts(status.get(key))
                    if last_ts:
                        break

            if time.time() - last_ts >= interval_min * 60:
                if _reserve_data_job():
                    try:
                        t = threading.Thread(target=_run_data_update_job, daemon=True)
                        t.start()
                    except Exception:
                        _release_data_job(last_msg="thread_start_failed")
        except Exception:
            pass

        time.sleep(30)


def health_check_all(force=False, send_telegram=False):
    now = time.time()
    if not force and HEALTH_CACHE["data"] and (now - HEALTH_CACHE["ts"] < 10):
        return HEALTH_CACHE["data"]

    upbit_access = os.getenv("UPBIT_ACCESS") or os.getenv("UPBIT_ACCESS_KEY")
    upbit_secret = os.getenv("UPBIT_SECRET") or os.getenv("UPBIT_SECRET_KEY")

    upbit_status = {"status": "missing", "latency_ms": None}
    if upbit_access and upbit_secret:
        try:
            adapter = UpbitAdapter(use_env=True)
            h = adapter.health()
            upbit_status = {
                "status": "OK" if h.get("status") != "error" else "error",
                "latency_ms": h.get("latency_ms"),
                "details": h.get("details")
            }
        except Exception as e:
            upbit_status = {"status": "error", "latency_ms": None, "details": str(e)}

    bithumb_key = os.getenv("BITHUMB_KEY")
    bithumb_secret = os.getenv("BITHUMB_SECRET")
    bithumb_status = {"status": "missing", "latency_ms": None}
    if bithumb_key and bithumb_secret:
        try:
            adapter = BithumbAdapter(bithumb_key, bithumb_secret)
            h = adapter.health()
            bithumb_status = {
                "status": "OK" if h.get("status") != "error" else "error",
                "latency_ms": h.get("latency_ms"),
                "details": h.get("details")
            }
        except Exception as e:
            bithumb_status = {"status": "error", "latency_ms": None, "details": str(e)}

    tg_token = os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat = os.getenv("TELEGRAM_CHAT_ID")
    tg_status = {"status": "missing"}
    if tg_token and tg_chat:
        tg_status = {"status": "configured"}
        if send_telegram:
            try:
                notifier = TelegramNotifier()
                notifier._send_telegram("HEALTH CHECK", f"Upbit: {upbit_status} | Telegram: OK")
                tg_status = {"status": "OK"}
            except Exception as e:
                tg_status = {"status": "error", "details": str(e)}

    hl_priv = os.getenv("HL_PRIVATE_KEY")
    hl_addr = os.getenv("HL_ACCOUNT_ADDRESS")
    hl_status = {"status": "missing"}
    if hl_priv and hl_addr:
        hl_status = {"status": "configured"}

    exchange_ok = (upbit_status["status"] == "OK") or (bithumb_status["status"] == "OK")
    telegram_ok = tg_status["status"] in ("OK", "configured")
    overall = "OK" if (exchange_ok and telegram_ok) else "WARN"

    data = {
        "ts": now,
        "overall": overall,
        "upbit": upbit_status,
        "bithumb": bithumb_status,
        "telegram": tg_status,
        "hyperliquid": hl_status
    }

    HEALTH_CACHE["ts"] = now
    HEALTH_CACHE["data"] = data

    _log_health(f"HealthCheck overall={overall} upbit={upbit_status} telegram={tg_status}")
    if send_telegram and tg_status["status"] in ("OK", "configured"):
        try:
            notifier = TelegramNotifier()
            msg = f"HEALTH CHECK\nOverall: {overall}\nUpbit: {upbit_status}\nTelegram: {tg_status}"
            notifier.emit_event("SYSTEM", "ALL", "HEALTH CHECK", msg, severity="INFO")
        except Exception:
            pass

    return data


def _parse_hhmm_to_parts(value: str):
    normalized = _normalize_hhmm(value, default="09:00")
    hh, mm = normalized.split(":")
    return int(hh), int(mm)


def _schedule_slot(now_dt: datetime, anchor_hhmm: str, interval_hours: int):
    interval_hours = max(1, int(interval_hours))
    hh, mm = _parse_hhmm_to_parts(anchor_hhmm)
    anchor = now_dt.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now_dt < anchor:
        anchor = anchor - timedelta(hours=interval_hours)
    elapsed_sec = max(0.0, (now_dt - anchor).total_seconds())
    step = int(elapsed_sec // (interval_hours * 3600))
    last_due = anchor + timedelta(hours=step * interval_hours)
    next_due = last_due + timedelta(hours=interval_hours)
    return last_due, next_due


def evolution_scheduler():
    while True:
        try:
            settings = load_settings()
            if not settings.get("evolution_enabled", False):
                time.sleep(10)
                continue

            runtime = _labs_runtime_snapshot()
            if runtime["running"]:
                time.sleep(10)
                continue

            interval_hours = int(settings.get("evolution_interval_hours", 24))
            anchor_hhmm = str(settings.get("evolution_anchor_time", "09:00"))
            last_status = _read_labs_status()
            last_ts = float(last_status.get("last_evolution_ts", 0))
            now_dt = datetime.now()
            last_due_dt, next_due_dt = _schedule_slot(now_dt, anchor_hhmm, interval_hours)
            last_due_ts = last_due_dt.timestamp()

            if last_ts < last_due_ts:
                job = _reserve_labs_job("evolution")
                if job:
                    _log_labs(
                        f"Scheduler trigger now={now_dt.isoformat()} "
                        f"slot={last_due_dt.isoformat()} next={next_due_dt.isoformat()} "
                        f"anchor={anchor_hhmm} interval_h={interval_hours} job_id={job['job_id']}"
                    )
                    try:
                        t = threading.Thread(
                            target=_run_evolution_job,
                            args=(settings, job["job_id"]),
                            daemon=True,
                        )
                        t.start()
                    except Exception as e:
                        _release_labs_job()
                        _log_labs(f"Scheduler failed to start evolution thread: {e}")
        except Exception:
            pass

        time.sleep(30)


class BotService:
    def __init__(self):
        self._lock = threading.Lock()
        self.controller = None
        self.thread = None
        self.last_error = None
        self.last_start_params = None

    def is_running(self):
        return (
            self.controller is not None
            and self.thread is not None
            and self.thread.is_alive()
            and getattr(self.controller, "running", False)
        )

    def start(self, mode: str, seed: int, exchange: str, confirm_phrase: str = ""):
        with self._lock:
            if self.is_running():
                return False, "Already running."

            mode = mode.upper()
            exchange = exchange.upper()
            confirm_live = False
            if mode == "LIVE":
                expected = f"LIVE {exchange} SEED={seed}"
                if confirm_phrase != expected:
                    return False, f"LIVE confirm required: '{expected}'"
                confirm_live = True

            try:
                if exchange == "UPBIT":
                    adapter = UpbitAdapter(use_env=True)
                elif exchange == "BITHUMB":
                    key = os.getenv("BITHUMB_KEY")
                    secret = os.getenv("BITHUMB_SECRET")
                    if not key or not secret:
                        return False, "BITHUMB_KEY/BITHUMB_SECRET missing in .env"
                    adapter = BithumbAdapter(key, secret)
                else:
                    return False, f"Unsupported exchange: {exchange}"
                notifier = TelegramNotifier()
                ledger = CapitalLedger(exchange_name=exchange, initial_seed=seed)
                watch = WatchEngine(notifier)

                controller = RunController(adapter, ledger, watch, notifier, mode=mode)
                if not controller.perform_preflight_check(confirm_live=confirm_live):
                    return False, "Pre-flight check failed."

                thread = threading.Thread(target=controller.run, daemon=True)
                thread.start()

                self.controller = controller
                self.thread = thread
                self.last_start_params = {"mode": mode, "seed": seed, "exchange": exchange}
                self.last_error = None
                return True, "Started."
            except Exception as e:
                self.last_error = str(e)
                return False, f"Start failed: {e}"

    def stop(self):
        with self._lock:
            if not self.is_running():
                return False, "Not running."
            try:
                self.controller.stop()
                self.thread.join(timeout=5)
                return True, "Stopped."
            except Exception as e:
                self.last_error = str(e)
                return False, f"Stop failed: {e}"

    def restart(self, mode: str, seed: int, exchange: str, confirm_phrase: str = ""):
        with self._lock:
            stop_status, stop_message = self.stop()
            if stop_status:
                # give controller shutdown chance to release locks
                time.sleep(0.2)
            start_status, start_message = self.start(mode, seed, exchange, confirm_phrase)
            if start_status:
                return True, "Restarted."
            if not start_status:
                return False, f"Restart failed: {start_message} (stop: {stop_message})"
            return False, "Unknown restart error."


class _ApiTestExchangeSim:
    """
    Deterministic mock exchange for controller execution-path tests.
    """
    def __init__(self, default_price=100000.0, fill_ratio=1.0, fee_rate=0.0, force_market_block=False):
        self.default_price = max(1.0, float(default_price or 100000.0))
        self.fill_ratio = min(1.0, max(0.0, float(fill_ratio or 1.0)))
        self.fee_rate = min(0.01, max(0.0, float(fee_rate or 0.0)))
        self.force_market_block = bool(force_market_block)
        self._orders = {}
        self._trades = []
        self._seq = 0

    def _next_order_id(self, side):
        self._seq += 1
        return f"mock_{side}_{self._seq}"

    def _market_obj(self):
        if self.force_market_block:
            return {
                "active": False,
                "state": "HALTED",
                "warning": "CAUTION",
                "info": {"market_state": "HALTED", "market_warning": "CAUTION"},
            }
        return {
            "active": True,
            "state": "ACTIVE",
            "warning": "NONE",
            "info": {"market_state": "ACTIVE", "market_warning": "NONE"},
        }

    def load_markets(self):
        # Controller/engine may request any symbol, so keep fallback via market().
        return {}

    def market(self, ccxt_symbol):
        return self._market_obj()

    def fetch_order_book(self, ccxt_symbol):
        mid = self.default_price
        ask = mid * 1.0005
        bid = mid * 0.9995
        return {
            "asks": [[ask, 50.0], [ask * 1.0005, 50.0], [ask * 1.001, 100.0]],
            "bids": [[bid, 50.0], [bid * 0.9995, 50.0], [bid * 0.999, 100.0]],
        }

    def fetch_ticker(self, ccxt_symbol):
        return {"last": self.default_price, "close": self.default_price}

    def _create_limit_order(self, ccxt_symbol, side, qty, price):
        oid = self._next_order_id(side)
        qty = max(0.0, float(qty or 0.0))
        px = max(1.0, float(price or self.default_price))
        filled = qty * self.fill_ratio
        status = "closed" if filled >= qty - 1e-12 else "open"
        order = {
            "id": oid,
            "symbol": ccxt_symbol,
            "side": side,
            "type": "limit",
            "price": px,
            "amount": qty,
            "filled": filled,
            "remaining": max(0.0, qty - filled),
            "status": status,
            "timestamp": int(time.time() * 1000),
        }
        self._orders[oid] = order

        if filled > 0:
            fee = filled * px * self.fee_rate
            self._trades.append(
                {
                    "id": f"trade_{oid}",
                    "order": oid,
                    "symbol": ccxt_symbol,
                    "amount": filled,
                    "price": px,
                    "timestamp": int(time.time() * 1000),
                    "fee": {"cost": fee},
                }
            )
        return dict(order)

    def create_limit_buy_order(self, ccxt_symbol, qty, price, params=None):
        return self._create_limit_order(ccxt_symbol, "buy", qty, price)

    def create_limit_sell_order(self, ccxt_symbol, qty, price, params=None):
        return self._create_limit_order(ccxt_symbol, "sell", qty, price)

    def create_order(self, ccxt_symbol, order_type, side, qty, price, params=None):
        return self._create_limit_order(ccxt_symbol, side, qty, price)

    def fetch_order(self, order_id, ccxt_symbol):
        return dict(self._orders.get(order_id, {}))

    def cancel_order(self, order_id, ccxt_symbol):
        od = self._orders.get(order_id)
        if not od:
            return {"id": order_id, "status": "canceled"}
        if od.get("status") not in {"closed", "filled"}:
            od["status"] = "canceled"
        return {"id": order_id, "status": od.get("status")}

    def fetch_my_trades(self, ccxt_symbol, since=None, limit=200):
        out = []
        for tr in self._trades:
            if tr.get("symbol") != ccxt_symbol:
                continue
            if since is not None and int(tr.get("timestamp", 0)) < int(since):
                continue
            out.append(dict(tr))
        if limit is not None:
            return out[-int(limit):]
        return out


def _to_bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def _build_api_test_entry_signal(symbol, target_money, timeframe, candle_ts, max_slippage_pct=0.01):
    t_money = max(1000.0, float(target_money or 10000.0))
    return {
        "symbol": symbol,
        "target_money": t_money,
        "timeframe": timeframe or "1m",
        "candle_timestamp": candle_ts if candle_ts is not None else time.time(),
        "max_entry_slippage_pct": max(0.001, float(max_slippage_pct or 0.01)),
        # Gate-pass fields for deterministic execution-path test.
        "spread_bp": 0.0,
        "ask_depth_sum": t_money * 20.0,
        "chase_pct": 0.0,
        "vol_spike": 1.2,
    }


class BackendState:
    def __init__(self):
        self.started_ts = time.time()
        self.last_heartbeat = self.started_ts
        self.pid = os.getpid()


class Handler(BaseHTTPRequestHandler):
    service: BotService = None
    state: BackendState = None

    def log_message(self, format, *args):
        return

    def _send_json(self, data, status=200):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_html(self, html, status=200):
        payload = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return ""
        return self.rfile.read(length).decode("utf-8")

    def do_GET(self):
        if self.path == "/":
            return self._send_html(INDEX_HTML)
        if self.path == "/api/settings":
            return self._send_json(load_settings())
        if self.path == "/api/status":
            return self._send_json(build_status(self.service, self.state))
        if self.path == "/api/labs/status":
            return self._send_json(build_labs_payload())
        if self.path == "/api/data/status":
            return self._send_json(build_data_payload())
        if self.path == "/api/models":
            return self._send_json(build_models_payload())
        if self.path == "/api/orders":
            return self._send_json(_build_orders_payload(self.service.controller))
        self._send_json({"error": "Not found"}, status=404)

    def do_POST(self):
        if self.path == "/api/health_all":
            data = health_check_all(force=True, send_telegram=True)
            status = 200 if data.get("overall") != "WARN" else 200
            return self._send_json(data, status=status)

        if self.path == "/api/shutdown":
            # Stop bot if running, then shutdown server
            try:
                self.service.stop()
            except Exception:
                pass

            def _shutdown():
                time.sleep(0.2)
                self.server.shutdown()

            threading.Thread(target=_shutdown, daemon=True).start()
            return self._send_json({"ok": True, "message": "Backend shutting down..."})

        if self.path == "/api/stop":
            ok, msg = self.service.stop()
            status = 200 if ok else 400
            return self._send_json({"ok": ok, "message": msg}, status=status)

        body = self._read_body()
        try:
            data = json.loads(body) if body else {}
        except Exception:
            data = {}

        if self.path == "/api/settings":
            try:
                settings = save_settings(data)
                return self._send_json(settings)
            except Exception as e:
                return self._send_json({"error": str(e)}, status=400)

        if self.path == "/api/start":
            settings = load_settings()
            ok, msg = self.service.start(
                mode=settings.get("mode", "PAPER"),
                seed=int(settings.get("seed_krw", 1000000)),
                exchange=settings.get("exchange", "UPBIT"),
                confirm_phrase=str(data.get("confirm", "")),
            )
            status = 200 if ok else 400
            return self._send_json({"ok": ok, "message": msg}, status=status)

        if self.path == "/api/restart":
            settings = load_settings()
            ok, msg = self.service.restart(
                mode=settings.get("mode", "PAPER"),
                seed=int(settings.get("seed_krw", 1000000)),
                exchange=settings.get("exchange", "UPBIT"),
                confirm_phrase=str(data.get("confirm", "")),
            )
            status = 200 if ok else 400
            return self._send_json({"ok": ok, "message": msg}, status=status)

        if self.path == "/api/panic":
            if not self.service.is_running() or self.service.controller is None:
                return self._send_json({"ok": False, "message": "Controller is not running."}, status=400)
            controller = self.service.controller
            settings = load_settings()
            symbol = str(data.get("symbol") or controller._get_runtime_state().get("symbol") or "")
            hard_loss_cap = float(data.get("hard_loss_cap", -0.05)) if data.get("hard_loss_cap") is not None else -0.05

            forced_exit = None
            try:
                forced_exit = controller.process_panic_exit(symbol=symbol, hard_loss_cap=hard_loss_cap)
            except Exception:
                forced_exit = None
            fallback_exit = None
            if not forced_exit:
                fallback_exit = controller.process_exit_signal(symbol=symbol if symbol else None, qty="ALL")

            cancel_res = _cancel_open_orders(controller, all_orders=True)
            _notify_openclaw_emergency(
                f"[Panic Trigger] symbol={symbol or '-'} mode={controller.mode if hasattr(controller, 'mode') else '-'}" +
                f" forced_exit={'YES' if forced_exit else 'NO'} hard_loss_cap={hard_loss_cap}",
                exchange=getattr(controller, 'adapter', None).exchange_name if getattr(controller, 'adapter', None) else "SYSTEM",
            )

            ok = bool((forced_exit and forced_exit.get("ok")) or (fallback_exit and fallback_exit.get("ok")) or cancel_res.get("canceled", 0) > 0)
            msg = "panic completed" if ok else "panic accepted but action may be unavailable"
            return self._send_json({
                "ok": ok,
                "message": msg,
                "forced_exit": forced_exit,
                "fallback_exit": fallback_exit,
                "cancel_result": cancel_res,
            })

        if self.path == "/api/orders/cancel":
            if not self.service.is_running() or self.service.controller is None:
                return self._send_json({"ok": False, "message": "Controller is not running."}, status=400)
            controller = self.service.controller
            all_orders = bool(data.get("all", False))
            order_id = data.get("order_id")
            symbol = data.get("symbol")
            cancel_res = _cancel_open_orders(controller, order_id=str(order_id) if order_id else None, symbol=str(symbol) if symbol else None, all_orders=all_orders)
            return self._send_json(cancel_res)

        if self.path == "/api/orders":
            return self._send_json(_build_orders_payload(self.service.controller))

        if self.path == "/api/test/entry":
            if not self.service.is_running() or self.service.controller is None:
                return self._send_json({"ok": False, "message": "Controller is not running."}, status=400)
            controller = self.service.controller
            try:
                runtime_state = controller._get_runtime_state()
                settings = load_settings()
                symbol = str(
                    data.get("symbol")
                    or runtime_state.get("symbol")
                    or (settings.get("watchlist") or ["KRW-BTC"])[0]
                )
                target_money = float(data.get("target_money") or max(10000, int(settings.get("seed_krw", 100000)) // 10))
                timeframe = str(data.get("timeframe") or "1m")
                candle_ts = data.get("candle_timestamp", time.time())
                max_slippage = float(data.get("max_entry_slippage_pct") or 0.01)
                mock = _to_bool(data.get("mock"), True)
                fill_ratio = float(data.get("fill_ratio") or 1.0)
                test_price = float(data.get("price") or 100000.0)
                balance_krw = float(data.get("balance_krw") or max(target_money * 3, 100000.0))
                force_market_block = _to_bool(data.get("force_market_block"), False)

                signal = _build_api_test_entry_signal(
                    symbol=symbol,
                    target_money=target_money,
                    timeframe=timeframe,
                    candle_ts=candle_ts,
                    max_slippage_pct=max_slippage,
                )
                market_data = {"price": test_price, "balance": balance_krw}

                exchange_api = None
                if mock:
                    exchange_api = _ApiTestExchangeSim(
                        default_price=test_price,
                        fill_ratio=fill_ratio,
                        fee_rate=0.0,
                        force_market_block=force_market_block,
                    )
                result = controller.process_entry_signal(
                    signal=signal,
                    current_market_data=market_data,
                    exchange_api=exchange_api,
                )
                new_state = controller._get_runtime_state()
                return self._send_json(
                    {
                        "ok": bool(result and result.get("ok", False)),
                        "message": "entry executed" if (result and result.get("ok", False)) else "entry blocked_or_failed",
                        "mock": mock,
                        "input": {
                            "symbol": symbol,
                            "target_money": target_money,
                            "timeframe": timeframe,
                            "price": test_price,
                            "fill_ratio": fill_ratio,
                            "force_market_block": force_market_block,
                        },
                        "result": result,
                        "runtime_state": new_state,
                    }
                )
            except Exception as e:
                return self._send_json({"ok": False, "message": f"test entry failed: {e}"}, status=500)

        if self.path == "/api/test/exit":
            if not self.service.is_running() or self.service.controller is None:
                return self._send_json({"ok": False, "message": "Controller is not running."}, status=400)
            controller = self.service.controller
            try:
                runtime_state = controller._get_runtime_state()
                symbol = str(data.get("symbol") or runtime_state.get("symbol") or "KRW-BTC")
                qty = data.get("qty", "ALL")
                mock = _to_bool(data.get("mock"), True)
                fill_ratio = float(data.get("fill_ratio") or 1.0)
                test_price = float(data.get("price") or 100000.0)
                force_market_block = _to_bool(data.get("force_market_block"), False)
                reason = str(data.get("reason") or "API_TEST_EXIT")

                exchange_api = None
                if mock:
                    exchange_api = _ApiTestExchangeSim(
                        default_price=test_price,
                        fill_ratio=fill_ratio,
                        fee_rate=0.0,
                        force_market_block=force_market_block,
                    )

                result = controller.process_exit_signal(
                    symbol=symbol,
                    qty=qty,
                    exchange_api=exchange_api,
                    reason=reason,
                )
                new_state = controller._get_runtime_state()
                return self._send_json(
                    {
                        "ok": bool(result and result.get("ok", False)),
                        "message": "exit executed" if (result and result.get("ok", False)) else "exit blocked_or_failed",
                        "mock": mock,
                        "input": {
                            "symbol": symbol,
                            "qty": qty,
                            "price": test_price,
                            "fill_ratio": fill_ratio,
                            "force_market_block": force_market_block,
                            "reason": reason,
                        },
                        "result": result,
                        "runtime_state": new_state,
                    }
                )
            except Exception as e:
                return self._send_json({"ok": False, "message": f"test exit failed: {e}"}, status=500)

        if self.path == "/api/labs/run_backtest":
            job = _reserve_labs_job("backtest")
            if not job:
                return self._send_json({"error": "Labs job already running."}, status=400)
            settings = load_settings()
            try:
                t = threading.Thread(target=_run_backtest_job, args=(settings, job["job_id"]), daemon=True)
                t.start()
            except Exception as e:
                _release_labs_job()
                return self._send_json({"error": f"Backtest thread start failed: {e}"}, status=500)
            return self._send_json({"ok": True, "message": "Backtest started."})

        if self.path == "/api/labs/run_evolution":
            job = _reserve_labs_job("evolution")
            if not job:
                return self._send_json({"error": "Labs job already running."}, status=400)
            settings = load_settings()
            try:
                t = threading.Thread(target=_run_evolution_job, args=(settings, job["job_id"]), daemon=True)
                t.start()
            except Exception as e:
                _release_labs_job()
                return self._send_json({"error": f"Evolution thread start failed: {e}"}, status=500)
            return self._send_json({"ok": True, "message": "Evolution started."})

        if self.path == "/api/labs/approve_live":
            pending = _safe_read_json(LABS_PENDING_LIVE_PATH, default=None)
            if not pending:
                return self._send_json({"error": "No pending live params."}, status=400)
            approved_path = LABS_DIR / "live_approved.json"
            _safe_write_json(approved_path, {
                "approved_at": datetime.now().isoformat(),
                "params": pending.get("params"),
                "metrics": pending.get("metrics"),
            })
            try:
                LABS_PENDING_LIVE_PATH.unlink(missing_ok=True)
            except Exception:
                pass
            _log_labs("LIVE params approved via UI.")
            _notify_labs("LIVE params approved.", pending.get("metrics"))
            return self._send_json({"ok": True, "message": "LIVE params approved."})

        if self.path == "/api/data/update":
            if not _reserve_data_job():
                return self._send_json({"error": "Data update already running."}, status=400)
            try:
                t = threading.Thread(target=_run_data_update_job, daemon=True)
                t.start()
            except Exception as e:
                _release_data_job(last_msg="thread_start_failed")
                return self._send_json({"error": f"Data update thread start failed: {e}"}, status=500)
            return self._send_json({"ok": True, "message": "Data update started."})

        self._send_json({"error": "Not found"}, status=404)


def parse_lock_info():
    if not LOCK_PATH.exists():
        return {"exists": False, "pid": None, "mode": None}
    try:
        content = LOCK_PATH.read_text().strip().split(",")
        pid = int(content[0]) if len(content) >= 1 else None
        mode = content[2] if len(content) >= 3 else None
        return {"exists": True, "pid": pid, "mode": mode}
    except Exception:
        return {"exists": True, "pid": None, "mode": None}


def build_labs_payload():
    labs_status = _read_labs_status()
    pending_live = _safe_read_json(LABS_PENDING_LIVE_PATH, default=None)
    last_result = _safe_read_json(LABS_LAST_RESULT_PATH, default=None)
    baseline = _safe_read_json(LABS_LAST_BASELINE_PATH, default=None)
    runtime = _labs_runtime_snapshot()
    return {
        "status": labs_status,
        "pending_live": pending_live,
        "last_result": last_result,
        "baseline": baseline,
        "running": runtime["running"],
        "job_type": runtime["job_type"],
        "job_id": runtime["job_id"],
    }


def build_data_payload():
    return _safe_read_json(DATA_STATUS_PATH, default={})


def _to_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _history_time_key(iso_value):
    if not iso_value:
        return 0.0
    try:
        text = str(iso_value).replace("Z", "+00:00")
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0


def _build_model_history_row(run_id, bucket, mtime_iso, summary=None, meta=None):
    summary = summary or {}
    meta = meta or {}

    candidate = ((summary.get("candidate") or {}).get("oos_metrics") or {})
    active = ((summary.get("active_baseline") or {}).get("oos_metrics") or {})
    gate = summary.get("gate") or {}
    windows = summary.get("windows") or {}

    decision = str(gate.get("decision") or "").upper()
    if not decision:
        if "pass" in gate:
            decision = "PROMOTE" if bool(gate.get("pass")) else "KEEP_ACTIVE"
        elif str(bucket).lower() == "archive":
            decision = "ARCHIVED"
        elif str(bucket).lower() == "active":
            decision = "ACTIVE"
        else:
            decision = "UNKNOWN"

    reasons = gate.get("reasons")
    if isinstance(reasons, list):
        reason = ", ".join([str(x) for x in reasons if str(x)])
    else:
        reason = str(gate.get("reason") or reasons or "")
    if not reason:
        reason = "-"

    score = _metric_val(candidate, "score", 0.0)
    active_score = _metric_val(active, "score", 0.0)
    delta = gate.get("delta")
    if delta is None:
        delta = score - active_score
    delta = _to_float(delta, 0.0)

    positive_weeks = candidate.get("positive_weeks", None)
    if positive_weeks is None:
        positive_weeks = (summary.get("candidate") or {}).get("positive_weeks", 0)

    created_at = summary.get("created_at") or meta.get("created_at") or mtime_iso

    return {
        "run_id": str(run_id or meta.get("model_id") or "-"),
        "bucket": str(bucket).upper(),
        "created_at": created_at,
        "decision": decision,
        "gate_pass": bool(gate.get("pass")) if "pass" in gate else None,
        "score": score,
        "active_score": active_score,
        "delta": delta,
        "roi": _metric_val(candidate, "roi", 0.0),
        "mdd": _metric_val(candidate, "mdd", 0.0),
        "trades": int(_metric_val(candidate, "trades", 0)),
        "cost_drop": _metric_val(candidate, "cost_drop", 0.0),
        "positive_weeks": int(_to_float(positive_weeks, 0)),
        "negative_weeks": int(_metric_val(candidate, "negative_weeks", 0)),
        "worst_week": _metric_val(candidate, "worst_week", 0.0),
        "reason": reason,
        "oos_start": windows.get("oos_start"),
        "oos_end": windows.get("oos_end"),
    }


def build_models_payload():
    mgr = ModelManager(base_dir=ROOT_DIR / "models")
    payload = {
        "active_model_id": mgr.active_model_id(),
        "active": None,
        "staging": [],
        "archive": [],
        "history": [],
    }
    history_rows = []

    active_meta = _safe_read_json(mgr.active_dir / "model_meta.json", default=None)
    active_summary = _safe_read_json(mgr.active_dir / "run_summary.json", default=None)
    if active_meta or active_summary:
        payload["active"] = {
            "meta": active_meta,
            "summary": active_summary,
        }
        active_run_id = (
            (active_meta or {}).get("model_id")
            or (active_summary or {}).get("run_id")
            or payload.get("active_model_id")
        )
        active_mtime = datetime.fromtimestamp(mgr.active_dir.stat().st_mtime).isoformat()
        history_rows.append(
            _build_model_history_row(
                run_id=active_run_id,
                bucket="active",
                mtime_iso=active_mtime,
                summary=active_summary,
                meta=active_meta,
            )
        )

    if mgr.staging_dir.exists():
        for d in sorted(
            [x for x in mgr.staging_dir.iterdir() if x.is_dir()],
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        ):
            summary = _safe_read_json(d / "run_summary.json", default=None)
            meta = _safe_read_json(d / "model_meta.json", default=None)
            mtime = datetime.fromtimestamp(d.stat().st_mtime).isoformat()
            payload["staging"].append(
                {
                    "run_id": d.name,
                    "mtime": mtime,
                }
            )
            history_rows.append(
                _build_model_history_row(
                    run_id=d.name,
                    bucket="staging",
                    mtime_iso=mtime,
                    summary=summary,
                    meta=meta,
                )
            )

    if mgr.archive_dir.exists():
        for d in sorted(
            [x for x in mgr.archive_dir.iterdir() if x.is_dir()],
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )[:120]:
            summary = _safe_read_json(d / "run_summary.json", default=None)
            meta = _safe_read_json(d / "model_meta.json", default=None)
            mtime = datetime.fromtimestamp(d.stat().st_mtime).isoformat()
            payload["archive"].append(
                {
                    "run_id": d.name,
                    "mtime": mtime,
                }
            )
            history_rows.append(
                _build_model_history_row(
                    run_id=d.name,
                    bucket="archive",
                    mtime_iso=mtime,
                    summary=summary,
                    meta=meta,
                )
            )
    history_rows.sort(key=lambda x: _history_time_key(x.get("created_at")), reverse=True)
    payload["history"] = history_rows[:200]
    payload["history_count"] = len(history_rows)
    return payload


def _normalize_symbol(sym: str):
    if sym is None:
        return ""
    s = str(sym)
    if "KRW-" in s:
        idx = s.find("KRW-")
        return s[idx:]
    if "UPBIT_" in s:
        return s.replace("UPBIT_", "").replace("_", "-")
    if "BITHUMB_" in s:
        return s.replace("BITHUMB_", "").replace("_", "-")
    return s


def _build_reason(row):
    parts = []
    try:
        rsi = row.get("rsi", None)
        vol = row.get("vol_spike", None)
        tag = str(row.get("tag_exec", row.get("tag", "")) or "")
        pump_state = str(row.get("pump_state_exec", row.get("pump_state", "NORMAL")) or "NORMAL").upper()
        anti_reason = str(row.get("anti_chase_reason_exec", row.get("anti_chase_reason", "")) or "")
        reentry_reason = str(row.get("reentry_reason_exec", row.get("reentry_reason", "")) or "")
        if tag and tag != "None":
            parts.append(tag)
        if rsi is not None:
            parts.append(f"RSI {rsi:.0f}")
        if vol is not None:
            parts.append(f"Vol {vol:.2f}x")
        if pump_state != "NORMAL":
            parts.append(f"State {pump_state}")
        if reentry_reason:
            parts.append(f"ReEntry {reentry_reason}")
        if anti_reason:
            parts.append(f"Blocked {anti_reason}")
    except Exception:
        pass
    return " | ".join(parts)


def _build_reason_detail(row):
    parts = []
    try:
        def _f(v, default=None):
            try:
                if v is None:
                    return default
                n = float(v)
                if pd.isna(n):
                    return default
                return n
            except Exception:
                return default

        price = row.get("close", None)
        rsi = row.get("rsi", None)
        vol = row.get("vol_spike", None)
        ma_fast = row.get("ma_fast", None)
        ma_slow = row.get("ma_slow", None)
        gap_pct = row.get("gap_pct", None)
        atr_exec = _f(row.get("atr_exec", row.get("atr", None)))
        pump_state = str(row.get("pump_state_exec", row.get("pump_state", "NORMAL")) or "NORMAL").upper()
        penalty = _f(row.get("penalty_factor_exec", row.get("penalty_factor", 1.0)), 1.0)
        anti_reason = str(row.get("anti_chase_reason_exec", row.get("anti_chase_reason", "")) or "")
        reentry_reason = str(row.get("reentry_reason_exec", row.get("reentry_reason", "")) or "")
        cooling_box_high = _f(row.get("cooling_box_high", None))
        tag = str(row.get("tag_exec", row.get("tag", "")) or "")
        signal_exec = bool(row.get("signal_buy_exec", False))
        if price is not None:
            parts.append(f"Price {price:,.0f}")
        if rsi is not None:
            parts.append(f"RSI {rsi:.1f}")
        if vol is not None:
            parts.append(f"VolSpike {vol:.2f}x")
        if ma_fast is not None and ma_slow is not None:
            parts.append(f"MA {ma_fast:.0f}/{ma_slow:.0f}")
        if gap_pct is not None:
            parts.append(f"Gap {gap_pct*100:.2f}%")
        if atr_exec is not None:
            parts.append(f"ATR(exec) {atr_exec:,.0f}")
        if cooling_box_high is not None:
            parts.append(f"CoolingBox {cooling_box_high:,.0f}")
        if tag and tag != "None":
            parts.append(f"Tag {tag}")
        parts.append(f"SignalExec {'BUY' if signal_exec else 'NO'}")
        parts.append(f"PumpState {pump_state}")
        parts.append(f"Penalty x{penalty:.2f}")
        if reentry_reason:
            parts.append(f"ReEntry {reentry_reason}")
        if anti_reason:
            parts.append(f"AntiChase {anti_reason}")
    except Exception:
        pass
    return " | ".join(parts)


def _grade_from_score(score, settings):
    alert = float(settings.get("watch_alert_score", 2.0))
    if score >= alert * 1.5:
        return "S"
    if score >= alert:
        return "A"
    if score >= float(settings.get("watch_score_min", 1.0)):
        return "B"
    return "C"


def compute_watchlist():
    settings = load_settings()
    cfg = load_user_config()
    params = config_to_params(cfg)
    raw_dfs = _load_data_map()
    if not raw_dfs:
        return []

    def _fnum(value, default=0.0):
        try:
            if value is None:
                return float(default)
            out = float(value)
            if pd.isna(out):
                return float(default)
            return out
        except Exception:
            return float(default)

    symbol_dfs = _prepare_symbol_dfs(raw_dfs, params)
    candidates = []

    exchange_filter = (settings.get("exchange") or "").upper()
    exclude_symbols = set([s.upper() for s in settings.get("watch_exclude_symbols", [])])
    min_turnover = cfg.get("min_turnover", 0)
    top_n = cfg.get("universe_top_n", 0)
    score_min = float(settings.get("watch_score_min", 1.0))

    turnover_list = []
    for sym, df in symbol_dfs.items():
        if df is None or df.empty:
            continue
        row = df.iloc[-1]
        turnover = row.get("turnover", row.get("notional", 0))
        turnover_list.append((sym, turnover))

    if top_n and top_n > 0:
        turnover_list.sort(key=lambda x: x[1], reverse=True)
        allowed = set([s for s, _ in turnover_list[:top_n]])
    else:
        allowed = set([s for s, _ in turnover_list])

    for sym, df in symbol_dfs.items():
        sym_u = str(sym).upper()
        if exchange_filter == "UPBIT" and "UPBIT_" not in sym_u:
            continue
        if exchange_filter == "BITHUMB" and "BITHUMB_" not in sym_u:
            continue
        norm = _normalize_symbol(sym_u)
        if norm.startswith("KRW-"):
            base = norm.split("-", 1)[1]
            if base in exclude_symbols:
                continue
        if sym not in allowed:
            continue
        row = df.iloc[-1]
        turnover = row.get("turnover", row.get("notional", 0))
        if turnover < min_turnover:
            continue
        signal_exec = bool(row.get("signal_buy_exec", False))
        anti_chase_reason = str(row.get("anti_chase_reason_exec", row.get("anti_chase_reason", "")) or "").strip()
        reentry_reason = str(row.get("reentry_reason_exec", row.get("reentry_reason", "")) or "").strip()
        if (not signal_exec) and (not anti_chase_reason) and (not reentry_reason):
            continue
        score = float(row.get("score_exec", row.get("score", 0.0)) or 0.0)
        if score < score_min and (not anti_chase_reason):
            continue
        status = "BLOCKED" if anti_chase_reason else ("REENTRY" if reentry_reason else "BUY")
        status_priority = 1 if status == "BLOCKED" else 0

        current_price = _fnum(row.get("close", 0.0), 0.0)
        prev_close = current_price
        if len(df) >= 2:
            prev_close = _fnum(df.iloc[-2].get("close", current_price), current_price)
        anchor_price = prev_close if prev_close > 0 else current_price
        atr_exec = _fnum(row.get("atr_exec", row.get("atr", 0.0)), 0.0)
        if atr_exec < 0:
            atr_exec = 0.0
        cap_rate = _fnum(params.get("entry_cap_rate", params.get("close_confirm_pct_A", 0.005)), 0.005)
        cap_rate = min(0.05, max(0.0, cap_rate))
        l1_price = anchor_price * (1.0 + cap_rate) if anchor_price > 0 else 0.0
        l2_price = max(0.0, anchor_price - (0.5 * atr_exec)) if anchor_price > 0 else 0.0
        l3_price = max(0.0, anchor_price - (1.0 * atr_exec)) if anchor_price > 0 else 0.0
        chase_atr_k = _fnum(params.get("chase_ext_atr_k", 1.8), 1.8)
        sl_atr_k = _fnum(params.get("sl_atr_mult_A", 2.0), 2.0)
        ttl_days = max(1, int(_fnum(params.get("rearmed_ttl_days", 1), 1)))
        chase_cancel_price = anchor_price + (chase_atr_k * atr_exec) if anchor_price > 0 else 0.0
        stop_loss_price = max(0.0, anchor_price - (sl_atr_k * atr_exec)) if anchor_price > 0 else 0.0
        entry_plan = {
            "basis": "T-1 close + ATR(exec)",
            "current_price": float(current_price),
            "anchor_price": float(anchor_price),
            "atr_exec": float(atr_exec),
            "l1_price": float(l1_price),
            "l2_price": float(l2_price),
            "l3_price": float(l3_price),
            "l1_weight": 0.40,
            "l2_weight": 0.30,
            "l3_weight": 0.30,
            "ttl_days": ttl_days,
            "chase_atr_k": float(chase_atr_k),
            "chase_cancel_price": float(chase_cancel_price),
            "sl_atr_k": float(sl_atr_k),
            "stop_loss_price": float(stop_loss_price),
            "valid_atr": bool(atr_exec > 0),
        }
        grade = _grade_from_score(score, settings)
        candidates.append({
            "symbol": _normalize_symbol(sym),
            "score": score,
            "status": status,
            "status_priority": status_priority,
            "signal_exec": signal_exec,
            "tag": row.get("tag_exec", row.get("tag", "")),
            "reason": _build_reason(row),
            "detail": _build_reason_detail(row),
            "pump_state": row.get("pump_state_exec", row.get("pump_state", "NORMAL")),
            "penalty_factor": float(row.get("penalty_factor_exec", row.get("penalty_factor", 1.0)) or 1.0),
            "anti_chase_reason": anti_chase_reason,
            "reentry_reason": reentry_reason,
            "entry_plan": entry_plan,
            "grade": grade,
        })

    candidates.sort(key=lambda x: (x.get("status_priority", 0), -x["score"]))

    max_score = max([c["score"] for c in candidates], default=0.0)
    alert_score = float(settings.get("watch_alert_score", 2.0)) or 1.0
    auto_buy_min = int(settings.get("auto_buy_score_min_100", 100))

    highlight_top = int(settings.get("watch_highlight_top", 3))
    actionable_rank = 0
    for idx, item in enumerate(candidates):
        item["rank"] = idx + 1
        is_blocked = str(item.get("status", "")).upper() == "BLOCKED"
        if not is_blocked:
            actionable_rank += 1
        item["highlight"] = (not is_blocked) and (actionable_rank <= highlight_top)
        item["score_max"] = max_score
        item["score_pct"] = (item["score"] / max_score * 100.0) if max_score > 0 else 0.0
        item["score_100"] = round(item["score"] / alert_score * 100.0, 1)
        item["auto_buy_ok"] = (item["score_100"] >= auto_buy_min) and (not is_blocked)

    return candidates


def watchlist_scheduler():
    notifier = TelegramNotifier()
    while True:
        try:
            settings = load_settings()
            refresh_sec = int(settings.get("watch_refresh_sec", 60))
            watch_alert_score = float(settings.get("watch_alert_score", 2.0))
            cooldown_min = int(settings.get("watch_alert_cooldown_min", 60))

            now = time.time()
            if now - WATCH_CACHE["ts"] < refresh_sec:
                time.sleep(1)
                continue

            watchlist = compute_watchlist()
            WATCH_CACHE["list"] = watchlist
            WATCH_CACHE["ts"] = now

            # SELL signal: items that disappeared from watchlist
            prev_map = WATCH_CACHE.get("last_list", {})
            current_map = {item.get("symbol"): item for item in watchlist}
            for sym, prev_item in prev_map.items():
                if sym in current_map:
                    continue
                last_ts = WATCH_CACHE["last_sell_alert"].get(sym, 0)
                if now - last_ts < cooldown_min * 60:
                    continue
                WATCH_CACHE["last_sell_alert"][sym] = now
                if notifier:
                    msg = f"SELL SIGNAL\n{sym}\nReason: dropped from watchlist\nPrev Score: {prev_item.get('score'):.3f}\nPrev Detail: {prev_item.get('detail')}"
                    notifier.emit_event("WATCH", "UPBIT", "SELL SIGNAL", msg, severity="INFO",
                                        dedupe_key=f"WATCH_SELL_{sym}", cooldown_min=cooldown_min)

            WATCH_CACHE["last_list"] = current_map

            for item in watchlist:
                if str(item.get("status", "BUY")).upper() == "BLOCKED":
                    continue
                if item.get("score", 0) < watch_alert_score:
                    continue
                if not item.get("auto_buy_ok", False):
                    continue
                sym = item.get("symbol")
                last_ts = WATCH_CACHE["last_alert"].get(sym, 0)
                if now - last_ts < cooldown_min * 60:
                    continue
                WATCH_CACHE["last_alert"][sym] = now
                if notifier:
                    msg = f"BUY CANDIDATE (AUTO)\n{sym}\nGrade: {item.get('grade')}\nScore: {item.get('score_100'):.1f}/100\nReason: {item.get('reason')}\nDetail: {item.get('detail')}"
                    notifier.emit_event("WATCH", "UPBIT", "BUY CANDIDATE", msg, severity="INFO",
                                        dedupe_key=f"WATCH_BUY_{sym}", cooldown_min=cooldown_min)

        except Exception:
            pass
        time.sleep(2)


def _build_orders_payload(controller) -> dict:
    if controller is None:
        return {"ok": False, "exchange": "-", "orders": []}
    adapter = getattr(controller, "adapter", None)
    if adapter is None:
        return {"ok": False, "exchange": "-", "orders": []}
    fetcher = getattr(adapter, "get_open_orders", None)
    exchange_name = getattr(adapter, "exchange_name", "-")
    if not callable(fetcher):
        return {"ok": False, "exchange": exchange_name, "orders": []}

    try:
        raw = fetcher() or []
    except Exception:
        raw = []

    orders = []
    for row in raw if isinstance(raw, list) else []:
        try:
            normalized = _normalize_order_row(dict(row))
            normalized["exchange"] = exchange_name
            orders.append(normalized)
        except Exception:
            continue
    return {"ok": True, "exchange": exchange_name, "orders": orders, "count": len(orders)}


def _cancel_open_orders(controller, order_id: str = None, symbol: str = None, all_orders: bool = False):
    if controller is None:
        return {"ok": False, "message": "Controller is not running.", "requested": 0, "canceled": 0, "failed": 0}
    adapter = getattr(controller, "adapter", None)
    if adapter is None:
        return {"ok": False, "message": "Adapter not available.", "requested": 0, "canceled": 0, "failed": 0}

    client = getattr(adapter, "client", None)
    cancel_fn = getattr(client, "cancel_order", None)
    if not callable(cancel_fn):
        return {"ok": False, "message": "Cancel API unavailable.", "requested": 0, "canceled": 0, "failed": 0}

    payload = _build_orders_payload(controller)
    if not payload.get("ok"):
        return {"ok": False, "message": "No open orders.", "requested": 0, "canceled": 0, "failed": 0, "orders": []}

    candidates = payload.get("orders") or []
    to_cancel = []
    if all_orders:
        to_cancel = candidates
    elif order_id:
        to_cancel = [o for o in candidates if str(o.get("order_id") or "") == str(order_id)]
    elif symbol:
        to_cancel = [o for o in candidates if str(o.get("symbol") or "") == str(symbol)]

    if not to_cancel:
        return {"ok": False, "message": "No matching open orders.", "requested": 0, "canceled": 0, "failed": 0}

    requested = len(to_cancel)
    canceled = 0
    failed = 0
    results = []
    for item in to_cancel:
        oid = str(item.get("order_id") or "")
        sym = str(item.get("symbol") or "")
        if not oid or not sym:
            failed += 1
            continue
        try:
            cancel_fn(_to_ccxt_symbol(adapter, sym), oid)
            canceled += 1
            results.append({"order_id": oid, "symbol": sym, "ok": True})
        except Exception as e:
            failed += 1
            results.append({"order_id": oid, "symbol": sym, "ok": False, "error": str(e)})

    return {
        "ok": canceled > 0,
        "requested": requested,
        "canceled": canceled,
        "failed": failed,
        "results": results,
        "message": f"Cancel requested: {requested}, canceled: {canceled}, failed: {failed}",
        "orders": payload.get("orders", []),
    }


def build_status(service: BotService, state: BackendState):
    now = time.time()
    current_settings = load_settings()
    runtime = _safe_read_json(RUNTIME_STATUS_PATH, default=None)
    runtime_state = _safe_read_json(RUNTIME_STATE_PATH, default=None)
    runtime_age = None
    if runtime and "ts" in runtime:
        runtime_age = max(0.0, now - float(runtime["ts"]))

    lock_info = parse_lock_info()
    controller_running = service.is_running()
    controller_owner = "web_backend" if controller_running else ("external" if lock_info["exists"] else "none")
    controller_mode = None
    if service.controller is not None:
        controller_mode = service.controller.mode
    elif lock_info["mode"]:
        controller_mode = lock_info["mode"]

    state.last_heartbeat = now
    backend = {
        "ok": True,
        "pid": state.pid,
        "uptime_sec": now - state.started_ts,
        "last_heartbeat": state.last_heartbeat,
    }

    recent_errors = _safe_tail(RESULTS_DIR / "logs" / "crash_log.txt", max_lines=20)

    max_score = 0.0
    if WATCH_CACHE.get("list"):
        try:
            max_score = max([x.get("score", 0.0) for x in WATCH_CACHE["list"]])
        except Exception:
            max_score = 0.0

    mode_value = str(
        controller_mode
        or (runtime or {}).get("mode")
        or current_settings.get("mode", "PAPER")
    ).upper()
    running_value = bool(
        ((runtime or {}).get("status") == "RUNNING")
        or controller_running
    )
    equity_krw = 0.0
    pnl_ratio = 0.0
    try:
        equity_krw = float((runtime or {}).get("equity", 0.0) or 0.0)
    except Exception:
        equity_krw = 0.0
    try:
        pnl_ratio = float((runtime or {}).get("pnl_pct", 0.0) or 0.0)
    except Exception:
        pnl_ratio = 0.0

    rs = runtime_state if isinstance(runtime_state, dict) else {}
    position_symbol = rs.get("symbol")
    try:
        position_qty = float(rs.get("position_qty", 0.0) or 0.0)
    except Exception:
        position_qty = 0.0
    try:
        avg_entry_price = float(rs.get("avg_entry_price", 0.0) or 0.0)
    except Exception:
        avg_entry_price = 0.0
    position_state = str(rs.get("state") or "UNKNOWN")

    portfolio = {
        "mode": mode_value,
        "running": running_value,
        "equity_krw": equity_krw,
        "pnl_ratio": pnl_ratio,
        "pnl_pct": pnl_ratio * 100.0,
        "position": {
            "symbol": position_symbol,
            "qty": position_qty,
            "avg_entry_price": avg_entry_price,
            "state": position_state,
            "has_position": bool(position_qty > 0),
        },
    }

    status = {
        "backend": backend,
        "settings": current_settings,
        "runtime": runtime,
        "runtime_state": runtime_state,
        "portfolio": portfolio,
        "runtime_age_sec": runtime_age,
        "controller_state": (runtime or {}).get("status") if runtime else ("RUNNING" if controller_running else "STOPPED"),
        "controller_owner": controller_owner,
        "controller_mode": controller_mode,
        "lock": lock_info,
        "last_error": service.last_error,
        "health": HEALTH_CACHE.get("data"),
        "labs": build_labs_payload(),
        "recent_errors": recent_errors,
        "data_status": build_data_payload(),
        "watchlist_ranked": WATCH_CACHE.get("list", []),
        "watchlist_score_max": max_score
    }
    return status


def heartbeat_loop(state: BackendState, service: BotService):
    while True:
        payload = build_status(service, state)
        _safe_write_json(BACKEND_STATUS_PATH, {
            "ts": payload["backend"]["last_heartbeat"],
            "pid": payload["backend"]["pid"],
            "uptime_sec": payload["backend"]["uptime_sec"],
            "controller_state": payload["controller_state"],
            "controller_owner": payload["controller_owner"],
            "controller_mode": payload["controller_mode"],
            "lock": payload["lock"],
        })
        time.sleep(1)


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "locks").mkdir(parents=True, exist_ok=True)
    LABS_DIR.mkdir(parents=True, exist_ok=True)

    # Load .env if available
    if load_dotenv:
        load_dotenv(str(AUTO_DIR / ".env"))
        load_dotenv(str(ROOT_DIR / ".env"))

    service = BotService()
    state = BackendState()

    Handler.service = service
    Handler.state = state

    t = threading.Thread(target=heartbeat_loop, args=(state, service), daemon=True)
    t.start()

    evo_thread = threading.Thread(target=evolution_scheduler, daemon=True)
    evo_thread.start()

    watch_thread = threading.Thread(target=watchlist_scheduler, daemon=True)
    watch_thread.start()

    data_thread = threading.Thread(target=data_update_scheduler, daemon=True)
    data_thread.start()

    # Initial API health check on startup
    try:
        health_check_all(force=True, send_telegram=True)
    except Exception:
        pass

    host = "127.0.0.1"
    port = 8765
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"[WebBackend] Serving on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
