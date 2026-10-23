// Exercise the deployed API/storage handlers with delayed responses and a small DOM fixture.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
const base=path.join(__dirname,'..'),read=relative=>fs.readFileSync(path.join(base,relative),'utf8').replace(/\r\n/g,'\n'),app=read('static/app.js');
const apiSource=app.slice(app.indexOf('const server={csrf:'),app.indexOf('function activityPanel(){')).trim();
const storageSource=app.slice(app.indexOf('function storageSize(bytes)'),app.indexOf('// People, connection entry and declared workflows')).trim();
const publishSource=app.slice(app.indexOf('async function publish(){'),app.indexOf('function versionManager(')).trim();
const tick=()=>new Promise(setImmediate);
function deferred(){let resolve,reject;const promise=new Promise((ok,fail)=>{resolve=ok;reject=fail;});return {promise,resolve,reject};}

function setup(){
 const nodes=new Map(),controls=[],requests=[],refreshes=[],announcements=[],listeners={};let observer;
 function element(id=''){
  const node={id,textContent:'',hidden:false,isConnected:true,disabled:false,dataset:{},attrs:{},
   classList:{contains:()=>false},setAttribute(name,value){this.attrs[name]=value;},removeAttribute(name){delete this.attrs[name];},
   querySelector(selector){return selector.split(',').map(s=>nodes.get(s)).find(Boolean)||null;},
   prepend(child){nodes.set('#'+child.id,child);},scrollIntoView(){this.scrolled=true;}};
  if(id)nodes.set('#'+id,node);return node;
 }
 const dialog=element('sq-dialog');dialog.open=false;
 const body=element('sq-dialog-body'),shell=element();nodes.set('.sq-shell',shell);
 element('sq-status');element('sq-modal-status');
 element('sq-session');nodes.set('.sq-demo',element());nodes.set('[data-action=logout]',element());
 const items=[{id:1,likes:0,downloads:3},{id:2,likes:0,downloads:5}];
 const context={runtime:{},state:{liked:new Set()},items,actions:{},FormData:class{},organizations:[],requests:[],policy:{},audit:[],render(){},renderWorkspace(){},
  document:{createElement:()=>element()},root:{addEventListener:(name,fn)=>{(listeners[name]??=[]).push(fn);}},
  MutationObserver:class{constructor(fn){observer=fn;}observe(){}},
  $:selector=>nodes.get(selector)||null,
  $$:selector=>selector.startsWith('[data-action="like"]')?controls.filter(b=>b.dataset.id===selector.match(/data-id="(\d+)"/)[1]):selector.split(',').map(s=>nodes.get(s)).filter(Boolean),
  motion:{matches:true},num:String,getItem:id=>items.find(x=>x.id===+id),announce:text=>announcements.push(text),
  fetch:(url,options)=>{const request=deferred();requests.push({...request,url,options,body:options.body?JSON.parse(options.body):null});return request.promise;},
  fakeRefresh:()=>{const request=deferred();refreshes.push(request);return request.promise;},
 };
 vm.createContext(context);vm.runInContext(apiSource+'\nglobalThis.realRefresh=refresh;refresh=globalThis.fakeRefresh;globalThis.serverState=server;',context,{filename:'static/app.js API'});
 function control(id,detail=false){
  const node=element();node.dataset.id=String(id);node.count=element();node.count.textContent='0';node.label=element();
  node.classList.contains=name=>!detail&&name==='sq-like';
  node.querySelector=selector=>selector==='[data-like-count]'?detail?node.count:null:selector==='span'?node.count:selector==='[data-like-label]'?detail?node.label:null:null;
  controls.push(node);return node;
 }
 function capacity(){
  const message=element('ws-capacity-message'),button=element(),form=element('sq-capacity-form');
  form.dataset.revision='2';form.elements={quotaGB:{value:'5'},reserveGB:{value:'1'},mode:{value:'manual'}};
  form.querySelector=selector=>selector==='[type=submit]'?button:selector==='#ws-capacity-message'?message:null;
  vm.runInContext(storageSource,context,{filename:'static/app.js storage'});
  const submit=()=>listeners.submit[0]({target:form,preventDefault(){},stopImmediatePropagation(){}});
  return {form,message,button,submit};
 }
 return {context,nodes,items,controls,requests,refreshes,announcements,dialog,body,element,control,capacity,mutate:()=>observer(),
  respond:(request,value)=>request.resolve({ok:true,status:200,json:async()=>value})};
}

