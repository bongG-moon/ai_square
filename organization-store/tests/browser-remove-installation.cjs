// Real Edge with a synthetic extension host; never touches user records or a real server.
const assert=require('node:assert/strict'), fs=require('node:fs'), path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(require('node:os').homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const source=path.resolve(__dirname,'..'), root=path.dirname(source);
const html=fs.readFileSync(path.join(source,'ui/index.html'),'utf8').replace('<!--STORE_STYLE-->','<style>'+fs.readFileSync(path.join(source,'ui/store.css'),'utf8')+'</style>');
const script=fs.readFileSync(path.join(source,'ui/store.js'),'utf8');
(async()=>{
 const browser=await chromium.launch({executablePath:path.join(process.env['ProgramFiles(x86)']||'C:/Program Files (x86)','Microsoft/Edge/Application/msedge.exe'),headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1100,height:900}});page.setDefaultTimeout(7000);
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  async function fixture(){
   await page.goto('about:blank');await page.setContent(html);
   await page.evaluate(()=>{
    window.requests=[];window.holdRemove=false;window.deleted=[];
    window.records=[{installationId:'one',recordDigest:'a'.repeat(64),toolId:1,name:'보고서 도구',release:1,scope:'project',target:'C:/demo/a',status:'installed'},
      {installationId:'two',recordDigest:'b'.repeat(64),toolId:1,name:'보고서 도구',release:1,scope:'user',target:'C:/demo/b',status:'installed'}];
    window.addEventListener('message',event=>{
     const msg=event.data;if(msg.type==='ax-extension-ready')return window.postMessage({type:'ax-extension-init',channel:'remove-fixture',hostFeatures:[],context:{}},'*');
     if(msg.type!=='ax-extension-request')return;window.requests.push(msg);
     const send=result=>window.postMessage({type:'ax-extension-response',channel:msg.channel,requestId:msg.requestId,ok:true,result},'*');
     if(msg.action==='status')return send({configured:true,baseUrl:'https://square.example.test'});
     if(msg.action==='options')return send({organizations:[],categories:[]});
     if(msg.action==='catalog')return send({items:[{id:1,name:'보고서 도구',type:'Skill',access:'approved',likes:3}],total:1});
     if(msg.action==='installations')return send({items:window.records.filter(r=>!window.deleted.includes(r.installationId)),recovery:{recovered:[],blocked:[]}});
     if(msg.action==='checkUpdates')return send({items:window.records.filter(r=>!window.deleted.includes(r.installationId)).map(r=>({...r,updateAvailable:true,result:{toolId:1,installedRelease:1,activeRelease:2,status:'update_available'}})),summary:{},complete:true});
     if(msg.action==='detail')return send({item:{id:1,name:'보고서 도구',type:'Skill',access:'approved',likes:3},manifest:{},canInstall:false});
     if(msg.action==='like')return send({liked:msg.payload.liked,count:msg.payload.liked?4:3});
     if(msg.action==='removeInstallationRecord'){
       const complete=()=>{window.deleted.push(msg.payload.installationId);send({removed:true,installationId:msg.payload.installationId});};
       if(window.holdRemove)window.releaseRemove=complete;else complete();return;
     }
     send({});
    });
   });
   await page.addScriptTag({content:script});await page.locator('.catalog-card').first().waitFor();
  }
  const tab=name=>page.locator(`[data-tab="${name}"]`), row=id=>page.locator(`[data-installation-id="${id}"]`);
  await fixture();await page.locator('.catalog-card .tool-title').click();await page.getByRole('button',{name:/좋아요/}).click();
  await page.getByRole('button',{name:/좋아요 4/}).waitFor();assert.deepEqual(await page.evaluate(()=>requests.find(r=>r.action==='like').payload),{toolId:1,liked:true});
  await page.locator('#detail-close').click();await tab('installed').click();await row('one').waitFor();
  await row('one').getByRole('button',{name:'목록에서 제거'}).click();assert.match(await page.locator('#confirm-content').innerText(),/파일과 연결 설정은 그대로/);
  await page.locator('#confirm-no').click();assert.equal(await page.evaluate(()=>requests.filter(r=>r.action==='removeInstallationRecord').length),0);
  await row('one').getByRole('button',{name:'목록에서 제거'}).click();await page.locator('#confirm-yes').click();
  await row('one').waitFor({state:'detached'});assert.equal(await row('two').count(),1);
  assert.deepEqual(await page.evaluate(()=>requests.find(r=>r.action==='removeInstallationRecord').payload),{installationId:'one',recordDigest:'a'.repeat(64),confirmed:true});
  await tab('updates').click();await row('two').waitFor();assert.equal(await row('one').count(),0);
  // A delayed removal must not drag the user back to the installed tab.
  await fixture();await tab('installed').click();await row('one').waitFor();await page.evaluate(()=>window.holdRemove=true);
  await row('one').getByRole('button',{name:'목록에서 제거'}).click();await page.locator('#confirm-yes').click();await page.waitForFunction(()=>typeof window.releaseRemove==='function');
  await tab('catalog').click();await page.evaluate(()=>window.releaseRemove());await page.locator('.catalog-card').first().waitFor();
  assert.equal(await tab('catalog').getAttribute('aria-current'),'page');assert.equal(await row('one').count(),0);
  assert.deepEqual(errors,[]);console.log('PASS: likes, cancel, confirmed list removal, independent scope, updates and late response');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
