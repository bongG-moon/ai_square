// Real maintained handlers, synthetic accounts and deferred API responses only.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_workspace.js'),'utf8');
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function setup(){
 const calls=[],opened=[],errors=[],decisions=[],listeners={};
 const inert={append(){},remove(){},insertAdjacentHTML(){},addEventListener(){}};
 const dialog={open:false,addEventListener(){}};
 const items=[1,2].map(id=>({id,name:`Tool ${id}`,owner:'Owner',org:'Team',access:'none',requestStatus:'none',requestRevision:null,canCancel:false,comments:[],likes:0}));
 const context={runtime:{},state:{route:'home'},server:{user:{id:'one',role:'user'}},items,requests:decisions,
  root:{addEventListener(name,fn){(listeners[name]??=[]).push(fn);}},document:{createElement:()=>({...inert}),addEventListener(){}},window:{addEventListener(){}},
  $:selector=>selector==='#sq-dialog'?dialog:['#sq-main','.sq-header nav','.sq-header-actions','.sq-header-actions [data-action="manage"]','.sq-detail-top .sq-row-actions'].includes(selector)?inert:null,
  $$:()=>[],setInterval(){},esc:s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
  button:(action,label,classes='',attrs='')=>`<button data-action="${action}" class="${classes}" ${attrs}>${label}</button>`,badge:s=>`<span>${s}</span>`,icon:()=>'',mountIcons(){},enhanceSelects(){},decoratePackageForm(){},deploymentLinks(){},
  getItem:id=>items.find(x=>x.id===+id),render(){},manage(){},showError:error=>errors.push(error.message),
  requestAPI:(url,method,body)=>{const pending=deferred();calls.push({...pending,url,method,body});return pending.promise;},refresh:async()=>{},
  openModal(title,kicker,html){dialog.open=true;opened.push({title,html});},closeModal(){dialog.open=false;},navigate(){},
  detail(id){context.runtime.detailId=+id;context.openModal(context.getItem(id).name);},
  ask(title,copy,action){context.confirm=action;},FormData:class {constructor(form){return Object.entries(form.data||{});}}
 };
 context.actions={'close-dialog':context.closeModal};vm.createContext(context);vm.runInContext(source,context);
 const form={id:'sq-access-form',dataset:{toolId:'1'},elements:{reason:{disabled:false}},submit:{disabled:false,setAttribute(name,value){this[name]=value;}},querySelector(){return this.submit;}};
 function openRequest(){context.runtime.detailId=1;context.requestAccess();return form;}
 function pending(){Object.assign(items[0],{access:'pending',requestStatus:'pending',requestRevision:'a'.repeat(32),canCancel:true});context.lockedDetail(items[0]);}
 return {context,calls,opened,errors,items,dialog,form,openRequest,pending,decisions,listeners,last:()=>opened.at(-1)};
}
const reply=(access,extra={})=>({ok:true,toolId:1,access,requestStatus:access==='pending'?'pending':'none',requestRevision:access==='pending'?'a'.repeat(32):null,canCancel:access==='pending',...extra});
const click=id=>({dataset:{id:String(id)}});
const tick=()=>new Promise(setImmediate);

test('request shows immediate progress, blocks duplicate submits and confirms pending without a global refresh',async()=>{
 const h=setup(),form=h.openRequest(),operation=h.context.submitAccessRequest(form,'Need this tool');
 assert.equal(form.submit.textContent,'신청 중…');assert.equal(form.submit.disabled,true);assert.equal(form.elements.reason.disabled,true);
 await h.context.submitAccessRequest(form,'duplicate');assert.equal(h.calls.length,1);
 assert.equal(h.calls[0].url,'/api/tools/1/requests');assert.deepEqual({...h.calls[0].body},{reason:'Need this tool'});
 h.calls[0].resolve(reply('pending'));await operation;
 assert.match(h.last().html,/승인 대기/);assert.match(h.last().html,/신청 취소/);assert.equal(h.calls.length,1);
});

test('cancel waits for confirmation and uses the reviewed attempt revision',async()=>{
 const h=setup();h.pending();h.context.actions['cancel-access-request'](click(1));assert.equal(h.calls.length,0);
 const operation=h.context.confirm();assert.match(h.last().html,/취소 중…/);assert.equal(h.calls.length,1);
 assert.equal(h.calls[0].url,'/api/tools/1/requests/cancel');assert.equal(h.calls[0].body.expectedRevision,'a'.repeat(32));
 await h.context.actions['cancel-access-request'](click(1));assert.equal(h.calls.length,1);
 h.calls[0].resolve(reply('none',{requestStatus:'cancelled',cancelled:true}));await operation;
 assert.match(h.last().html,/신청을 취소했어요/);assert.match(h.last().html,/권한 신청하기/);assert.doesNotMatch(h.last().html,/data-action="cancel-access-request"/);
});

test('an unknown request outcome offers only read-only reconciliation before reapplying and preserves the reason',async()=>{
 const h=setup(),operation=h.context.submitAccessRequest(h.openRequest(),'Preserve <reason>');
 h.calls[0].reject(Error('secret internal error'));await operation;
 assert.match(h.last().html,/신청 상태 확인/);assert.doesNotMatch(h.last().html,/secret|data-action="request-access"/);
 h.context.requestAccess();assert.doesNotMatch(h.last().html,/sq-access-form/);
 const check=h.context.actions['access-status-check'](click(1));assert.equal(h.calls[1].method,'GET');assert.equal(h.calls[1].url,'/api/tools/1/access-status');
 assert.match(h.last().html,/상태 확인 중…/);h.calls[1].resolve(reply('none'));await check;
 h.context.requestAccess();assert.match(h.last().html,/Preserve &lt;reason>/);assert.equal(h.calls.filter(c=>c.method==='POST').length,1);
});

