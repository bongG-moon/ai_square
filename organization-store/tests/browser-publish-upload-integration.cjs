// Sandboxed extension iframe using the production AX Workspace message host;
// server and upload sink are synthetic, so no files, keys or network are published.
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const root=path.resolve(__dirname,'../..'), source=path.join(root,'organization-store');
const app=process.env.AX_WORKSPACE_SOURCE||path.join(root,'build/workspace-local-repository');
const host=fs.readFileSync(path.join(app,'local_app/web/extensions.js'),'utf8');
const ui=fs.readFileSync(path.join(source,'ui/index.html'),'utf8')
 .replace('<!--STORE_STYLE-->','<style>'+fs.readFileSync(path.join(source,'ui/store.css'),'utf8')+'</style>')
 .replace('<!--STORE_SCRIPT-->','<script>'+fs.readFileSync(path.join(source,'ui/store.js'),'utf8')+'</script>');
(async()=>{
 const browser=await chromium.launch({executablePath:path.join(process.env['ProgramFiles(x86)']||'C:/Program Files (x86)','Microsoft/Edge/Application/msedge.exe'),headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:980}});page.setDefaultTimeout(10000);
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.route('http://127.0.0.1:17360/**',route=>{
   const u=new URL(route.request().url());
   if(u.pathname==='/extension-ui/pt-ai-square.store')return route.fulfill({status:200,contentType:'text/html',body:ui});
   if(u.pathname==='/')return route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><html><head></head><body><div class="app"><nav class="primary-nav"></nav><div id="work-area"></div></div></body></html>'});
   return route.fulfill({status:404,body:''});
  });
  await page.goto('http://127.0.0.1:17360/');await page.addScriptTag({content:host});
  await page.evaluate(()=>{
   window.calls=[];window.uploaded=null;
   const ext={id:'pt-ai-square.store',name:'P&T AI Square',version:'0.1.0',hostApi:1,actions:['status','options','catalog','publishOptions','inspectPublishSource']};
   WorkspaceExtensions.mount({extensions:[ext],isClosed:()=>false,getContext:()=>({kind:'work',workspace:'C:\\dummy',sessionId:'s',title:'검증 업무'}),
    uploadFile:async(id,file)=>{window.uploaded={id,name:file.name,size:file.size,text:await file.text(),fileInstance:file instanceof File};return {cancelled:false,fileToken:'a'.repeat(43),name:file.name,size:file.size};},
    api:async(route,payload)=>{
     if(route.endsWith('/view'))return {url:'/extension-ui/pt-ai-square.store?ticket=synthetic'};
     if(!route.endsWith('/action'))throw Error('Unexpected route');
     window.calls.push({action:payload.action,fileToken:payload.fileToken});
     const data={status:{configured:true,baseUrl:'https://square.example.test'},options:{organizations:[]},catalog:{items:[],total:0},publishOptions:{canPublish:true,options:{organizations:[],categories:[]},candidates:[]},inspectPublishSource:{source:{name:'weekly.zip',bytes:7},metadata:{name:'테스트 스킬',packageId:'test-package'}}}[payload.action];
     if(!data)throw Error('Unexpected action '+payload.action);
     return {ok:true,result:data};
    }});
  });
  await page.locator('.workspace-extension-menu').click();
  const frame=page.frameLocator('.workspace-extension-frame');
  await frame.locator('#publish-open').waitFor({state:'visible'});await frame.locator('#publish-open').click();
  await frame.locator('#publish-pick-file').waitFor({state:'visible'});
  await frame.locator('#publish-file-panel').evaluate(node=>{const transfer=new DataTransfer();transfer.items.add(new File(['example'],'weekly.zip',{type:'application/zip'}));node.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}));});
  await frame.locator('#publish-file-name').filter({hasText:'weekly.zip'}).waitFor();
  assert.deepEqual(await page.evaluate(()=>window.uploaded),{id:'pt-ai-square.store',name:'weekly.zip',size:7,text:'example',fileInstance:true});
  assert.ok(await page.evaluate(()=>window.calls.some(row=>row.action==='inspectPublishSource'&&row.fileToken==='a'.repeat(43))));
  assert.equal(await frame.locator('#publish-name').inputValue(),'테스트 스킬');assert.deepEqual(errors,[]);
  console.log('PASS: actual AX Workspace iframe host transferred dropped File and inspection token; synthetic worker/upload sink.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
