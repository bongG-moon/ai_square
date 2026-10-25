// Exercise the maintained AX Workspace handlers with controlled network completion.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_ax_workspace.js'),'utf8');
const shared=fs.readFileSync(path.join(__dirname,'../frontend/frontend_workspace.js'),'utf8');
const afterSave=shared.slice(shared.indexOf('async function afterWorkspaceSave('),shared.indexOf('const originalRender='));
const tick=()=>new Promise(setImmediate);
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
const item={id:'a'.repeat(32),name:'AX Workspace 설치',description:'업무 공간을 설치합니다.',category:'workspace',version:'1.0.0',fileName:'workspace.zip',size:120,created:1,downloadUrl:'/api/ax-workspace/'+ 'a'.repeat(32)+'/download'};

function setup(role='admin'){
 const requests=[],errors=[],announcements=[],opened=[],listeners={};
 const workspace={innerHTML:''},dialog={open:false},area={outerHTML:''},pageError={hidden:true,textContent:'',isConnected:true};
 let currentForm=null;
 class FormData{
  constructor(form){this.values=form?[...form.entries]:[];}
  append(key,value){this.values.push([key,value]);}
  [Symbol.iterator](){return this.values[Symbol.iterator]();}
 }
 const context={runtime:{detailLoadToken:0},state:{route:'ax'},server:{user:{id:'admin',role}},workspace,FormData,
  actions:{},root:{addEventListener:(name,fn)=>(listeners[name]??=[]).push(fn)},
  $:selector=>selector==='#sq-dialog'?dialog:selector==='#sq-ax-form'?currentForm:selector==='[data-ax-drop]'?area:selector==='#sq-server-error'?pageError:null,
  $$:()=>[],esc:value=>String(value).replace(/</g,'&lt;').replace(/"/g,'&quot;'),icon:()=>'',mountIcons(){},
  button:(action,label,cls='',extra='')=>`<button data-action="${action}" ${extra}>${label}</button>`,
  badge:value=>String(value),blank:()=>'<p>Empty</p>',dated:()=>'',fileSize:bytes=>`${bytes} bytes`,
  openModal(title,kicker,html){context.runtime.detailLoadToken++;dialog.open=true;opened.push({title,html});},
  closeModal(){context.runtime.detailLoadToken++;dialog.open=false;},
  navigate(route){context.runtime.detailLoadToken++;context.state.route=route;},
  announce:message=>announcements.push(message),showError:error=>errors.push(error),clearErrorMessages(){},
  requestAPI:(url,method='GET',body)=>{const pending=deferred();requests.push({...pending,url,method,body});return pending.promise;},
 };
 vm.createContext(context);vm.runInContext(afterSave+'\n'+source,context,{filename:'frontend_ax_workspace.js'});
 function newForm(){
  context.actions['ax-register']();
  const controls=[{disabled:false},{disabled:false}];
  const node={id:'sq-ax-form',dataset:{},isConnected:true,
   entries:[['name',item.name],['description',item.description],['category',item.category],['version',item.version]],
   querySelectorAll:()=>controls};
  currentForm=node;
  const file={name:item.fileName,size:item.size};context.chooseAxFile([file]);
  return {node,controls,file,submit:()=>listeners.submit[0]({target:node,preventDefault(){},stopImmediatePropagation(){}})};
 }
 return {context,requests,errors,announcements,opened,listeners,workspace,dialog,pageError,newForm,
  value:expression=>vm.runInContext(expression,context)};
}

test('only administrators see registration controls; download data is escaped',()=>{
 for(const role of ['admin','member']){
  const h=setup(role);h.context.renderAxWorkspace();
  assert.equal(h.workspace.innerHTML.includes('data-action="ax-register"'),role==='admin');
  h.context.actions['ax-register']();assert.equal(h.opened.length,role==='admin'?1:0);
 }
 const h=setup();vm.runInContext(`axFiles=[${JSON.stringify({...item,name:'<img src=x onerror=alert(1)>',description:'<script>bad</script>'})}];`,h.context);
 h.context.renderAxWorkspace();assert.ok(!h.workspace.innerHTML.includes('<script>'));assert.ok(!h.workspace.innerHTML.includes('<img src=x'));
 assert.ok(h.workspace.innerHTML.includes('&lt;script>'));
});

test('optional Square extension stays separate from administrator-published app files',()=>{
 const h=setup('member');
 vm.runInContext(`axFiles=[${JSON.stringify(item)}];`,h.context);
 h.context.renderAxWorkspace();
 assert.match(h.workspace.innerHTML,/href="\/local-access\/workspace-extension\.zip" download/);
 assert.match(h.workspace.innerHTML,/개인 KEY만 입력/);
 assert.match(h.workspace.innerHTML,/href="\/local-access">KEY와 연결 안내/);
 assert.ok(h.workspace.innerHTML.includes(item.downloadUrl));
 assert.match(h.workspace.innerHTML,/ws-ax-count">1개 파일/);
 h.context.actions['ax-filter']({dataset:{category:'plugin'}});
 assert.match(h.workspace.innerHTML,/P&T AI Square 확장 받기/);
 assert.match(h.workspace.innerHTML,/ws-ax-count">0개 파일/);
 assert.equal(h.requests.length,0);
});

test('successful upload preserves multipart contract and shows the new file despite an earlier filter',async()=>{
 const h=setup();h.context.actions['ax-filter']({dataset:{category:'plugin'}});const form=h.newForm();
 form.submit();form.submit();assert.equal(h.requests.length,1);assert.ok(form.controls.every(x=>x.disabled));
 assert.equal(h.requests[0].url,'/api/ax-workspace');assert.equal(h.requests[0].method,'POST');
 assert.deepEqual(JSON.parse(h.requests[0].body.values.find(([name])=>name==='metadata')[1]),Object.fromEntries(form.node.entries));
 assert.equal(h.requests[0].body.values.find(([name])=>name==='file')[1],form.file);
 h.requests[0].resolve({file:item,followupsPending:false});await tick();
 assert.equal(h.dialog.open,false);assert.equal(form.node.dataset.saved,'true');assert.equal(h.requests.length,2);
 h.requests[1].resolve({files:[item],canManage:true,maxFileBytes:128*1048576-65536});await tick();
 assert.match(h.workspace.innerHTML,/AX Workspace 설치/);assert.match(h.workspace.innerHTML,/workspace\.zip/);
 assert.deepEqual(h.announcements,['배포 파일을 등록했습니다.']);assert.equal(h.errors.length,0);
 form.submit();assert.equal(h.requests.length,2);
});

test('failed upload keeps the draft and selection for retry',async()=>{
 const h=setup(),form=h.newForm();form.submit();const failure=Error('upload failed');h.requests[0].reject(failure);await tick();
 assert.deepEqual(h.errors,[failure]);assert.equal(h.dialog.open,true);assert.equal(form.node.dataset.saved,undefined);
 assert.ok(form.controls.every(x=>!x.disabled));assert.equal(h.value('axFile'),form.file);
 form.submit();assert.equal(h.requests.length,2);h.requests[1].reject(failure);await tick();
});

test('late upload failure cannot report into a newer modal',async()=>{
 const h=setup(),form=h.newForm();form.submit();h.context.closeModal();h.context.openModal('새 팝업','', 'new');
 h.requests[0].reject(Error('old upload failed'));await tick();
 assert.equal(h.dialog.open,true);assert.equal(h.opened.at(-1).title,'새 팝업');assert.deepEqual(h.errors,[]);
});

test('late successful upload cannot dismiss a newer modal',async()=>{
 const h=setup(),form=h.newForm();form.submit();h.context.closeModal();h.context.openModal('새 팝업','', 'new');
 h.requests[0].resolve({file:item});await tick();
 assert.equal(h.dialog.open,true);assert.equal(h.requests.length,1);assert.equal(form.node.dataset.saved,'true');assert.deepEqual(h.announcements,[]);
});

test('current list failure after a successful upload reports saved status and prevents duplicate submit',async()=>{
 const h=setup(),form=h.newForm();form.submit();h.requests[0].resolve({file:item});await tick();
 h.requests[1].reject(Error('list unavailable'));await tick();
 assert.equal(form.node.dataset.saved,'true');assert.equal(h.dialog.open,false);assert.equal(h.errors.length,1);
 assert.equal(h.errors[0].saved,true);assert.match(h.errors[0].message,/서버에 저장되었습니다/);
 form.submit();assert.equal(h.requests.length,2);
});

test('late list failure after saved upload cannot replace a newer dialog with an error',async()=>{
 const h=setup(),form=h.newForm();form.submit();h.requests[0].resolve({file:item});await tick();
 h.context.openModal('다른 작업','', 'new');h.requests[1].reject(Error('old list failure'));await tick();
 assert.equal(h.dialog.open,true);assert.deepEqual(h.errors,[]);assert.deepEqual(h.announcements,[]);
});

test('late catalog navigation error is ignored after moving to another route',async()=>{
 const h=setup();const navigation=Promise.resolve(h.context.actions['ax-workspace']()).catch(h.context.showError);
 h.context.navigate('ideas');h.requests[0].reject(Error('old catalog failure'));await navigation;
 assert.equal(h.context.state.route,'ideas');assert.deepEqual(h.errors,[]);
});

test('file picker uses server size configuration instead of a hardcoded installer cap',async()=>{
 const h=setup(),pending=h.context.loadAxWorkspace(),maximum=256*1048576-65536;
 h.requests[0].resolve({files:[],canManage:true,maxFileBytes:maximum});await pending;
 h.context.chooseAxFile([{name:'large-installer.exe',size:200*1048576}]);
 assert.throws(()=>h.context.chooseAxFile([{name:'too-large.exe',size:maximum+1}]));
 assert.equal(h.value('axFile').name,'large-installer.exe');
});
