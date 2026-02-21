import { spawn } from 'node:child_process';
import { writeFileSync, mkdirSync, readFileSync } from 'node:fs';
import { chromium } from 'playwright';

const ROOT='/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/ui';
const EVID=`${ROOT}/evidence/ui-subagent-verify`;
mkdirSync(EVID,{recursive:true});
const logs=[];
const log=t=>{const s=`[${new Date().toISOString()}] ${t}`;logs.push(s); console.log(s);};

const mk=(cmd,args)=>{const p=spawn(cmd,args,{cwd:ROOT,env:{...process.env},stdio:['ignore','pipe','pipe']});
  p.stdout.on('data',d=>logs.push(`${p.pid} out ${String(d).trim()}`));
  p.stderr.on('data',d=>logs.push(`${p.pid} err ${String(d).trim()}`));
  return p;
};

const mock=mk('node',['mock-worker-api.mjs']);
const dash=mk('node',['server_for_verify.mjs']);

function sleep(ms){return new Promise(r=>setTimeout(r,ms));}

(async()=>{
  await sleep(1300);
  const browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1400,height:1000}});
  await page.goto('http://127.0.0.1:18890',{waitUntil:'domcontentloaded',timeout:15000});
  await sleep(600);

  const before=await page.evaluate(()=>({
    upbitChecked:document.getElementById('upbitToggle')?.checked,
    bithumbChecked:document.getElementById('bithumbToggle')?.checked,
    marketOneVisible: document.getElementById('marketOneLiner')?.style.display!== 'none',
    marketText: document.getElementById('marketOneLiner')?.textContent||''
  }));

  await page.check('#upbitToggle');
  await page.waitForTimeout(300);
  await page.uncheck('#bithumbToggle');
  await page.waitForTimeout(500);
  const afterClick=await page.evaluate(()=>({
    upbitChecked:document.getElementById('upbitToggle')?.checked,
    bithumbChecked:document.getElementById('bithumbToggle')?.checked,
    statusText:document.getElementById('exchangeToggleStatus')?.textContent||''
  }));

  const controlResp=await page.request.post('http://127.0.0.1:18890/api/worker/control/exchanges',{headers:{'content-type':'application/json'},data:JSON.stringify({upbit:false,bithumb:false})});
  const controlBody=await controlResp.text();

  const apiOverview=await (await page.request.get('http://127.0.0.1:18890/api/overview')).text();

  const runtimePath=' /mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runtime_status.json';
  const runtimePayload={mode:'PAPER',exchange:'UPBIT',status:'OK',volatility:0.05,riskLevel:'low',ts:Date.now()};
  writeFileSync('/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runtime_status.json', JSON.stringify(runtimePayload));
  await sleep(800);
  const apiOverviewPaper=await (await page.request.get('http://127.0.0.1:18890/api/overview')).json();

  await page.screenshot({path:`${EVID}/exchange_market_verify.png`,fullPage:true});
  writeFileSync(`${EVID}/exchange_market_verify.json`, JSON.stringify({before,afterClick,controlResp:{status:controlResp.status(),body:controlBody},apiOverviewParsed:JSON.parse(apiOverview),apiOverviewPaper},null,2));

  await page.screenshot({path:`${EVID}/exchange_market_verify_final.png`,fullPage:true});
  await browser.close();
})().finally(async()=>{
  await sleep(200);
  mock.kill('SIGTERM');
  dash.kill('SIGTERM');
  writeFileSync('/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/ui/evidence/ui-subagent-verify/run_exchange_market_verify_tmp.log', logs.join('\n')+'\n');
});