test('deployed handlers match maintained sources and have one centralized error presenter',()=>{
 assert.equal(apiSource,read('frontend/frontend_api.js').trim());
 assert.equal(storageSource,read('frontend/frontend_storage.js').trim());
 assert.equal(publishSource,read('frontend/frontend_publish.js').trim());
 assert.ok(app.includes(read('frontend/frontend_workspace.js').trim()));
 assert.equal((app.match(/function showError\(|showError=function/g)||[]).length,1);
});

test('an error has one accessible banner and never produces a blue status message',()=>{
 const h=setup();h.nodes.get('#sq-status').textContent='Old success';h.context.showError(Error('MongoDB unavailable'));
 const banner=h.nodes.get('#sq-server-error');assert.equal(banner.textContent,'MongoDB unavailable');
 assert.equal(banner.attrs.role,'alert');assert.equal(banner.attrs['aria-live'],'assertive');
 assert.equal(h.nodes.get('#sq-status').textContent,'');assert.equal(h.nodes.get('#sq-modal-status').textContent,'');
 assert.deepEqual(h.announcements,[]);
});

test('the current form receives the sole error; a closed dialog cannot capture a page error',()=>{
 const h=setup(),inline=h.element('sq-register-error');h.context.showError(Error('Page failure'));
 assert.equal(inline.textContent,'');assert.equal(h.nodes.get('#sq-server-error').textContent,'Page failure');
 h.dialog.open=true;h.context.showError(Error('Registration failure'));
 assert.equal(inline.textContent,'Registration failure');assert.equal(inline.attrs.role,'alert');
 assert.equal(h.nodes.get('#sq-server-error').hidden,true);assert.equal(h.nodes.get('#sq-server-error').textContent,'');
 assert.equal(h.nodes.has('#ws-dialog-error'),false);assert.deepEqual(h.announcements,[]);
});

test('a modal without a form has one visible alert inside the dialog',()=>{
 const h=setup();h.dialog.open=true;h.context.showError(Error('Like failed'));h.context.showError(Error('Like failed again'));
 assert.equal(h.nodes.get('#ws-dialog-error').textContent,'Like failed again');
 assert.equal(h.nodes.get('#ws-dialog-error').attrs.role,'alert');assert.equal(h.nodes.has('#sq-server-error'),false);
 assert.deepEqual(h.announcements,[]);
});

test('generic mutations distinguish a saved change from failed refresh and never resubmit',async()=>{
 const h=setup();let after=0;
 const work=h.context.mutate('/api/tools/1','PATCH',{name:'saved'},()=>{after++;});
 h.respond(h.requests[0],{ok:true});await tick();h.refreshes[0].reject(Error('Read unavailable'));
 await assert.rejects(work,/변경 내용은 저장되었습니다.*Read unavailable/);
 assert.equal(h.requests.length,1);assert.equal(after,0);
 const failed=h.context.mutate('/api/tools/1','PATCH',{name:'unsaved'});
 h.requests[1].reject(Error('Write unavailable'));
 await assert.rejects(failed,error=>error.message==='Write unavailable');
 assert.equal(h.refreshes.length,1);
});

test('rapid clicks on every copy of one tool send one PUT and wait for confirmed counts',async()=>{
 const h=setup(),card=h.control(1),detail=h.control(1,true),other=h.control(2);
 const pending=h.context.actions.like(card);
 for(let n=0;n<12;n++)assert.equal(h.context.actions.like(detail),pending);
 assert.equal(h.requests.length,1);assert.deepEqual(h.requests[0].body,{liked:true});
 assert.equal(card.disabled,true);assert.equal(detail.disabled,true);assert.equal(other.disabled,false);
 assert.equal(card.attrs['aria-busy'],'true');assert.equal(h.context.state.liked.has(1),false);assert.equal(card.count.textContent,'0');
 const replacement=h.control(1);h.mutate();assert.equal(replacement.disabled,true);
 h.respond(h.requests[0],{count:4,liked:true,pending:false});await tick();
 assert.equal(card.count.textContent,'4');assert.equal(detail.label.textContent,'좋아요 취소');assert.equal(h.items[0].likes,3);
 assert.equal(h.refreshes.length,1);assert.equal(detail.disabled,true);
 h.refreshes[0].resolve();await pending;
 assert.equal(card.disabled,false);assert.equal(detail.disabled,false);assert.equal(replacement.disabled,false);
 assert.equal(card.attrs['aria-busy'],undefined);assert.equal(h.announcements.length,1);
});

test('failed writes leave counts unchanged, unlock every copy, and never retry automatically',async()=>{
 const h=setup(),card=h.control(1),detail=h.control(1,true),pending=h.context.actions.like(card);
 assert.equal(h.context.actions.like(detail),pending);h.requests[0].reject(Error('MongoDB unavailable'));
 await assert.rejects(pending,/MongoDB unavailable/);h.context.showError(Error('MongoDB unavailable'));
 assert.equal(h.requests.length,1);assert.equal(h.refreshes.length,0);assert.equal(h.context.state.liked.has(1),false);
 assert.equal(h.items[0].likes,0);assert.equal(card.count.textContent,'0');assert.equal(card.disabled,false);assert.equal(detail.disabled,false);
 assert.deepEqual(h.announcements,[]);
 const retry=h.context.actions.like(card);assert.equal(h.requests.length,2);assert.deepEqual(h.requests[1].body,{liked:true});
 h.requests[1].reject(Error('Still unavailable'));await assert.rejects(retry,/Still unavailable/);
});

test('different tools write independently while their refresh responses apply in order',async()=>{
 const h=setup(),first=h.control(1),second=h.control(2),one=h.context.actions.like(first),two=h.context.actions.like(second);
 assert.equal(h.requests.length,2);
 h.respond(h.requests[1],{count:2,liked:true});await tick();
 h.respond(h.requests[0],{count:1,liked:true});await tick();assert.equal(h.refreshes.length,1);
 h.refreshes[0].resolve();await two;await tick();
 assert.equal(second.disabled,false);assert.equal(first.disabled,true);assert.equal(h.refreshes.length,2);
 h.refreshes[1].resolve();await one;assert.equal(first.disabled,false);assert.equal(h.context.state.liked.size,2);
});

test('a failed refresh after a confirmed like explains the saved state without repeating the write',async()=>{
 const h=setup(),card=h.control(1),pending=h.context.actions.like(card);
 h.respond(h.requests[0],{count:1,liked:true});await tick();h.refreshes[0].reject(Error('Read unavailable'));await pending;
 assert.equal(h.context.state.liked.has(1),true);assert.equal(card.count.textContent,'1');assert.equal(card.disabled,false);
 assert.equal(h.requests.length,1);assert.deepEqual(h.announcements,[]);
 assert.match(h.nodes.get('#sq-server-error').textContent,/좋아요 추가는 저장되었습니다/);
});

test('a queued refresh failure restores its confirmed like after an earlier snapshot replaced the items',async()=>{
 const h=setup(),first=h.control(1),second=h.control(2),one=h.context.actions.like(first),two=h.context.actions.like(second);
 h.respond(h.requests[0],{count:1,liked:true});await tick();h.respond(h.requests[1],{count:2,liked:true});await tick();
 h.context.state.liked.delete(2);h.items[1]={id:2,likes:0,downloads:5};second.count.textContent='0';
 h.refreshes[0].resolve();await one;await tick();h.refreshes[1].reject(Error('Read unavailable'));await two;
 assert.equal(h.context.state.liked.has(2),true);assert.equal(h.items[1].likes,1);assert.equal(second.count.textContent,'2');
 assert.equal(second.disabled,false);assert.equal(h.requests.length,2);
});

for(const liked of [false,true])test(`a saved ${liked?'like removal':'like'} keeps a safe provisional count when aggregation is pending`,async()=>{
 const h=setup(),card=h.control(1);h.items[0].likes=4;
 if(liked)h.context.state.liked.add(1);
 card.count.textContent=String(4+(liked?1:0));const pending=h.context.actions.like(card);
 h.respond(h.requests[0],{count:null,liked:!liked,historyPending:true,countsPending:true});await tick();
 assert.equal(card.count.textContent,String(liked?4:5));assert.equal(h.items[0].likes,4);
 h.refreshes[0].reject(Error('Read unavailable'));await pending;
 assert.equal(card.count.textContent,String(liked?4:5));assert.equal(h.context.state.liked.has(1),!liked);
 assert.equal(h.requests.length,1);assert.equal(card.disabled,false);
});

test('pending aggregation never displays a negative or NaN count and honors the saved selection',async()=>{
 const h=setup(),card=h.control(1);h.context.state.liked.add(1);h.items[0].likes=-1;
 const pending=h.context.actions.like(card);h.respond(h.requests[0],{count:null,liked:false,pending:true,historyPending:false,countsPending:true});await tick();
 assert.equal(card.count.textContent,'0');assert.equal(h.items[0].likes,0);
 h.refreshes[0].resolve();await pending;assert.match(h.announcements[0],/집계는 목록 조회 시/);
 h.items[0].likes=NaN;const another=h.context.actions.like(card);h.respond(h.requests[1],{count:null,liked:true,historyPending:true});await tick();
 assert.equal(card.count.textContent,'1');assert.equal(h.items[0].likes,0);
 h.refreshes[1].resolve();await another;assert.match(h.announcements[1],/이력은 다음 조회/);
});

test('a saved like distinguishes simultaneous history and aggregation delay in one status',async()=>{
 const h=setup(),card=h.control(1),pending=h.context.actions.like(card);
 h.respond(h.requests[0],{liked:true,count:null,pending:true,historyPending:true,countsPending:true});await tick();
 h.refreshes[0].resolve();await pending;
 assert.equal(h.announcements.length,1);assert.match(h.announcements[0],/이력·집계는 다음 조회/);
});

function bootstrap(likes=0,revision=2){return {items:[{id:1,likes,liked:likes>0,downloads:3}],organizations:[],requests:[],policy:{},audit:[],user:{name:'User',org:'Team'},authMode:'mock',storage:{limitRevision:revision}};}

test('global bootstrap generation rejects an earlier response after a newer caller has rendered',async()=>{
 const h=setup();let rendered=0;h.context.render=()=>{rendered++;};
 const earlier=h.context.realRefresh(),latest=h.context.realRefresh();
 h.respond(h.requests[1],bootstrap(5));assert.equal(await latest,true);
 h.respond(h.requests[0],bootstrap(0));assert.equal(await earlier,false);
 assert.equal(h.items[0].likes,4);assert.equal(h.context.state.liked.has(1),true);assert.equal(rendered,1);
});

test('a stale bootstrap failure cannot surface after a newer successful response',async()=>{
 const h=setup(),earlier=h.context.realRefresh(),latest=h.context.realRefresh();
 h.respond(h.requests[1],bootstrap(2));await latest;
 h.requests[0].reject(Error('Old read failed'));assert.equal(await earlier,false);
 assert.equal(h.items[0].likes,1);assert.equal(h.nodes.has('#sq-server-error'),false);
 const current=h.context.realRefresh();h.requests[2].reject(Error('Current read failed'));
 await assert.rejects(current,/Current read failed/);
});

test('authoritative bootstrap replaces provisional like counts after a count query failure',async()=>{
 const h=setup(),card=h.control(1);h.items[0].likes=4;h.context.refresh=h.context.realRefresh;
 const pending=h.context.actions.like(card);h.respond(h.requests[0],{liked:true,count:null,countsPending:true});await tick();
 assert.equal(h.items[0].likes,4);assert.equal(card.count.textContent,'5');
 h.respond(h.requests[1],bootstrap(8));await pending;
 assert.equal(h.items[0].likes,7);assert.equal(h.context.state.liked.has(1),true);assert.equal(h.requests.length,2);
});

test('capacity write failure stays inline with alert semantics and enables deliberate retry',async()=>{
 const h=setup(),form=h.capacity(),pending=form.submit();assert.equal(form.button.disabled,true);
 assert.equal(form.submit(),undefined);assert.equal(h.requests.length,1);
 h.requests[0].reject(Error('Write unavailable'));await pending;
 assert.equal(form.message.textContent,'Write unavailable');assert.equal(form.message.attrs.role,'alert');
 assert.equal(form.message.attrs['aria-live'],'assertive');assert.equal(form.button.disabled,false);assert.equal(form.form.dataset.revision,'2');
 assert.equal(h.refreshes.length,0);assert.equal(h.nodes.has('#sq-server-error'),false);assert.deepEqual(h.announcements,[]);
});

test('confirmed capacity settings/revision render directly without a bootstrap or second PUT',async()=>{
 const h=setup(),form=h.capacity(),pending=form.submit(),storage={limitRevision:3,configuredQuota:5*1073741824,mode:'manual'};
 let rendered=0;h.context.renderWorkspace=()=>{rendered++;};
 h.respond(h.requests[0],{storage,ok:true});await pending;
 assert.equal(form.form.dataset.revision,'3');assert.equal(h.context.serverState.storage.limitRevision,3);
 assert.equal(rendered,1);assert.equal(h.refreshes.length,0);
 assert.match(form.message.textContent,/저장했습니다/);assert.equal(form.message.attrs.role,'status');
 assert.equal(h.requests.length,1);assert.equal(form.button.disabled,false);assert.deepEqual(h.announcements,[]);
});

test('an in-flight bootstrap cannot replace an acknowledged capacity revision with an older policy',async()=>{
 const h=setup(),earlier=h.context.realRefresh(),form=h.capacity(),pending=form.submit();
 h.respond(h.requests[1],{storage:{limitRevision:3},ok:true});await pending;
 h.respond(h.requests[0],bootstrap(0,2));assert.equal(await earlier,false);
 assert.equal(h.context.serverState.storage.limitRevision,3);assert.equal(form.form.dataset.revision,'3');
 assert.equal(h.requests.length,2);assert.equal(h.refreshes.length,0);
});

for(const outcome of ['success','failure'])test(`an older dedicated capacity GET ${outcome} cannot override a confirmed save`,async()=>{
 const h=setup(),form=h.capacity(),earlier=h.context.fetchStorageCapacity(),pending=form.submit();
 h.respond(h.requests[1],{storage:{limitRevision:3,configuredQuota:9000},ok:true});await pending;
 if(outcome==='success')h.respond(h.requests[0],{storage:{limitRevision:2,configuredQuota:1000}});
 else h.requests[0].reject(Error('Older capacity read failed'));
 assert.equal(await earlier,false);assert.equal(h.context.serverState.storage.limitRevision,3);
 assert.equal(h.context.serverState.storage.configuredQuota,9000);assert.equal(form.form.dataset.revision,'3');
 assert.equal(form.message.attrs.role,'status');assert.match(form.message.textContent,/저장했습니다/);
 assert.equal(h.requests.length,2);assert.equal(h.refreshes.length,0);
});

test('dedicated capacity GET uses its newest response and still reports a current read error',async()=>{
 const h=setup();h.capacity();const earlier=h.context.fetchStorageCapacity(),latest=h.context.fetchStorageCapacity();
 h.respond(h.requests[1],{storage:{limitRevision:5}});assert.equal(await latest,true);
 h.respond(h.requests[0],{storage:{limitRevision:4}});assert.equal(await earlier,false);
 assert.equal(h.context.serverState.storage.limitRevision,5);
 const current=h.context.fetchStorageCapacity();h.requests[2].reject(Error('Current capacity read failed'));
 await assert.rejects(current,/Current capacity read failed/);
});

test('capacity validation is an alert, but pending and successful states are polite status messages',async()=>{
 const h=setup(),form=h.capacity();form.form.elements.quotaGB.value='0';form.submit();
 assert.equal(form.message.attrs.role,'alert');assert.equal(h.requests.length,0);
 form.form.elements.quotaGB.value='5';const pending=form.submit();assert.equal(form.message.attrs.role,'status');
 h.respond(h.requests[0],{storage:{limitRevision:3},ok:true});await pending;
 assert.equal(form.message.attrs.role,'status');assert.equal(form.message.attrs['aria-live'],'polite');
 assert.match(form.message.textContent,/저장했습니다/);assert.equal(form.button.disabled,false);
});

test('queued secondary synchronization is reported as a saved like and saved capacity setting',async()=>{
 const h=setup(),card=h.control(1),like=h.context.actions.like(card);
 h.respond(h.requests[0],{count:1,liked:true,pending:true});await tick();h.refreshes[0].resolve();await like;
 assert.match(h.announcements[0],/저장되었습니다/);assert.equal(h.nodes.has('#sq-server-error'),false);
 const form=h.capacity(),saved=form.submit();h.respond(h.requests[1],{storage:{limitRevision:3},pending:true});
 await saved;assert.equal(h.refreshes.length,1);assert.equal(form.message.attrs.role,'status');
 assert.match(form.message.textContent,/한도 설정은 저장되었습니다/);assert.match(form.message.textContent,/다음 조회/);
});

function publishSetup(){
 const requests=[],opened=[],draft={name:'Example',desc:'Description',owner:'Owner',platform:'Claude',type:'Skill',guide:'Guide',org:'Team',category:'General',mode:'file',file:{name:'tool.zip'},workTags:'report, report',expectedRevision:2};
 const context={runtime:{draft,step:3,releaseId:null},actions:{},packageBlockingError:()=>'',Core:{validate:()=>''},
  crypto:require('node:crypto').webcrypto,Uint8Array,
  FormData:class{constructor(){this.values={};}append(key,value){this.values[key]=value;}},
  requestAPI:(url,method,form)=>{const request=deferred();requests.push({...request,url,method,metadata:JSON.parse(form.values.metadata),artifact:form.values.artifact});return request.promise;},
  refresh:async()=>{},openModal:(title,kicker,html)=>opened.push({title,kicker,html}),getItem:()=>undefined,esc:String,button:()=>'',icon:()=>'',
 };
 vm.createContext(context);vm.runInContext(publishSource,context,{filename:'static/app.js publish'});
 vm.runInContext(app.match(/^function invalidateDetailLoad\(\).*$/m)[0],context,{filename:'static/app.js invalidation'});
 vm.runInContext(apiSource.slice(apiSource.indexOf("actions['published-detail']="),apiSource.indexOf("actions['rank-refresh']=")),context,{filename:'static/app.js published-detail'});
 async function failed(){const pending=context.publish(),request=requests.at(-1);request.reject(Error('Response unavailable'));await assert.rejects(pending,/Response unavailable/);return request;}
 return {context,draft,requests,opened,failed};
}

test('concurrent programmatic publish calls send one POST and release the busy guard on failure and success',async()=>{
 const h=publishSetup(),first=h.context.publish();assert.equal(h.context.runtime.publishBusy,true);
 await h.context.publish();assert.equal(h.requests.length,1);
 h.requests[0].reject(Error('Write unavailable'));await assert.rejects(first,/Write unavailable/);
 assert.equal(h.context.runtime.publishBusy,false);assert.equal(h.context.runtime.draft,h.draft);
 const refresh=deferred();h.context.refresh=()=>refresh.promise;
 const next=h.context.publish();assert.equal(h.requests.length,2);
 assert.equal(h.requests[0].metadata.clientRequestId,h.requests[1].metadata.clientRequestId);
 h.requests[1].resolve({id:19,version:1});await tick();assert.equal(h.context.runtime.publishBusy,true);
 await h.context.publish();assert.equal(h.requests.length,2);
 refresh.resolve();await next;assert.equal(h.context.runtime.publishBusy,false);assert.equal(h.opened.length,1);
 await h.context.publish();assert.equal(h.requests.length,2);
});

test('an unchanged explicit publish retry keeps its UUID even when preview/revision state changes',async()=>{
 const h=publishSetup(),first=await h.failed();assert.match(first.metadata.clientRequestId,/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
 h.draft.packageInspection={state:'done'};h.draft.sample=true;h.draft.expectedRevision=3;h.draft.name=' Example ';h.draft.workTags=['report'];
 const second=await h.failed();assert.equal(first.metadata.clientRequestId,second.metadata.clientRequestId);
 assert.equal(second.metadata.expectedRevision,3);assert.equal(second.metadata.packageInspection,undefined);
 assert.equal(h.requests.length,2);assert.equal(h.context.runtime.draft,h.draft);
});

test('changing publish content, immutable file, release target, URL or commands starts a new UUID',async()=>{
 const h=publishSetup();let previous=(await h.failed()).metadata.clientRequestId;
 for(const change of [
  ()=>{h.draft.desc='Changed';},()=>{h.draft.file={name:'tool.zip'};},()=>{h.context.runtime.releaseId=7;},
  ()=>{h.draft.workflow={steps:[{title:'New workflow'}]};},
  ()=>{h.draft.mode='url';h.draft.url='https://example.test/tool';},()=>{h.draft.url='https://example.test/new-tool';},
  ()=>{h.draft.mode='command';h.draft.commandProject='install first';},()=>{h.draft.commandUser='install user';},
 ]){change();const request=await h.failed();assert.notEqual(request.metadata.clientRequestId,previous);previous=request.metadata.clientRequestId;}
 assert.equal(h.requests.at(-1).url,'/api/tools/7/versions');assert.equal(h.requests.at(-1).artifact,undefined);
});

test('primary publish errors keep the draft and no success UI, while refresh failure preserves saved success',async()=>{
 const h=publishSetup();await h.failed();assert.equal(h.opened.length,0);assert.ok(h.context.runtime.publishAttempt);
 h.context.refresh=async()=>{throw Error('Read unavailable');};const pending=h.context.publish();
 h.requests.at(-1).resolve({id:19,version:4,pending:true});await pending;
 assert.equal(h.requests.length,2);assert.equal(h.context.runtime.draft,null);assert.equal(h.context.runtime.publishAttempt,null);
 assert.equal(h.context.runtime.newId,19);assert.equal(h.opened.length,1);assert.equal(h.opened[0].kicker,'게시 완료');
 assert.match(h.opened[0].html,/Example/);assert.match(h.opened[0].html,/v4을 서버에 저장했습니다/);
 assert.match(h.opened[0].html,/목록을 갱신하지 못했으므로/);assert.match(h.opened[0].html,/이력·알림은 다음 조회/);
});

test('details after acknowledged new publish and failed refresh reload the missing tool without publishing again',async()=>{
 const h=publishSetup(),rows=[],details=[];let refreshCount=0;
 h.context.getItem=id=>rows.find(row=>row.id===id);
 h.context.refresh=async()=>{if(++refreshCount===1)throw Error('Read unavailable');rows.push({id:19,name:'Example'});};
 h.context.detail=async id=>{h.context.invalidateDetailLoad();assert.ok(h.context.getItem(id));details.push(id);return true;};
 const publish=h.context.publish();h.requests[0].resolve({id:19,version:1});await publish;
 assert.equal(rows.length,0);assert.equal(h.opened[0].kicker,'게시 완료');assert.equal(h.context.runtime.draft,null);
 assert.equal(await h.context.actions['published-detail'](),true);
 assert.equal(refreshCount,2);assert.deepEqual(details,[19]);assert.equal(h.requests.length,1);
 assert.equal(h.requests[0].method,'POST');assert.equal(h.context.runtime.publishAttempt,null);
});

test('a failed published-detail recovery is a viewing error and never restores or resubmits the draft',async()=>{
 const h=publishSetup();h.context.refresh=async()=>{throw Error('Read unavailable');};
 h.context.detail=async()=>{throw Error('Must not open a missing tool');};
 const publish=h.context.publish();h.requests[0].resolve({id:19,version:1});await publish;
 await assert.rejects(h.context.actions['published-detail'](),/게시한 도구는 저장되어 있습니다\. 상세 화면을 불러오지 못했습니다\. Read unavailable/);
 h.context.refresh=async()=>{};
 await assert.rejects(h.context.actions['published-detail'](),/상세 화면을 불러오지 못했습니다\. 목록에서 게시한 도구를 찾지 못했습니다/);
 assert.equal(h.requests.length,1);assert.equal(h.context.runtime.draft,null);assert.equal(h.context.runtime.publishAttempt,null);
});

for(const action of ['close','navigate'])for(const outcome of ['success','failure']){
 test(`published-detail recovery ignores refresh ${outcome} after ${action}`,async()=>{
  const h=publishSetup(),refresh=deferred(),screen={dialogOpen:true,route:'home'},errors=[];let item,details=0;
  h.context.runtime.newId=19;h.context.getItem=()=>item;h.context.refresh=()=>refresh.promise;
  h.context.originalCloseModal=()=>{screen.dialogOpen=false;};
  h.context.originalNavigate=route=>{screen.route=route;screen.dialogOpen=false;};
  vm.runInContext(app.slice(app.indexOf('closeModal=function(){invalidateDetailLoad();'),app.indexOf('// This action captured the original function')),h.context,{filename:'static/app.js navigation invalidation'});
  h.context.detail=async()=>{h.context.invalidateDetailLoad();details++;screen.dialogOpen=true;return true;};
  const pending=h.context.actions['published-detail']().catch(error=>{errors.push(error.message);});
  if(action==='close')h.context.closeModal();else h.context.navigate('browse');
  if(outcome==='success'){item={id:19,name:'Example'};refresh.resolve();}else refresh.reject(Error('Late read failure'));
  assert.equal(await pending,false);assert.equal(details,0);assert.equal(screen.dialogOpen,false);assert.deepEqual(errors,[]);
  assert.equal(screen.route,action==='navigate'?'browse':'home');assert.equal(h.requests.length,0);
 });
}

test('published-detail delegates to detail token ownership without hiding a current detail failure',async()=>{
 const h=publishSetup();h.context.runtime.newId=19;h.context.getItem=()=>({id:19,name:'Example'});
 h.context.refresh=async()=>{throw Error('Unexpected refresh');};
 h.context.detail=async()=>{h.context.invalidateDetailLoad();throw Error('Current detail read failed');};
 await assert.rejects(h.context.actions['published-detail'](),/상세 화면을 불러오지 못했습니다\. Current detail read failed/);
 assert.equal(h.context.runtime.detailLoadToken,2);assert.equal(h.requests.length,0);
});
