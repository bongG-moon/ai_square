// Real Edge rendering against an isolated synthetic host. No personal profile, KEY or server.
// Run: node organization-store/tests/browser-installed-ui.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || path.join(require('node:os').homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const root = path.resolve(__dirname, '../..');
const source = path.join(root, 'organization-store');
const output = path.join(root, 'outputs/store-installed-refresh-20261026');
const html = fs.readFileSync(path.join(source, 'ui/index.html'), 'utf8').replace('<!--STORE_STYLE-->', '<style>' + fs.readFileSync(path.join(source, 'ui/store.css'), 'utf8') + '</style>');
const script = fs.readFileSync(path.join(source, 'ui/store.js'), 'utf8');
const font = fs.readFileSync(path.join(root, 'build/workspace-local-repository/local_app/web/fonts/NotoSansKR-Variable.woff'));
const records = [
  {installationId:'report', toolId:101, name:'주간 실적 보고서 작성', type:'Skill', kind:'skill', release:2, scope:'directory', target:'D:/업무 자료/2026년/생산성 개선 프로젝트/주간 실적 보고서/.claude/skills/weekly-performance-report', status:'installed', rollbackAvailable:true, metadataStatus:'current'},
  {installationId:'analysis', toolId:102, name:'제조 데이터 분석 도구', type:'MCP/Tool', kind:'mcp', release:4, scope:'user', target:'C:/Users/사용자/.claude.json', status:'configured', rollbackAvailable:false, metadataStatus:'current'},
  {installationId:'meeting', toolId:103, name:'회의록 정리와 후속 업무 실행을 함께 돕는 조직 공통 하네스', type:'하네스/플러그인', release:1, scope:'directory', target:'D:/Projects/이름이 매우 긴 업무 폴더/연구 개발 부서와 협업하는 2026년 하반기 프로젝트/공통 자료와 참고 문서/.claude/plugins/meeting-follow-up', status:'installed', rollbackAvailable:true, metadataStatus:'snapshot'},
];
const checks = [];
const report = {fixture:'Synthetic host responses; real current extension HTML/CSS/JS and Edge. No real platform API or personal credentials.', checks, screenshots:[], measurements:{}, pageErrors:[]};
fs.mkdirSync(output, {recursive:true});
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

