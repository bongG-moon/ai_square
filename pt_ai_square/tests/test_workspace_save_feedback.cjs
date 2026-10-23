// Run the deployed workspace writes and inject primary/follow-up failures separately.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
const base=path.join(__dirname,'..'),read=p=>fs.readFileSync(path.join(base,p),'utf8').replace(/\r\n/g,'\n');
const app=read('static/app.js'),source=app.slice(app.indexOf('// Workspace extension:'),app.indexOf('function fileSize(n)')).trim();
const tick=()=>new Promise(setImmediate);
function deferred(){let resolve,reject;const promise=new Promise((ok,fail)=>{resolve=ok;reject=fail;});return {promise,resolve,reject};}

function setup(){
 const writes=[],reads=[],errors=[],announcements=[],listeners={},confirmations=[];
 const inert={append(){},remove(){},insertAdjacentHTML(){},addEventListener(){}};
 const dialog={open:false,addEventListener(){}};
 const items=[{id:1,name:'Tool',revision:3,comments:[],subscribed:false}];
 const query=label=>{const job=deferred();reads.push({...job,label});return job.promise;};
 class FormData{
  constructor(form){this.values=form?[...form.entries]:[];}
  append(name,value){this.values.push([name,value]);}
  [Symbol.iterator](){return this.values[Symbol.iterator]();}
 }
 const context={runtime:{},state:{route:'home'},server:{user:{id:'owner',role:'admin'}},items,
  root:{addEventListener:(name,fn)=>{(listeners[name]??=[]).push(fn);}},
  document:{createElement:()=>({...inert}),addEventListener(){}},window:{addEventListener(){}},
  $:selector=>selector==='#sq-dialog'?dialog:['#sq-main','.sq-header nav','.sq-header-actions','.sq-header-actions [data-action="manage"]'].includes(selector)?inert:null,
  $$:()=>[],setInterval(){},esc:String,button:()=>'',icon:()=>'',mountIcons(){},FormData,
  getItem:id=>items.find(x=>x.id===+id),render(){},manage(){},detail(){},
  openModal(){dialog.open=true;},closeModal(){dialog.open=false;},navigate(route){context.state.route=route;},
  announce:message=>announcements.push(message),showError:error=>errors.push(error),
  ask:(title,body,callback)=>confirmations.push(callback),
  requestAPI:(url,method='GET',body)=>{if(method==='GET')return query(url);const job=deferred();writes.push({...job,url,method,body});return job.promise;},
  refresh:()=>query('refresh'),
 };
 context.actions={'close-dialog':context.closeModal};
 vm.createContext(context);vm.runInContext(source+'\nglobalThis.workState=work;',context,{filename:'static/app.js workspace'});
 Object.assign(context,{detail:()=>query('detail'),ideaDetail:()=>query('ideaDetail'),loadIdeas:()=>query('loadIdeas'),inbox:()=>query('inbox'),renderWorkspace(){},renderIdeas(){}});
 Object.assign(context.workState,{idea:{id:9,revision:3},feedback:{id:7,tool:1},taxonomy:{id:'category-0',kind:'category'},access:{id:'1:member',status:'승인'},grantTool:1,userMode:'grant',notifications:[{id:'n1',target:{type:'tool',id:1}}]});
 function invoke(action){const result=context.actions[action]({dataset:{id:action==='notification-open'?'n1':action==='idea-claim'?'9':'1',user:'member'}});return confirmations.length?confirmations.shift()():result;}
 function form(kind){
  const button={disabled:false},node={dataset:{workForm:kind},entries:[['name','Example'],['desc','Description'],['reason','Reason'],['order','1'],['enabled','true'],['text','Reply'],['status','접수'],['tool','1']],querySelectorAll:()=>[button]};
  return {node,button,submit:()=>listeners.submit[0]({target:node,preventDefault(){},stopImmediatePropagation(){}})};
 }
 return {context,writes,reads,errors,announcements,invoke,form};
}

