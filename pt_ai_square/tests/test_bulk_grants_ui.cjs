// Run maintained permission handlers with independently controlled HTTP completions.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_grants.js'),'utf8');
const plain=value=>JSON.parse(JSON.stringify(value));
const tick=()=>new Promise(setImmediate);
function deferred(){let resolve,reject;const promise=new Promise((ok,fail)=>{resolve=ok;reject=fail;});return {promise,resolve,reject};}
const snapshot={users:[],departments:[],revision:4};
const employees=[{id:'1001',name:'김하늘',dept:'융합기술'},{id:'1002',name:'이바다',dept:'기술팀'},{id:'1003',name:'박별',dept:'제조팀'}];
const departments=[{id:'first',code:'D1',name:'기술팀',memberCount:3},{id:'second',code:'D2',name:'기술팀',memberCount:8}];

function setup(){
 const requests=[],errors=[],opened=[],confirmations=[],listeners={};
 const nodes={'#sq-dialog':{open:false},'#sq-dialog-body':{innerHTML:''},'#ws-grant-preview':{innerHTML:''},'#ws-grant-notice':{textContent:''},'#ws-grant-save':{disabled:true,textContent:''}};
 const items=[{id:7,name:'메모 도구',org:'공통',type:'Skill',icon:'file',approval:true,canManage:true},{id:8,name:'다른 도구',approval:true,canManage:false}];
 const context={runtime:{detailLoadToken:0},actions:{},items,Set,Map,encodeURIComponent,
  root:{addEventListener:(name,fn)=>(listeners[name]??=[]).push(fn)},
  $:selector=>nodes[selector]||null,getItem:id=>items.find(item=>item.id===id),
  esc:value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;'),
  icon:name=>`<i data-icon="${name}"></i>`,mountIcons(){},blank:()=>'<p>Empty</p>',
  button:(action,label,cls='',extra='')=>`<button data-action="${action}" class="${cls}" ${extra}>${label}</button>`,
  openModal(title,kicker,html){context.runtime.detailLoadToken++;nodes['#sq-dialog'].open=true;nodes['#sq-dialog-body'].innerHTML=html;opened.push({title,kicker,html});},
  showError:error=>errors.push(error),ask:(title,message,callback,label)=>confirmations.push({title,message,callback,label}),
  refreshCount:0,async refresh(){context.refreshCount++;},
  requestAPI:(url,method='GET',body)=>{const request=deferred();requests.push({...request,url,method,body});return request.promise;},
 };
 vm.createContext(context);vm.runInContext(source,context,{filename:'frontend_grants.js'});
 const state=()=>vm.runInContext('grantState',context);
 function input(value){listeners.input[0]({target:{value,matches:selector=>selector==='[data-grant-input]'}});}
 function select(key,checked=true){listeners.change[0]({target:{checked,dataset:{grantSelect:key},matches:selector=>selector==='[data-grant-select]'}});}
 function departmentInput(value){listeners.change[0]({target:{value,matches:selector=>selector==='[data-grant-department-input]'}});}
 async function open(result=snapshot){const pending=context.openGrantManager(7);requests.at(-1).resolve(result);await pending;return state();}
 function preview(value){input(value);const pending=context.previewGrantTargets(state());return {pending,request:requests.at(-1)};}
 async function people(rows=employees,unknown=[]){const next=preview(rows.map(row=>row.id).join(', '));next.request.resolve({mode:'users',users:rows,unknown});await next.pending;}
 function replaceDialog(){context.openModal('새 작업','', '<p>NEW DIALOG</p>');}
 return {context,nodes,requests,errors,opened,confirmations,listeners,state,input,select,departmentInput,open,preview,people,replaceDialog,
  html:()=>nodes['#sq-dialog-body'].innerHTML,saveButton:nodes['#ws-grant-save']};
}