(async () => {
  const server = await chromium.launchServer({executablePath:path.join(process.env['ProgramFiles(x86)'] || 'C:/Program Files (x86)', 'Microsoft/Edge/Application/msedge.exe'), headless:true});
  const browser = await chromium.connect(server.wsEndpoint());
  try {
    const page = await browser.newPage({viewport:{width:1100,height:900}});
    page.setDefaultTimeout(7000);
    page.on('pageerror', error => report.pageErrors.push(error.message));
    await page.route('http://127.0.0.1:48591/**', route => route.fulfill({status:200, contentType:route.request().url().endsWith('.woff')?'font/woff':'text/html', body:route.request().url().endsWith('.woff')?font:html}));
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Performance.enable');
    async function fixture(options={}) {
      await page.goto('http://127.0.0.1:48591/');
      await page.evaluate(config => {
        window.requests=[]; window.heldRequests=[]; window.fixtureConfig=config;
        const reply=(message,result,ok=true,error='')=>window.postMessage({type:'ax-extension-response',channel:message.channel,requestId:message.requestId,ok,result,error},'*');
        const item=record=>({id:record.toolId,name:record.name,type:record.type,desc:'정해진 자료를 확인하고 업무 결과를 정리하는 도구입니다.',platform:'Claude',org:'업무 혁신팀',registrantName:'예시 등록자',access:'approved',active:5,versions:[{n:5,note:'새 배포 내용'},{n:2,note:'설치한 배포'}]});
        function respond(message) {
          const cfg=window.fixtureConfig;
          if(cfg.errors?.[message.action])return reply(message,null,false,cfg.errors[message.action]);
          let result={};
          if(message.action==='status')result={configured:true,baseUrl:'https://square.example.test'};
          if(message.action==='options')result={organizations:[]};
          if(message.action==='catalog')result={items:config.catalogRecords.map(item),total:config.catalogRecords.length};
          if(message.action==='installations')result={items:cfg.records,recovery:{recovered:[],blocked:[]}};
          if(message.action==='checkUpdates')result=cfg.updates;
          if(message.action==='verify')result={filesIntact:!cfg.changedFiles,configurationIntact:true,notice:'설치 파일을 확인했습니다.'};
          if(message.action==='rollback')result={restored:true,notice:'이전 설치 상태로 복구했어요.'};
          if(message.action==='detail')result={item:item(config.catalogRecords.find(record=>record.toolId===message.payload.toolId) || config.catalogRecords[0]),canInstall:true,manifest:{release:5,downloadUrl:'/download/test',installProfile:{scopes:['user','project']}}};
          reply(message,result);
        }
        window.releaseHost = action => {
          delete window.fixtureConfig.hold[action];
          const held=window.heldRequests.filter(message=>message.action===action);
          window.heldRequests=window.heldRequests.filter(message=>message.action!==action);
          held.forEach(respond);
        };
        window.addEventListener('message',event=>{
          const message=event.data;
          if(message.type==='ax-extension-ready')return window.postMessage({type:'ax-extension-init',channel:'installed-fixture',hostFeatures:['workspaces','publishFiles'],theme:config.dark?'dark':'light',context:{kind:'work',title:'업무 UI 검증',workspace:'D:/Projects/fixture'}},'*');
          if(message.type!=='ax-extension-request')return;
          window.requests.push(message);
          if(window.fixtureConfig.hold[message.action])window.heldRequests.push(message);else respond(message);
        });
      }, {records, catalogRecords:records, updates:{items:[],summary:{total:0,checked:0,available:0,current:0,attention:0,failed:0,pending:0},complete:true},hold:{},...options});
      await page.addScriptTag({content:script});
      await page.locator('.catalog-card').first().waitFor();
      await page.evaluate(()=>document.fonts.ready);
    }
    const tab=name=>page.locator(`[data-tab="${name}"]`);
    const row=id=>page.locator(`.install-record[data-installation-id="${id}"]`);
    const count=action=>page.evaluate(a=>window.requests.filter(request=>request.action===a).length,action);
    async function waitRows(total) {await page.waitForFunction(n=>document.querySelectorAll('#results .install-record').length===n,total);}
    async function settled() {await page.waitForFunction(()=>document.getAnimations().every(animation=>animation.playState!=='running'&&animation.playState!=='pending'));}
    async function screenshot(name) {await settled();await page.screenshot({path:path.join(output,name),fullPage:true});report.screenshots.push(name);}
    async function noOverflow() {assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true,'Viewport must not horizontally overflow');}
    async function metrics() {
      await cdp.send('HeapProfiler.collectGarbage');
      const dom=await cdp.send('Memory.getDOMCounters');
      const values=(await cdp.send('Performance.getMetrics')).metrics;
      return {...dom,heapBytes:values.find(value=>value.name==='JSHeapUsedSize')?.value,activeAnimations:await page.evaluate(()=>document.getAnimations().length)};
    }

    await fixture(); await tab('installed').click(); await waitRows(3);
    assert.deepEqual(await page.locator('.record-title').allTextContents(),records.map(record=>record.name));
    for(const record of records)assert.equal(await row(record.installationId).locator('.record-target').getAttribute('title'),record.target);
    assert.equal(await page.locator('#results').innerText().then(text=>/기능\s*#\d+/.test(text)),false);
    await noOverflow(); await screenshot('01-installed-light.png');
    await page.evaluate(()=>window.postMessage({type:'ax-extension-theme',channel:'installed-fixture',theme:'dark'},'*'));
    await page.waitForFunction(()=>document.documentElement.dataset.theme==='dark');
    await screenshot('02-installed-dark.png');
    await page.setViewportSize({width:420,height:850}); await noOverflow();
    for(const id of ['report','analysis','meeting'])assert.equal(await row(id).getByRole('button',{name:'상태 확인',exact:true}).isVisible(),true);
    await screenshot('03-installed-narrow.png');
    checks.push('Readable real tool names, full path on hover, all controls accessible at 420px, light and dark themes without horizontal overflow');
    await page.setViewportSize({width:1100,height:900});
    await row('report').getByRole('button',{name:'상태 확인',exact:true}).click();
    await page.waitForFunction(()=>window.requests.filter(request=>request.action==='verify').length===1);
    assert.equal(await count('verify'),1);
    assert.deepEqual(await page.evaluate(()=>window.requests.find(request=>request.action==='verify').payload),{installationId:'report'});
    await page.locator('#feedback').filter({hasText:'설치 파일을 확인했습니다.'}).waitFor();
    await page.evaluate(()=>window.fixtureConfig.changedFiles=true);
    await row('report').getByRole('button',{name:'상태 확인',exact:true}).click();
    await page.locator('#feedback.error').waitFor();
    assert.equal(await page.locator('#feedback').evaluate(node=>node.classList.contains('error')),true);

    const opener=row('report').getByRole('button',{name:'상세 보기',exact:true});
    await opener.click(); await page.locator('#detail-panel').waitFor();
    assert.equal(await page.locator('#detail-dialog').evaluate(node=>node.open),true);
    assert.equal(await page.locator('#detail-title').innerText(),records[0].name);
    const dialogMotion=await page.locator('#detail-dialog').evaluate(node=>({properties:getComputedStyle(node).transitionProperty,durations:getComputedStyle(node).transitionDuration,animations:node.getAnimations().map(animation=>animation.effect.getTiming().duration)}));
    assert(dialogMotion.properties.includes('opacity')&&dialogMotion.properties.includes('transform'));
    assert(dialogMotion.durations.split(',').every(value=>value.trim()==='0.3s'),'Native dialog open and close transition duration should be 300ms');
    await page.getByRole('tab',{name:'설치·연결',exact:true}).click();
    const motion=await page.locator('#detail-panel').evaluate(node=>node.getAnimations().map(animation=>({duration:animation.effect.getTiming().duration,properties:Object.keys(animation.effect.getKeyframes()[0])})));
    assert(motion.some(animation=>animation.duration===300&&animation.properties.includes('opacity')),'Detail content should have a finite 300ms opacity transition');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#detail-dialog').evaluate(node=>node.open),false);
    assert.equal(await opener.evaluate(node=>node===document.activeElement),true,'Closing detail restores keyboard focus');
    const dialogExit=await page.locator('#detail-dialog').evaluate(node=>({pointerEvents:getComputedStyle(node).pointerEvents,animations:node.getAnimations().map(animation=>({duration:animation.effect.getTiming().duration,state:animation.playState}))}));
    assert.equal(dialogExit.pointerEvents,'none','Closing visual layer must never block newly focused controls');
    assert(dialogExit.animations.some(animation=>animation.duration===300),'Native close should retain a finite fade-out after releasing focus');
    await settled();
    const restore=row('report').getByRole('button',{name:'이전 상태로 복구',exact:true});
    await restore.click(); await page.locator('#confirm-dialog').waitFor({state:'visible'});
    assert.equal(await page.locator('#confirm-no').evaluate(node=>node===document.activeElement),true,'Rollback defaults focus to cancellation');
    await page.keyboard.press('Escape'); await settled();
    assert.equal(await count('rollback'),0,'Cancelling must not mutate installation');
    assert.equal(await restore.evaluate(node=>node===document.activeElement),true);
    await restore.click(); await page.locator('#confirm-dialog').waitFor({state:'visible'}); await page.locator('#confirm-yes').click(); await waitRows(3);
    await page.waitForFunction(()=>window.requests.filter(request=>request.action==='rollback').length===1);
    assert.deepEqual(await page.evaluate(()=>window.requests.find(request=>request.action==='rollback').payload),{installationId:'report',confirmed:true});
    assert.equal(await count('install'),0); assert.equal(await count('download'),0);
    checks.push('Verify reports changed files; detail opens and returns focus; rollback cancel is inert and explicit acceptance sends exactly one confirmed operation');

    const statusRows=[
      {installationId:'report',updateAvailable:true,updateStatus:'available',result:{toolId:101,installedRelease:2,activeRelease:5,status:'update_available',message:'새 버전을 설치할 수 있습니다.'}},
      {installationId:'analysis',updateAvailable:false,updateStatus:'current',result:{installedRelease:4,activeRelease:4,status:'current',message:'현재 배포 버전입니다.'}},
      {installationId:'meeting',updateAvailable:false,updateStatus:'rollback',result:{installedRelease:3,activeRelease:1,status:'rollback_available',message:'서버가 이전 버전으로 복구되었습니다.'}},
      {installationId:'unknown',name:'이전 배포 도구',updateAvailable:false,updateStatus:'attention',result:{installedRelease:1,status:'unknown_release',message:'설치한 버전의 배포 정보를 확인할 수 없습니다.'}},
      {installationId:'denied',name:'승인 대기 분석 도구',updateAvailable:false,updateStatus:'attention',result:{status:'denied',message:'사용 권한을 확인해야 합니다.'}},
      {installationId:'error',name:'연결 확인 도구',updateAvailable:false,updateStatus:'error',result:{status:'error',message:'서버에 연결하지 못했습니다.'}},
      {installationId:'paused',name:'배포 보류 도구',updateAvailable:false,updateStatus:'paused',result:{installedRelease:1,activeRelease:5,status:'update_available',message:'새 배포 설치가 일시 중지되었습니다.'}},
      {installationId:'blocked',name:'복구 확인 도구',updateAvailable:false,updateStatus:'recovery_blocked',result:{installedRelease:1,activeRelease:5,status:'update_available',message:'중단된 설치를 먼저 확인해 주세요.'}},
    ].map(row=>({...records.find(record=>record.installationId===row.installationId),...row}));
    await fixture({updates:{items:statusRows,summary:{total:8,checked:7,available:1,current:1,attention:5,failed:1,pending:0},complete:false}});
    await tab('updates').click(); await waitRows(1);
    assert.equal(await page.locator('.update-record').count(),1);
    assert.equal(await page.locator('.update-record').getAttribute('data-installation-id'),'report');
    assert.equal(await page.locator('.update-record .record-title').innerText(),records[0].name);
    assert.equal(await page.locator('#results').innerText().then(text=>text.includes('모두 최신')),false);
    await page.locator('.update-summary summary').click();
    const summaryText=await page.locator('.update-summary').innerText();
    for(const name of ['승인 대기 분석 도구','연결 확인 도구','배포 보류 도구','복구 확인 도구'])assert(summaryText.includes(name),`Non-actionable reason must remain discoverable: ${name}`);
    await screenshot('04-updates-mixed.png');
    await page.locator('.update-record').getByRole('button',{name:'업데이트 보기',exact:true}).click();
    await page.getByRole('button',{name:'바로 설치하기',exact:true}).waitFor();
    assert.equal(await count('install'),0,'Viewing an update must not install it');
    assert.equal(await page.getByRole('tab',{name:'설치·연결',exact:true}).getAttribute('aria-selected'),'true');
    await page.keyboard.press('Escape'); await settled();
    checks.push('Updates lists only actionable newer releases; current, rollback, unknown, denied, errors, paused and recovery-blocked records are excluded with discoverable reasons');

    // The installer blocks all writes while any interrupted installation needs
    // recovery. Even an otherwise eligible unrelated tool must not offer Update.
    await fixture({updates:{items:[statusRows[0]],summary:{total:1,checked:1,available:0,current:0,attention:1,failed:0,pending:0},complete:false,recovery:{blocked:[{toolId:999,message:'다른 기능의 중단된 설치를 먼저 확인해 주세요.'}]}}});
    await tab('updates').click(); await page.locator('.update-summary').waitFor();
    assert.equal(await page.locator('.update-record').count(),0,'Global recovery gate must prevent all actionable updates');
    await page.locator('.update-summary summary').click();
    assert.match(await page.locator('.update-summary').innerText(),/중단된 설치/);
    assert.equal(await page.locator('#results').innerText().then(text=>text.includes('모두 최신')),false);
    checks.push('An unrelated interrupted installation globally disables update actions and explains recovery before installation');

    await fixture({updates:{items:[statusRows[1]],summary:{total:1,checked:1,available:0,current:1,attention:0,failed:0,pending:0},complete:true}});
    await tab('updates').click(); await page.locator('#results .empty').waitFor();
    assert.equal(await page.locator('.update-record').count(),0);
    assert.match(await page.locator('#results').innerText(),/최신/);
    await fixture({records:[]}); await tab('installed').click(); await page.locator('#results .empty').waitFor();
    assert.match(await page.locator('#results').innerText(),/설치한 기능이 없/);
    await tab('updates').click(); await page.locator('#results .empty').waitFor();
    assert.equal(await page.locator('#results').innerText().then(text=>text.includes('모두 최신')),false);
    await fixture({updates:{items:[statusRows[5]],summary:{total:1,checked:0,available:0,current:0,attention:0,failed:1,pending:0},complete:false}});
    await tab('updates').click(); await page.locator('.update-summary').waitFor();
    assert.equal(await page.locator('#results').innerText().then(text=>text.includes('모두 최신')),false);
    await fixture({errors:{checkUpdates:'네트워크 확인에 실패했습니다. 잠시 뒤 새로고침해 주세요.'}}); await tab('updates').click();
    await page.locator('#feedback.error').waitFor();
    assert.equal(await page.locator('.update-record').count(),0);
    assert.equal(await page.locator('#results').innerText().then(text=>text.includes('모두 최신')),false);
    checks.push('Empty installations, all-current, partial failure and total RPC failure have truthful distinct results without a false all-current claim');

    await fixture({hold:{installations:true}});
    await tab('installed').click(); await page.waitForFunction(()=>window.heldRequests.length===1);
    await tab('catalog').click(); await page.evaluate(()=>window.releaseHost('installations'));
    await page.locator('.catalog-card').first().waitFor();
    assert.equal(await page.locator('.install-record').count(),0);
    assert.equal(await tab('catalog').getAttribute('aria-current'),'page');
    await fixture({hold:{checkUpdates:true},updates:{items:statusRows,summary:{total:8,checked:7,available:1,current:1,attention:5,failed:1,pending:0},complete:false}});
    await tab('updates').click(); await page.waitForFunction(()=>window.heldRequests.some(message=>message.action==='checkUpdates'));
    await tab('installed').click(); await page.evaluate(()=>window.releaseHost('checkUpdates')); await waitRows(3);
    assert.equal(await page.locator('.update-record').count(),0);
    assert.equal(await tab('installed').getAttribute('aria-current'),'page');
    checks.push('Delayed old installations/updates responses cannot replace the newly selected tab');

    await fixture(); await tab('installed').click(); await waitRows(3); await settled();
    // Warm up the same paths before measuring to avoid mistaking first-time JIT/font caches for leaks.
    async function transitionCycle() {
      await tab('catalog').click(); await page.locator('.catalog-card').first().waitFor();
      await tab('installed').click(); await waitRows(3);
      await row('report').getByRole('button',{name:'상세 보기',exact:true}).click();
      await page.locator('#detail-panel').waitFor();
      await page.getByRole('tab',{name:'설치·연결',exact:true}).click();
      await page.keyboard.press('Escape');
      await settled();
    }
    for(let i=0;i<4;i++)await transitionCycle();
    const before=await metrics();
    for(let i=0;i<24;i++)await transitionCycle();
    await settled(); const after=await metrics();
    assert.equal(after.activeAnimations,0,'All finite transitions must settle');
    assert.equal(after.documents,before.documents,'No detached browser documents should accumulate');
    assert(after.nodes-before.nodes<80,`Unexpected DOM growth: ${after.nodes-before.nodes}`);
    assert(after.jsEventListeners-before.jsEventListeners<30,`Unexpected event listener growth: ${after.jsEventListeners-before.jsEventListeners}`);
    assert(after.heapBytes-before.heapBytes<2*1024*1024,`Unexpected retained heap growth: ${after.heapBytes-before.heapBytes}`);
    report.measurements.transitions={cycles:24,before,after,delta:{nodes:after.nodes-before.nodes,listeners:after.jsEventListeners-before.jsEventListeners,heapBytes:after.heapBytes-before.heapBytes}};
    checks.push('24 repeated tab/detail/close cycles settle without ongoing animations, detached documents or unbounded retained DOM/listener/heap growth');

    await page.emulateMedia({reducedMotion:'reduce'});
    await tab('catalog').click(); await page.locator('.catalog-card').first().waitFor();
    await tab('installed').click(); await waitRows(3);
    await row('report').getByRole('button',{name:'상세 보기',exact:true}).click(); await page.locator('#detail-panel').waitFor();
    await page.getByRole('tab',{name:'설치·연결',exact:true}).click();
    assert.equal(await page.evaluate(()=>document.getAnimations().length),0,'Reduced motion must disable content and dialog animations');
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(()=>document.getAnimations().length),0);
    checks.push('Reduced-motion preference disables transitions while preserving dialog focus and interactions');
    report.measurements.detailMotion=motion;
    report.measurements.dialogMotion={open:dialogMotion,close:dialogExit};
    assert.deepEqual(report.pageErrors,[]);
    report.passed=true;
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(report,null,2));
    console.log(JSON.stringify(report,null,2));
  } catch(error) {
    report.passed=false;report.failure=error.stack;
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(report,null,2));
    throw error;
  } finally {
    if(process.platform==='win32')require('node:child_process').spawnSync('taskkill.exe',['/PID',String(server.process().pid),'/T','/F'],{windowsHide:true,timeout:10000,stdio:'ignore'});
    await Promise.race([server.close(),sleep(3000)]);
  }
})().then(()=>process.exit(0),error=>{console.error(error);process.exit(1);});