test('stale cancellation does not pretend cancellation succeeded or replay a write; known pending can be cancelled anew',async()=>{
 const h=setup();h.pending();h.context.actions['cancel-access-request'](click(1));let operation=h.context.confirm();
 h.calls[0].reject(Object.assign(Error('stale revision'),{status:409}));await operation;
 assert.match(h.last().html,/취소 결과를 확인하지 못했어요/);assert.doesNotMatch(h.last().html,/data-action="cancel-access-request"|신청을 취소했어요/);
 operation=h.context.actions['access-status-check'](click(1));h.calls[1].resolve(reply('pending',{requestRevision:'b'.repeat(32)}));await operation;
 h.context.actions['cancel-access-request'](click(1));operation=h.context.confirm();assert.equal(h.calls[2].body.expectedRevision,'b'.repeat(32));
 h.calls[2].resolve(reply('none',{requestStatus:'cancelled',cancelled:true}));await operation;
});

test('failed reconciliation leaves only status retry without duplicate requests',async()=>{
 const h=setup(),operation=h.context.submitAccessRequest(h.openRequest(),'Reason');h.calls[0].reject(Error('offline'));await operation;
 const check=h.context.actions['access-status-check'](click(1));h.calls[1].reject(Error('offline'));await check;
 assert.match(h.last().html,/신청 상태를 확인하지 못했어요/);assert.doesNotMatch(h.last().html,/data-action="request-access"|data-action="cancel-access-request"/);
 assert.equal(h.calls.filter(c=>c.method==='POST').length,1);
});

test('a late mutation updates its tool but never replaces another dialog',async()=>{
 const h=setup(),operation=h.context.submitAccessRequest(h.openRequest(),'Reason');h.context.openModal('Registration','', 'Unsaved fields');
 h.calls[0].resolve(reply('pending'));await operation;
 assert.equal(h.last().title,'Registration');assert.equal(h.items[0].access,'pending');
});

test('an account switch drops the late mutation result',async()=>{
 const h=setup(),operation=h.context.submitAccessRequest(h.openRequest(),'Reason');h.context.server.user.id='two';h.context.openModal('New account');
 h.calls[0].resolve(reply('pending'));await operation;
 assert.equal(h.items[0].access,'none');assert.equal(h.last().title,'New account');
});

test('another tool is not blocked by a pending request',async()=>{
 const h=setup(),operation=h.context.submitAccessRequest(h.openRequest(),'Reason');h.context.runtime.detailId=2;h.context.requestAccess();
 assert.match(h.last().html,/data-tool-id="2"/);assert.doesNotMatch(h.last().html,/신청 중…/);
 h.calls[0].resolve(reply('pending'));await operation;assert.match(h.last().html,/data-tool-id="2"/);
});

test('approval won a cancellation race: confirmed access stays approved even if the detail read fails',async()=>{
 const h=setup();h.pending();h.context.actions['cancel-access-request'](click(1));const operation=h.context.confirm();
 h.calls[0].resolve(reply('approved',{requestStatus:'approved',cancelled:false}));await tick();
 assert.equal(h.calls[1].url,'/api/tools/1');h.calls[1].reject(Error('unavailable'));await operation;
 assert.equal(h.items[0].access,'approved');assert.equal(h.last().title,'사용 권한을 확인했어요.');assert.match(h.last().html,/상세 다시 열기/);
 assert.doesNotMatch(h.context.accessRequestControls(h.items[0]),/신청 상태 확인|취소 중/);
});

test('leaving the reviewed modal invalidates its later cancellation confirmation',()=>{
 const h=setup();h.pending();h.context.actions['cancel-access-request'](click(1));h.context.openModal('Other');h.context.confirm();assert.equal(h.calls.length,0);
});

test('workspace approval snapshots the reviewed application revision instead of using a later application',async()=>{
 const h=setup();h.decisions.push({id:'request-one',requestRevision:'a'.repeat(32)});
 h.context.actions['access-decision']({dataset:{request:'request-one',status:'승인'}});
 h.decisions[0].requestRevision='b'.repeat(32);
 const form={dataset:{workForm:'access'},data:{reason:'Reviewed'},querySelectorAll:()=>[]};
 h.listeners.submit[0]({target:form,preventDefault(){},stopImmediatePropagation(){}});
 assert.equal(h.calls[0].body.expectedRevision,'a'.repeat(32));h.calls[0].reject(Object.assign(Error('stale revision'),{status:409}));await tick();
 assert.match(h.errors[0],/stale/);assert.equal(h.dialog.open,true);
});

test('base submit source routes access requests to scoped handlers and legacy rejection snapshots are maintained',()=>{
 const submit=fs.readFileSync(path.join(__dirname,'../frontend/frontend_submit.js'),'utf8');
 const api=fs.readFileSync(path.join(__dirname,'../frontend/frontend_api.js'),'utf8');
 const built=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
 for(const line of submit.split(/\r?\n/).filter(line=>/sq-access-form|sq-reject-form/.test(line)))assert.ok(built.includes(line));
 assert.ok(built.replaceAll('\r','').includes(source.replaceAll('\r','').trim()));
 assert.match(submit,/submitAccessRequest\(form,data.reason\)/);
 assert.match(submit,/expectedRevision:form.dataset.requestRevision/);
 assert.match(built,/sq-reject-form" data-request="\$\{r.id\}" data-request-revision=/);
 assert.ok(built.includes(api.split('\n').find(line=>line.startsWith('actions.approve='))));
});
