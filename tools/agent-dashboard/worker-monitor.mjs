const DEFAULT_TIMEOUT_MS = 800;

function withTimeout(promise, timeoutMs = DEFAULT_TIMEOUT_MS) {
  return Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), timeoutMs)),
  ]);
}

async function fetchJson(url, { method = 'GET', body, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  const res = await withTimeout(fetch(url, {
    method,
    headers: { 'content-type': 'application/json' },
    body: body == null ? undefined : JSON.stringify(body),
  }), timeoutMs);

  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status}`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export class WorkerApiClient {
  constructor(baseUrl, timeoutMs = DEFAULT_TIMEOUT_MS) {
    this.baseUrl = (baseUrl || '').replace(/\/$/, '');
    this.timeoutMs = timeoutMs;
  }

  url(path) {
    return `${this.baseUrl}${path}`;
  }

  async health() { return fetchJson(this.url('/health'), { timeoutMs: this.timeoutMs }); }
  async state() { return fetchJson(this.url('/state'), { timeoutMs: this.timeoutMs }); }
  async orders() { return fetchJson(this.url('/orders'), { timeoutMs: this.timeoutMs }); }
  async control(action, body = {}) {
    return fetchJson(this.url(`/control/${action}`), { method: 'POST', body, timeoutMs: this.timeoutMs });
  }

  async pollOnce() {
    const calls = [
      this.health().then((v) => ({ ok: true, v })).catch((e) => ({ ok: false, e: String(e?.message || e) })),
      this.state().then((v) => ({ ok: true, v })).catch((e) => ({ ok: false, e: String(e?.message || e) })),
      this.orders().then((v) => ({ ok: true, v })).catch((e) => ({ ok: false, e: String(e?.message || e) })),
    ];
    const [health, state, orders] = await Promise.all(calls);

    const result = {
      ts: Date.now(),
      connected: health.ok,
      health: health.ok ? health.v : null,
      state: state.ok ? state.v : null,
      orders: orders.ok ? orders.v : null,
      errors: {
        health: health.ok ? null : health.e,
        state: state.ok ? null : state.e,
        orders: orders.ok ? null : orders.e,
      },
    };
    result.trafficLight = computeTrafficLight(result);
    result.stopAll = shouldStopAll(result.trafficLight);
    return result;
  }
}

export function computeTrafficLight(snapshot) {
  if (!snapshot || snapshot.connected !== true) return 'DISCONNECTED';

  const h = snapshot.health || {};
  const s = snapshot.state || {};
  const o = snapshot.orders || {};

  const healthBad = h.ok === false || h.status === 'down' || h.status === 'error';
  const emergency = s.emergencyStop === true || s.killSwitch === true || s.halt === true;
  const engineStopped = String(s.engine || s.mode || '').toLowerCase() === 'stopped';
  const riskRed = ['red', 'halted', 'critical', 'blocked'].includes(String(s.risk || s.riskLevel || '').toLowerCase());

  const orderErr = Number(o.errorCount || o.errors || 0) > 0;
  const queueHigh = Number(o.pending || o.queue || 0) >= 20;

  if (healthBad || emergency || engineStopped || riskRed) return 'RED';
  if (orderErr || queueHigh) return 'YELLOW';
  return 'GREEN';
}

export function shouldStopAll(trafficLight) {
  return trafficLight === 'DISCONNECTED' || trafficLight === 'RED';
}

export function toBannerText(trafficLight) {
  if (trafficLight === 'DISCONNECTED') return 'DISCONNECTED: 워커 연결 끊김 · 전체 중단';
  if (trafficLight === 'RED') return 'RED: 위험 상태 · 전체 중단';
  return '';
}

export class WorkerMonitor {
  constructor({ client, pollMs = 1000 }) {
    this.client = client;
    this.pollMs = pollMs;
    this.last = {
      ts: 0,
      connected: false,
      health: null,
      state: null,
      orders: null,
      errors: { health: 'not_started', state: 'not_started', orders: 'not_started' },
      trafficLight: 'DISCONNECTED',
      stopAll: true,
      banner: toBannerText('DISCONNECTED'),
    };
    this.timer = null;
  }

  async tick() {
    try {
      const snap = await this.client.pollOnce();
      this.last = { ...snap, banner: toBannerText(snap.trafficLight) };
    } catch (e) {
      this.last = {
        ...this.last,
        ts: Date.now(),
        connected: false,
        trafficLight: 'DISCONNECTED',
        stopAll: true,
        banner: toBannerText('DISCONNECTED'),
        errors: { ...this.last.errors, poll: String(e?.message || e) },
      };
    }
    return this.last;
  }

  start() {
    if (this.timer) return;
    this.tick();
    this.timer = setInterval(() => { this.tick(); }, this.pollMs);
  }

  stop() {
    if (!this.timer) return;
    clearInterval(this.timer);
    this.timer = null;
  }

  snapshot() {
    return this.last;
  }
}
