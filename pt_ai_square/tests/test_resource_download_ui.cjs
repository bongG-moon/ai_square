const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_api.js'),'utf8');
const handler=source.slice(source.indexOf("actions['download-skill']="),source.indexOf("actions['download-guide']="));
const guideHandler=source.slice(source.indexOf("actions['download-guide']="),source.indexOf('actions.fullscreen='));

function fixture({status=200,mime='application/zip',failure=null,action='download-skill'}={}){
 const requests=[],downloads=[];
 const context={actions:{},Error,
  location:{assign(){assert.fail('A failed resource request must not replace the page with JSON');}},
  fetch:async(url,options)=>{requests.push({url,options});if(failure)throw failure;return {ok:status>=200&&status<300,status,headers:{get:()=>mime}};},
  document:{createElement(tag){assert.equal(tag,'a');return {click(){downloads.push({url:this.href,name:this.download});}};}}
 };
 vm.createContext(context);vm.runInContext(action==='download-guide'?guideHandler:handler,context);
 return {run:()=>context.actions[action](),requests,downloads};
}

for(const mime of ['application/zip','application/x-zip-compressed','application/octet-stream','APPLICATION/ZIP; charset=binary']){
 test(`Skill download preflights an ASCII route and saves a ZIP (${mime})`,async()=>{
  const h=fixture({mime});await h.run();
  assert.deepEqual(h.downloads,[{url:'/resources/distribution-skill.zip',name:'pt-file-distribution.zip'}]);
  assert.equal(h.requests.length,1);assert.equal(h.requests[0].url,'/resources/distribution-skill.zip');
  const options=h.requests[0].options;
  assert.equal(options.method,'HEAD');assert.equal(options.credentials,'same-origin');
  assert.equal(options.redirect,'error');assert.equal(options.cache,'no-store');
 });
}

for(const status of [404,500,503]){
 test(`missing or unavailable Skill stays in the modal with actionable error (${status})`,async()=>{
  const h=fixture({status});await assert.rejects(h.run(),/최신 배포 파일/);
  assert.equal(h.downloads.length,0);
 });
}

for(const status of [401,403]){
 test(`authentication failure gives a login explanation (${status})`,async()=>{
  const h=fixture({status});await assert.rejects(h.run(),/로그인 상태/);assert.equal(h.downloads.length,0);
 });
}

test('network and redirect failure does not expose raw exceptions or navigate',async()=>{
 const h=fixture({failure:Error('private upstream detail')});
 await assert.rejects(h.run(),error=>/서버 연결과 로그인 상태/.test(error.message)&&!error.message.includes('private'));
 assert.equal(h.downloads.length,0);
});

for(const mime of ['text/html','application/json','']){
 test(`a success page cannot be saved as the Skill ZIP (${mime||'missing type'})`,async()=>{
  const h=fixture({mime});await assert.rejects(h.run(),/다운로드 파일 대신/);assert.equal(h.downloads.length,0);
 });
}

test('the served JS contains the same maintained download handler',()=>{
 const served=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
 assert.ok(served.includes(handler.trim()));
 assert.doesNotMatch(served,/location\.assign\('\/static\/guides\/PT_AI_SQUARE_파일배포_Skill\.zip'\)/);
});

test('the public user guide uses an ASCII URL and download filename',async()=>{
 const h=fixture({action:'download-guide',mime:'text/html; charset=utf-8'});await h.run();
 assert.deepEqual(h.downloads,[{url:'/static/guides/pt-ai-square-user-guide.html',name:'pt-ai-square-user-guide.html'}]);
 assert.equal(h.requests.length,1);assert.equal(h.requests[0].options.method,'HEAD');
 assert.equal(h.requests[0].options.redirect,'error');assert.equal(h.requests[0].options.cache,'no-store');
});

for(const status of [404,500,503]){
 test(`unavailable user guide reports deployment problem without downloading an error (${status})`,async()=>{
  const h=fixture({action:'download-guide',status,mime:'application/json'});
  await assert.rejects(h.run(),/등록 가이드.*최신 배포 파일/);assert.equal(h.downloads.length,0);
 });
}

for(const status of [401,403]){
 test(`user guide authentication failure stays on the page (${status})`,async()=>{
  const h=fixture({action:'download-guide',status});await assert.rejects(h.run(),/로그인 상태/);
  assert.equal(h.downloads.length,0);
 });
}

test('user guide network or redirect failure does not expose raw details',async()=>{
 const h=fixture({action:'download-guide',failure:Error('private upstream detail')});
 await assert.rejects(h.run(),error=>/등록 가이드.*서버 연결/.test(error.message)&&!error.message.includes('private'));
 assert.equal(h.downloads.length,0);
});

test('a JSON error response cannot be saved as the user guide',async()=>{
 const h=fixture({action:'download-guide',mime:'application/json'});
 await assert.rejects(h.run(),/등록 가이드 대신/);assert.equal(h.downloads.length,0);
});

test('served guide handler matches source and contains no old Korean guide URL',()=>{
 const served=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
 assert.ok(served.includes(guideHandler.trim()));
 assert.doesNotMatch(served,/\/static\/guides\/PT_AI_SQUARE_등록가이드\.html/);
});