test('only a manageable tool opens permission management and initial snapshot renders existing grants',async()=>{
 const h=setup();await assert.rejects(h.context.openGrantManager(8),/등록자 또는 관리자/);assert.equal(h.requests.length,0);assert.equal(h.opened.length,0);
 await h.open({revision:9,users:[{...employees[0],requestId:'7:1001',source:'직접 추가'}],departments:[departments[0]]});
 assert.equal(h.requests[0].url,'/api/tools/7/grants');assert.equal(h.requests[0].method,'GET');
 assert.match(h.html(),/김하늘/);assert.match(h.html(),/부서 코드 D1/);assert.match(h.html(),/data-action="grant-revoke-user"/);
 assert.equal(h.state().snapshot.revision,9);assert.equal(h.saveButton.disabled,true);
});

test('preview binds exact input, enables confirmed users, and editing immediately invalidates it',async()=>{
 const h=setup();await h.open();const p=h.preview('1001, 1002\n1001');
 assert.equal(p.request.url,'/api/tools/7/grants/preview');assert.deepEqual(plain(p.request.body),{mode:'users',value:'1001, 1002\n1001'});
 p.request.resolve({mode:'users',users:employees.slice(0,2),unknown:[]});await p.pending;
 assert.equal(h.saveButton.disabled,false);assert.equal(h.saveButton.textContent,'선택한 2명 추가');
 const before=h.requests.length;h.input('1003');
 assert.equal(h.state().preview,null);assert.equal(h.state().selected.size,0);assert.equal(h.saveButton.disabled,true);
 await h.context.saveGrantTargets();assert.equal(h.requests.length,before);
});

test('an unknown employee blocks the batch until input is corrected and checked again',async()=>{
 const h=setup();await h.open();await h.people(employees.slice(0,1),['9999']);
 assert.equal(h.saveButton.disabled,true);assert.match(h.html(),/확인되지 않은 사번: 9999/);
 const count=h.requests.length;await h.context.saveGrantTargets();assert.equal(h.requests.length,count);
 await h.people(employees.slice(0,1));assert.equal(h.saveButton.disabled,false);
});

test('late preview completion cannot restore an approval after typing newer input',async()=>{
 for(const failure of [false,true]){
  const h=setup();await h.open();const p=h.preview('1001');h.input('1002');
  failure?p.request.reject(Error('OLD ERROR')):p.request.resolve({mode:'users',users:employees.slice(0,1),unknown:[]});await p.pending;
  assert.equal(h.state().value,'1002');assert.equal(h.state().preview,null);assert.equal(h.state().notice,'');assert.equal(h.saveButton.disabled,true);assert.deepEqual(h.errors,[]);
 }
});

test('newer preview wins when previous HTTP response arrives last',async()=>{
 const h=setup();await h.open();const first=h.preview('1001'),second=h.preview('1002');
 second.request.resolve({mode:'users',users:[employees[1]],unknown:[]});await second.pending;
 first.request.resolve({mode:'users',users:[employees[0]],unknown:[]});await first.pending;
 assert.deepEqual(plain(h.state().preview.users),[employees[1]]);assert.equal(h.state().value,'1002');assert.equal(h.saveButton.textContent,'선택한 1명 추가');
});

test('changing mode discards selected people and ignores the previous mode response',async()=>{
 const h=setup();await h.open();const old=h.preview('1001');
 h.context.actions['grant-mode']({dataset:{mode:'department'}});
 old.request.resolve({mode:'users',users:employees,unknown:[]});await old.pending;
 assert.equal(h.state().mode,'department');assert.equal(h.state().preview,null);assert.equal(h.state().selected.size,0);assert.equal(h.state().value,'');
 assert.equal(h.saveButton.disabled,true);assert.match(h.html(),/부서 코드 여러 개/);
});

test('closed or replaced dialogs ignore late preview success and failure',async()=>{
 for(const replaced of [false,true])for(const failure of [false,true]){
  const h=setup();await h.open();const p=h.preview('1001');
  if(replaced)h.replaceDialog();else h.nodes['#sq-dialog'].open=false;
  const before=h.html();failure?p.request.reject(Error('OLD PREVIEW')):p.request.resolve({mode:'users',users:employees,unknown:[]});await p.pending;
  assert.equal(h.html(),before);assert.equal(h.state().preview,null);assert.deepEqual(h.errors,[]);
 }
});

