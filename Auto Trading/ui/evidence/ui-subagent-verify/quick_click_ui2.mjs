import { spawn } from 'node:child_process';
import { chromium } from 'playwright';
import { writeFileSync } from 'node:fs';

(async()=>{
  const mock = spawn('node', ['mock-worker-api.mjs'], { stdio:['ignore','ignore','ignore'] });
  const srv = spawn('node', ['server.mjs'], { stdio:['ignore','ignore','ignore'], env:{...process.env, WORKER_API_BASE_URL:'http://127.0.0.1:18080'} });
  await new Promise(r=>setTimeout(r,1200));

  // seed toggles false,false
  await (await fetch('http://127.0.0.1:18890/api/worker/control/exchanges', {
    method:'POST', headers:{'content-type':'application/json'}, body: JSON.stringify({ upbit:false,bithumb:false })
  })).json();

  const browser = await chromium.launch({headless:true});
  const page = await browser.newPage({viewport:{width:1200,height:1000}});
  await page.goto('http://127.0.0.1:18890', {waitUntil:'domcontentloaded'});
  await page.waitForTimeout(400);
  const before = await page.evaluate(()=>({up:!!document.getElementById('upbitToggle')?.checked,bithumb:!!document.getElementById('bithumbToggle')?.checked,status:document.getElementById('exchangeToggleStatus')?.textContent}));

  await page.check('#upbitToggle');
  await page.waitForTimeout(600);
  const after = await page.evaluate(()=>({up:!!document.getElementById('upbitToggle')?.checked,bithumb:!!document.getElementById('bithumbToggle')?.checked,status:document.getElementById('exchangeToggleStatus')?.textContent}));

  const ov = await (await page.request.get('http://127.0.0.1:18890/api/overview')).json();
  await page.screenshot({path:'./evidence/ui-subagent-verify/market-toggle-click.png', fullPage:true});
  writeFileSync('./evidence/ui-subagent-verify/click2_toggle_result.json', JSON.stringify({before,after,exchangeToggles:ov.exchangeToggles,marketOneLiner:ov.marketOneLiner},null,2));

  await browser.close();
  mock.kill('SIGTERM');
  srv.kill('SIGTERM');
})();
