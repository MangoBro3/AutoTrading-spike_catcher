import http from 'node:http';
import { exec as execCb } from 'node:child_process';
import { promisify } from 'node:util';
import { readFileSync, existsSync } from 'node:fs';
import { readFile, mkdir, appendFile, writeFile } from 'node:fs/promises';
import { extname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { WorkerApiClient, WorkerMonitor } from './worker-monitor.mjs';

const exec = promisify(execCb);

const PORT = process.env.PORT ? Number(process.env.PORT) : 18890;
const ROOT = fileURLToPath(new URL('./public/', import.meta.url));
const WORKSPACE_ROOT = fileURLToPath(new URL('../../', import.meta.url));
const USAGE_DIR = join(WORKSPACE_ROOT, 'team', 'usage');
const SNAPSHOT_FILE = `${USAGE_DIR}/token_snapshots.jsonl`;
const ACTIVITY_LOG_FILE = `${USAGE_DIR}/activity_log.jsonl`;
const ACTIVITY_STATE_FILE = `${USAGE_DIR}/activity_state.json`;
const PROJECT_NAME = 'openclaw-news-workspace';
const WORKER_API_BASE_URL = process.env.AT_UI_WORKER_API_BASE_URL || process.env.WORKER_API_BASE_URL || 'http://127.0.0.1:8765/api/v1';
const WORKER_API_TIMEOUT_MS = process.env.AT_UI_WORKER_API_TIMEOUT_MS || process.env.WORKER_API_TIMEOUT_MS || 3000;
const WORKER_POLL_MS = process.env.WORKER_POLL_MS ? Number(process.env.WORKER_POLL_MS) : 1000;
const WORKER_DOWN_DEBOUNCE_MS = process.env.WORKER_DOWN_DEBOUNCE_MS ? Number(process.env.WORKER_DOWN_DEBOUNCE_MS) : 4000;
const OVERVIEW_REFRESH_MS = process.env.AT_UI_OVERVIEW_REFRESH_MS ? Number(process.env.AT_UI_OVERVIEW_REFRESH_MS) : 2000;
const OVERVIEW_CMD_TIMEOUT_MS = process.env.AT_UI_OVERVIEW_CMD_TIMEOUT_MS ? Number(process.env.AT_UI_OVERVIEW_CMD_TIMEOUT_MS) : 1200;
const API_WORKER_KICK_TIMEOUT_MS = process.env.AT_UI_API_WORKER_KICK_TIMEOUT_MS ? Number(process.env.AT_UI_API_WORKER_KICK_TIMEOUT_MS) : 120;
const RUNTIME_STATUS_PATH = join(WORKSPACE_ROOT, 'Auto Trading', 'results', 'runtime_status.json');
const RUNTIME_STATE_PATH = join(WORKSPACE_ROOT, 'Auto Trading', 'results', 'runtime_state.json');
const LEDGER_RUNTIME_DIR = join(WORKSPACE_ROOT, 'Auto Trading', 'runtime', 'ledger');
const RESULTS_RUNTIME_DIR = join(WORKSPACE_ROOT, 'Auto Trading', 'results', 'runtime');
const EXCHANGE_TOGGLES_PATH = join(WORKSPACE_ROOT, 'Auto Trading', 'results', 'ui_exchange_toggles.json');
const UI_SETTINGS_PATH = join(WORKSPACE_ROOT, 'Auto Trading', 'ui_settings.json');
const DEFAULT_TIMELINE_LIMIT = process.env.AT_UI_TIMELINE_DEFAULT_LIMIT ? Number(process.env.AT_UI_TIMELINE_DEFAULT_LIMIT) : 30;
const DEFAULT_TIMELINE_WINDOW_HOURS = process.env.AT_UI_TIMELINE_DEFAULT_HOURS ? Number(process.env.AT_UI_TIMELINE_DEFAULT_HOURS) : 24;
const TIMELINE_MAX_CAP = process.env.AT_UI_TIMELINE_MAX_CAP ? Number(process.env.AT_UI_TIMELINE_MAX_CAP) : 300;

let requestSeq = 0;

function requestStart(req, url) {
  const id = ++requestSeq;
  const startedAt = Date.now();
  console.log(`[watchdog] #${id} START ${req.method || 'GET'} ${url.pathname}`);
  return { id, startedAt };
}

function requestEnd(ctx, res, note = '') {
  const tookMs = Date.now() - ctx.startedAt;
  const suffix = note ? ` ${note}` : '';
  console.log(`[watchdog] #${ctx.id} END status=${res.statusCode} took=${tookMs}ms${suffix}`);
}

function sendJson(res, statusCode, body, ctx, note = '') {
  if (res.writableEnded) return;
  res.writeHead(statusCode, { 'content-type': MIME['.json'] });
  res.end(JSON.stringify(body, null, 2));
  if (ctx) requestEnd(ctx, res, note);
}

function sendApiError(res, ctx, error, route = 'unknown') {
  const message = String(error?.message || error || 'internal_error');
  sendJson(res, 500, { ok: false, route, error: message }, ctx, `route=${route} error=${message}`);
}

async function tryExecJson(cmd, timeoutMs = OVERVIEW_CMD_TIMEOUT_MS) {
  const { stdout } = await exec(cmd, {
    encoding: 'utf8',
    timeout: Math.max(100, Number(timeoutMs) || OVERVIEW_CMD_TIMEOUT_MS),
    windowsHide: true,
    maxBuffer: 1024 * 1024,
  });
  return JSON.parse(stdout || 'null');
}

async function runJson(cmd) {
  try {
    return await tryExecJson(cmd);
  } catch {
    const escaped = cmd.replace(/"/g, '\\"');
    return tryExecJson(`wsl -e bash -lc "${escaped}"`);
  }
}

async function safeRun(cmd, fallback = null) {
  try { return await runJson(cmd); } catch { return fallback; }
}

async function readJsonFile(path, fallback = null) {
  try {
    const raw = await readFile(path, 'utf8');
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

async function readStatePoint() {
  const p = join(WORKSPACE_ROOT, 'team', 'statepoints', 'latest.json');
  return readJsonFile(p, null);
}

async function readRuntimeStatus() {
  return readJsonFile(RUNTIME_STATUS_PATH, null);
}

async function readRuntimeState() {
  return readJsonFile(RUNTIME_STATE_PATH, null);
}


function toNum(v, d = null) {
  const n = Number(v);
  return Number.isFinite(n) ? n : d;
}

function dateKeyFromTs(tsMs) {
  const d = new Date(Number(tsMs || 0));
  if (Number.isNaN(d.getTime())) return null;
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function normalizeDailyRow(raw = {}) {
  const date = String(raw.date || raw.day || '').trim();
  const pnl = toNum(raw.pnl_krw ?? raw.pnl ?? raw.daily_pnl_krw, null);
  const equity = toNum(raw.virtual_equity ?? raw.equity ?? raw.equity_krw, null);
  const trades = toNum(raw.trades ?? raw.trade_count, 0);
  const winRate = toNum(raw.win_rate ?? raw.winRate, null);
  const source = String(raw.source || raw.kind || 'ledger_snapshot');
  if (!date) return null;
  return { date, pnl_krw: pnl, virtual_equity: equity, trades, win_rate: winRate, source };
}

async function readLedgerDailySnapshots() {
  const paths = [LEDGER_RUNTIME_DIR, RESULTS_RUNTIME_DIR];
  const out = [];
  for (const dir of paths) {
    try {
      const names = await readFile(join(dir, '.keep'), 'utf8').then(() => []).catch(async () => {
        const { readdir } = await import('node:fs/promises');
        return readdir(dir);
      });
      for (const name of names) {
        const low = String(name || '').toLowerCase();
        if (!low.endsWith('.json')) continue;
        if (!(low.includes('ledger') || low.includes('snapshot'))) continue;
        const obj = await readJsonFile(join(dir, name), null);
        if (!obj || typeof obj !== 'object') continue;
        const candidates = [];
        if (Array.isArray(obj.daily_reviews)) candidates.push(...obj.daily_reviews);
        if (Array.isArray(obj.daily)) candidates.push(...obj.daily);
        if (Array.isArray(obj.reviews)) candidates.push(...obj.reviews);
        if (Array.isArray(obj.snapshots)) candidates.push(...obj.snapshots);
        if (!candidates.length && (obj.date || obj.day)) candidates.push(obj);
        for (const c of candidates) {
          const row = normalizeDailyRow(c || {});
          if (row) out.push(row);
        }
      }
    } catch {
      // ignore missing dirs/files
    }
  }
  const dedup = new Map();
  for (const r of out) dedup.set(r.date, r);
  return [...dedup.values()].sort((a, b) => String(b.date).localeCompare(String(a.date)));
}

function normalizeExchange(v, fallback = 'total') {
  const s = String(v || '').toLowerCase();
  if (s.includes('upbit')) return 'upbit';
  if (s.includes('bithumb')) return 'bithumb';
  return fallback;
}

function exchangeHintFromName(name = '') {
  return normalizeExchange(name, 'total');
}

function normalizeDayPoint(raw = {}, exchangeHint = 'total') {
  const date = String(raw.date || raw.day || dateKeyFromTs(raw.ts || raw.timestamp || raw.time) || '').trim();
  if (!date) return null;
  const exchange = normalizeExchange(raw.exchange || raw.exchange_name || raw.venue, exchangeHint);
  return {
    date,
    exchange,
    virtual_equity: toNum(raw.virtual_equity ?? raw.equity_virtual ?? raw.equity ?? raw.next_available_capital, null),
    pnl_krw: toNum(raw.pnl_krw ?? raw.pnl_virtual ?? raw.pnl ?? raw.daily_pnl_krw, null),
    trades: toNum(raw.trades ?? raw.trade_count, 0),
    source: String(raw.source || raw.kind || ''),
  };
}

async function readDailyVirtualSnapshotRows() {
  const { readdir } = await import('node:fs/promises');
  const scanDirs = [
    join(WORKSPACE_ROOT, 'Auto Trading', 'runtime'),
    LEDGER_RUNTIME_DIR,
    RESULTS_RUNTIME_DIR,
    join(WORKSPACE_ROOT, 'Auto Trading', 'results'),
  ];
  const out = [];
  for (const dir of scanDirs) {
    let names = [];
    try { names = await readdir(dir); } catch { continue; }
    for (const name of names) {
      const low = String(name || '').toLowerCase();
      if (!low.includes('daily_virtual_snapshot')) continue;
      const full = join(dir, name);
      try {
        if (low.endsWith('.jsonl')) {
          const raw = await readFile(full, 'utf8');
          for (const line of raw.split('\n').filter(Boolean)) {
            let j = null;
            try { j = JSON.parse(line); } catch { j = null; }
            if (!j) continue;
            const p = normalizeDayPoint(j, exchangeHintFromName(name));
            if (p) out.push({ ...p, source: p.source || 'daily_virtual_snapshot' });
          }
        } else if (low.endsWith('.json')) {
          const j = await readJsonFile(full, null);
          const rows = Array.isArray(j) ? j : (Array.isArray(j?.daily_virtual_snapshot) ? j.daily_virtual_snapshot : (Array.isArray(j?.daily) ? j.daily : (Array.isArray(j?.snapshots) ? j.snapshots : [j])));
          for (const row of rows) {
            const p = normalizeDayPoint(row || {}, exchangeHintFromName(name));
            if (p) out.push({ ...p, source: p.source || 'daily_virtual_snapshot' });
          }
        }
      } catch {
        // ignore broken snapshot file
      }
    }
  }
  const dedup = new Map();
  for (const r of out) dedup.set(r.date, r);
  return [...dedup.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)));
}

function aggregateDailyRows(rows, limit = 30, source = 'runtime_ledger_aggregate', targetExchange = 'total') {
  const grouped = new Map();
  for (const raw of rows || []) {
    const hint = normalizeExchange(raw?.__exchange_hint || raw?.exchange || raw?.exchange_name || raw?.venue, 'total');
    const p = normalizeDayPoint(raw || {}, hint);
    if (!p || !p.date) continue;

    if (targetExchange !== 'total' && p.exchange !== targetExchange) continue;
    if (targetExchange === 'total' && p.exchange === 'total') {
      // total 전용 레코드는 그대로 사용
    }

    const prev = grouped.get(p.date) || { date: p.date, pnl_krw: 0, virtual_equity: 0, trades: 0, source, exchange: targetExchange };
    if (Number.isFinite(p.pnl_krw)) prev.pnl_krw += Number(p.pnl_krw);
    if (Number.isFinite(p.trades)) prev.trades += Number(p.trades);
    if (Number.isFinite(p.virtual_equity)) prev.virtual_equity += Number(p.virtual_equity);
    grouped.set(p.date, prev);
  }
  const sorted = [...grouped.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)));
  const tail = sorted.slice(-Math.max(1, Number(limit) || 30));
  for (let i = 0; i < tail.length; i += 1) {
    if (!Number.isFinite(tail[i].virtual_equity) && i > 0 && Number.isFinite(tail[i - 1].virtual_equity) && Number.isFinite(tail[i].pnl_krw)) {
      tail[i].virtual_equity = Number(tail[i - 1].virtual_equity) + Number(tail[i].pnl_krw);
    }
  }
  return tail;
}

async function readRuntimeLedgerAggregatePoints() {
  const { readdir } = await import('node:fs/promises');
  const scanDirs = [join(WORKSPACE_ROOT, 'Auto Trading', 'runtime'), LEDGER_RUNTIME_DIR, RESULTS_RUNTIME_DIR];
  const points = [];

  for (const dir of scanDirs) {
    let names = [];
    try { names = await readdir(dir); } catch { continue; }
    for (const name of names) {
      const low = String(name || '').toLowerCase();
      if (!(low.endsWith('.json') || low.endsWith('.jsonl'))) continue;
      if (!(low.includes('ledger') || low.includes('runtime') || low.includes('snapshot'))) continue;
      const full = join(dir, name);
      const exHint = exchangeHintFromName(name);
      try {
        if (low.endsWith('.jsonl')) {
          const raw = await readFile(full, 'utf8');
          for (const line of raw.split('\n').filter(Boolean)) {
            let j = null;
            try { j = JSON.parse(line); } catch { j = null; }
            if (!j || typeof j !== 'object') continue;
            points.push({ ...j, __exchange_hint: exHint });
          }
        } else {
          const j = await readJsonFile(full, null);
          if (!j) continue;
          if (Array.isArray(j)) points.push(...j.map((x) => ({ ...(x || {}), __exchange_hint: exHint })));
          else {
            if (Array.isArray(j.daily_reviews)) points.push(...j.daily_reviews.map((x) => ({ ...(x || {}), __exchange_hint: exHint })));
            if (Array.isArray(j.daily)) points.push(...j.daily.map((x) => ({ ...(x || {}), __exchange_hint: exHint })));
            if (Array.isArray(j.reviews)) points.push(...j.reviews.map((x) => ({ ...(x || {}), __exchange_hint: exHint })));
            if (Array.isArray(j.snapshots)) points.push(...j.snapshots.map((x) => ({ ...(x || {}), __exchange_hint: exHint })));
            if (j.date || j.day || j.ts || j.timestamp) points.push({ ...j, __exchange_hint: exHint });
          }
        }
      } catch {
        // ignore parse errors
      }
    }
  }

  const fromLedgerDaily = (await readLedgerDailySnapshots()).map((x) => ({ ...(x || {}), __exchange_hint: normalizeExchange(x?.exchange, 'total') }));
  return [...fromLedgerDaily, ...points];
}

function finalizeCapitalGraph(rows, runtimeStatus, runtimeState, source, exchangeKey) {
  const r = (rows || []).slice(-30);
  const seed = toNum(runtimeStatus?.virtual_capital?.allocated ?? runtimeStatus?.seed_krw ?? runtimeState?.seed_krw, null);
  const initialEquity = Number.isFinite(r[0]?.virtual_equity) ? Number(r[0].virtual_equity) : toNum(runtimeStatus?.virtual_capital?.equity_virtual ?? runtimeStatus?.equity, null);
  const startBase = Number.isFinite(seed) && seed > 0 ? seed : initialEquity;
  const currentEquity = Number.isFinite(r[r.length - 1]?.virtual_equity)
    ? Number(r[r.length - 1].virtual_equity)
    : toNum(runtimeStatus?.virtual_capital?.equity_virtual ?? runtimeStatus?.equity, null);
  const prevEquity = Number.isFinite(r[r.length - 2]?.virtual_equity) ? Number(r[r.length - 2].virtual_equity) : null;
  const dayDelta = Number.isFinite(currentEquity) && Number.isFinite(prevEquity) ? currentEquity - prevEquity : null;
  const dayDeltaPct = Number.isFinite(dayDelta) && Number.isFinite(prevEquity) && prevEquity !== 0 ? (dayDelta / prevEquity) * 100 : null;
  const cumulativeReturnPct = Number.isFinite(currentEquity) && Number.isFinite(startBase) && startBase > 0
    ? ((currentEquity - startBase) / startBase) * 100
    : null;

  return {
    exchange: exchangeKey,
    source,
    rows: r,
    current_equity: currentEquity,
    prev_equity: prevEquity,
    day_delta_krw: dayDelta,
    day_delta_pct: dayDeltaPct,
    start_capital: startBase,
    cumulative_return_pct: cumulativeReturnPct,
    has_data: r.length > 0,
  };
}

async function buildCapitalDailyGraph(runtimeStatus, runtimeState) {
  const fromSnapshot = await readDailyVirtualSnapshotRows();
  const source = fromSnapshot.length ? 'daily_virtual_snapshot' : 'runtime_ledger_aggregate';
  const points = fromSnapshot.length ? fromSnapshot : await readRuntimeLedgerAggregatePoints();

  const totalRows = aggregateDailyRows(points, 30, source, 'total');
  const upbitRows = aggregateDailyRows(points, 30, source, 'upbit');
  const bithumbRows = aggregateDailyRows(points, 30, source, 'bithumb');

  return {
    selected: 'total',
    total: finalizeCapitalGraph(totalRows, runtimeStatus, runtimeState, source, 'total'),
    upbit: finalizeCapitalGraph(upbitRows, runtimeStatus, runtimeState, source, 'upbit'),
    bithumb: finalizeCapitalGraph(bithumbRows, runtimeStatus, runtimeState, source, 'bithumb'),
  };
}

function buildFallbackDailyReview(runtimeStatus, runtimeState, days = 7) {
  const nowKey = dateKeyFromTs(Date.now());
  const yesterday = nowKey ? new Date(Date.now() - 24 * 3600 * 1000) : null;
  const yk = yesterday ? dateKeyFromTs(yesterday.getTime()) : null;
  const vc = runtimeStatus?.virtual_capital || runtimeState?.virtual_capital || {};
  const pnl = toNum(vc.pnl_virtual ?? runtimeStatus?.pnl_krw ?? runtimeState?.realized_pnl_krw, 0);
  const veq = toNum(vc.equity_virtual ?? runtimeStatus?.equity ?? runtimeState?.equity, null);
  const one = yk ? [{ date: yk, pnl_krw: pnl, virtual_equity: veq, trades: 0, win_rate: null, source: 'fallback' }] : [];
  return one.slice(0, Math.max(1, Number(days) || 7));
}

function deriveVirtualCapital({ runtimeStatus, runtimeState, workerSnap }) {
  const fromStatus = runtimeStatus?.virtual_capital || {};
  const equity = toNum(
    fromStatus.equity_virtual
      ?? fromStatus.next_available_capital
      ?? runtimeStatus?.equity
      ?? runtimeState?.equity
      ?? workerSnap?.state?.equity,
    0,
  );
  const seed = toNum(fromStatus.allocated ?? runtimeStatus?.seed_krw ?? workerSnap?.state?.seed ?? 0, 0);
  const pnl = toNum(fromStatus.pnl_virtual, equity - seed);
  const pnlPct = toNum(fromStatus.pnl_pct_virtual, seed > 0 ? (pnl / seed) * 100 : 0);
  const cap = toNum(fromStatus.cap_krw, null);
  const nextAvail = cap != null && cap > 0 ? Math.min(equity, cap) : equity;
  return {
    rule: 'next_available_capital = current_virtual_equity',
    seed_krw: seed,
    equity_virtual: equity,
    pnl_virtual: pnl,
    pnl_pct_virtual: pnlPct,
    next_available_capital: Math.max(0, nextAvail),
    available_for_bot: Math.max(0, nextAvail),
    cap_krw: cap,
  };
}

function pickArray(obj, paths = []) {
  for (const p of paths) {
    const v = p.split('.').reduce((acc, key) => (acc && typeof acc === 'object') ? acc[key] : undefined, obj);
    if (Array.isArray(v)) return v;
  }
  return [];
}

function normalizeSymbols(list) {
  return [...new Set((Array.isArray(list) ? list : []).map((x) => String(x || '').trim()).filter(Boolean))];
}

function deriveWatchingSymbols({ runtimeStatus, runtimeState, statePoint, workerSnap }) {
  const fromRuntimeStatus = pickArray(runtimeStatus, ['watchlist', 'symbols']);
  const fromRuntimeState = pickArray(runtimeState, ['watchlist', 'symbols']);
  const fromStatePoint = pickArray(statePoint, ['watchlist', 'symbols', 'runtime.watchlist', 'runtime.symbols']);
  const fromWorkerState = pickArray(workerSnap, ['state.watchlist', 'state.symbols', 'watchlist', 'symbols']);
  return normalizeSymbols([...fromRuntimeStatus, ...fromRuntimeState, ...fromStatePoint, ...fromWorkerState]);
}

function deriveExchangeIndicators({ runtimeStatus, workerSnap }) {
  const activeExchange = String(
    runtimeStatus?.exchange
    || workerSnap?.state?.pending?.exchange
    || workerSnap?.state?.exchange
    || ''
  ).toUpperCase();
  const connected = workerSnap?.connected === true;

  const asStatus = (exchange) => {
    if (!exchange || !activeExchange) return { status: 'unknown', detail: 'exchange state unavailable' };
    if (activeExchange !== exchange) return { status: 'idle', detail: `active=${activeExchange}` };
    return connected
      ? { status: 'connected', detail: 'worker connected' }
      : { status: 'disconnected', detail: 'worker disconnected' };
  };

  return {
    upbit: asStatus('UPBIT'),
    bithumb: asStatus('BITHUMB'),
  };
}

function normalizeExchangeToggles(raw) {
  const upbit = raw?.upbit !== false;
  const bithumb = raw?.bithumb !== false;
  return { upbit, bithumb };
}

async function readExchangeToggles() {
  const saved = await readJsonFile(EXCHANGE_TOGGLES_PATH, null);
  return normalizeExchangeToggles(saved);
}

async function writeExchangeToggles(next) {
  const normalized = normalizeExchangeToggles(next);
  try {
    await mkdir(join(WORKSPACE_ROOT, 'Auto Trading', 'results'), { recursive: true });
    await writeFile(EXCHANGE_TOGGLES_PATH, JSON.stringify(normalized, null, 2), 'utf8');
  } catch {
    // ignore persistence failure
  }
  return normalized;
}

function normalizeCapitalCap(raw, fallback = null) {
  const n = Number(raw);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(0, Math.floor(n));
}

async function readUiSettings() {
  const payload = await readJsonFile(UI_SETTINGS_PATH, {});
  const capitalCap = normalizeCapitalCap(payload?.capital_cap_krw, null);
  return {
    ...payload,
    capital_cap_krw: capitalCap,
  };
}

async function writeUiSettings(next = {}) {
  const prev = await readJsonFile(UI_SETTINGS_PATH, {});
  const cap = normalizeCapitalCap(next?.capital_cap_krw, normalizeCapitalCap(prev?.capital_cap_krw, 0));
  const merged = {
    ...prev,
    ...next,
    capital_cap_krw: cap,
  };
  await writeFile(UI_SETTINGS_PATH, JSON.stringify(merged, null, 2), 'utf8');
  return merged;
}

function deriveMarketOneLiner({ runtimeStatus, runtimeState, statePoint, workerSnap }) {
  const mode = String(runtimeStatus?.mode || workerSnap?.state?.pending?.mode || '').toUpperCase();
  if (mode !== 'PAPER') return '';

  const riskRaw = String(
    runtimeState?.riskLevel
    || runtimeState?.risk
    || statePoint?.riskLevel
    || statePoint?.risk
    || workerSnap?.state?.riskLevel
    || workerSnap?.state?.risk
    || ''
  ).toLowerCase();

  const volRaw = Number(
    runtimeState?.volatility
    || runtimeStatus?.volatility
    || statePoint?.volatility
    || statePoint?.market?.volatility
    || NaN
  );

  if (riskRaw.includes('red') || riskRaw.includes('critical') || riskRaw.includes('high')) {
    return '시장 한줄 코멘트: 리스크 경계 (고위험 신호 감지, 포지션 축소/관망 권장)';
  }
  if (Number.isFinite(volRaw) && volRaw >= 0.04) {
    return '시장 한줄 코멘트: 변동성 확대 (급등락 가능성↑, 진입 신중)';
  }
  if (Number.isFinite(volRaw) && volRaw <= 0.01) {
    return '시장 한줄 코멘트: 횡보 구간 (모멘텀 약함, 신호 선별 필요)';
  }
  return '시장 한줄 코멘트: 데이터 제한으로 추세 판별 보류 (fallback)';
}

async function readTaskSignals() {
  const p = join(WORKSPACE_ROOT, 'TASKS.md');
  let raw;
  try {
    raw = await readFile(p, 'utf8');
  } catch {
    return { inProgressWorkers: [], tasks: [], agentWork: {} };
  }

  try {
    const lines = raw.split('\n').filter((l) => l.trim().startsWith('|'));
    const rows = lines.slice(2);
    const tasks = [];
    const inProgressWorkers = new Set();
    const agentWork = {};

    for (const row of rows) {
      const cols = row.split('|').map((c) => c.trim());
      if (cols.length < 10) continue;
      const taskId = cols[1];
      const status = (cols[2] || '').toUpperCase();
      const owner = (cols[3] || '').toLowerCase();
      const description = cols[4] || '';
      const ownership = (cols[6] || '').toLowerCase();

      tasks.push({ taskId, status, owner, description, ownership });
      if (status === 'IN_PROGRESS') {
        if (owner.includes('pm')) {
          inProgressWorkers.add('pm');
          agentWork.pm = { taskId, description, status };
        }
        if (owner.includes('tl')) {
          inProgressWorkers.add('tl');
          agentWork.tl = { taskId, description, status };
        }
        if (owner.includes('architect')) {
          inProgressWorkers.add('architect');
          agentWork.architect = { taskId, description, status };
        }
        if (owner.includes('coder_a') || ownership.includes('a:')) {
          inProgressWorkers.add('coder_a');
          agentWork.coder_a = { taskId, description, status };
        }
        if (owner.includes('coder_b') || ownership.includes('b:')) {
          inProgressWorkers.add('coder_b');
          agentWork.coder_b = { taskId, description, status };
        }
      }
    }

    return { inProgressWorkers: [...inProgressWorkers], tasks, agentWork };
  } catch {
    return { inProgressWorkers: [], tasks: [], agentWork: {} };
  }
}

function normalizeRuns(status) {
  return status?.sessions?.recent || status?.sessions?.list || status?.sessions?.sessions || [];
}

function computeTokenSnapshot(status, checkpoint) {
  const runList = normalizeRuns(status);
  const perAgent = {};
  for (const s of runList) {
    const agentId = s.agentId || String(s.key || '').split(':')[1] || 'unknown';
    const used = Number(s.inputTokens || 0) + Number(s.outputTokens || 0);
    perAgent[agentId] = Math.max(perAgent[agentId] || 0, used);
  }
  const total = Object.values(perAgent).reduce((a, b) => a + b, 0);
  return {
    ts: Date.now(),
    iso: new Date().toISOString(),
    task_id: checkpoint?.task_id || checkpoint?.taskId || null,
    per_agent: perAgent,
    total,
  };
}

async function appendSnapshot(snapshot) {
  try {
    await mkdir(USAGE_DIR, { recursive: true });
    await appendFile(SNAPSHOT_FILE, `${JSON.stringify(snapshot)}\n`, 'utf8');
  } catch {
    // ignore
  }
}

async function readSnapshots() {
  try {
    const raw = await readFile(SNAPSHOT_FILE, 'utf8');
    const lines = raw.split('\n').filter(Boolean);
    return lines.map((l) => JSON.parse(l)).filter((x) => x && x.ts);
  } catch {
    return [];
  }
}

async function readActivityState() {
  const parsed = await readJsonFile(ACTIVITY_STATE_FILE, { runs: {}, tasks: {} });
  return {
    runs: (parsed && typeof parsed.runs === 'object' && !Array.isArray(parsed.runs)) ? parsed.runs : {},
    tasks: (parsed && typeof parsed.tasks === 'object' && !Array.isArray(parsed.tasks)) ? parsed.tasks : {},
  };
}

async function writeActivityState(state) {
  try {
    await mkdir(USAGE_DIR, { recursive: true });
    await writeFile(ACTIVITY_STATE_FILE, JSON.stringify(state), 'utf8');
  } catch {
    // ignore
  }
}

async function appendActivityEvents(events) {
  if (!events?.length) return;
  try {
    await mkdir(USAGE_DIR, { recursive: true });
    const payload = events.map((e) => JSON.stringify(e)).join('\n') + '\n';
    await appendFile(ACTIVITY_LOG_FILE, payload, 'utf8');
  } catch {
    // ignore
  }
}

function toSafeInt(v, fallback) {
  const n = Number(v);
  if (!Number.isFinite(n)) return fallback;
  return Math.floor(n);
}

function clampTimelineLimit(v) {
  const n = toSafeInt(v, DEFAULT_TIMELINE_LIMIT);
  return Math.max(1, Math.min(TIMELINE_MAX_CAP, n));
}

function normalizeTimelineEvents(rows) {
  if (!Array.isArray(rows)) return [];
  return rows
    .filter((x) => x && typeof x === 'object')
    .map((x) => ({ ...x, ts: Number(x.ts || 0), count: Math.max(1, Number(x.count || 1) || 1) }))
    .sort((a, b) => (b.ts || 0) - (a.ts || 0));
}

function compressConsecutiveSessionUpdates(rows) {
  const out = [];
  for (const item of normalizeTimelineEvents(rows)) {
    const prev = out[out.length - 1];
    const sameSessionUpdate =
      prev
      && prev.work === 'session_update'
      && item.work === 'session_update'
      && prev.agent === item.agent
      && prev.detail === item.detail;

    if (sameSessionUpdate) {
      prev.count = Math.max(1, Number(prev.count || 1)) + Math.max(1, Number(item.count || 1));
      if ((item.ts || 0) > (prev.ts || 0)) {
        prev.ts = item.ts;
        prev.time = item.time;
      }
    } else {
      out.push({ ...item, count: Math.max(1, Number(item.count || 1)) });
    }
  }
  return out;
}

function applyTimelineWindow(rows, hours = DEFAULT_TIMELINE_WINDOW_HOURS) {
  if (hours === 'all' || hours === 0) return [...rows];
  const h = Math.max(1, toSafeInt(hours, DEFAULT_TIMELINE_WINDOW_HOURS));
  const cutoff = Date.now() - h * 3600 * 1000;
  return rows.filter((x) => Number(x.ts || 0) >= cutoff);
}

function buildTimelineView(rows, { hours = DEFAULT_TIMELINE_WINDOW_HOURS, limit = DEFAULT_TIMELINE_LIMIT } = {}) {
  const compressed = compressConsecutiveSessionUpdates(rows);
  const windowed = applyTimelineWindow(compressed, hours);
  const safeLimit = clampTimelineLimit(limit);
  return {
    rows: windowed.slice(0, safeLimit),
    meta: {
      limit: safeLimit,
      hours,
      totalAfterCompress: compressed.length,
      totalAfterWindow: windowed.length,
      cap: TIMELINE_MAX_CAP,
    },
  };
}

async function readActivityLog(limit = TIMELINE_MAX_CAP) {
  try {
    const safeLimit = clampTimelineLimit(limit);
    const raw = await readFile(ACTIVITY_LOG_FILE, 'utf8');
    const lines = raw.split('\n').filter(Boolean);
    const rows = lines.slice(-safeLimit).map((l) => JSON.parse(l));
    return normalizeTimelineEvents(rows).slice(0, TIMELINE_MAX_CAP);
  } catch {
    return [];
  }
}

async function collectActivityEvents(status, taskSignals) {
  const state = await readActivityState();
  state.runs = state.runs || {};
  state.tasks = state.tasks || {};

  const events = [];
  const runList = normalizeRuns(status);

  for (const s of runList) {
    const key = s.key;
    const updatedAt = Number(s.updatedAt || 0);
    if (!key || !updatedAt) continue;
    const prev = Number(state.runs[key] || 0);
    if (updatedAt > prev) {
      const agentId = s.agentId || String(key).split(':')[1] || 'unknown';
      events.push({
        ts: updatedAt,
        time: new Date(updatedAt).toISOString(),
        agent: agentId,
        work: 'session_update',
        project: PROJECT_NAME,
        detail: `${key} updated`,
      });
      state.runs[key] = updatedAt;
    }
  }

  for (const t of taskSignals.tasks || []) {
    if (!t.taskId) continue;
    const prev = state.tasks[t.taskId] || {};
    if (prev.status !== t.status || prev.owner !== t.owner || prev.description !== t.description) {
      const ts = Date.now();
      events.push({
        ts,
        time: new Date(ts).toISOString(),
        agent: t.owner || 'pm',
        work: 'task_status',
        project: PROJECT_NAME,
        detail: `${t.taskId}: ${(prev.status || 'NEW')} -> ${t.status} | ${t.description || ''}`,
      });
      state.tasks[t.taskId] = { status: t.status, owner: t.owner, description: t.description };
    }
  }

  await appendActivityEvents(events);
  await writeActivityState(state);
  return readActivityLog();
}

function summarizeUsage(snapshots) {
  const now = Date.now();
  const dayAgo = now - 24 * 3600 * 1000;
  const weekAgo = now - 7 * 24 * 3600 * 1000;

  const ordered = [...snapshots].sort((a, b) => a.ts - b.ts);
  const prevByAgent = {};
  const deltas = [];

  for (const s of ordered) {
    const d = { ts: s.ts, task_id: s.task_id || 'unassigned', per_agent: {}, total: 0 };
    for (const [agent, absRaw] of Object.entries(s.per_agent || {})) {
      const abs = Number(absRaw || 0);
      if (!(agent in prevByAgent)) {
        prevByAgent[agent] = abs;
        continue;
      }
      const prev = Number(prevByAgent[agent] || 0);
      const delta = abs >= prev ? (abs - prev) : 0;
      prevByAgent[agent] = abs;
      if (delta > 0) {
        d.per_agent[agent] = delta;
        d.total += delta;
      }
    }
    deltas.push(d);
  }

  const day = deltas.filter((s) => s.ts >= dayAgo);
  const week = deltas.filter((s) => s.ts >= weekAgo);

  const sumPerAgent = (arr) => {
    const out = {};
    for (const s of arr) {
      for (const [k, v] of Object.entries(s.per_agent || {})) out[k] = (out[k] || 0) + Number(v || 0);
    }
    return out;
  };

  const dailyPerAgent = sumPerAgent(day);
  const weeklyPerAgent = sumPerAgent(week);
  const dailyTotal = Object.values(dailyPerAgent).reduce((a, b) => a + b, 0);
  const weeklyTotal = Object.values(weeklyPerAgent).reduce((a, b) => a + b, 0);

  const byTask = {};
  for (const s of week) {
    const t = s.task_id || 'unassigned';
    byTask[t] = (byTask[t] || 0) + Number(s.total || 0);
  }

  const warning = dailyTotal >= 2_000_000 ? 'critical' : dailyTotal >= 1_000_000 ? 'warn' : 'ok';

  return {
    daily: { total: dailyTotal, perAgent: dailyPerAgent },
    weekly: { total: weeklyTotal, perAgent: weeklyPerAgent },
    byTask,
    warning,
    snapshotCount: snapshots.length,
    deltaCount: deltas.length,
  };
}

const workerClient = new WorkerApiClient(WORKER_API_BASE_URL, Number(WORKER_API_TIMEOUT_MS));
const workerMonitor = new WorkerMonitor({
  client: workerClient,
  pollMs: WORKER_POLL_MS,
  downDebounceMs: WORKER_DOWN_DEBOUNCE_MS,
});
workerMonitor.start();

let overviewCache = {
  now: new Date().toISOString(),
  sourceOk: false,
  worker: workerMonitor.stableSnapshotFallback(),
  statePoint: null,
  runtimeStatus: null,
  runtimeState: null,
  watchingSymbols: [],
  exchangeIndicators: {
    upbit: { status: 'unknown', detail: 'backend state unavailable' },
    bithumb: { status: 'unknown', detail: 'backend state unavailable' },
  },
  uiSettings: { capital_cap_krw: null },
  usage: summarizeUsage([]),
  taskSignals: { inProgressWorkers: [], tasks: [], agentWork: {} },
  timeline: [],
  timelineMeta: {
    limit: DEFAULT_TIMELINE_LIMIT,
    hours: DEFAULT_TIMELINE_WINDOW_HOURS,
    totalAfterCompress: 0,
    totalAfterWindow: 0,
    cap: TIMELINE_MAX_CAP,
  },
};
let overviewTimelineBase = [];
let exchangeTogglesCache = normalizeExchangeToggles(null);
let overviewRefreshRunning = false;

async function rebuildOverviewCache() {
  if (overviewRefreshRunning) return;
  overviewRefreshRunning = true;
  try {
    const [status, agents, statePoint, taskSignals, runtimeStatus, runtimeState, uiSettings] = await Promise.all([
      safeRun('openclaw status --all --json', null),
      safeRun('openclaw agents list --json', null),
      readStatePoint(),
      readTaskSignals(),
      readRuntimeStatus(),
      readRuntimeState(),
      readUiSettings(),
    ]);

    let rawTimeline = [];
    if (status) {
      const snap = computeTokenSnapshot(status, statePoint);
      await appendSnapshot(snap);
      rawTimeline = await collectActivityEvents(status, taskSignals);
    } else {
      rawTimeline = await readActivityLog(TIMELINE_MAX_CAP);
    }

    overviewTimelineBase = compressConsecutiveSessionUpdates(rawTimeline).slice(0, TIMELINE_MAX_CAP);
    const timelineView = buildTimelineView(overviewTimelineBase, {
      hours: DEFAULT_TIMELINE_WINDOW_HOURS,
      limit: DEFAULT_TIMELINE_LIMIT,
    });

    const usage = summarizeUsage(await readSnapshots());

    const workerSnap = workerMonitor.stableSnapshotFallback();
    exchangeTogglesCache = await readExchangeToggles();
    const virtualCapital = deriveVirtualCapital({ runtimeStatus, runtimeState, workerSnap });
    const capitalDailyGraph = await buildCapitalDailyGraph(runtimeStatus, runtimeState);
    const ledgerReviews = await readLedgerDailySnapshots();
    const yesterdayTradingReview = (ledgerReviews.length ? ledgerReviews : buildFallbackDailyReview(runtimeStatus, runtimeState, 7)).slice(0, 7);
    // Auto Trading UI split: keep only fields actually used by this UI.
    overviewCache = {
      now: new Date().toISOString(),
      sourceOk: Boolean(status && agents),
      worker: workerSnap,
      statePoint,
      runtimeStatus,
      runtimeState,
      watchingSymbols: deriveWatchingSymbols({ runtimeStatus, runtimeState, statePoint, workerSnap }),
      exchangeIndicators: deriveExchangeIndicators({ runtimeStatus, workerSnap }),
      exchangeToggles: exchangeTogglesCache,
      uiSettings,
      marketOneLiner: deriveMarketOneLiner({ runtimeStatus, runtimeState, statePoint, workerSnap }),
      virtualCapital,
      capitalDailyGraph,
      yesterdayTradingReview,
      usage,
      taskSignals,
      timeline: timelineView.rows,
      timelineMeta: timelineView.meta,
    };
  } catch {
    overviewCache = {
      ...overviewCache,
      now: new Date().toISOString(),
      sourceOk: false,
      worker: workerMonitor.stableSnapshotFallback(),
    };
  } finally {
    overviewRefreshRunning = false;
  }
}

rebuildOverviewCache();
setInterval(() => {
  rebuildOverviewCache().catch(() => {});
}, Math.max(500, OVERVIEW_REFRESH_MS));

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
};