test('deployed workspace matches its maintained source',()=>assert.equal(source,read('frontend/frontend_workspace.js').trim()));

const cases=[['idea-claim'],['subscribe'],['delete-tool'],['restore-tool'],['choose-user','grant'],['choose-user','admin'],['remove-admin'],['read-all'],['notification-open']];
for(const [action,mode] of cases){
 test(`${action}${mode?':'+mode:''} distinguishes a confirmed save from follow-up failure`,async()=>{
  const h=setup();if(mode)h.context.workState.userMode=mode;
  const pending=h.invoke(action);assert.equal(h.writes.length,1);h.writes[0].resolve({ok:true});await tick();
  assert.equal(h.reads.length,1);h.reads[0].reject(Error('Read unavailable'));
  await assert.rejects(pending,error=>error.saved===true&&/서버에 저장되었습니다/.test(error.message)&&/Read unavailable/.test(error.message));
  assert.equal(h.writes.length,1);assert.deepEqual(h.announcements,[]);
 });
 test(`${action}${mode?':'+mode:''} leaves a primary write failure unchanged`,async()=>{
  const h=setup();if(mode)h.context.workState.userMode=mode;
  const pending=h.invoke(action),failure=Object.assign(Error('Primary write unavailable'),{status:503});
  h.writes[0].reject(failure);await assert.rejects(pending,error=>error===failure&&!error.saved);
  assert.equal(h.writes.length,1);assert.equal(h.reads.length,0);assert.deepEqual(h.announcements,[]);
 });
}

for(const kind of ['idea','idea-reply','feedback','taxonomy','access']){
 test(`${kind} form retains confirmed success and blocks duplicate resubmission when its read fails`,async()=>{
  const h=setup(),form=h.form(kind);form.submit();assert.equal(h.writes.length,1);assert.equal(form.button.disabled,true);
  h.writes[0].resolve({ok:true,id:9});await tick();assert.equal(form.node.dataset.saved,'true');
  assert.equal(h.reads.length,1);h.reads[0].reject(Error('Read unavailable'));await tick();
  assert.equal(h.errors.length,1);assert.equal(h.errors[0].saved,true);assert.match(h.errors[0].message,/서버에 저장되었습니다/);
  assert.equal(form.node.dataset.busy,undefined);assert.equal(form.button.disabled,true);
  form.submit();assert.equal(h.writes.length,1);
 });
 test(`${kind} form primary failure is unchanged and permits a deliberate retry`,async()=>{
  const h=setup(),form=h.form(kind),failure=Object.assign(Error('Primary write unavailable'),{status:503});form.submit();
  h.writes[0].reject(failure);await tick();assert.equal(h.errors[0],failure);assert.equal(h.reads.length,0);
  assert.equal(form.node.dataset.saved,undefined);assert.equal(form.button.disabled,false);
  form.submit();assert.equal(h.writes.length,2);h.writes[1].reject(failure);await tick();
 });
}

test('successful grant still refreshes once and announces completion without changing its request',async()=>{
 const h=setup(),pending=h.invoke('choose-user');
 assert.equal(h.writes[0].url,'/api/tools/1/grants');assert.equal(h.writes[0].method,'POST');assert.equal(h.writes[0].body.user,'member');
 h.writes[0].resolve({ok:true});await tick();h.reads[0].resolve({});await pending;
 assert.deepEqual(h.announcements,['권한을 부여했습니다.']);assert.equal(h.writes.length,1);assert.equal(h.errors.length,0);
});

test('a successful idea registration follows its normal list/detail path without replaying its POST',async()=>{
 const h=setup(),form=h.form('idea');form.submit();h.writes[0].resolve({ok:true,id:9});await tick();
 assert.equal(h.reads[0].label,'loadIdeas');h.reads[0].resolve({});await tick();
 assert.equal(h.reads[1].label,'ideaDetail');h.reads[1].resolve({});await tick();
 assert.equal(h.context.state.route,'ideas');assert.equal(h.writes.length,1);assert.equal(h.errors.length,0);
});
