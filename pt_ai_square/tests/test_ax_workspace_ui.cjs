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
const item={id:'a'.repeat(32),name:'AX Workspace 설치',description:'업무 공간을 설치합니다.',category:'workspace',version:'1.0.0',fileName:'workspace.zip',size:120,created:1,revision:3,release:1,subscribed:false,downloadUrl:'/api/ax-workspace/'+ 'a'.repeat(32)+'/download'};

function setup(role='admin',{search='',route='ax'}={}){
 const requests=[],errors=[],announcements=[],opened=[],listeners={},windowListeners={},documentListeners={},timers=[],subscriptionButtons=[],cards=[];
 const workspace={innerHTML:''},dialog={open:false},area={outerHTML:''},pageError={hidden:true,textContent:'',isConnected:true};
 let currentForm=null;
 class FormData{
  constructor(form){this.values=form?[...form.entries]:[];}
  append(key,value){this.values.push([key,value]);}
  [Symbol.iterator](){return this.values[Symbol.iterator]();}
 }
 const session={},demo={},logout={},catalogRequests=[];
 const context={runtime:{detailLoadToken:0},state:{route,rankMode:'recent'},server:{user:{id:'admin',role}},workspace,FormData,now:10000,
  window:{addEventListener:(name,fn)=>(windowListeners[name]??=[]).push(fn)},document:{hidden:false,addEventListener:(name,fn)=>(documentListeners[name]??=[]).push(fn)},Date:{now:()=>context.now},
  setTimeout:(callback,delay)=>{const timer={callback,delay,cancelled:false};timers.push(timer);return timer;},clearTimeout:timer=>{if(timer)timer.cancelled=true;},
  location:{search},URLSearchParams,items:[],organizations:[],requests:catalogRequests,policy:{},audit:[],render(){},loadPeopleRanks:async()=>{},
  actions:{},root:{addEventListener:(name,fn)=>(listeners[name]??=[]).push(fn)},
  $:selector=>selector==='#sq-dialog'?dialog:selector==='#sq-ax-form'?currentForm:selector==='[data-ax-drop]'?area:selector==='#sq-server-error'?pageError:selector==='#sq-session'?session:selector==='.sq-demo'?demo:selector==='[data-action=logout]'?logout:null,
  $$:selector=>selector==='[data-action="ax-subscription"]'?subscriptionButtons:selector==='[data-ax-card]'?cards:[],esc:value=>String(value).replace(/</g,'&lt;').replace(/"/g,'&quot;'),icon:()=>'',mountIcons(){},
  button:(action,label,cls='',extra='')=>`<button data-action="${action}" ${extra}>${label}</button>`,
  badge:value=>String(value),blank:(icon,title,body)=>`<div class="ws-empty"><h3>${title}</h3><p>${body}</p></div>`,dated:()=>'',fileSize:bytes=>`${bytes} bytes`,
  openModal(title,kicker,html){context.runtime.detailLoadToken++;dialog.open=true;opened.push({title,html});},
  closeModal(){context.runtime.detailLoadToken++;dialog.open=false;},
  navigate(route){context.runtime.detailLoadToken++;context.state.route=route;},
  announce:message=>announcements.push(message),showError:error=>errors.push(error),clearErrorMessages(){},
  requestAPI:(url,method='GET',body)=>{const pending=deferred();requests.push({...pending,url,method,body});return pending.promise;},
 };
 vm.createContext(context);vm.runInContext(bootstrapRefresh+'\nconst basePeopleRefresh=refresh;\n'+peopleRefresh+'\n'+afterSave+'\n'+source,context,{filename:'frontend_ax_workspace.js'});
 function newForm(id=null){
  id===null?context.actions['ax-register']():context.actions['ax-version']({dataset:{id}});
  const controls=[{disabled:false},{disabled:false}];
  const node={id:'sq-ax-form',dataset:{},isConnected:true,
   entries:[['name',item.name],['description',item.description],['category',item.category],['version',item.version]],
   querySelectorAll:()=>controls};
  currentForm=node;
  const file={name:item.fileName,size:item.size};context.chooseAxFile([file]);
  return {node,controls,file,submit:()=>listeners.submit[0]({target:node,preventDefault(){},stopImmediatePropagation(){}})};
 }
 return {context,requests,errors,announcements,opened,listeners,windowListeners,documentListeners,timers,subscriptionButtons,cards,workspace,dialog,pageError,newForm,
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

test('AX extension selection preserves the download filename and excludes unrelated files',()=>{
 const h=setup(),file={name:'PNT-AI-Square.axextension',size:1024};
 h.context.chooseAxFile([file]);assert.equal(h.value('axFile'),file);
 assert.match(h.context.axUploadArea(),/accept="\.zip,\.axextension,/);
 assert.match(h.context.axUploadArea(),/PNT-AI-Square\.axextension/);
 assert.throws(()=>h.context.chooseAxFile([{name:'not-package.html',size:1024}]));
 assert.equal(h.value('axFile'),file);
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

function seed(h,rows=[item]){vm.runInContext(`axFiles=${JSON.stringify(rows)};`,h.context);}
function subscriptionButton(h,id=item.id){const b={dataset:{id},disabled:false,innerHTML:'',setAttribute(k,v){this[k]=v;}};h.subscriptionButtons.push(b);return b;}

test('administrator version form retains escaped metadata, requires a new version, and is unavailable to members',()=>{
 for(const role of ['admin','member']){
  const h=setup(role);seed(h,[{...item,name:'<img src=x>',description:'<script>unsafe</script>',category:'plugin'}]);h.context.renderAxWorkspace();
  assert.equal(h.workspace.innerHTML.includes('data-action="ax-version"'),role==='admin');
  h.context.actions['ax-version']({dataset:{id:item.id}});assert.equal(h.opened.length,role==='admin'?1:0);
  if(role==='admin'){
   const html=h.opened[0].html;assert.match(html,/value="&lt;img src=x>"/);assert.match(html,/&lt;script>unsafe&lt;\/script>/);
   assert.match(html,/<option value="plugin" selected>/);assert.match(html,/name="version" required[^>]*현재 1\.0\.0/);
   assert.doesNotMatch(html,/name="version"[^>]*value=/);assert.equal(h.value('axVersionTarget.revision'),3);
  }
 }
});

test('new version posts one multipart request to the stable file id with its revision and then refreshes the same card',async()=>{
 const h=setup();seed(h);const form=h.newForm(item.id);form.node.entries[3][1]='1.1.0';form.submit();form.submit();
 assert.equal(h.requests.length,1);assert.equal(h.requests[0].url,`/api/ax-workspace/${item.id}/versions`);
 assert.deepEqual(JSON.parse(h.requests[0].body.values.find(([k])=>k==='metadata')[1]),{...Object.fromEntries(form.node.entries),expectedRevision:3});
 assert.equal(h.requests[0].body.values.find(([k])=>k==='file')[1],form.file);
 h.requests[0].resolve({file:{...item,version:'1.1.0',revision:4,release:2},followupsPending:true});await tick();
 h.requests[1].resolve({files:[{...item,version:'1.1.0',revision:4,release:2}]});await tick();
 assert.equal(h.value('axFiles.length'),1);assert.equal(h.value('axFiles[0].id'),item.id);assert.match(h.workspace.innerHTML,/v1\.1\.0/);
 assert.deepEqual(h.announcements,['새 버전을 등록했습니다.']);assert.equal(form.node.dataset.saved,'true');
});

test('legacy release uses revision 1, version conflict preserves its draft, and opening a fresh registration clears the target',async()=>{
 const h=setup();seed(h,[{...item,revision:undefined}]);const form=h.newForm(item.id);form.submit();
 assert.equal(JSON.parse(h.requests[0].body.values[0][1]).expectedRevision,1);
 h.requests[0].reject(Error('다른 관리자가 새 버전을 등록했습니다.'));await tick();
 assert.equal(h.value('axFile'),form.file);assert.ok(form.controls.every(x=>!x.disabled));assert.equal(h.errors.length,1);
 form.submit();assert.equal(h.requests[1].url,`/api/ax-workspace/${item.id}/versions`);h.requests[1].reject(Error('conflict'));await tick();
 h.newForm();assert.equal(h.value('axVersionTarget'),null);
});

test('subscription toggle blocks repeat clicks and uses only the confirmed response for its pressed state',async()=>{
 const h=setup('member');seed(h);const b=subscriptionButton(h),first=h.context.toggleAxSubscription(item.id);
 await h.context.toggleAxSubscription(item.id);assert.equal(h.requests.length,1);assert.equal(b.disabled,true);assert.equal(b['aria-pressed'],'false');
 assert.equal(h.requests[0].url,`/api/ax-workspace/${item.id}/subscription`);assert.equal(h.requests[0].method,'PUT');assert.equal(h.requests[0].body.enabled,true);
 h.requests[0].resolve({ok:true,subscribed:true});await first;assert.equal(b.disabled,false);assert.equal(b['aria-pressed'],'true');assert.match(b['aria-label'],/끄기$/);
 const second=h.context.toggleAxSubscription(item.id);assert.equal(h.requests[1].body.enabled,false);
 h.requests[1].resolve({ok:true,subscribed:false});await second;assert.equal(b['aria-pressed'],'false');assert.match(b.innerHTML,/꺼짐/);
});

test('failed or malformed subscription response does not invent success and leaves the control retryable',async()=>{
 for(const malformed of [false,true]){
  const h=setup('member');seed(h);const b=subscriptionButton(h),toggle=h.context.toggleAxSubscription(item.id);
  malformed?h.requests[0].resolve({ok:true}):h.requests[0].reject(Error('offline'));
  await assert.rejects(toggle);assert.equal(h.value('axFiles[0].subscribed'),false);assert.equal(b.disabled,false);
  const retry=h.context.toggleAxSubscription(item.id);h.requests[1].resolve({subscribed:true});await retry;assert.equal(b['aria-pressed'],'true');
 }
});

test('late subscription completion does not navigate or paint over another view, and late errors stay with the old view',async()=>{
 for(const failed of [false,true]){
  const h=setup('member');seed(h);const b=subscriptionButton(h),toggle=h.context.toggleAxSubscription(item.id);
  h.context.navigate('ideas');h.workspace.innerHTML='새 화면';failed?h.requests[0].reject(Error('late')):h.requests[0].resolve({subscribed:true});await toggle;
  assert.equal(h.context.state.route,'ideas');assert.equal(h.workspace.innerHTML,'새 화면');assert.deepEqual(h.errors,[]);
  if(!failed)assert.equal(h.value('axFiles[0].subscribed'),true);
  assert.equal(b['aria-pressed'],'false');
 }
});

test('catalog and subscription reads started before a toggle cannot overwrite its confirmed value',async()=>{
 for(const background of [false,true]){
  const h=setup('member');seed(h);subscriptionButton(h);
  const old=background?h.context.refreshAxSubscriptions(true):h.context.loadAxWorkspace();
  const toggle=h.context.toggleAxSubscription(item.id);h.requests[1].resolve({subscribed:true});await toggle;
  h.requests[0].resolve({files:[{...item,subscribed:false}]});await old;assert.equal(h.value('axFiles[0].subscribed'),true);
 }
});

test('a catalog response during a pending toggle retains the earlier confirmed setting until mutation completes',async()=>{
 const h=setup('member');seed(h);const toggle=h.context.toggleAxSubscription(item.id),read=h.context.loadAxWorkspace();
 h.requests[1].resolve({files:[{...item,subscribed:true}]});await read;assert.equal(h.value('axFiles[0].subscribed'),false);
 h.requests[0].resolve({subscribed:true});await toggle;assert.equal(h.value('axFiles[0].subscribed'),true);
});

test('browser download stays an anchor and later GET alone confirms automatic subscription without replacing the catalog',async()=>{
 const h=setup('member');seed(h);const b=subscriptionButton(h);h.context.renderAxWorkspace();const before=h.workspace.innerHTML;
 let prevented=false;h.listeners.click[0]({target:{closest:selector=>selector==='a[data-ax-download]'?{dataset:{axDownload:item.id}}:null},preventDefault(){prevented=true;}});
 assert.equal(prevented,false);assert.equal(h.requests.length,0);assert.equal(h.value('axFiles[0].subscribed'),false);assert.equal(h.timers[0].delay,1500);
 h.timers[0].callback();await tick();
 assert.equal(h.requests.length,1);assert.equal(h.requests[0].url,'/api/ax-workspace');assert.equal(h.requests[0].method,'GET');
 h.requests[0].resolve({files:[{...item,subscribed:true}]});await tick();
 assert.equal(b['aria-pressed'],'true');assert.equal(h.workspace.innerHTML,before);
});

test('explicit off survives the post-download check and refresh failure never blocks streaming or raises a download error',async()=>{
 for(const failed of [false,true]){
  const h=setup('member');seed(h);const b=subscriptionButton(h);
  h.listeners.click[0]({target:{closest:()=>({})}});h.timers[0].callback();await tick();
  failed?h.requests[0].reject(Error('status unavailable')):h.requests[0].resolve({files:[{...item,subscribed:false}]});await tick();
  assert.equal(h.value('axFiles[0].subscribed'),false);assert.deepEqual(h.errors,[]);assert.notEqual(b['aria-pressed'],'true');
 }
});

test('focus and visibility subscription reads are throttled, single flight, skipped when hidden or away, and ignore old navigation results',async()=>{
 const h=setup('member');seed(h);h.context.document.hidden=true;h.documentListeners.visibilitychange[0]();assert.equal(h.requests.length,0);
 h.context.document.hidden=false;h.windowListeners.focus[0]();h.windowListeners.focus[0]();assert.equal(h.requests.length,1);
 h.requests[0].resolve({files:[item]});await tick();h.windowListeners.focus[0]();assert.equal(h.requests.length,1);
 h.context.now+=6000;h.documentListeners.visibilitychange[0]();assert.equal(h.requests.length,2);
 h.context.navigate('home');h.requests[1].resolve({files:[{...item,subscribed:true}]});await tick();assert.equal(h.value('axFiles[0].subscribed'),false);
 h.windowListeners.focus[0]();assert.equal(h.requests.length,2);
});

test('workspace notification navigation clears filters and highlights, focuses and scrolls the stable file card',async()=>{
 const h=setup('member');seed(h);h.context.actions['ax-filter']({dataset:{category:'plugin'}});
 const calls=[],card={dataset:{axCard:item.id},focus:args=>calls.push(['focus',args]),scrollIntoView:args=>calls.push(['scroll',args])};h.cards.push(card);
 const open=h.context.openAxWorkspaceFile(item.id);h.requests[0].resolve({files:[item]});await open;
 assert.equal(h.context.state.route,'ax');assert.equal(h.value('axFilter'),'all');assert.match(h.workspace.innerHTML,/ws-ax-card is-highlighted/);
 assert.ok(h.workspace.innerHTML.includes(`data-ax-card="${item.id}"`));assert.equal(calls[0][0],'focus');assert.equal(calls[1][0],'scroll');
});

test('late workspace notification catalog result cannot focus or replace a different page',async()=>{
 const h=setup('member'),calls=[];h.cards.push({dataset:{axCard:item.id},focus:()=>calls.push('focus'),scrollIntoView:()=>calls.push('scroll')});
 const open=h.context.openAxWorkspaceFile(item.id);h.context.navigate('home');h.workspace.innerHTML='home';h.requests[0].resolve({files:[item]});await open;
 assert.equal(h.context.state.route,'home');assert.equal(h.workspace.innerHTML,'home');assert.deepEqual(calls,[]);
});
