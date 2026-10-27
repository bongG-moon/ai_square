// Real browser with isolated responses. Never uses a personal KEY or publishes.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),app=path.join(root,'build/workspace-local-repository/local_app/web');
const {chromium}=require(path.join(require('node:os').homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const out=path.join(root,'outputs/usage-store-20261027');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1440,height:960}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 page.setDefaultTimeout(8000);
 try{
  let html=fs.readFileSync(path.join(app,'index.html'),'utf8').replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'');
  await page.route('http://127.0.0.1:17354/**',route=>{
   const name=new URL(route.request().url()).pathname.slice(1);
   if(!name)return route.fulfill({contentType:'text/html',body:html});
   const file=path.join(app,name);
   return route.fulfill({contentType:name.endsWith('.css')?'text/css':name.endsWith('.woff')?'font/woff':'text/javascript',body:fs.existsSync(file)?fs.readFileSync(file):''});
  });
  const usage=fs.readFileSync(path.join(app,'llm-usage.js'),'utf8');
  for(const theme of ['light','dark']){
   await page.goto('http://127.0.0.1:17354/');await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme);
   await page.addScriptTag({content:usage});
   await page.evaluate(()=>{
    window.usageData={usage:{team:'pro',teamAlias:'예시 팀',teams:[{id:'pro',name:'예시 팀'}],spend:7.2,max:20,remaining:12.8,percent:36,updatedAt:Date.now()/1000,resetAt:'2026-10-28T00:00:00',demo:true},loading:false,error:null};
    WorkspaceLlmUsage.start({api:async()=>window.usageData});
   });
   await page.locator('#llm-usage-percent').filter({hasText:'36%'}).waitFor();await page.evaluate(()=>document.fonts.ready);
   const box=await page.locator('#llm-usage').boundingBox(),menus=await page.locator('.sidebar-footer-actions').boundingBox();
   assert.ok(box.y+box.height<=menus.y+1,'usage above footer menus');assert.ok(menus.y+menus.height<=960,'menus fit');
   assert.equal(await page.locator('#llm-usage-track').evaluate(e=>getComputedStyle(e).height),'5px');
   await page.locator('#llm-usage-toggle').click();await page.locator('#llm-usage-details').waitFor({state:'visible'});
   const pop=await page.locator('#llm-usage-details').boundingBox();assert.ok(pop.y>=0&&pop.x+pop.width<=1440);
   await page.screenshot({path:path.join(out,`usage-${theme}.png`)});
   await page.keyboard.press('Escape');assert.equal(await page.locator('#llm-usage-toggle').getAttribute('aria-expanded'),'false');
   await page.evaluate(()=>{usageData.usage.percent=96;usageData.usage.spend=19.2;usageData.usage.remaining=.8;});
   await page.locator('#llm-usage-toggle').click();await page.locator('#llm-usage-refresh').click();
   assert.equal(await page.locator('#llm-usage').getAttribute('data-level'),'danger');
   await page.evaluate(()=>{usageData.error='key_required';});await page.locator('#llm-usage-refresh').click();
   assert.match(await page.locator('#llm-usage-state').innerText(),/LLM Key/);
  }
  html=fs.readFileSync(path.join(root,'organization-store/ui/index.html'),'utf8').replace('<!--STORE_STYLE-->','<style>'+fs.readFileSync(path.join(root,'organization-store/ui/store.css'),'utf8')+'</style>');
  await page.route('http://127.0.0.1:17355/**',route=>route.fulfill({contentType:'text/html',body:html}));
  await page.goto('http://127.0.0.1:17355/');
  await page.evaluate(()=>{
   window.requests=[];window.published=0;window.uploaded=false;
   const options={organizations:[{id:'org',name:'조직'}],categories:[{id:'cat',name:'업무'}]};
   const item={id:1,name:'사용자 도구',desc:'기능 설명',type:'Tool',platform:'Claude',access:'approved',guide:'설치 안내'};
   const candidates=Array.from({length:37},(_,i)=>({id:i+1,name:'내 도구 '+(i+1)}));let draft;
   addEventListener('message',async event=>{
    const m=event.data;if(m.type==='ax-extension-ready')return postMessage({type:'ax-extension-init',channel:'test',hostFeatures:['workspaces','publishFiles','publishUpload','installRequests','installRequestNavigation'],theme:'light',context:{kind:'work',title:'기존 업무',workspace:'C:/work'}},'*');
    if(m.type!=='ax-extension-request')return;requests.push(m);let result={};
    if(m.action==='status')result={configured:true,baseUrl:'https://square.example.test'};
    if(m.action==='options')result=options;
    if(m.action==='catalog')result={items:[item],total:1};
    if(m.action==='detail')result={item,canInstall:false,manifest:{downloadUrl:'/api/download/1'}};
    if(m.action==='publishOptions')result={canPublish:true,options,candidates};
    if(m.action==='host.uploadFile'){uploaded=await m.payload.file.text()==='fixture';result={cancelled:false,name:m.payload.file.name,size:m.payload.file.size,fileToken:'x'.repeat(43)};}
    if(m.action==='inspectPublishSource')result={source:{name:'skill.zip',bytes:7},metadata:{name:'자동 입력 도구',desc:'ZIP에서 읽은 설명',guide:'사용 안내',platform:'Claude',type:'Skill'},options,candidates:[candidates[3]]};
    if(m.action==='preparePublish'){draft={id:'a'.repeat(32),reviewDigest:'b'.repeat(64),status:'pending',metadata:m.payload.metadata};result=draft;}
    if(m.action==='publish'){if(m.payload.confirmed!==true||m.payload.reviewDigest!==draft.reviewDigest)throw Error('wrong confirmation');published++;result={published:true,status:'committed',id:99,version:1};}
    if(m.action==='host.listWorkspaces')result={items:[{id:'work-1',title:'기존 업무',workspace:'C:/work'}]};
    if(m.action==='host.requestInstall')result={requested:true,installed:false,title:'기존 업무',sessionId:'work-1'};
    postMessage({type:'ax-extension-response',channel:m.channel,requestId:m.requestId,ok:true,result},'*');
   });
  });
  await page.addScriptTag({content:fs.readFileSync(path.join(root,'organization-store/ui/store.js'),'utf8')});
  await page.locator('.tool-card').first().waitFor();await page.locator('#publish-open').click();
  await page.waitForFunction(()=>!document.querySelector('#publish-pick-file').disabled);
  assert.equal(await page.locator('#publish-existing option').count(),38);
  await page.locator('#publish-name').fill('직접 작성한 이름');
  await page.locator('#publish-file-panel').evaluate(e=>{const dt=new DataTransfer();dt.items.add(new File(['fixture'],'skill.zip',{type:'application/zip'}));e.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));});
  await page.waitForFunction(()=>window.uploaded&&document.querySelector('#publish-desc').value==='ZIP에서 읽은 설명');
  assert.equal(await page.locator('#publish-name').inputValue(),'직접 작성한 이름');
  assert.equal(await page.locator('#publish-existing option').count(),38,'ZIP suggestion does not replace my tools');
  await page.evaluate(()=>{for(const [id,value]of [['publish-target','new'],['publish-org','org'],['publish-category','cat']]){const e=document.getElementById(id);e.value=value;e.dispatchEvent(new Event('change',{bubbles:true}));}document.querySelector('input[name="publish-visibility"][value="public"]').click();});
  await page.screenshot({path:path.join(out,'store-registration-light.png')});
  await page.locator('#publish-prepare').click();await page.waitForFunction(()=>window.published===1);
  await page.waitForFunction(()=>document.querySelector('#publish-message').textContent.includes('등록했어요'));
  assert.equal(await page.locator('#publish-review-open').isVisible(),false);
  assert.equal(await page.locator('#publish-existing option').count(),38);
  await page.locator('#publish-close').click();await page.locator('#publish-open').click();
  assert.equal(await page.locator('#publish-existing option').count(),38);
  await page.locator('#publish-close').click();await page.locator('.tool-card').first().click();
  await page.locator('#detail-tab-connect').click();await page.getByRole('button',{name:'AI에게 설치 요청',exact:true}).click();
  await page.locator('#confirm-dialog[open]').waitFor({state:'visible'});
  assert.equal(await page.locator('#confirm-yes').innerText(),'설치 요청하고 업무로 이동');
  assert.match(await page.locator('#confirm-dialog').innerText(),/내 계정의 모든 업무에서 쓸 수 있게 설치해요/);
  await page.locator('#confirm-yes').click();
  await page.waitForFunction(()=>requests.some(r=>r.action==='host.requestInstall'));
  await page.waitForFunction(()=>document.querySelector('#installation-status').dataset.phase==='requested');
  const request=await page.evaluate(()=>requests.find(r=>r.action==='host.requestInstall').payload);
  assert.equal(request.sessionId,'work-1');assert.equal(request.scope,'user');assert.equal(request.confirmed,true);
  await page.getByRole('button',{name:'AI에게 설치 요청',exact:true}).click();
  await page.locator('#confirm-dialog[open]').waitFor({state:'visible'});
  await page.locator('select[aria-label="설치 범위"]').selectOption('work',{force:true});
  assert.match(await page.locator('#confirm-dialog').innerText(),/선택한 업무 폴더에 설치해요/);
  await page.locator('#confirm-yes').click();
  await page.waitForFunction(()=>requests.filter(r=>r.action==='host.requestInstall').length===2);
  assert.equal(await page.evaluate(()=>requests.filter(r=>r.action==='host.requestInstall')[1].payload.scope),'work');
  await page.evaluate(()=>document.documentElement.dataset.theme='dark');await page.waitForFunction(()=>document.getAnimations().every(a=>a.playState!=='running'));await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));await page.screenshot({path:path.join(out,'store-install-request-dark.png')});
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify({passed:true,checks:['usage light/dark placement','threshold and key error','all 37 tools retained','drag/drop bytes','manual fields retained','direct publish once','all tools after reopen','AI request scope and existing work'],errors},null,2));
  console.log('PASS usage + registration + install-request browser checks');
 }catch(error){console.error('UI STATE',await page.evaluate(()=>({message:document.getElementById('publish-message')?.textContent,requests:(window.requests||[]).map(x=>x.action)})));await page.screenshot({path:path.join(out,'failure.png')});throw error;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
