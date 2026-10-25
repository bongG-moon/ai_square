// Exercise the real workspace handlers with controllable network responses.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_workspace.js'),'utf8');

function deferred(){let resolve,reject;const promise=new Promise((ok,fail)=>{resolve=ok;reject=fail;});return {promise,resolve,reject};}
function setup(){
 const requests=[],refreshes=[],listeners={},opened=[],viewRequests=[];
 const inert={append(){},remove(){},insertAdjacentHTML(){},addEventListener(){}};
 const dialog={open:false,addEventListener(event,fn){(listeners[event]??=[]).push(fn);}};
 const items=[{id:1,name:'First',comments:[],likes:0},{id:2,name:'Second',comments:[],likes:0}];
 const context={runtime:{},state:{route:'home'},server:{user:{id:'me',role:'user'}},items,
  root:{addEventListener(){}},document:{createElement:()=>({...inert}),addEventListener(){}},window:{addEventListener(){}},
  $:selector=>selector==='#sq-dialog'?dialog:['#sq-main','.sq-header nav','.sq-header-actions','.sq-header-actions [data-action="manage"]','.sq-detail-top .sq-row-actions'].includes(selector)?inert:null,
  $$:()=>[],setInterval(){},esc:String,button:()=>'',icon:()=>'',mountIcons(){},decoratePackageForm(){},deploymentLinks(){},
  getItem:id=>items.find(x=>x.id===+id),render(){},manage(){},showError(){},
  requestAPI:(url,method,body)=>{const request=deferred();(url.endsWith('/view')?viewRequests:requests).push({...request,url,method,body});return request.promise;},
  refresh:()=>{const request=deferred();refreshes.push(request);return request.promise;},
  openModal(title){dialog.open=true;opened.push(title);},closeModal(){dialog.open=false;},
  navigate(route){context.state.route=route;},
  detail(id,tab){context.runtime.detailId=+id;context.runtime.detailTab=tab;context.openModal(context.getItem(id).name);},
 };
 context.actions={'close-dialog':context.closeModal};
 vm.createContext(context);vm.runInContext(source,context,{filename:'frontend_workspace.js'});
 return {context,requests,refreshes,dialog,opened,items,viewRequests,emit:event=>listeners[event]?.forEach(fn=>fn())};
}
const fresh={likes:3,liked:false,marker:'fresh'};

test('an authorized detail still opens normally and reports that it rendered',async()=>{
 const h=setup(),pending=h.context.detail(1);
 h.requests.shift().resolve(fresh);
 assert.equal(await pending,true);assert.deepEqual(h.opened,['First']);
 assert.equal(h.items[0].marker,'fresh');assert.equal(h.context.runtime.detailTab,'intro');
});

test('late detail success cannot overwrite a newly opened registration modal',async()=>{
 const h=setup(),pending=h.context.detail(1);
 h.context.openModal('Register','', '<form>unfinished input</form>');
 h.requests.shift().resolve(fresh);
 assert.equal(await pending,false);assert.deepEqual(h.opened,['Register']);
 assert.equal(h.items[0].marker,undefined);assert.equal(h.dialog.open,true);
});

test('the captured close button cancels a pending detail response',async()=>{
 const h=setup();h.context.openModal('Existing detail');const pending=h.context.detail(1,'connect');
 h.context.actions['close-dialog']();h.requests.shift().resolve(fresh);
 assert.equal(await pending,false);assert.equal(h.dialog.open,false);
 assert.deepEqual(h.opened,['Existing detail']);
});

test('Escape dismisses a pending detail, but a queued close event does not cancel a new one',async()=>{
 const h=setup();h.context.openModal('Existing detail');const pending=h.context.detail(1);
 h.emit('cancel');h.dialog.open=false;h.requests.shift().resolve(fresh);
 assert.equal(await pending,false);assert.equal(h.dialog.open,false);
 const next=h.context.detail(2);h.emit('close');h.requests.shift().resolve(fresh);
 assert.equal(await next,true);assert.deepEqual(h.opened,['Existing detail','Second']);
});