test('bulk save is single-flight and partial failure retries only unresolved employees',async()=>{
 const h=setup();await h.open();await h.people();
 const first=h.context.saveGrantTargets();await h.context.saveGrantTargets();
 assert.equal(h.requests.filter(request=>request.url==='/api/tools/7/grants'&&request.method==='POST').length,1);
 const post=h.requests.at(-1);assert.deepEqual(plain(post.body),{users:['1001','1002','1003']});assert.equal(h.state().busy,true);assert.equal(h.saveButton.disabled,true);
 h.context.actions['grant-mode']({dataset:{mode:'department'}});assert.equal(h.state().mode,'users');
 post.resolve({ok:false,saved:['1001'],alreadyGranted:['1002'],failed:[{id:'1003',error:'Temporary error'}],pending:true});await tick();
 assert.equal(h.requests.at(-1).method,'GET');h.requests.at(-1).resolve({...snapshot,users:employees.slice(0,2)});await first;
 assert.deepEqual(plain(h.state().preview.users),[employees[2]]);assert.deepEqual([...h.state().selected],['1003']);
 assert.match(h.state().notice,/1명 추가/);assert.match(h.state().notice,/1명은 이미 권한/);assert.match(h.state().notice,/1003/);assert.equal(h.saveButton.disabled,false);
 const retry=h.context.saveGrantTargets(),retryPost=h.requests.at(-1);assert.deepEqual(plain(retryPost.body),{users:['1003']});
 retryPost.resolve({ok:true,saved:['1003'],alreadyGranted:[],failed:[],pending:false});await tick();h.requests.at(-1).resolve({...snapshot,users:employees});await retry;
 assert.equal(h.state().preview,null);assert.equal(h.state().value,'');assert.equal(h.saveButton.disabled,true);assert.equal(h.context.refreshCount,2);
});

test('a confirmed save with failed reload reports saved status instead of permitting duplicate submission',async()=>{
 const h=setup();await h.open();await h.people([employees[0]]);const save=h.context.saveGrantTargets();
 h.requests.at(-1).resolve({ok:true,saved:['1001'],alreadyGranted:[],failed:[]});await tick();h.requests.at(-1).reject(Error('List offline'));await save;
 assert.equal(h.state().preview,null);assert.match(h.state().notice,/1명 추가/);assert.match(h.state().notice,/목록을 갱신하지 못했습니다/);assert.equal(h.saveButton.disabled,true);
 const count=h.requests.length;await h.context.saveGrantTargets();assert.equal(h.requests.length,count);
});

test('a write error retains reviewed targets, unlocks controls and reports uncertain outcome explicitly',async()=>{
 for(const uncertain of [false,true]){
  const h=setup();await h.open();await h.people([employees[0]]);const save=h.context.saveGrantTargets(),error=Error('Write failed');error.uncertain=uncertain;
  h.requests.at(-1).reject(error);await save;assert.equal(h.state().busy,false);assert.equal(h.saveButton.disabled,false);assert.deepEqual(plain(h.state().preview.users),[employees[0]]);
  assert.match(h.state().notice,uncertain?/반영 여부를 확인/:/Write failed/);
 }
});

test('a late save response cannot alter or close a newer dialog',async()=>{
 const h=setup();await h.open();await h.people([employees[0]]);const save=h.context.saveGrantTargets(),request=h.requests.at(-1);
 h.replaceDialog();const count=h.requests.length;request.resolve({ok:true,saved:['1001'],alreadyGranted:[],failed:[]});await save;
 assert.match(h.html(),/NEW DIALOG/);assert.equal(h.nodes['#sq-dialog'].open,true);assert.equal(h.requests.length,count);assert.equal(h.context.refreshCount,0);
});

