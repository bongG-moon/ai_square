// Run the maintained request handlers with controlled write/read completions.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_workspace.js'),'utf8');
const tick=()=>new Promise(setImmediate);
function deferred(){let resolve,reject;const promise=new Promise((ok,fail)=>{resolve=ok;reject=fail;});return {promise,resolve,reject};}
const idea={id:9,name:'장비 점검 비교',body:'여러 장비를 함께 비교하고 싶어요.',category:'공통 업무',created:1,status:'접수 대기',assignee:null,author:'요청자',replies:[],attachments:[],revision:0};

function setup(role='admin'){
 const requests=[],errors=[],announcements=[],listeners={},opened=[],navigated=[];
 const inert={append(){},remove(){},insertAdjacentHTML(){},addEventListener(){}};
 const dialog={open:false,addEventListener(){}},workspace={...inert,innerHTML:''},pageError={hidden:true,textContent:'',isConnected:true};
 class FormData{
  constructor(form){this.values=form?[...form.entries]:[];}
  append(name,value){this.values.push([name,value]);}
  [Symbol.iterator](){return this.values[Symbol.iterator]();}
 }
 const context={runtime:{},state:{route:'ideas'},server:{user:{id:'requester',role},categories:[{name:'공통 업무',enabled:true}]},items:[],
  root:{addEventListener:(name,fn)=>{(listeners[name]??=[]).push(fn);}},
  document:{createElement:()=>workspace,addEventListener(){}},window:{addEventListener(){}},
  $:selector=>selector==='#sq-dialog'?dialog:selector==='#sq-server-error'?pageError:['#sq-main','.sq-header nav','.sq-header-actions','.sq-header-actions [data-action="manage"]'].includes(selector)?inert:null,
  $$:()=>[],setInterval(){},esc:String,button:(action,text,cls='',extra='')=>`<button data-action="${action}" ${extra}>${text}</button>`,icon:()=>'',mountIcons(){},FormData,
  render(){},manage(){},detail(){},options:values=>values.map(value=>`<option>${value}</option>`).join(''),uploadArea:()=>'',attachmentLinks:()=>'',
  openModal(title,kicker,html){dialog.open=true;opened.push({title,html});},closeModal(){dialog.open=false;},navigate(route){context.state.route=route;navigated.push(route);},
  announce:message=>announcements.push(message),showError:error=>{errors.push(error);if(!dialog.open){pageError.textContent=error.message;pageError.hidden=false;}},
  requestAPI:(url,method='GET',body)=>{const request=deferred();requests.push({...request,url,method,body});return request.promise;},
 };
 context.actions={'close-dialog':context.closeModal};
 vm.createContext(context);vm.runInContext(source+'\nglobalThis.workState=work;',context,{filename:'frontend_workspace.js'});
 function newForm(){
  context.actions.idea();
  const button={disabled:false},node={dataset:{workForm:'idea'},entries:[['name',idea.name],['desc',idea.body],['category',idea.category]],querySelectorAll:()=>[button]};
  return {node,button,submit:()=>listeners.submit[0]({target:node,preventDefault(){},stopImmediatePropagation(){}})};
 }
 return {context,requests,errors,announcements,opened,navigated,dialog,workspace,pageError,newForm};
}

test('new request saves attachments once, closes the composer and returns to a list containing the request',async()=>{
 const h=setup(),form=h.newForm(),file={name:'screen.png'};h.context.workState.ideaFiles=[file];h.context.workState.ideaFilter='구현 완료';
 form.submit();form.submit();assert.equal(h.requests.length,1);assert.equal(form.button.disabled,true);
 const post=h.requests[0];assert.equal(post.url,'/api/ideas');assert.equal(post.method,'POST');
 assert.deepEqual(JSON.parse(post.body.values.find(([name])=>name==='metadata')[1]),{name:idea.name,desc:idea.body,category:idea.category});
 assert.equal(post.body.values.find(([name])=>name==='attachments')[1],file);
 post.resolve({ok:true,id:idea.id});await tick();
 assert.equal(h.dialog.open,false);assert.equal(h.context.state.route,'ideas');assert.equal(h.context.workState.ideaFilter,'전체');
 assert.equal(h.context.workState.ideaFiles.length,0);assert.equal(form.node.dataset.saved,'true');
 assert.equal(h.requests.length,2);assert.equal(h.requests[1].method,'GET');h.requests[1].resolve({ideas:[idea]});await tick();
 assert.equal(h.opened.length,1);assert.equal(h.requests.length,2);assert.match(h.workspace.innerHTML,/data-action="idea-open" data-id="9"/);
 assert.match(h.workspace.innerHTML,/장비 점검 비교/);assert.deepEqual(h.announcements,['기능 요청을 등록했습니다.']);
 form.submit();assert.equal(h.requests.length,2);assert.equal(h.errors.length,0);
});

