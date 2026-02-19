import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = '/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/ui';
const OUT = join(ROOT, 'evidence', 'ui-final-1');
mkdirSync(OUT, { recursive: true });

const logs = [];
const log = (msg) => {
  const line = `[${new Date().toISOString()}] ${msg}`;
  logs.push(line);
  console.log(line);
};

function start(cmd, args, env = {}) {
  const p = spawn(cmd, args, { cwd: ROOT, env: { ...process.env, ...env } });
  p.stdout.on('data', (d) => log(`${cmd} ${args[0]} :: ${String(d).trim()}`));
  p.stderr.on('data', (d) => log(`${cmd} ${args[0]} [err] :: ${String(d).trim()}`));
  return p;
}

function sleep(ms){ return new Promise(r => setTimeout(r, ms)); }

let mock;
let dash;
let browser;

try {
  log('Starting mock worker API');
  mock = start('node', ['mock-worker-api.mjs']);
  await sleep(800);

  log('Starting UI server');
  dash = start('node', ['server.mjs'], { WORKER_API_BASE_URL: 'http://127.0.0.1:18080' });
  await sleep(1500);

  log('Launching Playwright chromium');
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1024 } });

  await page.goto('http://127.0.0.1:18890', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);

  log('Step1: Dashboard/Traffic Light 확인');
  await page.waitForSelector('text=Worker Safety');
  await page.screenshot({ path: join(OUT, '01-dashboard-traffic-light.png'), fullPage: true });

  log('Step2: Panic 슬라이더+홀드 동작');
  await page.evaluate(() => {
    const s = document.querySelector('#panicSlider');
    s.value = '100';
    s.dispatchEvent(new Event('input', { bubbles: true }));
  });
  const holdBtn = page.locator('#panicHoldBtn');
  await holdBtn.dispatchEvent('mousedown');
  await page.waitForTimeout(2400);
  await holdBtn.dispatchEvent('mouseup');
  await page.waitForTimeout(600);
  await page.screenshot({ path: join(OUT, '02-panic-safety.png'), fullPage: true });

  log('Step3: Orders 취소 흐름');
  await page.fill('#orderIdInput', 'ORD-UI-E2E-001');
  await page.click('#orderCancelBtn');
  await page.waitForTimeout(1000);
  await page.screenshot({ path: join(OUT, '03-orders-cancel-flow.png'), fullPage: true });

  const panicStatus = await page.locator('#panicStatus').innerText();
  const orderStatus = await page.locator('#orderStatus').innerText();
  log(`panicStatus=${panicStatus}`);
  log(`orderStatus=${orderStatus}`);

  log('E2E evidence complete');
} catch (e) {
  log(`FAILED: ${e?.stack || e}`);
  process.exitCode = 1;
} finally {
  if (browser) await browser.close();
  if (dash) dash.kill('SIGTERM');
  if (mock) mock.kill('SIGTERM');
  writeFileSync(join(OUT, 'run.log'), logs.join('\n') + '\n', 'utf8');
}
