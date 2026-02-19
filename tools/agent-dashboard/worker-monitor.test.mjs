import test from 'node:test';
import assert from 'node:assert/strict';
import { computeTrafficLight, shouldStopAll, toBannerText } from './worker-monitor.mjs';

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
