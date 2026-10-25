const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || path.join(require('node:os').homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const out=path.resolve(__dirname,'../../outputs/square-page-qa');
const {url}=JSON.parse(fs.readFileSync(path.join(out,'runtime.json'),'utf8'));
(async()=>{
 const browserServer=await chromium.launchServer({executablePath:path.join(process.env['ProgramFiles(x86)'] || 'C:/Program Files (x86)','Microsoft/Edge/Application/msedge.exe'),headless:true});
 const browser=await chromium.connect(browserServer.wsEndpoint());
 try {
  const page=await browser.newPage({viewport:{width:1280,height:900}});await page.goto(url);await page.locator('.workspace-extension-menu').waitFor();
  const cdp=await page.context().newCDPSession(page);await cdp.send('Performance.enable');
  async function measure(){await cdp.send('HeapProfiler.collectGarbage');const result=await cdp.send('Performance.getMetrics');return Object.fromEntries(result.metrics.filter(m=>['JSHeapUsedSize','Nodes','Documents','JSEventListeners'].includes(m.name)).map(m=>[m.name,m.value]));}
  const samples=[];
  for(let i=0;i<12;i++){
   await page.locator('.workspace-extension-menu').click();const frame=page.frameLocator('.workspace-extension-frame');await frame.locator('.tool-card').first().waitFor();
   await page.locator('.workspace-extension-back').click();assert.equal(await page.locator('.workspace-extension-frame').count(),0);assert.equal(await page.locator('#workspace-extension-page').count(),0);
   await page.waitForTimeout(80);samples.push(await measure());
  }
  const growth=samples.at(-1).JSHeapUsedSize-samples[1].JSHeapUsedSize;
  assert.ok(growth<2*1024*1024,`retained heap grew ${growth} bytes`);
  assert.ok(samples.at(-1).Documents<=samples[1].Documents+1);
  fs.writeFileSync(path.join(out,'lifecycle-results.json'),JSON.stringify({passes:12,retainedHeapGrowthAfterWarmup: growth,samples,scope:'Chromium renderer synthetic catalog; not total OS process memory'},null,2));console.log(JSON.stringify({passes:12,retainedHeapGrowthAfterWarmup:growth}));
 }finally{if(process.platform==='win32')require('node:child_process').spawnSync('taskkill.exe',['/PID',String(browserServer.process().pid),'/T','/F'],{windowsHide:true,timeout:10000,stdio:'ignore'});await Promise.race([browserServer.close(),new Promise(resolve=>setTimeout(resolve,3000))]);}
})().then(()=>process.exit(0),e=>{console.error(e);process.exit(1);});
