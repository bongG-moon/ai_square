// Actual extension UI in Edge; synthetic postMessage host, no platform or installation calls.
// Run: node organization-store/tests/browser-action-icons.cjs
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(require('node:os').homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const root=path.resolve(__dirname,'../..'),source=path.join(root,'organization-store');
const output=process.env.STORE_ICONS_OUTPUT||path.join(root,'outputs/store-action-icons-20261026');
const html=fs.readFileSync(path.join(source,'ui/index.html'),'utf8').replace('<!--STORE_STYLE-->','<style>'+fs.readFileSync(path.join(source,'ui/store.css'),'utf8')+'</style>');
const script=fs.readFileSync(path.join(source,'ui/store.js'),'utf8');
const font=fs.readFileSync(path.join(root,'build/workspace-local-repository/local_app/web/fonts/NotoSansKR-Variable.woff'));
fs.mkdirSync(output,{recursive:true});

(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 const errors=[],checks=[],screenshots=[],network=[];
 try{
  const page=await browser.newPage({viewport:{width:1100,height:900}});page.setDefaultTimeout(7000);
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',route=>{
   const url=new URL(route.request().url());network.push(url.origin);
   if(url.origin!=='http://127.0.0.1:48591')return route.abort();
   return route.fulfill({status:200,contentType:url.pathname.endsWith('.woff')?'font/woff':'text/html',body:url.pathname.endsWith('.woff')?font:html});
  });
  await page.goto('http://127.0.0.1:48591/');
  await page.evaluate(()=>{
   window.requests=[];
   const item={id:41,name:'주간 업무 보고서',desc:'자료를 정리하고 보고서를 작성하는 도구입니다.',type:'Skill',platform:'Claude',registrantName:'예시 등록자',org:'업무 혁신팀',access:'approved',active:2,guide:'보고서에 사용할 자료를 선택한 뒤 요청하세요.',versions:[{n:2,note:'보고서 표와 검증 안내를 개선했습니다.',created:1792936800,filename:'weekly-report.zip'},{n:1,note:'첫 번째 배포입니다.',created:1792850400}],comments:[{author:'사용자',kind:'개선 의견',text:'팀별 자료를 비교하기 편리해졌습니다.',created:1792936800}]};
   window.addEventListener('message',event=>{
    const message=event.data;
    if(message.type==='ax-extension-ready')return window.postMessage({type:'ax-extension-init',channel:'icons-fixture',hostFeatures:['workspaces','publishFiles'],theme:'light',context:{kind:'work',title:'아이콘 확인',workspace:'D:/Fixture'}},'*');
    if(message.type!=='ax-extension-request')return;
    window.requests.push(message);
    let result={};
    if(message.action==='status')result={configured:true,baseUrl:'https://square.example.test'};
    if(message.action==='options')result={organizations:[]};
    if(message.action==='catalog')result={items:[item],total:1};
    if(message.action==='detail')result={item,canInstall:true,webUrl:'https://square.example.test/tool/41?view=detail',manifest:{release:2,downloadUrl:'/download/fixture',installProfile:{scopes:['user','project']}}};
    window.postMessage({type:'ax-extension-response',channel:message.channel,requestId:message.requestId,ok:true,result},'*');
   });
  });
  await page.addScriptTag({content:script});await page.locator('.catalog-card').waitFor();await page.evaluate(()=>document.fonts.ready);
  const settle=()=>page.waitForFunction(()=>document.getAnimations().every(a=>a.playState!=='running'&&a.playState!=='pending'));
  const count=()=>page.evaluate(()=>requests.filter(r=>r.action==='host.openExternal').length);
  async function inspect(name){
   const button=page.getByRole('button',{name,exact:true});await button.waitFor({state:'visible'});await settle();
   assert.equal(await button.locator('svg.action-icon').count(),1);
   const value=await button.evaluate(node=>{
    const svg=node.querySelector('svg'),r=svg.getBoundingClientRect(),b=node.getBoundingClientRect(),style=getComputedStyle(svg);
    return {name:node.textContent.trim(),width:r.width,height:r.height,stroke:style.stroke,fill:style.fill,hidden:svg.getAttribute('aria-hidden'),focusable:svg.getAttribute('focusable'),overflow:node.scrollWidth>node.clientWidth+1,iconInside:r.left>=b.left-1&&r.right<=b.right+1&&r.top>=b.top-1&&r.bottom<=b.bottom+1};
   });
   assert.equal(value.name,name);assert.ok(value.width>=14&&value.width<=16);assert.ok(value.height>=14&&value.height<=16);
   assert.equal(value.hidden,'true');assert.equal(value.focusable,'false');assert.equal(value.fill,'none');assert.notEqual(value.stroke,'none');
   assert.equal(value.overflow,false);assert.equal(value.iconInside,true);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
   return {button,value};
  }
  async function dispatch(button,url,keyboard){
   const before=await count();
   if(keyboard){await button.focus();await page.keyboard.press(keyboard);}else await button.click();
   await page.waitForFunction(n=>requests.filter(r=>r.action==='host.openExternal').length===n,before+1);
   assert.deepEqual(await page.evaluate(()=>requests.filter(r=>r.action==='host.openExternal').at(-1).payload),{url});
  }
  async function screenshot(name){await settle();await page.screenshot({path:path.join(output,name),fullPage:true});screenshots.push(name);}
  for(const [name,width,dark]of[['light',1100,false],['dark',1100,true],['narrow',420,true]]){
   await page.setViewportSize({width,height:900});
   await page.evaluate(dark=>window.postMessage({type:'ax-extension-theme',channel:'icons-fixture',theme:dark?'dark':'light'},'*'),dark);
   await page.waitForFunction(theme=>document.documentElement.dataset.theme===theme,dark?'dark':'light');
   await page.locator('#connection-button').click();
   const key=await inspect('웹에서 KEY 확인');
   await dispatch(key.button,'https://square.example.test/local-access',name==='dark'?'Enter':null);
   if(name!=='dark')await screenshot('key-'+name+'.png');
   await page.locator('#connection-cancel').click();await page.locator('.catalog-card').waitFor();
   await page.getByRole('button',{name:'주간 업무 보고서',exact:true}).click();await page.locator('#detail-title').filter({hasText:'주간 업무 보고서'}).waitFor();
   const views=[];
   for(const [tab,label]of[['설치·연결','웹에서 보기'],['버전','웹에서 배포 이력 보기'],['의견','웹에서 의견 남기기']]){
    await page.getByRole('tab',{name:tab,exact:true}).click();
    const action=await inspect(label);views.push(action.value);
    await dispatch(action.button,'https://square.example.test/tool/41?view=detail',name==='dark'?'Space':null);
    if((name!=='dark'&&tab==='설치·연결')||(name==='dark'&&tab!=='설치·연결'))await screenshot('detail-'+name+'-'+(tab==='설치·연결'?'connect':tab==='버전'?'versions':'opinions')+'.png');
   }
   checks.push({view:name,viewport:width,key:key.value,detailActions:views});
   await page.locator('#detail-close').click();await settle();
  }
  const actions=await page.evaluate(()=>requests.map(r=>r.action));
  assert.equal(actions.filter(a=>a==='host.openExternal').length,12);
  assert.deepEqual(actions.filter(a=>['connect','prepare','install','download','rollback','verify','publish'].includes(a)),[]);
  assert.deepEqual(errors,[]);assert.ok(network.every(origin=>origin==='http://127.0.0.1:48591'));
  const report={passed:true,browser:'Edge headless',fixture:'Real extension HTML/CSS/JS with isolated synthetic postMessage host. No real website, credentials, install, verification, or rollback.',checks,screenshots,externalDispatchCount:12,pageErrors:errors};
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify(report,null,2)+'\n');
  console.log('PASS: semantic action icons, accessible names, 15px rendering, exact external URLs, mouse/keyboard activation, light/dark/420px layouts; no platform mutations.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