test('same-name departments start unchecked and only an explicitly selected department code is saved',async()=>{
 const h=setup();await h.open();h.context.actions['grant-mode']({dataset:{mode:'department'}});h.departmentInput('search');const p=h.preview('기술팀');
 assert.deepEqual(plain(p.request.body),{mode:'department',value:'기술팀',departmentInput:'search'});p.request.resolve({mode:'department',departments,count:2,truncated:false});await p.pending;
 assert.equal(h.state().selected.size,0);assert.equal(h.saveButton.disabled,true);assert.match(h.html(),/부서 코드 D1/);assert.match(h.html(),/부서 코드 D2/);
 h.select('code:D2');assert.equal(h.saveButton.disabled,false);assert.equal(h.saveButton.textContent,'선택한 1개 부서 추가');
 const save=h.context.saveGrantTargets(),post=h.requests.at(-1);
 assert.equal(post.url,'/api/tools/7/grants/departments');assert.deepEqual(plain(post.body),{departments:[{code:'D2',name:'기술팀'}],expectedRevision:4});
 post.resolve({ok:true,departments:[departments[1]],revision:5,pending:false});await tick();h.requests.at(-1).resolve({...snapshot,departments:[departments[1]],revision:5});await save;
 assert.equal(h.state().snapshot.revision,5);assert.equal(h.state().preview,null);assert.match(h.state().notice,/1개 부서 권한/);
});

test('a forged or unselected checkbox value cannot become a grant target',async()=>{
 const h=setup();await h.open();await h.people([employees[0]]);h.select('1001',false);h.select('OTHER');
 assert.equal(h.saveButton.disabled,true);const before=h.requests.length;await h.context.saveGrantTargets();assert.equal(h.requests.length,before);
});

test('new department codes with no users are reviewed together and saved with their matching mode',async()=>{
 const h=setup();await h.open();h.context.actions['grant-mode']({dataset:{mode:'department'}});
 assert.equal(h.state().departmentInput,'code');
 const p=h.preview('  D001 ,  D 002  ');
 assert.deepEqual(plain(p.request.body),{mode:'department',departmentInput:'code',value:'D001 ,  D 002'});
 const rows=[{id:'a',code:'D001',name:'D001',match:'code',memberCount:0},{id:'b',code:'D 002',name:'D 002',match:'code',memberCount:0}];
 p.request.resolve({mode:'department',departments:rows,count:2,truncated:false});await p.pending;
 assert.equal(h.saveButton.disabled,false);assert.equal(h.saveButton.textContent,'선택한 2개 부서 추가');assert.match(h.html(),/플랫폼 등록 0명/);
 const save=h.context.saveGrantTargets(),post=h.requests.at(-1);
 assert.deepEqual(plain(post.body),{departments:rows.map(({code,name,match})=>({code,name,match})),expectedRevision:4});
 // A matching-mode change cannot reinterpret the reviewed batch during a write.
 h.departmentInput('name');assert.equal(h.state().departmentInput,'code');
 post.resolve({ok:true,revision:5,departments:rows});await tick();h.requests.at(-1).resolve({...snapshot,revision:5,departments:rows});await save;
 assert.equal(h.state().preview,null);assert.match(h.html(),/D 002/);assert.equal(h.state().snapshot.revision,5);
});

test('direct names preserve internal spaces and save exact-name semantics without inferred codes',async()=>{
 const h=setup();await h.open();h.context.actions['grant-mode']({dataset:{mode:'department'}});h.departmentInput('name');
 const p=h.preview(' 제조  기술팀, 품질 분석팀 ');
 assert.deepEqual(plain(p.request.body),{mode:'department',departmentInput:'name',value:'제조  기술팀, 품질 분석팀'});
 const rows=[{id:'name-a',code:'',name:'제조  기술팀',match:'name',memberCount:2},{id:'name-b',code:'',name:'품질 분석팀',match:'name',memberCount:0}];
 p.request.resolve({mode:'department',departments:rows});await p.pending;
 assert.match(h.html(),/같은 SSO 부서명을 가진 모든 구성원/);assert.match(h.html(),/SSO 부서명 정확히 일치/);
 h.select('name:품질 분석팀',false);
 const save=h.context.saveGrantTargets(),post=h.requests.at(-1);
 assert.deepEqual(plain(post.body),{departments:[{code:'',name:'제조  기술팀',match:'name'}],expectedRevision:4});
 post.resolve({ok:true,revision:5});await tick();h.requests.at(-1).resolve({...snapshot,revision:5,departments:[rows[0]]});await save;
 assert.match(h.html(),/제조  기술팀/);assert.match(h.html(),/SSO 부서명 정확히 일치/);
});

