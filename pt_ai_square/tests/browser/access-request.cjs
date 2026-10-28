// Actual served web bundle + Edge, with all traffic fulfilled in memory.
// No real users, keys, permissions, server changes or notification delivery.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(require('node:os').homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const root=path.resolve(__dirname,'../..'),out=path.resolve(root,'../outputs/web-access-ui-20261028');
fs.mkdirSync(out,{recursive:true});
const html=fs.readFileSync(path.join(root,'templates/index.html'),'utf8').replace(/{% if config\['DATA_MODE'\] != 'dummy' %}[\s\S]*?{% endif %}/,'');
(async()=>{
 const service=await chromium.launchServer({executablePath:path.join(process.env['ProgramFiles(x86)']||'C:/Program Files (x86)','Microsoft/Edge/Application/msedge.exe'),headless:true});
 const browser=await chromium.connect(service.wsEndpoint());
 try{
  const page=await browser.newPage({viewport:{width:1280,height:960}});page.setDefaultTimeout(8000);
  const errors=[],calls=[],held=[];page.on('pageerror',e=>errors.push(e.message));
  let mode='normal',hold=false,attempt=0;
  const item={id:1,name:'업무 보고서 작성',desc:'업무 폴더의 자료를 확인하고 보고서 초안을 작성합니다.',owner:'기능 담당자',registrantName:'등록자',org:'업무 혁신팀',category:'공통 업무',platform:'Claude',type:'Skill',icon:'file-text',access:'none',approval:true,requestStatus:'none',requestRevision:null,canCancel:false,likes:2,liked:false,downloads:3,views:5,created:1,editorial:1,rankScore:1,totalRankScore:1,visibility:'전체 공개',comments:[],versions:[],active:1};
  const bootstrap=()=>({csrf:'test-csrf',user:{id:'synthetic-member',name:'테스트 사용자',org:'업무 혁신팀',role:'user'},items:[item],organizations:[{name:'업무 혁신팀',enabled:true}],categories:[{name:'공통 업무',enabled:true}],requests:[],audit:[],policy:{keep:3,days:90},dataMode:'mongo',authMode:'sso',rankAsOf:1,unread:0});
  const status=()=>({ok:true,toolId:1,access:item.access,requestStatus:item.requestStatus,requestRevision:item.requestRevision,canCancel:item.canCancel});
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url()),method=route.request().method(),json=(body,statusCode=200)=>route.fulfill({status:statusCode,contentType:'application/json',body:JSON.stringify(body)});
   if(url.origin!=='http://127.0.0.1:17359')return route.fulfill({status:404,body:''});
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:html});
   if(url.pathname.startsWith('/static/')){
    const file=path.join(root,url.pathname.slice(1));if(!file.startsWith(path.join(root,'static')+path.sep)||!fs.existsSync(file))return route.fulfill({status:404,body:''});
    return route.fulfill({contentType:({'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.woff':'font/woff','.woff2':'font/woff2'})[path.extname(file)]||'application/octet-stream',body:fs.readFileSync(file)});
   }
   calls.push({url:url.pathname,method,body:route.request().postDataJSON()});
   if(url.pathname==='/api/bootstrap')return json(bootstrap());
   if(url.pathname==='/api/tools/1')return json({error:'Approval required'},403);
   if(url.pathname==='/api/notifications')return json({notifications:[],unread:0});
   if(url.pathname==='/api/tools/1/access-status')return json(status());
   if(url.pathname==='/api/tools/1/requests'&&method==='POST'){
    if(mode==='request-unknown')return json({error:'synthetic failure'},503);
    Object.assign(item,{access:'pending',requestStatus:'pending',requestRevision:String(++attempt).padStart(32,'0'),canCancel:true});
    const finish=()=>json(status());if(hold){held.push(finish);return;}return finish();
   }
   if(url.pathname==='/api/tools/1/requests/cancel'&&method==='POST'){
    assert.equal(route.request().postDataJSON().expectedRevision,item.requestRevision);
    if(mode==='cancel-unknown')return json({error:'synthetic failure'},503);
    Object.assign(item,{access:'none',requestStatus:'cancelled',canCancel:false});
    const finish=()=>json({...status(),cancelled:true});if(hold){held.push(finish);return;}return finish();
   }
   return json({error:'Unknown fixture endpoint'},404);
  });
  await page.goto('http://127.0.0.1:17359/');
  await page.locator('[data-action="detail"][data-id="1"]').first().click();
  await page.getByRole('button',{name:'권한 신청하기',exact:true}).click();
  await page.locator('#sq-access-form textarea').fill('보고서 작성에 활용합니다.');hold=true;
  await page.getByRole('button',{name:'신청하기',exact:true}).click();
  await page.getByRole('button',{name:'신청 중…',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'신청 중…',exact:true}).isDisabled(),true);
  assert.equal(calls.filter(c=>c.url.endsWith('/requests')&&c.method==='POST').length,1);
  await page.screenshot({path:path.join(out,'01-request-sending.png')});await held.shift()();hold=false;
  await page.getByRole('button',{name:'신청 취소',exact:true}).waitFor();
  await page.screenshot({path:path.join(out,'02-pending.png')});
  await page.getByRole('button',{name:'신청 취소',exact:true}).click();
  await page.locator('#sq-confirm').waitFor();hold=true;await page.locator('#sq-confirm-go').click();
  await page.getByRole('button',{name:'취소 중…',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'취소 중…',exact:true}).isDisabled(),true);
  await page.screenshot({path:path.join(out,'03-cancelling.png')});await held.shift()();hold=false;
  await page.getByRole('button',{name:'권한 신청하기',exact:true}).waitFor();
  assert.match(await page.locator('#sq-dialog-body').innerText(),/신청을 취소했어요/);
  await page.screenshot({path:path.join(out,'04-cancelled.png')});
  // Uncertain request must not offer a duplicate write before a read confirms none.
  mode='request-unknown';await page.getByRole('button',{name:'권한 신청하기',exact:true}).click();
  await page.locator('#sq-access-form textarea').fill('다시 필요한 사유');await page.getByRole('button',{name:'신청하기',exact:true}).click();
  await page.getByRole('button',{name:'신청 상태 확인',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'권한 신청하기',exact:true}).count(),0);
  await page.getByRole('button',{name:'신청 상태 확인',exact:true}).click();
  await page.getByRole('button',{name:'권한 신청하기',exact:true}).click();
  assert.equal(await page.locator('#sq-access-form textarea').inputValue(),'다시 필요한 사유');
  // Reapply and uncertain cancellation retains pending only after a read confirms it.
  mode='normal';await page.getByRole('button',{name:'신청하기',exact:true}).click();
  await page.getByRole('button',{name:'신청 취소',exact:true}).click();mode='cancel-unknown';await page.locator('#sq-confirm-go').click();
  await page.getByRole('button',{name:'신청 상태 확인',exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'신청 취소',exact:true}).count(),0);
  await page.getByRole('button',{name:'신청 상태 확인',exact:true}).click();
  await page.getByRole('button',{name:'신청 취소',exact:true}).waitFor();
  assert.equal(calls.filter(c=>c.url.endsWith('/requests')&&c.method==='POST').length,3);
  assert.equal(calls.filter(c=>c.url.endsWith('/requests/cancel')).length,2);
  assert.deepEqual(errors,[]);console.log(JSON.stringify({ok:true,requests:3,cancels:2,readOnlyReconciliations:2,pageErrors:errors.length,screenshots:out}));
 }finally{await browser.close();await service.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
