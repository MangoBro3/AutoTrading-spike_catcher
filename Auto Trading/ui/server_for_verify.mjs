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
const EXCHANGE_TOGGLES_PATH = join(WORKSPACE_ROOT, 'Auto Trading', 'results', 'ui_exchange_toggles.json');
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
    const [status, agents, statePoint, taskSignals, runtimeStatus, runtimeState] = await Promise.all([
      safeRun('openclaw status --all --json', null),
      safeRun('openclaw agents list --json', null),
      readStatePoint(),
      readTaskSignals(),
      readRuntimeStatus(),
      readRuntimeState(),
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
      marketOneLiner: deriveMarketOneLiner({ runtimeStatus, runtimeState, statePoint, workerSnap }),
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
      marketOneLiner: deriveMarketOneLiner({ runtimeStatus, runtimeState, statePoint, workerSnap }),
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
