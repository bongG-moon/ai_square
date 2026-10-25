// Real Chromium, synthetic parent/worker contract; no live KEY or publication.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(require('node:os').homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const root=path.resolve(__dirname,'../..'),source=path.join(root,'organization-store');
const output=path.join(root,'outputs/store-publish-ui-20261025');fs.mkdirSync(output,{recursive:true});
const html=fs.readFileSync(path.join(source,'ui/index.html'),'utf8').replace('<!--STORE_STYLE-->','<style>'+fs.readFileSync(path.join(source,'ui/store.css'),'utf8')+'</style>');
const script=fs.readFileSync(path.join(source,'ui/store.js'),'utf8');
(async()=>{
 const server=await chromium.launchServer({executablePath:path.join(process.env['ProgramFiles(x86)']||'C:/Program Files (x86)','Microsoft/Edge/Application/msedge.exe'),headless:true});
 const browser=await chromium.connect(server.wsEndpoint());
 try{
  const page=await browser.newPage({viewport:{width:1280,height:980}});page.setDefaultTimeout(7000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const base='http://127.0.0.1:17352';
  const font=fs.readFileSync(path.join(root,'build/workspace-local-repository/local_app/web/fonts/NotoSansKR-Variable.woff'));
  await page.route(base+'/**',route=>route.fulfill({status:200,contentType:route.request().url().endsWith('.woff')?'font/woff':'text/html',body:route.request().url().endsWith('.woff')?font:html}));
  async function fixture(config={}){
   await page.goto(base+'/',{waitUntil:'domcontentloaded',timeout:30000});await page.evaluate(()=>document.fonts.load('13px \"Noto Sans KR\"'));assert.equal(await page.evaluate(()=>document.fonts.check('13px \"Noto Sans KR\"')),true);
   await page.evaluate(config=>{
    window.requests=[];window.approved=false;window.cancelFile=false;window.inspectFail=false;window.sourceProfile=true;window.failPrepare=false;window.expireCommit=false;
    const options={organizations:[{id:'org',name:'업무 혁신팀'}],categories:[{id:'cat',name:'문서 작성'},...Array.from({length:40},(_,i)=>({id:'cat'+i,name:'추가 분류 '+(i+1)}))]};
    const types=['Skill','MCP/Tool','하네스','Skill','Tool','플러그인'];
    const desc='업무 폴더의 자료를 확인하고 핵심 내용을 보고서로 정리합니다. 등록한 양식과 업무 기준을 함께 적용하며 결과를 검토할 수 있습니다. 이 부분은 길어진 설명의 끝이며 상세 창에서 빠짐없이 보여야 합니다.';
    const items=types.map((type,i)=>({id:i+1,name:['업무 보고서 작성','사내 자료 검색','설비 점검 도우미','업무 시작 가이드','문서 연결 MCP','업무 템플릿 모음'][i],type,platform:'Claude',desc,registrantName:'예시 등록자',org:'업무 혁신팀',category:'문서 작성',workTags:['보고서','업무 지원'],statistics:{views:132,likes:12,downloads:28},access:'approved'}));
    const metadata={name:'주간 보고서 정리',desc,guide:'1. 업무 폴더를 선택합니다.\n2. 보고서 정리를 요청합니다.',type:'Skill',platform:'Claude'};
    const profile={kind:'skill',host:'claude',scopes:['user','project'],entrypoint:'SKILL.md'};
    let draft=null;
    window.addEventListener('message',event=>{
     const m=event.data;
     if(m.type==='ax-extension-ready')return window.postMessage({type:'ax-extension-init',channel:'test',hostFeatures:config.legacy?[]:['workspaces','publishFiles'],theme:config.dark?'dark':'light',context:{kind:'work',title:'업무 보고서'}},'*');
     if(m.type!=='ax-extension-request')return;
     window.requests.push(m);let result={},error;
     if(m.action==='status')result={configured:true,baseUrl:'https://square.example.test',existingConnectionAvailable:true};
     if(m.action==='options')result=options;
     if(m.action==='catalog')result={items,total:items.length};
     if(m.action==='detail')result={item:{...items.find(i=>i.id===m.payload.toolId),guide:metadata.guide},canInstall:false};
     if(m.action==='publishOptions')result={canPublish:!config.readonly,options,candidates:[{id:41,name:'기존 보고서 도구'}],...(m.payload.toolId?{existing:{metadata:{...metadata,installProfile:profile,orgId:'org',categoryId:'cat',approval:true,mode:'file'}}}:{})};
     if(m.action==='host.pickFile')result=window.cancelFile?{cancelled:true}:{cancelled:false,fileToken:'token-'+requests.length,name:window.sourceProfile?'weekly.zip':'other.md',size:1024};
     if(m.action==='inspectPublishSource'){
      if(window.inspectFail)error='선택한 파일을 읽지 못했습니다. 다시 선택하세요.';
      else result={source:{name:window.sourceProfile?'weekly.zip':'other.md',bytes:1024},metadata:{...metadata,...(window.sourceProfile?{packageId:'weekly-report',installProfile:profile}:{})},options,candidates:[{id:41,name:'기존 보고서 도구'}]};
     }
     if(m.action==='preparePublish'){
      if(window.failPrepare){window.failPrepare=false;error='응답을 확인하지 못했습니다. 다시 확인하세요.';}
      else {draft={id:'a'.repeat(32),status:'pending',reviewUrl:'https://square.example.test/publish-review/'+'a'.repeat(32),metadata:m.payload.metadata,toolId:m.payload.toolId,artifact:{name:m.payload.metadata.mode==='file'?'weekly.zip':''}};result=draft;}
     }
     if(m.action==='publishStatus')result={...draft,status:window.approved?'approved':'pending'};
     if(m.action==='publish')result=window.expireCommit?{...draft,status:'expired',published:false,notice:'웹 승인 기한이 지났습니다. 다시 준비하세요.'}:{id:7,version:1,published:true,status:'committed'};
     window.postMessage({type:'ax-extension-response',channel:m.channel,requestId:m.requestId,ok:!error,result,error},'*');
    });
   },config);
   await page.addScriptTag({content:script});await page.locator('.tool-card').first().waitFor();
  }
  const count=action=>page.evaluate(action=>window.requests.filter(r=>r.action===action).length,action);
  async function select(label,value){await page.getByRole('button',{name:label,exact:true}).click();await page.getByRole('option',{name:value,exact:true}).click();}
  async function fillRequired(){await select('등록 방식','새 도구 등록');await select('등록 조직','업무 혁신팀');await select('업무 분류','문서 작성');await page.locator('input[name=publish-visibility][value=public]').check();}
  await fixture();
  const layout=await page.locator('.tool-card').evaluateAll(nodes=>nodes.map(n=>({x:n.offsetLeft,y:n.offsetTop,height:n.offsetHeight,width:n.offsetWidth})));
  assert.equal(new Set(layout.slice(0,3).map(n=>n.y)).size,1);assert.ok(layout[3].y>layout[0].y);assert.ok(layout[0].height<300);
  assert.equal(await page.locator('.tool-desc').first().evaluate(n=>getComputedStyle(n).webkitLineClamp),'2');
  assert.match(await page.locator('body').evaluate(n=>getComputedStyle(n).fontFamily),/Noto Sans KR/);
  await page.screenshot({path:path.join(output,'01-catalog-light.png'),animations:'disabled'});
  await page.getByRole('button',{name:'업무 보고서 작성',exact:true}).click();await page.locator('#detail-dialog').waitFor({state:'visible'});
  assert.match(await page.locator('.detail-hero').innerText(),/이 부분은 길어진 설명의 끝/);
  await page.screenshot({path:path.join(output,'02-detail-light.png'),animations:'disabled'});await page.locator('#detail-close').click();
  await page.locator('#connection-button').click();assert.equal(await page.locator('#reuse-connection').innerText(),'저장된 플랫폼(MCP) 연결 사용');await page.locator('#connection-cancel').click();
  await page.locator('#publish-open').click();await page.locator('#publish-prepare').waitFor({state:'visible'});
  await page.locator('#publish-pick-file').click();await page.locator('#publish-file-name').filter({hasText:'weekly.zip'}).waitFor();
  assert.equal(await count('preparePublish'),0);assert.equal(await count('publish'),0);
  await fillRequired();
  await page.getByRole('button',{name:'업무 분류',exact:true}).click();
  const menuBounds=await page.locator('#publish-category-menu').evaluate(n=>{const rect=n.getBoundingClientRect(),area=n.closest('.publish-scroll').getBoundingClientRect();return {top:rect.top,bottom:rect.bottom,areaTop:area.top,areaBottom:area.bottom};});
  assert.ok(menuBounds.top>=menuBounds.areaTop&&menuBounds.bottom<=menuBounds.areaBottom);
  await page.keyboard.press('End');assert.equal(await page.evaluate(()=>document.activeElement.textContent),'추가 분류 40');await page.keyboard.press('Escape');
  assert.equal(await page.locator('#publish-category').inputValue(),'cat');
  await page.locator('.publish-scroll').evaluate(n=>n.scrollTop=0);await page.screenshot({path:path.join(output,'03-register-light.png'),animations:'disabled'});
  await page.locator('#publish-close').click();await page.locator('#publish-open').click();assert.equal(await page.locator('#publish-name').inputValue(),'주간 보고서 정리');
  await page.evaluate(()=>window.cancelFile=true);await page.locator('#publish-pick-file').click();await page.waitForFunction(()=>!document.querySelector('#publish-pick-file').disabled);assert.equal(await page.locator('#publish-file-name').innerText(),'weekly.zip');await page.evaluate(()=>window.cancelFile=false);
  await page.evaluate(()=>window.failPrepare=true);await page.locator('#publish-prepare').click();await page.waitForFunction(()=>!document.querySelector('#publish-prepare').disabled);await page.locator('#publish-message').filter({hasText:'응답을 확인하지 못했습니다.'}).waitFor();
  await page.locator('#publish-prepare').click();await page.locator('#publish-review').waitFor({state:'visible'});
  const requestIds=await page.evaluate(()=>requests.filter(r=>r.action==='preparePublish').map(r=>r.payload.requestId));assert.equal(requestIds[0],requestIds[1]);
  assert.equal(await page.locator('#publish-commit').isDisabled(),true);assert.equal(await count('publish'),0);
  await page.locator('#publish-review-open').click();await page.waitForFunction(()=>requests.some(r=>r.action==='host.openExternal'));assert.equal(await count('host.openExternal'),1);
  await page.locator('#publish-status').click();await page.waitForFunction(()=>!document.querySelector('#publish-status').disabled);assert.equal(await page.locator('#publish-commit').isDisabled(),true);
  await page.evaluate(()=>window.approved=true);await page.locator('#publish-status').click();await page.waitForFunction(()=>!document.querySelector('#publish-commit').disabled);
  await page.screenshot({path:path.join(output,'04-register-reviewed.png'),animations:'disabled'});
  await page.locator('#publish-commit').click();await page.locator('#publish-review-title').filter({hasText:'플랫폼에 등록했어요.'}).waitFor();assert.equal(await count('publish'),1);
  await page.locator('#publish-edit').click();assert.equal(await page.locator('#publish-name').inputValue(),'');
  await page.locator('#publish-pick-file').click();await page.locator('#publish-install-info').waitFor({state:'visible'});
  await page.evaluate(()=>window.sourceProfile=false);await page.locator('#publish-pick-file').click();await page.locator('#publish-file-name').filter({hasText:'other.md'}).waitFor();assert.equal(await page.locator('#publish-install-info').isVisible(),false);
  await fillRequired();await page.locator('#publish-prepare').click();await page.locator('#publish-review').waitFor({state:'visible'});
  const latest=await page.evaluate(()=>requests.filter(r=>r.action==='preparePublish').at(-1).payload);assert.equal('installProfile' in latest.metadata,false);assert.equal('packageId' in latest.metadata,false);
  await page.locator('#publish-status').click();await page.evaluate(()=>window.expireCommit=true);await page.locator('#publish-commit').click();await page.locator('#publish-review-label').filter({hasText:'확인 기한 만료'}).waitFor();assert.equal(await page.locator('#publish-commit').isDisabled(),true);
  await page.locator('#publish-edit').click();await page.evaluate(()=>window.inspectFail=true);await page.locator('#publish-pick-file').click();await page.locator('#publish-file-name').filter({hasText:'배포할 파일을 다시 선택하세요'}).waitFor();
  assert.equal(await page.locator('#publish-name').inputValue(),'주간 보고서 정리');const before=await count('preparePublish');await page.locator('#publish-prepare').click();await page.locator('#publish-message').filter({hasText:'배포할 파일을 선택해 주세요.'}).waitFor();assert.equal(await count('preparePublish'),before);
  await select('등록 방식','내 도구의 새 버전 등록');await select('기존 도구','기존 보고서 도구');await page.locator('#publish-message').filter({hasText:'기존 도구의 설정을 불러왔어요.'}).waitFor();
  await select('배포 방법','설치 명령어 안내');await page.locator('#publish-command-project').fill('example-tool setup --project');await page.locator('#publish-prepare').click();await page.locator('#publish-review').waitFor({state:'visible'});
  const updateRequest=await page.evaluate(()=>requests.filter(r=>r.action==='preparePublish').at(-1).payload);assert.equal(updateRequest.target,'update');assert.equal(updateRequest.toolId,41);assert.equal(updateRequest.metadata.mode,'command');assert.equal(updateRequest.metadata.approval,true);assert.equal('installProfile' in updateRequest.metadata,false);
  await fixture({legacy:true});await page.locator('#publish-open').click();await page.waitForFunction(()=>!document.querySelector('#publish-prepare').disabled);assert.equal(await page.locator('#publish-pick-file').isDisabled(),true);assert.match(await page.locator('#publish-file-help').innerText(),/업데이트/);
  await select('배포 방법','웹 주소 · 원격 연결 안내');await fillRequired();await page.locator('#publish-name').fill('업무 자료 웹');await page.locator('#publish-desc').fill('업무 자료를 보는 웹입니다.');await page.locator('#publish-guide').fill('주소를 열어 연결합니다.');await select('사용 프로그램','기타');await select('등록할 기능 유형','MCP/Tool');await page.locator('#publish-url').fill('https://docs.example.test/');
  await page.locator('#publish-prepare').click();await page.locator('#publish-review').waitFor({state:'visible'});const urlRequest=await page.evaluate(()=>requests.find(r=>r.action==='preparePublish').payload);assert.equal(urlRequest.metadata.mode,'url');assert.equal('fileToken' in urlRequest,false);
  await fixture({readonly:true});await page.locator('#publish-open').click();await page.locator('#publish-access').waitFor({state:'visible'});assert.equal(await page.locator('#publish-prepare').isDisabled(),true);assert.equal(await count('preparePublish'),0);
  await fixture({dark:true});await page.screenshot({path:path.join(output,'05-catalog-dark.png'),animations:'disabled'});await page.locator('#publish-open').click();await page.waitForFunction(()=>!document.querySelector('#publish-prepare').disabled);await page.locator('#publish-pick-file').click();await fillRequired();await page.locator('.publish-scroll').evaluate(n=>n.scrollTop=0);await page.screenshot({path:path.join(output,'06-register-dark.png'),animations:'disabled'});
  await page.setViewportSize({width:420,height:850});
  await page.getByRole('button',{name:'업무 분류',exact:true}).click();await page.keyboard.press('End');assert.equal(await page.evaluate(()=>document.activeElement.textContent),'추가 분류 40');
  const narrowBounds=await page.locator('#publish-category-menu').evaluate(n=>{const rect=n.getBoundingClientRect(),area=n.closest('.publish-scroll').getBoundingClientRect();return {top:rect.top,bottom:rect.bottom,areaTop:area.top,areaBottom:area.bottom};});assert.ok(narrowBounds.top>=narrowBounds.areaTop&&narrowBounds.bottom<=narrowBounds.areaBottom);await page.keyboard.press('Escape');
  await page.locator('.publish-scroll').evaluate(n=>n.scrollTop=0);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.screenshot({path:path.join(output,'07-register-narrow.png'),animations:'disabled'});
  await page.locator('#publish-close').click();assert.equal(await page.locator('.card-grid').evaluate(n=>getComputedStyle(n).gridTemplateColumns.split(' ').length),1);await page.screenshot({path:path.join(output,'08-catalog-narrow.png'),animations:'disabled'});
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({passed:true,layout,checks:['three columns and compact cards','description clamp and full detail','Noto font loaded','connection label','file prepare/review/commit','no automatic publish or polling','dialog preserves form','cancel preserves selected file','network retry reuses request id','new file clears stale profile','expired approval never reports success','failed inspection clears revoked selection','existing-tool command update and visibility','legacy host URL publishing','read-only key blocks preparation','dark/narrow layout'],errors},null,2));
  console.log('PASS: registration lifecycle, file capability UX, compact cards, detail, dark/narrow layouts.');
 }finally{
  if(process.platform==='win32')require('node:child_process').spawnSync('taskkill.exe',['/PID',String(server.process().pid),'/T','/F'],{windowsHide:true,timeout:10000,stdio:'ignore'});
  await Promise.race([server.close(),new Promise(resolve=>setTimeout(resolve,3000))]);
 }
})().then(()=>process.exit(0),error=>{console.error(error);process.exit(1);});