test('a failed primary write retains entered content and files and allows a deliberate retry',async()=>{
 const h=setup(),form=h.newForm(),files=[{name:'screen.png'}];h.context.workState.ideaFiles=files;h.context.workState.ideaFilter='개발 중';
 form.submit();const failure=Error('Save unavailable');h.requests[0].reject(failure);await tick();
 assert.equal(h.errors[0],failure);assert.equal(h.dialog.open,true);assert.equal(form.node.dataset.saved,undefined);assert.equal(form.button.disabled,false);
 assert.equal(h.context.workState.ideaFiles,files);assert.equal(form.node.entries[0][1],idea.name);assert.equal(h.context.workState.ideaFilter,'개발 중');
 assert.equal(h.requests.length,1);assert.deepEqual(h.navigated,[]);assert.deepEqual(h.announcements,[]);
 form.submit();assert.equal(h.requests.length,2);h.requests[1].reject(failure);await tick();
});

test('list refresh failure after a saved request reports saved status without retaining an actionable submit form',async()=>{
 const h=setup(),form=h.newForm();h.context.workState.ideaFiles=[{name:'screen.png'}];form.submit();
 h.requests[0].resolve({ok:true,id:9});await tick();h.requests[1].reject(Error('List unavailable'));await tick();
 assert.equal(h.dialog.open,false);assert.equal(h.context.state.route,'ideas');assert.equal(h.context.workState.ideaFiles.length,0);
 assert.equal(h.errors.length,1);assert.equal(h.errors[0].saved,true);assert.match(h.errors[0].message,/서버에 저장되었습니다/);
 assert.equal(form.node.dataset.saved,'true');assert.equal(form.button.disabled,true);form.submit();assert.equal(h.requests.length,2);
 assert.equal(h.opened.length,1);assert.deepEqual(h.announcements,[]);
});

test('clicking a registered request opens its reply and permitted status controls',async()=>{
 for(const role of ['admin','user']){
  const h=setup(role),pending=h.context.actions['idea-open']({dataset:{id:'9'}});
  assert.equal(h.opened.length,0);h.requests[0].resolve({ideas:[idea]});await pending;
  assert.equal(h.dialog.open,true);assert.equal(h.opened[0].title,idea.name);assert.match(h.opened[0].html,/data-work-form="idea-reply"/);
  assert.equal(h.opened[0].html.includes('name="status"'),role==='admin');assert.equal(h.requests.length,1);
 }
});

test('a late create response does not dismiss a new draft or clear its attachments',async()=>{
 const h=setup(),old=h.newForm();h.context.workState.ideaFiles=[{name:'old.png'}];old.submit();
 h.context.actions['close-dialog']();h.newForm();const newFiles=[{name:'new.png'}];h.context.workState.ideaFiles=newFiles;
 h.requests[0].resolve({ok:true,id:9});await tick();
 assert.equal(h.dialog.open,true);assert.equal(h.opened.length,2);assert.equal(h.context.workState.ideaFiles,newFiles);
 assert.equal(old.node.dataset.saved,'true');assert.equal(h.requests.length,1);assert.deepEqual(h.navigated,[]);
});

test('a late follow-up list failure cannot replace a newer dialog with a saved-status error',async()=>{
 const h=setup(),form=h.newForm();form.submit();h.requests[0].resolve({ok:true,id:9});await tick();
 h.newForm();h.requests[1].reject(Error('Old list unavailable'));await tick();
 assert.equal(h.dialog.open,true);assert.equal(h.opened.length,2);assert.deepEqual(h.errors,[]);
});

test('a later successful request clears only its previous saved-but-list-failed page notice',async()=>{
 const h=setup(),first=h.newForm();first.submit();h.requests[0].resolve({ok:true,id:9});await tick();
 h.requests[1].reject(Error('List unavailable'));await tick();assert.equal(h.pageError.hidden,false);assert.match(h.pageError.textContent,/서버에 저장되었습니다/);
 const second=h.newForm();second.submit();h.requests[2].resolve({ok:true,id:10});await tick();h.requests[3].resolve({ideas:[{...idea,id:10},idea]});await tick();
 assert.equal(h.pageError.hidden,true);assert.equal(h.pageError.textContent,'');assert.deepEqual(h.announcements,['기능 요청을 등록했습니다.']);
 assert.equal(h.requests.filter(request=>request.method==='POST').length,2);
});

test('successful request refresh preserves an unrelated newer page warning',async()=>{
 const h=setup(),first=h.newForm();first.submit();h.requests[0].resolve({ok:true,id:9});await tick();h.requests[1].reject(Error('Old list unavailable'));await tick();
 const second=h.newForm();second.submit();h.requests[2].resolve({ok:true,id:10});await tick();
 h.context.showError(Error('A different operation failed'));h.requests[3].resolve({ideas:[idea]});await tick();
 assert.equal(h.pageError.hidden,false);assert.equal(h.pageError.textContent,'A different operation failed');
});

test('a late request detail does not replace a newer dialog or reopen a dismissed detail',async()=>{
 for(const reject of [false,true]){
  const h=setup(),pending=h.context.actions['idea-open']({dataset:{id:'9'}});h.newForm();
  reject?h.requests[0].reject(Error('Old detail unavailable')):h.requests[0].resolve({ideas:[idea]});
  assert.equal(await pending,false);assert.equal(h.opened.length,1);assert.equal(h.opened[0].title,'어떤 기능이 필요하세요?');
 }
});