test('navigation invalidates an in-flight detail without reopening its dialog',async()=>{
 const h=setup(),pending=h.context.detail(1);h.context.navigate('browse');
 h.requests.shift().resolve(fresh);
 assert.equal(await pending,false);assert.equal(h.context.state.route,'browse');
 assert.equal(h.dialog.open,false);assert.deepEqual(h.opened,[]);
});

test('only the newest detail request renders when responses arrive out of order',async()=>{
 const h=setup(),first=h.context.detail(1),second=h.context.detail(2);
 const old=h.requests.shift(),current=h.requests.shift();current.resolve(fresh);
 assert.equal(await second,true);old.resolve(fresh);assert.equal(await first,false);
 assert.deepEqual(h.opened,['Second']);assert.equal(h.context.runtime.detailId,2);
});

test('stale authorization and server errors do not affect the new modal',async()=>{
 for(const status of [403,500]){
  const h=setup(),pending=h.context.detail(1);h.context.openModal('Register');
  h.requests.shift().reject(Object.assign(Error('Old request failed'),{status}));
  assert.equal(await pending,false);assert.equal(h.refreshes.length,0);
  assert.deepEqual(h.opened,['Register']);
 }
});

test('a forbidden detail refresh cannot replace a newer modal with the permission prompt',async()=>{
 const h=setup(),pending=h.context.detail(1);
 h.requests.shift().reject(Object.assign(Error('Forbidden'),{status:403}));
 await new Promise(setImmediate);assert.equal(h.refreshes.length,1);
 h.context.openModal('Register');h.refreshes.shift().resolve();
 assert.equal(await pending,false);assert.deepEqual(h.opened,['Register']);
});

test('current access denial still shows the permission prompt and current errors still reject',async()=>{
 const h=setup(),pending=h.context.detail(1);
 h.requests.shift().reject(Object.assign(Error('Forbidden'),{status:403}));
 await new Promise(setImmediate);h.refreshes.shift().resolve();
 assert.equal(await pending,false);assert.deepEqual(h.opened,['조회 권한이 필요합니다.']);
 const current=h.context.detail(1);h.requests.shift().reject(Object.assign(Error('Service unavailable'),{status:503}));
 await assert.rejects(current,/Service unavailable/);
});

test('views count once for a visible detail, not on tab changes or permission denial',async()=>{
 const h=setup();let pending=h.context.detail(1);h.requests.shift().resolve(fresh);await pending;
 assert.equal(h.viewRequests.length,1);assert.equal(h.viewRequests[0].method,'POST');
 pending=h.context.detail(1,'connect');h.requests.shift().resolve(fresh);await pending;
 assert.equal(h.viewRequests.length,1);
 h.context.actions['close-dialog']();pending=h.context.detail(1);h.requests.shift().resolve(fresh);await pending;
 assert.equal(h.viewRequests.length,2);
 h.context.actions['close-dialog']();pending=h.context.detail(2);h.requests.shift().reject(Object.assign(Error('Forbidden'),{status:403}));
 await new Promise(setImmediate);h.refreshes.shift().resolve();await pending;
 assert.equal(h.viewRequests.length,2);
});

test('a delayed or failed view write does not reopen a closed detail',async()=>{
 const h=setup(),pending=h.context.detail(1);h.requests.shift().resolve(fresh);await pending;
 h.context.actions['close-dialog']();h.viewRequests.shift().resolve({views:7});await new Promise(setImmediate);
 assert.equal(h.dialog.open,false);assert.equal(h.items[0].views,7);assert.deepEqual(h.opened,['First']);
 const next=h.context.detail(2);h.requests.shift().resolve(fresh);await next;
 h.viewRequests.shift().reject(Error('Offline'));await new Promise(setImmediate);
 assert.equal(h.dialog.open,true);assert.equal(h.context.runtime.detailId,2);
});
