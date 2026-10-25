// Exercise the maintained AX Workspace handlers with controlled network completion.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_ax_workspace.js'),'utf8');
const shared=fs.readFileSync(path.join(__dirname,'../frontend/frontend_workspace.js'),'utf8');
const afterSave=shared.slice(shared.indexOf('async function afterWorkspaceSave('),shared.indexOf('const originalRender='));
const api=fs.readFileSync(path.join(__dirname,'../frontend/frontend_api.js'),'utf8');
const bootstrapRefresh=api.slice(api.indexOf('async function refresh('),api.indexOf('async function mutate('));
const people=fs.readFileSync(path.join(__dirname,'../frontend/frontend_people.js'),'utf8');
const peopleRefresh=people.slice(people.indexOf('refresh=async function(){'),people.indexOf("actions['rank-mode']="));
const tick=()=>new Promise(setImmediate);
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
const item={id:'a'.repeat(32),name:'AX Workspace 설치',description:'업무 공간을 설치합니다.',category:'workspace',version:'1.0.0',fileName:'workspace.zip',size:120,created:1,downloadUrl:'/api/ax-workspace/'+ 'a'.repeat(32)+'/download'};

function setup(role='admin',{search='',route='ax'}={}){
 const requests=[],errors=[],announcements=[],opened=[],listeners={};
 const workspace={innerHTML:''},dialog={open:false},area={outerHTML:''},pageError={hidden:true,textContent:'',isConnected:true};
 let currentForm=null;
 class FormData{
  constructor(form){this.values=form?[...form.entries]:[];}
  append(key,value){this.values.push([key,value]);}
  [Symbol.iterator](){return this.values[Symbol.iterator]();}
 }
 const session={},demo={},logout={},catalogRequests=[];
 const context={runtime:{detailLoadToken:0},state:{route,rankMode:'recent'},server:{user:{id:'admin',role}},workspace,FormData,
  location:{search},URLSearchParams,items:[],organizations:[],requests:catalogRequests,policy:{},audit:[],render(){},loadPeopleRanks:async()=>{},
  actions:{},root:{addEventListener:(name,fn)=>(listeners[name]??=[]).push(fn)},
  $:selector=>selector==='#sq-dialog'?dialog:selector==='#sq-ax-form'?currentForm:selector==='[data-ax-drop]'?area:selector==='#sq-server-error'?pageError:selector==='#sq-session'?session:selector==='.sq-demo'?demo:selector==='[data-action=logout]'?logout:null,
  $$:()=>[],esc:value=>String(value).replace(/</g,'&lt;').replace(/"/g,'&quot;'),icon:()=>'',mountIcons(){},
  button:(action,label,cls='',extra='')=>`<button data-action="${action}" ${extra}>${label}</button>`,
  badge:value=>String(value),blank:(icon,title,body)=>`<div class="ws-empty"><h3>${title}</h3><p>${body}</p></div>`,dated:()=>'',fileSize:bytes=>`${bytes} bytes`,
  openModal(title,kicker,html){context.runtime.detailLoadToken++;dialog.open=true;opened.push({title,html});},
  closeModal(){context.runtime.detailLoadToken++;dialog.open=false;},
  navigate(route){context.runtime.detailLoadToken++;context.state.route=route;},
  announce:message=>announcements.push(message),showError:error=>errors.push(error),clearErrorMessages(){},
  requestAPI:(url,method='GET',body)=>{const pending=deferred();requests.push({...pending,url,method,body});return pending.promise;},
 };
 vm.createContext(context);vm.runInContext(bootstrapRefresh+'\nconst basePeopleRefresh=refresh;\n'+peopleRefresh+'\n'+afterSave+'\n'+source,context,{filename:'frontend_ax_workspace.js'});
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

test('AX catalog displays only administrator-published downloads and normal filtered empty state',()=>{
 const h=setup('member');
 vm.runInContext(`axFiles=[${JSON.stringify(item)}];`,h.context);
 h.context.renderAxWorkspace();
 assert.doesNotMatch(h.workspace.innerHTML,/workspace-extension\.zip|P&T AI Square를 AX Workspace 안에서|P&T AI Square 확장 받기/);
 assert.match(h.workspace.innerHTML,/관리자가 등록한 AX Workspace 설치 파일과 플러그인·연동 도구/);
 assert.equal((h.workspace.innerHTML.match(/ download /g)||[]).length,1);
 assert.ok(h.workspace.innerHTML.includes(item.downloadUrl));
 assert.match(h.workspace.innerHTML,/ws-ax-count">1개 파일/);
 h.context.actions['ax-filter']({dataset:{category:'plugin'}});
 assert.match(h.workspace.innerHTML,/이 분류에 등록된 파일이 없습니다/);
 assert.match(h.workspace.innerHTML,/관리자가 파일을 등록하면/);
 assert.ok(!h.workspace.innerHTML.includes(item.downloadUrl));
 assert.doesNotMatch(h.workspace.innerHTML,/ download[ >]/);
 assert.match(h.workspace.innerHTML,/ws-ax-count">0개 파일/);
 assert.equal(h.requests.length,0);
});

test('empty catalog guides administrators to register without providing a built-in installer',()=>{
 const h=setup();h.context.renderAxWorkspace();
 assert.match(h.workspace.innerHTML,/아직 등록된 파일이 없습니다/);
 assert.match(h.workspace.innerHTML,/파일 등록을 눌러 설치 파일이나 플러그인을 공유하세요/);
 assert.doesNotMatch(h.workspace.innerHTML,/ download[ >]|workspace-extension\.zip/);
});

const bootstrapData=(overrides={})=>({items:[],user:{id:'viewer',name:'사용자',org:'공통',role:'member'},csrf:'test-csrf',authMode:'mock',organizations:[],requests:[],policy:{},rankAsOf:123,audit:[],...overrides});

test('AX deep link waits for bootstrap, loads the catalog, and is consumed once',async()=>{
 const h=setup('member',{search:'?view=ax',route:'home'}),first=h.context.refresh();
 assert.equal(h.context.state.route,'home');assert.equal(h.requests.length,1);assert.equal(h.requests[0].url,'/api/bootstrap');
 h.requests[0].resolve(bootstrapData());await tick();
 assert.equal(h.context.state.route,'ax');assert.equal(h.requests.length,2);assert.equal(h.requests[1].url,'/api/ax-workspace');
 h.requests[1].resolve({files:[item]});await first;
 assert.ok(h.workspace.innerHTML.includes(item.downloadUrl));
 h.context.navigate('ideas');const next=h.context.refresh();h.requests[2].resolve(bootstrapData());await next;
 assert.equal(h.context.state.route,'ideas');assert.equal(h.requests.length,3);
});

test('AX deep link also works for dummy bootstrap with an empty CSRF token',async()=>{
 const h=setup('member',{search:'?view=ax',route:'home'}),loading=h.context.refresh();
 h.requests[0].resolve(bootstrapData({csrf:'',dataMode:'dummy'}));await tick();
 assert.equal(h.context.state.route,'ax');h.requests[1].resolve({files:[]});await loading;
 assert.match(h.workspace.innerHTML,/아직 등록된 파일이 없습니다/);
});

test('unknown, missing, and ambiguous view parameters do not change the initial route',async()=>{
 for(const search of ['', '?view=home','?view=AX','?other=ax','?view=ax&view=home','?view=ax&view=ax']){
  const h=setup('member',{search,route:'home'}),loading=h.context.refresh();
  h.requests[0].resolve(bootstrapData());await loading;
  assert.equal(h.context.state.route,'home',search);assert.equal(h.requests.length,1,search);
 }
});

test('user navigation during bootstrap wins over the requested AX landing view',async()=>{
 for(const returnHome of [false,true]){
  const h=setup('member',{search:'?view=ax',route:'home'}),loading=h.context.refresh();
  h.context.navigate('ideas');if(returnHome)h.context.navigate('home');
  h.requests[0].resolve(bootstrapData());await loading;
  assert.equal(h.context.state.route,returnHome?'home':'ideas');assert.equal(h.requests.length,1);
  const next=h.context.refresh();h.requests[1].resolve(bootstrapData());await next;
  assert.equal(h.context.state.route,returnHome?'home':'ideas');assert.equal(h.requests.length,2);
 }
});

test('a dialog opened while bootstrap is loading is not dismissed by AX deep link',async()=>{
 const h=setup('member',{search:'?view=ax',route:'home'}),loading=h.context.refresh();
 h.context.openModal('사용자가 선택한 화면','','내용');h.requests[0].resolve(bootstrapData());await loading;
 assert.equal(h.dialog.open,true);assert.equal(h.context.state.route,'home');assert.equal(h.requests.length,1);
});

test('failed bootstrap preserves its error and waits for a successful retry before AX loading',async()=>{
 const h=setup('member',{search:'?view=ax',route:'home'}),failure=Error('session unavailable');
 const first=h.context.refresh();h.requests[0].reject(failure);await assert.rejects(first,error=>error===failure);
 assert.equal(h.requests.length,1);assert.equal(h.context.state.route,'home');
 const retry=h.context.refresh();h.requests[1].resolve(bootstrapData());await tick();
 assert.equal(h.requests[2].url,'/api/ax-workspace');h.requests[2].resolve({files:[item]});await retry;
 assert.equal(h.context.state.route,'ax');
});

test('superseded bootstrap cannot activate the AX deep link before current bootstrap succeeds',async()=>{
 const h=setup('member',{search:'?view=ax',route:'home'}),older=h.context.refresh(),newer=h.context.refresh();
 h.requests[0].resolve(bootstrapData());await older;
 assert.equal(h.requests.length,2);assert.equal(h.context.state.route,'home');
 h.requests[1].resolve(bootstrapData());await tick();assert.equal(h.requests[2].url,'/api/ax-workspace');
 h.requests[2].resolve({files:[item]});await newer;
 assert.equal(h.context.state.route,'ax');assert.equal(h.requests.length,3);
});

test('late AX deep-link catalog response cannot replace a later user route',async()=>{
 const h=setup('member',{search:'?view=ax',route:'home'}),loading=h.context.refresh();
 h.requests[0].resolve(bootstrapData());await tick();h.context.navigate('ideas');h.workspace.innerHTML='사용자가 연 화면';
 h.requests[1].resolve({files:[item]});await loading;
 assert.equal(h.context.state.route,'ideas');assert.equal(h.workspace.innerHTML,'사용자가 연 화면');
});

test('catalog failure is reported once without reapplying the initial AX navigation on refresh',async()=>{
 const h=setup('member',{search:'?view=ax',route:'home'}),loading=h.context.refresh(),failure=Error('catalog unavailable');
 h.requests[0].resolve(bootstrapData());await tick();h.requests[1].reject(failure);
 await assert.rejects(loading,error=>error===failure);
 h.context.navigate('home');const next=h.context.refresh();h.requests[2].resolve(bootstrapData());await next;
 assert.equal(h.context.state.route,'home');assert.equal(h.requests.length,3);
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
