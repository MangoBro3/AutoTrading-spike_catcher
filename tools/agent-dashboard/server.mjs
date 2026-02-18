import http from 'node:http';
import { execSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import { extname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const PORT = process.env.PORT ? Number(process.env.PORT) : 18890;
const ROOT = fileURLToPath(new URL('./public/', import.meta.url));

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

function buildOverview() {
  const status = safeRun('openclaw status --all --json', null);
  const agents = safeRun('openclaw agents list --json', null);

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
    checkpoint: readCheckpoint(),
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
