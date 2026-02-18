import http from 'node:http';
import { execSync } from 'node:child_process';
import { readFileSync, existsSync, mkdirSync, appendFileSync, writeFileSync } from 'node:fs';
import { extname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const PORT = process.env.PORT ? Number(process.env.PORT) : 18890;
const ROOT = fileURLToPath(new URL('./public/', import.meta.url));
const USAGE_DIR = '/mnt/f/SafeBot/openclaw-news-workspace/python/team/usage';
const SNAPSHOT_FILE = `${USAGE_DIR}/token_snapshots.jsonl`;
const ACTIVITY_LOG_FILE = `${USAGE_DIR}/activity_log.jsonl`;
const ACTIVITY_STATE_FILE = `${USAGE_DIR}/activity_state.json`;
const PROJECT_NAME = 'openclaw-news-workspace';

function tryExecJson(cmd) {
  const out = execSync(cmd, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  return JSON.parse(out);
}

function runJson(cmd) {
  // 1) native shell (WSL/Linux)
  try {
    return tryExecJson(cmd);
  } catch {
    // 2) Windows PowerShell -> WSL fallback
    try {
      const escaped = cmd.replace(/"/g, '\\"');
      return tryExecJson(`wsl -e bash -lc "${escaped}"`);
    } catch (err) {
      throw err;
    }
  }
}

function safeRun(cmd, fallback = null) {
  try { return runJson(cmd); } catch { return fallback; }
}

function readCheckpoint() {
  const p = '/mnt/f/SafeBot/openclaw-news-workspace/python/team/checkpoints/latest.json';
  if (!existsSync(p)) return null;
  try { return JSON.parse(readFileSync(p, 'utf8')); } catch { return null; }
}

function readTaskSignals() {
  const p = '/mnt/f/SafeBot/openclaw-news-workspace/python/TASKS.md';
  if (!existsSync(p)) return { inProgressAgents: [], tasks: [], agentWork: {} };
  try {
    const lines = readFileSync(p, 'utf8').split('\n').filter((l) => l.trim().startsWith('|'));
    const rows = lines.slice(2); // skip header + separator
    const tasks = [];
    const inProgressAgents = new Set();
    const agentWork = {};

    for (const row of rows) {
      const cols = row.split('|').map((c) => c.trim());
      // | ID | Status | Owner | Description | Dependency | Ownership | Contract Ref | Blocker | Fail Count |
      if (cols.length < 10) continue;
      const taskId = cols[1];
      const status = (cols[2] || '').toUpperCase();
      const owner = (cols[3] || '').toLowerCase();
      const description = cols[4] || '';
      const ownership = (cols[6] || '').toLowerCase();

      tasks.push({ taskId, status, owner, description, ownership });
      if (status === 'IN_PROGRESS') {
        if (owner.includes('pm')) {
          inProgressAgents.add('pm');
          agentWork.pm = { taskId, description, status };
        }
        if (owner.includes('tl')) {
          inProgressAgents.add('tl');
          agentWork.tl = { taskId, description, status };
        }
        if (owner.includes('architect')) {
          inProgressAgents.add('architect');
          agentWork.architect = { taskId, description, status };
        }
        if (owner.includes('coder_a') || ownership.includes('a:')) {
          inProgressAgents.add('coder_a');
          agentWork.coder_a = { taskId, description, status };
        }
        if (owner.includes('coder_b') || ownership.includes('b:')) {
          inProgressAgents.add('coder_b');
          agentWork.coder_b = { taskId, description, status };
        }
      }
    }

    return { inProgressAgents: [...inProgressAgents], tasks, agentWork };
  } catch {
    return { inProgressAgents: [], tasks: [], agentWork: {} };
  }
}

function normalizeSessions(status) {
  return status?.sessions?.recent || status?.sessions?.list || status?.sessions?.sessions || [];
}

function computeTokenSnapshot(status, checkpoint) {
  const sessions = normalizeSessions(status);
  const perAgent = {};
  for (const s of sessions) {
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

function appendSnapshot(snapshot) {
  try {
    mkdirSync(USAGE_DIR, { recursive: true });
    appendFileSync(SNAPSHOT_FILE, JSON.stringify(snapshot) + '\n', 'utf8');
  } catch {
    // ignore write errors for dashboard availability
  }
}

function readSnapshots() {
  if (!existsSync(SNAPSHOT_FILE)) return [];
  try {
    const lines = readFileSync(SNAPSHOT_FILE, 'utf8').split('\n').filter(Boolean);
    return lines.map((l) => JSON.parse(l)).filter((x) => x && x.ts);
  } catch {
    return [];
  }
}

function readActivityState() {
  if (!existsSync(ACTIVITY_STATE_FILE)) return { sessions: {}, tasks: {} };
  try { return JSON.parse(readFileSync(ACTIVITY_STATE_FILE, 'utf8')); } catch { return { sessions: {}, tasks: {} }; }
}

function writeActivityState(state) {
  try {
    mkdirSync(USAGE_DIR, { recursive: true });
    writeFileSync(ACTIVITY_STATE_FILE, JSON.stringify(state), 'utf8');
  } catch {
    // ignore
  }
}

function appendActivityEvents(events) {
  if (!events?.length) return;
  try {
    mkdirSync(USAGE_DIR, { recursive: true });
    for (const e of events) appendFileSync(ACTIVITY_LOG_FILE, JSON.stringify(e) + '\n', 'utf8');
  } catch {
    // ignore
  }
}

function readActivityLog(limit = 600) {
  if (!existsSync(ACTIVITY_LOG_FILE)) return [];
  try {
    const lines = readFileSync(ACTIVITY_LOG_FILE, 'utf8').split('\n').filter(Boolean);
    const rows = lines.slice(-limit).map((l) => JSON.parse(l));
    return rows.sort((a, b) => (b.ts || 0) - (a.ts || 0));
  } catch {
    return [];
  }
}

function collectActivityEvents(status, taskSignals) {
  const state = readActivityState();
  const events = [];
  const sessions = normalizeSessions(status);

  for (const s of sessions) {
    const key = s.key;
    const updatedAt = Number(s.updatedAt || 0);
    if (!key || !updatedAt) continue;
    const prev = Number(state.sessions[key] || 0);
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
      state.sessions[key] = updatedAt;
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

  appendActivityEvents(events);
  writeActivityState(state);
  return readActivityLog();
}

function summarizeUsage(snapshots) {
  const now = Date.now();
  const dayAgo = now - 24 * 3600 * 1000;
  const weekAgo = now - 7 * 24 * 3600 * 1000;

  // Convert absolute session-token snapshots -> delta usage snapshots
  const ordered = [...snapshots].sort((a, b) => a.ts - b.ts);
  const prevByAgent = {};
  const deltas = [];

  for (const s of ordered) {
    const d = { ts: s.ts, task_id: s.task_id || 'unassigned', per_agent: {}, total: 0 };
    for (const [agent, absRaw] of Object.entries(s.per_agent || {})) {
      const abs = Number(absRaw || 0);
      if (!(agent in prevByAgent)) {
        // first observation is baseline, not usage
        prevByAgent[agent] = abs;
        continue;
      }
      const prev = Number(prevByAgent[agent] || 0);
      // If counter drops (session reset/compaction), treat as fresh baseline (no negative usage)
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

function buildOverview() {
  const status = safeRun('openclaw status --all --json', null);
  const agents = safeRun('openclaw agents list --json', null);
  const checkpoint = readCheckpoint();
  const taskSignals = readTaskSignals();

  let timeline = [];
  if (status) {
    const snap = computeTokenSnapshot(status, checkpoint);
    appendSnapshot(snap);
    timeline = collectActivityEvents(status, taskSignals);
  } else {
    timeline = readActivityLog();
  }
  const usage = summarizeUsage(readSnapshots());

  return {
    now: new Date().toISOString(),
    sourceOk: Boolean(status && agents),
    gateway: status?.gateway || null,
    channelSummary: status?.channelSummary || null,
    sessions: status?.sessions || null,
    agentsMeta: status?.agents || null,
    agents: agents || [],
    heartbeat: status?.heartbeat || null,
    securityAudit: status?.securityAudit || null,
    checkpoint,
    usage,
    taskSignals,
    timeline,
  };
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
};

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  if (url.pathname === '/api/overview') {
    const payload = buildOverview();
    res.writeHead(200, { 'content-type': MIME['.json'] });
    return res.end(JSON.stringify(payload, null, 2));
  }

  const path = url.pathname === '/' ? 'index.html' : url.pathname.slice(1);
  const filePath = join(ROOT, path);
  try {
    const buf = readFileSync(filePath);
    res.writeHead(200, { 'content-type': MIME[extname(filePath)] || 'application/octet-stream' });
    res.end(buf);
  } catch {
    res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
    res.end('Not Found');
  }
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`agent-dashboard listening on http://127.0.0.1:${PORT}`);
});