const server = http.createServer((req, res) => {
  let url;
  try {
    url = new URL(req.url, `http://${req.headers.host || '127.0.0.1'}`);
  } catch (e) {
    res.writeHead(400, { 'content-type': MIME['.json'] });
    return res.end(JSON.stringify({ ok: false, error: 'bad_request', detail: String(e?.message || e) }, null, 2));
  }

  const ctx = requestStart(req, url);

  try {
    if (url.pathname === '/api/overview') {
      const qHoursRaw = url.searchParams.get('timelineHours');
      const qLimitRaw = url.searchParams.get('timelineLimit');
      const hours = (qHoursRaw === 'all' || qHoursRaw === '0') ? 'all' : toSafeInt(qHoursRaw, DEFAULT_TIMELINE_WINDOW_HOURS);
      const limit = clampTimelineLimit(qLimitRaw || DEFAULT_TIMELINE_LIMIT);
      const timelineView = buildTimelineView(overviewTimelineBase.length ? overviewTimelineBase : (overviewCache.timeline || []), { hours, limit });

      const workerSnap = workerMonitor.stableSnapshotFallback();
      const runtimeStatus = overviewCache.runtimeStatus || null;
      const runtimeState = overviewCache.runtimeState || null;
      const virtualCapital = deriveVirtualCapital({ runtimeStatus, runtimeState, workerSnap });
      const capitalDailyGraph = overviewCache.capitalDailyGraph || {
        selected: 'total',
        total: { source: 'fallback', rows: [], has_data: false },
        upbit: { source: 'fallback', rows: [], has_data: false },
        bithumb: { source: 'fallback', rows: [], has_data: false },
      };
      const yesterdayTradingReview = Array.isArray(overviewCache.yesterdayTradingReview) && overviewCache.yesterdayTradingReview.length
        ? overviewCache.yesterdayTradingReview.slice(0, 7)
        : buildFallbackDailyReview(runtimeStatus, runtimeState, 7);
      return sendJson(
        res,
        200,
        {
          ...overviewCache,
          worker: workerSnap,
          watchingSymbols: deriveWatchingSymbols({
            runtimeStatus,
            runtimeState: overviewCache.runtimeState || null,
            statePoint: overviewCache.statePoint || null,
            workerSnap,
          }),
          exchangeIndicators: deriveExchangeIndicators({ runtimeStatus, workerSnap }),
          exchangeToggles: exchangeTogglesCache,
          marketOneLiner: deriveMarketOneLiner({
            runtimeStatus,
            runtimeState: overviewCache.runtimeState || null,
            statePoint: overviewCache.statePoint || null,
            workerSnap,
          }),
          virtualCapital,
          capitalDailyGraph,
          yesterdayTradingReview,
          timeline: timelineView.rows,
          timelineMeta: timelineView.meta,
        },
        ctx,
        `route=/api/overview cache=immediate timelineLimit=${limit} timelineHours=${String(hours)}`,
      );
    }

    if (url.pathname === '/api/worker') {
      Promise.race([
        workerMonitor.tick(),
        new Promise((resolve) => setTimeout(resolve, Math.max(10, Number(API_WORKER_KICK_TIMEOUT_MS) || 120))),
      ]).catch(() => {});

      return sendJson(
        res,
        200,
        workerMonitor.stableSnapshotFallback(),
        ctx,
        'route=/api/worker non_blocking',
      );
    }


    if (url.pathname === '/api/worker/control/exchanges') {
      if ((req.method || 'GET').toUpperCase() !== 'POST') {
        return sendJson(res, 405, { ok: false, error: 'method_not_allowed' }, ctx, 'route=/api/worker/control/exchanges method_guard');
      }
      let body = '';
      req.on('data', (chunk) => { body += chunk; });
      req.on('error', (e) => sendApiError(res, ctx, e, '/api/worker/control/exchanges'));
      req.on('end', async () => {
        try {
          const parsed = body ? JSON.parse(body) : {};
          const toggles = normalizeExchangeToggles({
            upbit: parsed?.upbit ?? parsed?.upbitEnabled,
            bithumb: parsed?.bithumb ?? parsed?.bithumbEnabled,
          });
          exchangeTogglesCache = await writeExchangeToggles(toggles);

          const modePayload = {
            mode: String(parsed?.mode || overviewCache?.runtimeStatus?.mode || 'PAPER').toUpperCase(),
            exchanges: {
              upbit: exchangeTogglesCache.upbit,
              bithumb: exchangeTogglesCache.bithumb,
            },
          };

          let backendResult = null;
          let backendRoute = null;
          const attempts = [
            { route: 'control/mode', fn: () => workerClient.control('mode', modePayload) },
            { route: 'control/exchanges', fn: () => workerClient.control('exchanges', modePayload.exchanges) },
          ];
          for (const attempt of attempts) {
            try {
              backendResult = await attempt.fn();
              backendRoute = attempt.route;
              break;
            } catch {
              // try next
            }
          }

          await workerMonitor.tick();
          return sendJson(res, 200, {
            ok: true,
            action: 'exchanges',
            applied: exchangeTogglesCache,
            backendRoute,
            result: backendResult,
            worker: workerMonitor.snapshot(),
          }, ctx, 'route=/api/worker/control/exchanges');
        } catch (e) {
          return sendApiError(res, ctx, e, '/api/worker/control/exchanges');
        }
      });
      return;
    }

    if (url.pathname === '/api/ui-settings') {
      if ((req.method || 'GET').toUpperCase() === 'GET') {
        const settings = await readUiSettings();
        return sendJson(res, 200, { ok: true, settings }, ctx, 'route=/api/ui-settings get');
      }
      if ((req.method || 'GET').toUpperCase() !== 'POST') {
        return sendJson(res, 405, { ok: false, error: 'method_not_allowed' }, ctx, 'route=/api/ui-settings method_guard');
      }
      let body = '';
      req.on('data', (chunk) => { body += chunk; });
      req.on('error', (e) => sendApiError(res, ctx, e, '/api/ui-settings'));
      req.on('end', async () => {
        try {
          const parsed = body ? JSON.parse(body) : {};
          const capitalCap = normalizeCapitalCap(parsed?.capital_cap_krw, null);
          if (!Number.isFinite(capitalCap)) {
            return sendJson(res, 400, { ok: false, error: 'invalid_capital_cap_krw' }, ctx, 'route=/api/ui-settings invalid');
          }

          let backendResult = null;
          let backendRoute = null;
          const attempts = [
            { route: 'control/settings', fn: () => workerClient.control('settings', { capital_cap_krw: capitalCap }) },
            { route: 'control/config', fn: () => workerClient.control('config', { capital_cap_krw: capitalCap }) },
          ];
          for (const attempt of attempts) {
            try {
              backendResult = await attempt.fn();
              backendRoute = attempt.route;
              break;
            } catch {
              // fallback to local file save
            }
          }

          const saved = await writeUiSettings({ capital_cap_krw: capitalCap });
          overviewCache = { ...overviewCache, uiSettings: saved };
          return sendJson(res, 200, {
            ok: true,
            settings: saved,
            backendRoute,
            result: backendResult,
          }, ctx, 'route=/api/ui-settings post');
        } catch (e) {
          return sendApiError(res, ctx, e, '/api/ui-settings');
        }
      });
      return;
    }

    if (url.pathname.startsWith('/api/worker/control/')) {
      if ((req.method || 'GET').toUpperCase() !== 'POST') {
        return sendJson(res, 405, { ok: false, error: 'method_not_allowed' }, ctx, 'route=/api/worker/control method_guard');
      }
      const action = url.pathname.replace('/api/worker/control/', '').trim();
      let body = '';
      req.on('data', (chunk) => { body += chunk; });
      req.on('error', (e) => sendApiError(res, ctx, e, '/api/worker/control'));
      req.on('end', async () => {
        try {
          const parsed = body ? JSON.parse(body) : {};
          const out = await workerClient.control(action, parsed);
          await workerMonitor.tick();
          return sendJson(res, 200, { ok: true, action, result: out, worker: workerMonitor.snapshot() }, ctx, 'route=/api/worker/control');
        } catch (e) {
          return sendApiError(res, ctx, e, '/api/worker/control');
        }
      });
      return;
    }

    const path = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
    const filePath = join(ROOT, path);
    try {
      const buf = readFileSync(filePath);
      res.writeHead(200, { 'content-type': MIME[extname(filePath)] || 'application/octet-stream' });
      res.end(buf);
      requestEnd(ctx, res, `static=${path}`);
      return;
    } catch {
      res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
      res.end('Not Found');
      requestEnd(ctx, res, `static_missing=${path}`);
      return;
    }
  } catch (e) {
    if (url.pathname.startsWith('/api/')) {
      return sendApiError(res, ctx, e, url.pathname);
    }
    res.writeHead(500, { 'content-type': 'text/plain; charset=utf-8' });
    res.end('Internal Server Error');
    requestEnd(ctx, res, `route=${url.pathname} error=${String(e?.message || e)}`);
  }
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`auto-trading-ui listening on http://127.0.0.1:${PORT}`);
  console.log(`[startup] worker.baseURL=${WORKER_API_BASE_URL}`);
  console.log(`[startup] worker.timeoutMs=${Number(WORKER_API_TIMEOUT_MS)}`);
  console.log(`[startup] worker.pollMs=${Number(WORKER_POLL_MS)} worker.downDebounceMs=${Number(WORKER_DOWN_DEBOUNCE_MS)}`);
  console.log(`[startup] overview.refreshMs=${Number(OVERVIEW_REFRESH_MS)} overview.cmdTimeoutMs=${Number(OVERVIEW_CMD_TIMEOUT_MS)}`);
  console.log(`[startup] api.workerKickTimeoutMs=${Number(API_WORKER_KICK_TIMEOUT_MS)}`);
});