test('switching department input invalidates earlier previews and rejects late success or error',async()=>{
 for(const failure of [false,true]){
  const h=setup();await h.open();h.context.actions['grant-mode']({dataset:{mode:'department'}});
  const p=h.preview('D001');h.departmentInput('name');
  failure?p.request.reject(Error('stale result')):p.request.resolve({mode:'department',departments:[{code:'D001',name:'D001',match:'code'}]});await p.pending;
  assert.equal(h.state().departmentInput,'name');assert.equal(h.state().value,'');assert.equal(h.state().preview,null);assert.equal(h.saveButton.disabled,true);assert.equal(h.state().notice,'');
 }
});

test('multiple search terms remain an explicit selection and show truncated result counts',async()=>{
 const h=setup();await h.open();h.context.actions['grant-mode']({dataset:{mode:'department'}});h.departmentInput('search');
 const p=h.preview(' 기술팀, 제조 팀 ');
 assert.deepEqual(plain(p.request.body),{mode:'department',departmentInput:'search',value:'기술팀, 제조 팀'});
 p.request.resolve({mode:'department',departments,count:80,truncated:true});await p.pending;
 assert.equal(h.state().selected.size,0);assert.equal(h.saveButton.disabled,true);assert.match(h.html(),/검색 결과 80개 중 2개/);
});

test('employee, department and error strings are escaped in rendering and data attributes',async()=>{
 const h=setup();await h.open();const attack='<img src=x onerror="alert(1)">';
 await h.people([{id:'1001" autofocus="yes',name:attack,dept:'<script>bad</script>'}],['<script>unknown</script>']);
 assert.ok(!h.html().includes('<img src=x'));assert.ok(!h.html().includes('<script>'));assert.ok(h.html().includes('&lt;img'));assert.ok(h.html().includes('1001&quot; autofocus=&quot;yes'));
 h.context.actions['grant-mode']({dataset:{mode:'department'}});const group=h.preview('팀');
 group.request.resolve({mode:'department',departments:[{id:'x',code:'D" bad="x',name:attack,memberCount:1}]});await group.pending;
 assert.ok(h.html().includes('code:D&quot; bad=&quot;x'));assert.ok(!h.html().includes('<img src=x'));
 const fail=h.preview('다른 팀');fail.request.reject(Error('<script>error</script>'));await fail.pending;
 assert.ok(h.html().includes('&lt;script&gt;error'));assert.ok(!h.html().includes('<script>'));
});

test('department revocation requires confirmation and preserves independent personal grants in the explanation',async()=>{
 const h=setup();await h.open({...snapshot,departments:[departments[0]]});
 await h.context.revokeGrant('department','first');assert.equal(h.requests.length,1);assert.equal(h.confirmations.length,1);assert.match(h.confirmations[0].message,/개인 권한은 유지/);
 const saving=h.confirmations[0].callback(),post=h.requests.at(-1);assert.equal(post.method,'DELETE');assert.equal(post.url,'/api/tools/7/grants/departments/first');assert.deepEqual(plain(post.body),{expectedRevision:4});
 post.resolve({ok:true});await tick();h.requests.at(-1).resolve({...snapshot,revision:5});await saving;
 assert.equal(h.state().snapshot.departments.length,0);assert.match(h.state().notice,/회수했습니다/);
});

