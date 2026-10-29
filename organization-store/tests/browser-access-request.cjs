// Real Edge UI with a synthetic extension host. No real KEY, server or notifications.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || path.join(require('node:os').homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const root = path.resolve(__dirname, '../..'), source = path.join(root, 'organization-store');
const output = path.join(root, 'outputs/store-access-ui-20261028');
fs.mkdirSync(output, {recursive:true});
const html = fs.readFileSync(path.join(source, 'ui/index.html'), 'utf8').replace('<!--STORE_STYLE-->', '<style>'+fs.readFileSync(path.join(source, 'ui/store.css'), 'utf8')+'</style>');
const script = fs.readFileSync(path.join(source, 'ui/store.js'), 'utf8');
const font = fs.readFileSync(path.join(process.env.AX_WORKSPACE_SOURCE || path.join(root, 'build/workspace-local-repository'), 'local_app/web/fonts/NotoSansKR-Variable.woff'));

(async()=>{
  const server = await chromium.launchServer({executablePath:path.join(process.env['ProgramFiles(x86)'] || 'C:/Program Files (x86)', 'Microsoft/Edge/Application/msedge.exe'), headless:true});
  const browser = await chromium.connect(server.wsEndpoint());
  try {
    const page = await browser.newPage({viewport:{width:1280, height:980}});
    page.setDefaultTimeout(7000);
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    const base='http://127.0.0.1:17358';
    await page.route(base+'/**',route=>route.fulfill({status:200,contentType:route.request().url().endsWith('.woff')?'font/woff':'text/html',body:route.request().url().endsWith('.woff')?font:html}));
    async function fixture(config={}) {
      await page.goto(base+'/',{waitUntil:'domcontentloaded'});
      await page.evaluate(()=>document.fonts.load('13px "Noto Sans KR"'));
      await page.evaluate(config=>{
        window.requests=[];window.requestMode=config.mode || 'pending';window.holdRequest=false;window.failRefresh=false;
        window.cancelMode='cancelled';window.holdCancel=false;window.requestAttempt=0;
        window.items=[
          {id:1,name:'업무 보고서 작성',access:config.approved?'approved':'none',approval:true},
          {id:2,name:'사내 자료 검색',access:'none',approval:true},
          {id:3,name:'업무 시작 가이드',access:'approved',approval:false},
        ].map(item=>({...item,requestRevision:null,requestStatus:'none',canCancel:false,desc:'업무 폴더의 자료를 확인하고 핵심 내용을 정리합니다.',type:'Skill',platform:'Claude',org:'업무 혁신팀',category:'문서 작성',registrantName:'예시 등록자',owner:'기능 담당자',visibility:'전체 공개',views:12,likes:3,downloads:8}));
        window.addEventListener('message',event=>{
          const message=event.data;
          if(message.type==='ax-extension-ready')return window.postMessage({type:'ax-extension-init',channel:'test-access',theme:config.dark?'dark':'light',hostFeatures:[],context:{}},'*');
          if(message.type!=='ax-extension-request')return;
          window.requests.push(message);let result={},error;
          const respond=()=>window.postMessage({type:'ax-extension-response',channel:message.channel,requestId:message.requestId,ok:!error,result,error},'*');
          if(message.action==='status')result={configured:true,baseUrl:'https://square.example.test'};
          if(message.action==='options')result={organizations:[],categories:[]};
          if(message.action==='catalog')result={items:window.items,total:window.items.length};
          if(message.action==='detail') {
            const item=window.items.find(item=>item.id===message.payload.toolId);
            if(window.failRefresh&&message.payload.recordView===false)error='network failed: should not leak internals';
            else result={item:{...item},manifest:item.access==='approved'?{release:1,downloadUrl:'/api/artifact',installProfile:{kind:'skill',scopes:['user','project']}}:{},canInstall:item.access==='approved',canInspectInstall:false,canRequestAccess:!config.legacy&&item.access==='none',webUrl:'https://square.example.test/'};
          }
          if(message.action==='publishUpdateAccess')result={canUpdate:false};
          if(message.action==='like')result={liked:message.payload.liked,count:message.payload.liked?4:3};
          if(message.action==='requestAccess') {
            const item=window.items.find(item=>item.id===message.payload.toolId);
            if(window.requestMode==='error')error='private-server-detail';
            else if(window.requestMode==='rejected')result={status:'rejected',notice:'권한 신청을 지원하는 플랫폼 버전인지와 현재 KEY를 확인해 주세요.'};
            else {
              item.access=window.requestMode==='approved'?'approved':'pending';item.requestStatus=item.access;
              item.requestRevision=String(++window.requestAttempt).padStart(32,'0');item.canCancel=item.access==='pending';
              result=window.requestMode==='uncertain'?{status:'uncertain',notice:'신청 결과를 확인하지 못했어요. 신청 상태를 확인해 주세요.'}:{toolId:item.id,status:item.access,access:item.access,requested:true,requestRevision:item.requestRevision,requestStatus:item.requestStatus,canCancel:item.canCancel};
            }
            if(window.holdRequest){window.releaseRequest=respond;return;}
          }
          if(message.action==='cancelAccessRequest') {
            const item=window.items.find(item=>item.id===message.payload.toolId);
            if(message.payload.expectedRevision!==item.requestRevision)result={status:'rejected',notice:'신청 상태가 변경되었어요. 현재 상태를 먼저 확인해 주세요.'};
            else {
              item.access=window.cancelMode==='approved'?'approved':'none';item.requestStatus=window.cancelMode==='approved'?'approved':window.cancelMode==='none'?'rejected':'cancelled';item.canCancel=false;
              result=window.cancelMode==='uncertain'?{status:'uncertain',notice:'취소 결과를 확인하지 못했어요. 신청 상태를 먼저 확인해 주세요.'}:{toolId:item.id,status:window.cancelMode==='none'?'none':item.requestStatus,access:item.access,cancelled:item.requestStatus==='cancelled',requestRevision:item.requestRevision,requestStatus:item.requestStatus,canCancel:false,...(window.cancelMode==='none'?{notice:'취소할 대기 중인 신청이 없어요.'}:{})};
            }
            if(window.holdCancel){window.releaseCancel=respond;return;}
          }
          respond();
        });
      },config);
      await page.addScriptTag({content:script});await page.locator('.tool-card').first().waitFor();
    }
    const count=action=>page.evaluate(action=>requests.filter(request=>request.action===action).length,action);
    async function open(id=1) {await page.locator(`.tool-card[data-tool-id="${id}"] .tool-title`).click();await page.locator('#detail-title').filter({hasText:id===1?'업무 보고서 작성':id===2?'사내 자료 검색':'업무 시작 가이드'}).waitFor();}
    async function connect() {await page.locator('#detail-tab-connect').click();await page.locator('#detail-panel').waitFor();}
    const requestButton=()=>page.getByRole('button',{name:'권한 신청하기',exact:true}).first();
    const refreshButton=()=>page.getByRole('button',{name:'상태 새로고침',exact:true}).first();

    await fixture({approved:true});await open();await connect();
    assert.equal(await requestButton().count(),0);assert.equal(await page.getByRole('button',{name:'바로 설치하기',exact:true}).count(),1);assert.equal(await count('requestAccess'),0);
    await page.getByRole('button',{name:/좋아요/}).click();await page.getByRole('button',{name:/좋아요 4/}).waitFor();
    assert.deepEqual(await page.evaluate(()=>requests.find(r=>r.action==='like').payload),{toolId:1,liked:true});

    await fixture();await open();await connect();
    assert.equal(await count('requestAccess'),0);assert.equal(await page.getByRole('button',{name:'바로 설치하기',exact:true}).count(),0);
    assert.equal(await page.getByRole('button',{name:/좋아요/}).isDisabled(),true);
    await page.locator('#detail-tab-versions').click();
    assert.match(await page.locator('#detail-panel').innerText(),/사용 승인 후 배포 이력을 확인할 수 있어요/);
    assert.equal(await count('publishUpdateAccess'),0);
    await connect();
    await page.screenshot({path:path.join(output,'01-request-light.png'),animations:'disabled'});
    await requestButton().click();await page.locator('.access-pending').first().waitFor();
    assert.equal(await count('requestAccess'),1);assert.equal(await requestButton().count(),0);assert.equal(await count('host.openExternal'),0);
    assert.equal(await page.getByRole('button',{name:'바로 설치하기',exact:true}).count(),0);
    assert.match(await page.locator('.tool-card[data-tool-id="1"] .access-badge').innerText(),/승인 대기/);
    await page.screenshot({path:path.join(output,'02-pending-light.png'),animations:'disabled'});
    await page.locator('#detail-close').click();await open();await connect();assert.equal(await requestButton().count(),0);
    await refreshButton().click();await page.locator('.access-pending').first().waitFor();
    assert.equal(await count('requestAccess'),1);assert.equal(await page.evaluate(()=>requests.filter(r=>r.action==='detail').at(-1).payload.recordView),false);
    await page.evaluate(()=>window.items[0].access='approved');await refreshButton().click();await page.getByRole('button',{name:'바로 설치하기',exact:true}).waitFor();
    assert.equal(await page.locator('.access-pending').count(),0);assert.equal(await page.locator('.tool-card[data-tool-id="1"] .access-badge').count(),0);assert.equal(await count('requestAccess'),1);

    // A close/reopen while the reply is held cannot dispatch the write twice.
    await fixture();await open();await connect();await page.evaluate(()=>window.holdRequest=true);await requestButton().click();
    await page.waitForFunction(()=>typeof window.releaseRequest==='function');assert.equal(await page.getByRole('button',{name:'신청 중…',exact:true}).first().isDisabled(),true);
    await page.locator('#detail-tab-intro').click();assert.equal(await requestButton().count(),0);await page.locator('#detail-close').click();
    await page.locator('.tool-card[data-tool-id="1"] .tool-title').click();assert.equal(await count('requestAccess'),1);
    await page.evaluate(()=>window.releaseRequest());await page.locator('#detail-title').filter({hasText:'업무 보고서 작성'}).waitFor();await page.locator('.access-pending').first().waitFor();assert.equal(await count('requestAccess'),1);

    // An uncertain response is rechecked with a GET-like detail action, never another write.
    await fixture({mode:'uncertain'});await open();await connect();await requestButton().click();
    await page.getByRole('button',{name:'신청 상태 확인',exact:true}).first().waitFor();assert.equal(await requestButton().count(),0);
    await page.evaluate(()=>window.failRefresh=true);await page.getByRole('button',{name:'신청 상태 확인',exact:true}).first().click();
    await page.locator('.access-request-message').filter({hasText:'신청 상태를 확인하지 못했어요'}).waitFor();assert.doesNotMatch(await page.locator('#detail-view').innerText(),/network failed|private-server-detail/);
    await page.evaluate(()=>window.failRefresh=false);await page.getByRole('button',{name:'신청 상태 확인',exact:true}).first().click();await page.locator('.access-pending').first().waitFor();assert.equal(await count('requestAccess'),1);

    // Explicit server rejection retains the fixed explanation and only offers a read-only check.
    await fixture({mode:'rejected'});await open();await connect();await requestButton().click();
    await page.locator('.access-request-message').filter({hasText:'권한 신청을 지원하는 플랫폼 버전인지와 현재 KEY를 확인해 주세요.'}).waitFor();
    assert.equal(await requestButton().count(),0);assert.equal(await count('requestAccess'),1);
    assert.equal(await page.locator('.access-request-message').evaluate(node=>node.classList.contains('error')),true);
    await page.getByRole('button',{name:'신청 상태 확인',exact:true}).first().click();await requestButton().waitFor();
    assert.equal(await count('requestAccess'),1);assert.equal(await page.evaluate(()=>requests.filter(r=>r.action==='detail').at(-1).payload.recordView),false);

    // A failed operation for a closed tool does not contaminate the next detail.
    await fixture({mode:'error'});await open();await page.evaluate(()=>window.holdRequest=true);await requestButton().click();await page.waitForFunction(()=>typeof window.releaseRequest==='function');
    await page.locator('#detail-close').click();await page.locator('.tool-card[data-tool-id="2"] .tool-title').click();await page.evaluate(()=>window.releaseRequest());
    await page.locator('#detail-title').filter({hasText:'사내 자료 검색'}).waitFor();await requestButton().waitFor();assert.equal(await page.getByRole('button',{name:'신청 상태 확인',exact:true}).count(),0);assert.doesNotMatch(await page.locator('#detail-view').innerText(),/신청 결과를 확인하지 못했어요/);

    // Permission granted concurrently loads protected details before showing install controls.
    await fixture({mode:'approved'});await open();await connect();await requestButton().click();await page.getByRole('button',{name:'바로 설치하기',exact:true}).waitFor();assert.equal(await count('requestAccess'),1);assert.equal(await page.evaluate(()=>requests.filter(r=>r.action==='detail').at(-1).payload.recordView),false);

    // Confirmed cancellation keeps the version token and allows a fresh request.
    const cancelButton=()=>page.getByRole('button',{name:'신청 취소',exact:true}).first();
    const reapplyButton=()=>page.getByRole('button',{name:'권한 다시 신청하기',exact:true}).first();
    await fixture();await open();await connect();await requestButton().click();await cancelButton().waitFor();
    await page.evaluate(()=>window.holdCancel=true);await cancelButton().click();await page.waitForFunction(()=>typeof window.releaseCancel==='function');
    assert.equal(await page.getByRole('button',{name:'취소 중…',exact:true}).first().isDisabled(),true);assert.equal(await cancelButton().count(),0);assert.equal(await requestButton().count(),0);
    await page.screenshot({path:path.join(output,'05-cancelling-light.png'),animations:'disabled'});
    await page.evaluate(()=>window.releaseCancel());await reapplyButton().waitFor();assert.match(await page.locator('.access-request-message').innerText(),/신청을 취소했어요/);
    await page.screenshot({path:path.join(output,'06-cancelled-light.png'),animations:'disabled'});
    const firstRevision=await page.evaluate(()=>requests.find(r=>r.action==='cancelAccessRequest').payload.expectedRevision);assert.equal(firstRevision,'1'.padStart(32,'0'));assert.equal(await count('cancelAccessRequest'),1);
    await page.locator('#detail-close').click();await open();await connect();await reapplyButton().waitFor();await reapplyButton().click();await cancelButton().waitFor();
    assert.equal(await count('requestAccess'),2);assert.equal(await page.evaluate(()=>items[0].requestRevision),'2'.padStart(32,'0'));

    // Approval that wins the race is preserved; cancellation must not revoke it.
    await page.evaluate(()=>{window.cancelMode='approved';window.holdCancel=false;});await cancelButton().click();await page.getByRole('button',{name:'바로 설치하기',exact:true}).waitFor();
    await page.locator('#detail-feedback').filter({hasText:'현재 사용 권한은 유지됩니다'}).waitFor();assert.equal(await cancelButton().count(),0);

    // A lost cancel receipt is checked read-only before a new request becomes possible.
    await fixture();await open();await connect();await requestButton().click();await cancelButton().waitFor();await page.evaluate(()=>window.cancelMode='uncertain');await cancelButton().click();
    await page.getByRole('button',{name:'신청 상태 확인',exact:true}).first().waitFor();assert.equal(await reapplyButton().count(),0);assert.match(await page.locator('.access-request-message').innerText(),/취소 결과/);
    await page.getByRole('button',{name:'신청 상태 확인',exact:true}).first().click();await reapplyButton().waitFor();assert.equal(await count('cancelAccessRequest'),1);assert.equal(await count('requestAccess'),1);

    // A stale cancel cannot affect a new request created from another surface.
    await fixture();await open();await connect();await requestButton().click();await cancelButton().waitFor();await page.evaluate(()=>window.items[0].requestRevision='9'.padStart(32,'0'));await cancelButton().click();
    await page.locator('.access-request-message').filter({hasText:'신청 상태가 변경'}).waitFor();assert.equal(await page.evaluate(()=>window.items[0].access),'pending');
    await page.getByRole('button',{name:'신청 상태 확인',exact:true}).first().click();await cancelButton().waitFor();assert.equal(await count('cancelAccessRequest'),1);

    // An already rejected attempt has nothing to cancel; do not report a cancellation.
    await fixture();await open();await connect();await requestButton().click();await cancelButton().waitFor();await page.evaluate(()=>window.cancelMode='none');await cancelButton().click();
    await requestButton().waitFor();assert.match(await page.locator('.access-request-message').innerText(),/취소할 대기 중인 신청이 없어요/);assert.doesNotMatch(await page.locator('.access-request-message').innerText(),/신청을 취소했어요/);assert.equal(await count('cancelAccessRequest'),1);

    // Reapplying and then cancelling must clear the previous rejection explanation.
    await fixture();await page.evaluate(()=>Object.assign(window.items[0],{requestStatus:'rejected',accessDecision:'예전 신청 사유를 보완해 주세요.'}));await open();await connect();
    assert.match(await page.locator('#detail-panel').innerText(),/예전 신청 사유/);await requestButton().click();await cancelButton().waitFor();await cancelButton().click();await reapplyButton().waitFor();
    assert.doesNotMatch(await page.locator('#detail-panel').innerText(),/예전 신청 사유/);

    // A late cancellation response cannot contaminate another tool's detail.
    await fixture();await open();await connect();await requestButton().click();await cancelButton().waitFor();await page.evaluate(()=>window.holdCancel=true);await cancelButton().click();await page.waitForFunction(()=>typeof window.releaseCancel==='function');
    await page.locator('#detail-close').click();await page.locator('.tool-card[data-tool-id="2"] .tool-title').click();await page.evaluate(()=>window.releaseCancel());await page.locator('#detail-title').filter({hasText:'사내 자료 검색'}).waitFor();await requestButton().waitFor();assert.equal(await reapplyButton().count(),0);

    await fixture({dark:true});await open();await connect();await page.screenshot({path:path.join(output,'03-request-dark.png'),animations:'disabled'});await requestButton().click();await page.locator('.access-pending').first().waitFor();
    await page.setViewportSize({width:420,height:850});await page.screenshot({path:path.join(output,'04-pending-dark-narrow.png'),animations:'disabled'});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    assert.equal(await page.locator('#detail-view').evaluate(node=>node.scrollWidth<=node.clientWidth),true);
    await fixture({legacy:true});await open();assert.equal(await requestButton().count(),0);await page.getByRole('button',{name:'웹에서 권한 신청',exact:true}).first().waitFor();assert.equal(await count('requestAccess'),0);
    assert.deepEqual(errors,[]);
    const checks=['approved no request control','gated versions avoid unnecessary permission RPC','no automatic write','one click request','pending prevents duplicate and install','read-only refresh','approval unlocks install','in-flight close and reopen','uncertain reply read-only recovery','explicit rejection shows safe explanation without resubmission','late failure isolated to originating tool','concurrent grant refreshes details','cancel busy and single write','cancelled state survives reopen','fresh attempt after cancellation','approval wins cancellation race','uncertain cancellation reconciles read-only','stale attempt cannot cancel newer request','already rejected attempt never claims cancellation','late cancellation isolated to other tool','light dark narrow layout','older server fallback'];
    checks.push('new attempt clears previous rejection explanation');
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({passed:true,checks,errors},null,2));
    console.log('PASS: '+checks.join(', '));
  } finally {
    if(process.platform==='win32')require('node:child_process').spawnSync('taskkill.exe',['/PID',String(server.process().pid),'/T','/F'],{windowsHide:true,timeout:10000,stdio:'ignore'});
    await Promise.race([server.close(),new Promise(resolve=>setTimeout(resolve,3000))]);
  }
})().then(()=>process.exit(0),error=>{console.error(error);process.exit(1);});
