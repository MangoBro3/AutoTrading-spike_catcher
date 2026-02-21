import { spawn } from 'node:child_process';
import { writeFileSync, readFileSync, mkdirSync } from 'node:fs';
import { chromium } from 'playwright';

const ROOT = '/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/ui';
const RESULT_DIR = '/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results';
const EVID_DIR = '/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/ui/evidence/ui-subagent-verify';
mkdirSync(EVID_DIR, { recursive: true });

const logs = [];
const log = (msg) => {
  const line = `[${new Date().toISOString()}] ${msg}`;
  logs.push(line); console.log(line);
};

const writeRuntime = (exchange) => {
  const payload = { status: 'OK', mode: 'PAPER', exchange, ts: Date.now() };
  writeFileSync(`${RESULT_DIR}/runtime_status.json`, JSON.stringify(payload), 'utf8');
};

writeRuntime('UPBIT');

const mock = spawn('node', ['mock-worker-api.mjs'], { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'] });
mock.stdout.on('data', (d) => log(`mock: ${String(d).trim()}`));
mock.stderr.on('data', (d) => log(`mock[err]: ${String(d).trim()}`));

const dash = spawn('node', ['server.mjs'], {
  cwd: ROOT,
  env: { ...process.env, WORKER_API_BASE_URL: 'http://127.0.0.1:18080' },
  stdio: ['ignore', 'pipe', 'pipe']
});
dash.stdout.on('data', (d) => log(`ui: ${String(d).trim()}`));
dash.stderr.on('data', (d) => log(`ui[err]: ${String(d).trim()}`));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
try {
  await sleep(1800);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1400, height: 980 } });
  await page.goto('http://127.0.0.1:18890', { waitUntil: 'domcontentloaded' });

  await sleep(1200);
  await page.screenshot({ path: `${EVID_DIR}/ui-upbit.png`, fullPage: true });

  const indicatorsUpbit = await page.locator('#connIndicators').innerText();
  log(`indicators_upbit=${indicatorsUpbit}`);

  await page.goto('http://127.0.0.1:18890/api/overview');
  const preJson = await page.locator('body').innerText();
  writeFileSync(`${EVID_DIR}/overview-upbit.json`, preJson, 'utf8');

  writeRuntime('BITHUMB');
  await page.goto('http://127.0.0.1:18890');
  await sleep(1800);

  await page.screenshot({ path: `${EVID_DIR}/ui-bithumb.png`, fullPage: true });

  const indicatorsBithumb = await page.locator('#connIndicators').innerText();
  log(`indicators_bithumb=${indicatorsBithumb}`);

  const finalText = await page.locator('#connIndicators').innerText();
  await page.goto('http://127.0.0.1:18890/api/overview');
  const postJson = await page.locator('body').innerText();
  writeFileSync(`${EVID_DIR}/overview-bithumb.json`, postJson, 'utf8');

  log(`final_text=${finalText}`);
  await browser.close();
} finally {
  mock.kill('SIGTERM');
  dash.kill('SIGTERM');
  writeFileSync(`${EVID_DIR}/run.log`, logs.join('\n') + '\n', 'utf8');
}
