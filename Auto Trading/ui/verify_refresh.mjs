import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';

const INDEX_PATH = '/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/ui/public/index.html';
const html = readFileSync(INDEX_PATH, 'utf8');

let overviewCalls = 0;
let workerCalls = 0;

const server = createServer((req, res) => {
  if (req.url === '/') {
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    res.end(html);
    return;
  }
  if (req.url === '/api/overview') {
    overviewCalls++;
    const phase = overviewCalls >= 2 ? 'RUNNING' : 'STOPPED';
    const payload = { now: new Date().toISOString(), worker: { state: { phase, running: phase === 'RUNNING' }, ts: Date.now(), connected: true, trafficLight: 'GREEN', stopAll: false, banner: '' }, sourceOk: true, ts: Date.now() };
    res.writeHead(200, { 'content-type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify(payload));
    return;
  }
  if (req.url === '/api/worker') {
    workerCalls++;
    const phase = workerCalls >= 2 ? 'RUNNING' : 'STOPPED';
    const payload = { ts: Date.now(), connected: true, trafficLight: phase === 'RUNNING' ? 'GREEN' : 'YELLOW', state: { phase }, stopAll: false, banner: '' };
    res.writeHead(200, { 'content-type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify(payload));
    return;
  }
  res.writeHead(404);
  res.end('not found');
});

await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const { port } = server.address();
const base = `http://127.0.0.1:${port}`;

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.goto(base + '/');
await page.waitForTimeout(300);

const initial = await page.locator('#controlPhaseBadge').innerText();

const start = Date.now();
await page.click('#refreshConnBtn');
await page.waitForFunction(() => {
  const el = document.querySelector('#controlPhaseBadge');
  return el && el.textContent.includes('RUNNING');
}, { timeout: 1500 });
const elapsed = Date.now() - start;
const finalText = await page.locator('#controlPhaseBadge').innerText();

console.log('initial=', initial);
console.log('final=', finalText);
console.log('elapsedMs=', elapsed);
console.log('within1s=', elapsed <= 1000);

await browser.close();
server.close();
