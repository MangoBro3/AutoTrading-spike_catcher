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

async function readActivityLog(limit = 600) {
  try {
    const raw = await readFile(ACTIVITY_LOG_FILE, 'utf8');
    const lines = raw.split('\n').filter(Boolean);
    const rows = lines.slice(-limit).map((l) => JSON.parse(l));
    return rows.sort((a, b) => (b.ts || 0) - (a.ts || 0));
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
        work: 'run_update',
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
  usage: summarizeUsage([]),
  taskSignals: { inProgressWorkers: [], tasks: [], agentWork: {} },
  timeline: [],
};
let overviewRefreshRunning = false;

async function rebuildOverviewCache() {
  if (overviewRefreshRunning) return;
  overviewRefreshRunning = true;
  try {
    const [status, agents, statePoint, taskSignals] = await Promise.all([
      safeRun('openclaw status --all --json', null),
      safeRun('openclaw agents list --json', null),
      readStatePoint(),
      readTaskSignals(),
    ]);

    let timeline = [];
    if (status) {
      const snap = computeTokenSnapshot(status, statePoint);
      await appendSnapshot(snap);
      timeline = await collectActivityEvents(status, taskSignals);
    } else {
      timeline = await readActivityLog();
    }

    const usage = summarizeUsage(await readSnapshots());

    // Auto Trading UI split: keep only fields actually used by this UI.
    overviewCache = {
      now: new Date().toISOString(),
      sourceOk: Boolean(status && agents),
      worker: workerMonitor.stableSnapshotFallback(),
      statePoint,
      usage,
      taskSignals,
      timeline,
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
      return sendJson(
        res,
        200,
        { ...overviewCache, worker: workerMonitor.stableSnapshotFallback() },
        ctx,
        'route=/api/overview cache=immediate',
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
