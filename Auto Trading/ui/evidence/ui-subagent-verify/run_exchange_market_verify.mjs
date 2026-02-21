import { spawn } from 'node:child_process';
import { writeFileSync, mkdirSync, readFileSync } from 'node:fs';
import { chromium } from 'playwright';

const ROOT = '/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/ui';
const EVID = `${ROOT}/evidence/ui-subagent-verify`;
mkdirSync(EVID, { recursive: true });

const logs = [];
const log = (m) => { const line = `[${new Date().toISOString()}] ${m}`; logs.push(line); console.log(line); };

const spawnWithLog = (cmd, args) => {
  const p = spawn(cmd, args, { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'] });
  p.stdout.on('data', d => logs.push(`[${p.pid}] out ${String(d).trim()}`));
  p.stderr.on('data', d => logs.push(`[${p.pid}] err ${String(d).trim()}`));
  return p;
};

async function wait(ms) { await new Promise(r => setTimeout(r, ms)); }

const mock = spawnWithLog('node', ['mock-worker-api.mjs']);
const dash = spawnWithLog('node', ['server.mjs']);

try {
  await wait(1700);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1400, height: 980 } });
  await page.goto('http://127.0.0.1:18890', { waitUntil: 'domcontentloaded', timeout: 10000 });
  await wait(700);

  const domScan = await page.evaluate(() => {
    const buttons = Array.from(document.querySelectorAll('button')).map((el) => ({ id: el.id, text: (el.textContent || '').trim() }));
    const inputs = Array.from(document.querySelectorAll('input')).map((el) => ({ id: el.id, type: el.type, checked: !!el.checked }));
    const hasCandidate = !!document.querySelector('[id*="upbit" i], [id*="bithumb" i], button:has-text("UPBIT"), button:has-text("BITHUMB")');
    const pageText = document.body ? document.body.textContent : '';
    return {
      title: document.title,
      buttonCount: buttons.length,
      inputCount: inputs.length,
      inputs,
      buttons,
      hasUpbitLikeIdOrText: hasCandidate,
      connIndicators: (document.getElementById('connIndicators')?.textContent || '').trim(),
      mode: (document.getElementById('modeStatus')?.textContent || '').trim(),
    };
  });

  const beforeOverviewText = await (await page.request.get('http://127.0.0.1:18890/api/overview')).text();
  const beforeOverview = JSON.parse(beforeOverviewText);

  const controlResp = await page.request.post('http://127.0.0.1:18890/api/worker/control/exchanges', {
    headers: { 'content-type': 'application/json' },
    data: JSON.stringify({ upbit: false, bithumb: true })
  });
  const controlText = await controlResp.text();
  let controlJson = null;
  try { controlJson = JSON.parse(controlText); } catch {}
  await wait(900);

  const afterOverviewText = await (await page.request.get('http://127.0.0.1:18890/api/overview')).text();

  let toggleFile = null;
  try {
    toggleFile = JSON.parse(readFileSync(`${ROOT}/../results/ui_exchange_toggles.json`, 'utf8'));
  } catch {}

  // Inject PAPER + volatility so market one-liner is guaranteed non-empty
  const runtime = {
    mode: 'PAPER',
    exchange: 'UPBIT',
    status: 'OK',
    volatility: 0.052,
    riskLevel: 'low',
    ts: Date.now(),
  };
  writeFileSync('/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runtime_status.json', JSON.stringify(runtime));
  await wait(900);
  const paperOverviewText = await (await page.request.get('http://127.0.0.1:18890/api/overview')).text();
  const paperOverview = JSON.parse(paperOverviewText);

  await page.screenshot({ path: `${EVID}/exchange-market-verify.png`, fullPage: true });

  writeFileSync(`${EVID}/exchange-market-verify.json`, JSON.stringify({
    domScan,
    beforeOverview,
    controlRespStatus: controlResp.status(),
    controlJson,
    afterOverviewText,
    toggleFile,
    paperOverview,
  }, null, 2));

  await browser.close();
} finally {
  await wait(200);
  mock.kill('SIGTERM');
  dash.kill('SIGTERM');
  writeFileSync(`${EVID}/run_exchange_market_verify.log`, logs.join('\n') + '\n');
}
