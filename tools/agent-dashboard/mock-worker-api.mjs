import http from 'node:http';

const PORT = process.env.WORKER_PORT ? Number(process.env.WORKER_PORT) : 18080;

const state = {
  emergencyStop: false,
  engine: 'running',
  risk: 'green',
  pending: 3,
  errorCount: 0,
  cancelled: [],
};

function json(res, code, payload){
  res.writeHead(code, { 'content-type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(payload));
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  if (url.pathname === '/health') return json(res, 200, { ok: true, status: 'up' });
  if (url.pathname === '/state') return json(res, 200, { emergencyStop: state.emergencyStop, engine: state.engine, risk: state.risk });
  if (url.pathname === '/orders') return json(res, 200, { pending: state.pending, errorCount: state.errorCount, cancelled: state.cancelled });

  if (url.pathname.startsWith('/control/') && req.method === 'POST') {
    let body = '';
    req.on('data', (c) => { body += c; });
    req.on('end', () => {
      const parsed = body ? JSON.parse(body) : {};
      const action = url.pathname.replace('/control/', '');

      if (action === 'panic') {
        state.emergencyStop = true;
        state.engine = 'stopped';
        state.risk = 'red';
        return json(res, 200, { ok: true, action, status: 'panic_armed', detail: parsed });
      }

      if (action === 'cancel-order') {
        const orderId = String(parsed.orderId || '').trim() || 'UNKNOWN';
        state.pending = Math.max(0, state.pending - 1);
        state.cancelled.push(orderId);
        return json(res, 200, { ok: true, action, orderId, status: 'cancelled' });
      }

      return json(res, 200, { ok: true, action, status: 'noop', detail: parsed });
    });
    return;
  }

  return json(res, 404, { ok: false, error: 'not_found' });
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`mock-worker-api listening on http://127.0.0.1:${PORT}`);
});