test('stale permission snapshots and stale revoke confirmations cannot replace a newer dialog',async()=>{
 const h=setup(),loading=h.context.openGrantManager(7);h.replaceDialog();h.requests[0].resolve(snapshot);await loading;assert.match(h.html(),/NEW DIALOG/);
 await h.open({...snapshot,departments:[departments[0]]});await h.context.revokeGrant('department','first');h.replaceDialog();
 const count=h.requests.length;await h.confirmations[0].callback();assert.equal(h.requests.length,count);assert.match(h.html(),/NEW DIALOG/);
});

test('in-flight revocation completion cannot report an old error or reload into a newer dialog',async()=>{
 for(const failure of [false,true]){
  const h=setup();await h.open({...snapshot,departments:[departments[0]]});await h.context.revokeGrant('department','first');
  const saving=h.confirmations[0].callback(),request=h.requests.at(-1);assert.equal(h.state().busy,true);
  h.replaceDialog();const count=h.requests.length;
  failure?request.reject(Error('OLD REVOCATION ERROR')):request.resolve({ok:true});
  await assert.doesNotReject(saving);
  assert.match(h.html(),/NEW DIALOG/);assert.equal(h.nodes['#sq-dialog'].open,true);assert.equal(h.requests.length,count);
  assert.equal(h.context.refreshCount,0);assert.equal(h.state().busy,false);assert.deepEqual(h.errors,[]);
  assert.ok(!h.state().notice.includes('OLD REVOCATION ERROR'));
 }
});

test('uncertain revocation stays in its own dialog and asks to verify the current grant',async()=>{
 const h=setup();await h.open({...snapshot,departments:[departments[0]]});await h.context.revokeGrant('department','first');
 const saving=h.confirmations[0].callback(),error=Error('Raw transport failure');error.uncertain=true;
 h.requests.at(-1).reject(error);await assert.doesNotReject(saving);
 assert.equal(h.state().busy,false);assert.equal(h.nodes['#sq-dialog'].open,true);assert.deepEqual(h.errors,[]);
 assert.match(h.state().notice,/서버 응답을 확인하지 못했습니다/);assert.match(h.state().notice,/회수 여부를 확인/);
 assert.ok(!h.state().notice.includes('Raw transport failure'));assert.ok(!h.state().notice.includes('권한을 회수했습니다'));
 assert.deepEqual(plain(h.state().snapshot.departments),[departments[0]]);assert.equal(h.context.refreshCount,0);
});

test('a current definite revoke failure is contained and leaves the existing grant available',async()=>{
 const h=setup();await h.open({...snapshot,users:[{...employees[0],requestId:'7:1001'}]});await h.context.revokeGrant('user','7:1001');
 const saving=h.confirmations[0].callback();h.requests.at(-1).reject(Error('권한 상태가 이미 변경되었습니다.'));await assert.doesNotReject(saving);
 assert.equal(h.state().busy,false);assert.match(h.state().notice,/권한 상태가 이미 변경/);assert.equal(h.state().snapshot.users.length,1);
 assert.deepEqual(h.errors,[]);assert.equal(h.context.refreshCount,0);assert.ok(!h.state().notice.includes('권한을 회수했습니다'));
});

test('all unresolved writes plus failed reload never claim the changes were saved',async()=>{
 const h=setup();await h.open();await h.people();const saving=h.context.saveGrantTargets();
 h.requests.at(-1).resolve({ok:false,saved:[],alreadyGranted:[],failed:employees.map(row=>({id:row.id,error:'Result unknown'})),pending:false});await tick();
 h.requests.at(-1).reject(Error('Reload unavailable'));await saving;
 assert.match(h.state().notice,/0명 추가/);assert.match(h.state().notice,/3명은 저장 결과를 확인하지 못했습니다/);
 assert.match(h.state().notice,/목록을 갱신하지 못했습니다/);assert.match(h.state().notice,/현재 반영 여부를 확인/);
 assert.doesNotMatch(h.state().notice,/저장 결과는 반영되었습니다|저장되었습니다|권한을 적용했습니다/);
 assert.deepEqual(plain(h.state().preview.users),employees);assert.deepEqual([...h.state().selected],employees.map(row=>row.id));
 assert.equal(h.state().busy,false);assert.equal(h.saveButton.disabled,false);
});
