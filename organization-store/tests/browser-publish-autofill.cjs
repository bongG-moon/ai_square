// Real Chromium regression for file-derived defaults versus the user's draft.
// The parent/worker messages are fixtures; no real KEY, upload, or publication.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(require('node:os').homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const root=path.resolve(__dirname,'../..'),source=path.join(root,'organization-store');
const output=path.join(root,'outputs/store-publish-autofill-20261025');fs.mkdirSync(output,{recursive:true});
const html=fs.readFileSync(path.join(source,'ui/index.html'),'utf8').replace('<!--STORE_STYLE-->','<style>'+fs.readFileSync(path.join(source,'ui/store.css'),'utf8')+'</style>');
const script=fs.readFileSync(path.join(source,'ui/store.js'),'utf8');
(async()=>{
 const server=await chromium.launchServer({executablePath:path.join(process.env['ProgramFiles(x86)']||'C:/Program Files (x86)','Microsoft/Edge/Application/msedge.exe'),headless:true});
 const browser=await chromium.connect(server.wsEndpoint());
 try{
  const page=await browser.newPage({viewport:{width:1280,height:980}});page.setDefaultTimeout(7000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const base='http://127.0.0.1:17359';
  await page.route(base+'/**',route=>route.fulfill({status:200,contentType:'text/html',body:html}));
  async function fixture(){
   await page.goto(base+'/',{waitUntil:'domcontentloaded'});
   await page.evaluate(()=>{
    window.requests=[];window.fileChoice='A';window.cancelFile=false;window.inspectFail=false;
    const options={organizations:[{id:'org',name:'업무 혁신팀'}],categories:[{id:'cat',name:'문서 작성'}]};
    const profile={kind:'skill',host:'claude',scopes:['user','project'],entrypoint:'SKILL.md'};
    const common={orgId:'untrusted-org',categoryId:'untrusted-cat',approval:true};
    const files={
     A:{...common,packageId:'package-a',name:'A 보고서',desc:'A 파일 설명',guide:'A 사용 안내',platform:'Claude',type:'Skill',changes:'A 변경 내용',workTags:['A'],environment:'A 환경',workflow:{steps:['A']},installProfile:profile},
     B:{...common,packageId:'package-b',name:'B 도구',desc:'B 파일 설명',guide:'B 사용 안내',platform:'ChatGPT',type:'MCP/Tool',workTags:['B'],environment:'B 환경',workflow:null},
     plain:{}
    };
    window.addEventListener('message',event=>{
     const m=event.data;
     if(m.type==='ax-extension-ready')return window.postMessage({type:'ax-extension-init',channel:'autofill-test',hostFeatures:['workspaces','publishFiles'],theme:'light',context:{kind:'work',title:'업무 보고서'}},'*');
     if(m.type!=='ax-extension-request')return;
     window.requests.push(m);let result={},error;
     if(m.action==='status')result={configured:true,baseUrl:'https://square.example.test'};
     if(m.action==='options')result=options;
     if(m.action==='catalog')result={items:[{id:1,name:'확인용 도구',type:'Skill',platform:'Claude',desc:'설명',access:'approved'}],total:1};
     if(m.action==='publishOptions')result={canPublish:true,options,candidates:[{id:41,name:'기존 보고서 도구'}],...(m.payload.toolId?{existing:{metadata:{name:'기존 이름',desc:'기존 설명',guide:'기존 안내',platform:'Claude',type:'Skill',orgId:'org',categoryId:'cat',approval:true,mode:'file',changes:'기존 변경 내용',packageId:'old-package',installProfile:profile}}}:{})};
     if(m.action==='host.pickFile')result=window.cancelFile?{cancelled:true}:{cancelled:false,fileToken:'token-'+requests.length,name:window.fileChoice+'.zip',size:1024};
     if(m.action==='inspectPublishSource'){
      if(window.inspectFail)error='올바른 ZIP 파일을 선택해 주세요.';
      else result={source:{name:window.fileChoice+'.zip',bytes:1024},metadata:files[window.fileChoice],options,candidates:[{id:41,name:'기존 보고서 도구'}]};
     }
     if(m.action==='preparePublish')result={id:'a'.repeat(32),status:'pending',reviewUrl:'https://square.example.test/publish-review/'+'a'.repeat(32),metadata:m.payload.metadata,toolId:m.payload.toolId};
     window.postMessage({type:'ax-extension-response',channel:m.channel,requestId:m.requestId,ok:!error,result,error},'*');
    });
   });
   await page.addScriptTag({content:script});await page.locator('.tool-card').first().waitFor();
   await page.locator('#publish-open').click();await ready();
  }
  async function ready(){await page.waitForFunction(()=>!document.querySelector('#publish-pick-file').disabled);}
  async function select(label,value){await page.getByRole('button',{name:label,exact:true}).click();await page.getByRole('option',{name:value,exact:true}).click();}
  async function pick(choice){await page.evaluate(choice=>window.fileChoice=choice,choice);await page.locator('#publish-pick-file').click();await ready();}
  async function fields(){return page.evaluate(()=>Object.fromEntries(['name','desc','guide','platform','type','changes','org','category'].map(key=>[key,document.querySelector('#publish-'+key).value])));}
  async function prepare(){await page.locator('#publish-prepare').click();await ready();return page.evaluate(()=>requests.filter(r=>r.action==='preparePublish').at(-1)?.payload);}
  async function required(){await select('등록 방식','새 도구 등록');await select('등록 조직','업무 혁신팀');await select('업무 분류','문서 작성');await page.locator('input[name=publish-visibility][value=public]').check();}

  await fixture();await pick('A');
  assert.deepEqual(await fields(),{name:'A 보고서',desc:'A 파일 설명',guide:'A 사용 안내',platform:'Claude',type:'Skill',changes:'A 변경 내용',org:'',category:''});
  assert.equal(await page.locator('input[name=publish-visibility]:checked').count(),0);
  assert.match(await page.locator('#publish-message').innerText(),/ZIP에서.*자동으로 불러왔어요/);
  assert.equal(await page.locator('#publish-org option[value=untrusted-org]').count(),0);
  await required();
  await page.locator('#publish-name').fill('사용자가 정한 이름');
  await page.locator('#publish-desc').fill('직접 다듬은 설명');
  await pick('B');
  assert.deepEqual(await fields(),{name:'사용자가 정한 이름',desc:'직접 다듬은 설명',guide:'B 사용 안내',platform:'ChatGPT',type:'MCP/Tool',changes:'',org:'org',category:'cat'});
  assert.equal(await page.locator('input[name=publish-visibility][value=public]').isChecked(),true);
  assert.equal(await page.locator('#publish-install-info').isVisible(),false);
  await page.locator('#publish-close').click();await page.locator('#publish-open').click();
  assert.equal((await fields()).name,'사용자가 정한 이름');
  await page.evaluate(()=>window.cancelFile=true);await pick('A');
  assert.equal(await page.locator('#publish-file-name').innerText(),'B.zip');
  await page.evaluate(()=>window.cancelFile=false);
  const payload=await prepare();assert.equal(payload.metadata.packageId,'package-b');assert.equal(payload.metadata.workflow,null);
  assert.deepEqual(payload.metadata.workTags,['B']);assert.equal(payload.metadata.environment,'B 환경');
  assert.equal(payload.metadata.name,'사용자가 정한 이름');assert.equal(payload.metadata.desc,'직접 다듬은 설명');
  assert.equal(payload.metadata.changes,'');assert.equal('installProfile' in payload.metadata,false);
  assert.equal(payload.metadata.approval,false);assert.equal(payload.target,'new');assert.ok(payload.fileToken);
  await page.locator('#publish-edit').click();
  await select('등록할 기능 유형','Skill');
  const before=await page.evaluate(()=>requests.filter(r=>r.action==='preparePublish').length);
  await page.locator('#publish-prepare').click();await ready();
  assert.match(await page.locator('#publish-message').innerText(),/선택한 ZIP의 값/);
  assert.equal(await page.evaluate(()=>requests.filter(r=>r.action==='preparePublish').length),before);
  await page.locator('#publish-file-reapply').click();
  assert.equal((await fields()).name,'B 도구');assert.equal((await fields()).type,'MCP/Tool');
  assert.equal((await fields()).org,'org');assert.equal(await page.locator('input[name=publish-visibility][value=public]').isChecked(),true);
  await page.locator('#publish-desc').fill('오류가 나도 보존할 설명');
  await page.evaluate(()=>window.inspectFail=true);await pick('A');
  assert.equal((await fields()).desc,'오류가 나도 보존할 설명');
  assert.equal(await page.locator('#publish-file-reapply').isVisible(),false);
  await page.locator('#publish-prepare').click();await ready();assert.match(await page.locator('#publish-message').innerText(),/배포할 파일을 선택/);
  assert.equal(await page.evaluate(()=>requests.filter(r=>r.action==='preparePublish').length),before);
  await page.evaluate(()=>window.inspectFail=false);await pick('plain');
  assert.equal((await fields()).name,'');assert.equal((await fields()).guide,'');assert.equal((await fields()).platform,'');
  assert.equal((await fields()).desc,'오류가 나도 보존할 설명');
  assert.match(await page.locator('#publish-message').innerText(),/배포 정보가 없는 파일/);

  for(const order of ['file-first','existing-first']){
   await fixture();
   if(order==='file-first')await pick('B');
   await select('등록 방식','내 도구의 새 버전 등록');await select('기존 도구','기존 보고서 도구');await ready();
   if(order==='existing-first')await pick('B');
   assert.equal((await fields()).platform,'ChatGPT');assert.equal((await fields()).type,'MCP/Tool');
   assert.equal(await page.locator('#publish-install-info').isVisible(),false);
   const update=await prepare();assert.equal(update.target,'update');assert.equal(update.toolId,41);
   assert.equal(update.metadata.packageId,'package-b');assert.equal(update.metadata.type,'MCP/Tool');
   assert.equal(update.metadata.approval,true);assert.equal('installProfile' in update.metadata,false);
  }
  await fixture();await pick('A');await required();
  await select('배포 방법','웹 주소 · 원격 연결 안내');await page.locator('#publish-url').fill('https://docs.example.test/');
  const urlPayload=await prepare();assert.equal('fileToken' in urlPayload,false);
  for(const key of ['packageId','installProfile','workflow','workTags','environment'])assert.equal(key in urlPayload.metadata,false);
  await page.locator('#publish-edit').click();await select('배포 방법','배포 파일');
  const filePayload=await prepare();assert.equal(filePayload.metadata.packageId,'package-a');assert.equal(filePayload.metadata.installProfile.kind,'skill');assert.ok(filePayload.fileToken);
  await fixture();await pick('A');await select('사용 프로그램','기타');await pick('plain');
  assert.equal((await fields()).platform,'기타');await pick('B');assert.equal((await fields()).platform,'ChatGPT');
  await fixture();await page.locator('#publish-name').fill('처음부터 작성한 이름');await pick('A');
  assert.equal((await fields()).name,'처음부터 작성한 이름');
  await page.locator('#publish-guide').fill('');await pick('B');assert.equal((await fields()).guide,'');
  assert.deepEqual(errors,[]);
  await page.locator('.publish-scroll').evaluate(node=>node.scrollTop=0);
  await page.screenshot({path:path.join(output,'autofill-preserves-draft.png'),animations:'disabled'});
  await page.evaluate(()=>document.documentElement.dataset.theme='dark');
  await page.screenshot({path:path.join(output,'autofill-preserves-draft-dark.png'),animations:'disabled'});
  const report={passed:true,cases:['first ZIP autofill','organization and visibility remain explicit','manual draft before/after import preserved','A to B changes missing fields and artifact extras','cancel and reopen preserve file/draft','invalid ZIP revokes old token and preserves draft','plain file clears derived values and keeps manual identity','identity mismatch blocked before upload','explicit reapply','existing tool before/after ZIP','file to URL strips hidden file metadata and switch back restores it'],pageErrors:errors};
  fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));process.stdout.write(JSON.stringify(report));
 }finally{
  const pid=server.process()?.pid;
  if(pid)require('node:child_process').spawnSync('taskkill.exe',['/PID',String(pid),'/T','/F'],{windowsHide:true,timeout:10000,stdio:'ignore'});
  await Promise.race([server.close().catch(()=>{}),new Promise(resolve=>setTimeout(resolve,1500))]);
 }
})().then(()=>process.exit(0),error=>{console.error(error);process.exit(1);});
