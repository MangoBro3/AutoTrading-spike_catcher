import test from 'node:test';
import assert from 'node:assert/strict';
import { WorkerMonitor, computeTrafficLight, shouldStopAll, toBannerText } from './worker-monitor.mjs';

test('DISCONNECTED when not connected', () => {
  const light = computeTrafficLight({ connected: false });
  assert.equal(light, 'DISCONNECTED');
  assert.equal(shouldStopAll(light), true);
  assert.match(toBannerText(light), /DISCONNECTED/);
});

test('RED when emergency stop', () => {
  const light = computeTrafficLight({ connected: true, health: { ok: true }, state: { emergencyStop: true }, orders: {} });
  assert.equal(light, 'RED');
  assert.equal(shouldStopAll(light), true);
});



test('Worker disconnect is debounced', async (t) => {
  let connectedCallCount = 0;
  const client = {
    async pollOnce() {
      connectedCallCount += 1;
      if (connectedCallCount === 1) return { connected: true, trafficLight: 'GREEN', stopAll: false, ts: Date.now() };
      return { connected: false, trafficLight: 'DISCONNECTED', stopAll: true, ts: Date.now() };
    },
  };
  const monitor = new WorkerMonitor({ client, pollMs: 1000, downDebounceMs: 500 });
  await monitor.tick();
  const first = monitor.snapshot();
  assert.equal(first.connected, true);
  await monitor.tick();
  const second = monitor.snapshot();
  assert.equal(second.connected, true);
  assert.equal(second.stopAll, false);
});


test('YELLOW when pending queue high', () => {
  const light = computeTrafficLight({ connected: true, health: { ok: true }, state: {}, orders: { pending: 25 } });
  assert.equal(light, 'YELLOW');
  assert.equal(shouldStopAll(light), false);
});

test('GREEN when healthy + normal', () => {
  const light = computeTrafficLight({ connected: true, health: { ok: true, status: 'up' }, state: { engine: 'running' }, orders: { pending: 1, errorCount: 0 } });
  assert.equal(light, 'GREEN');
  assert.equal(shouldStopAll(light), false);
  assert.equal(toBannerText(light), '');
});
