const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_taxonomy.js'),'utf8');
const workspace=fs.readFileSync(path.join(__dirname,'../frontend/frontend_workspace.js'),'utf8');
const tick=()=>new Promise(setImmediate);
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};}
function preview(extra={}){return {item:{id:'old',name:'이전 조직',kind:'organization'},usage:{tools:2,ideas:0,users:1,total:3},targets:[{id:'next',name:'새 조직'}],protected:false,...extra};}
function setup(){
 const requests=[],opened=[],errors=[],notices=[],listeners={},dialog={open:false},nodes={};let refreshCount=0,persisted=0,refreshFailure=null;
 const c={actions:{},runtime:{detailLoadToken:0},server:{user:{id:'admin',role:'admin'}},state:{org:'이전 조직',category:'모든 업무',page:3},
 esc:v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),icon:n=>`<svg>${n}</svg>`,button:(action,label,css='',attrs='')=>`<button data-action="${action}" class="${css}" ${attrs}>${label}</button>`,
 root:{addEventListener:(name,fn)=>{listeners[name]=fn;}},
 $:selector=>selector==='#sq-dialog'?dialog:nodes[selector]||null,
 openModal(title,kicker,html){c.runtime.detailLoadToken++;dialog.open=true;opened.push({title,kicker,html});for(const key of Object.keys(nodes))delete nodes[key];
  if(html.includes('id="ws-taxonomy-delete-target"')){const selected=html.match(/<option value="([^"]+)" selected>/)?.[1]||'';nodes['#ws-taxonomy-delete-target']={id:'ws-taxonomy-delete-target',value:selected,disabled:false,nextElementSibling:{classList:{contains:name=>name==='ws-select'},disabled:false}};}
  if(html.includes('data-action="taxonomy-confirm-delete"'))nodes['[data-action="taxonomy-confirm-delete"]']={disabled:false,textContent:'',setAttribute(name,value){this[name]=value;}};
  if(html.includes('id="ws-taxonomy-delete-error"'))nodes['#ws-taxonomy-delete-error']={hidden:true,textContent:'',focus(){this.focused=true;}};
  if(html.includes('id="ws-taxonomy-delete-recovery"'))nodes['#ws-taxonomy-delete-recovery']={hidden:true};
 },
 closeModal(){c.runtime.detailLoadToken++;dialog.open=false;},
 requestAPI(url,method='GET',body){const d=deferred();requests.push({...d,url,method,body});return d.promise;},
 async refresh(){refreshCount++;if(refreshFailure)throw refreshFailure;return true;},persist(){persisted++;},announce:message=>notices.push(message),showError:error=>errors.push(error)};
 vm.createContext(c);vm.runInContext(workspace.slice(workspace.indexOf('async function afterWorkspaceSave('),workspace.indexOf('const originalRender=')),c);vm.runInContext(source,c);
 return {c,requests,opened,nodes,dialog,listeners,errors,notices,get refreshCount(){return refreshCount;},get persisted(){return persisted;},failRefresh(error){refreshFailure=error;},select(value){const node=nodes['#ws-taxonomy-delete-target'];node.value=value;listeners.change({target:node});}};
}
async function open(h,p=preview()){const pending=h.c.openTaxonomyDeletion(p.item.id);h.requests.at(-1).resolve(p);await pending;}
test('preview lists affected records, starts without a transfer choice and escapes names',async()=>{
 const h=setup();await open(h,preview({item:{id:'old',kind:'organization',name:'<img onerror="bad">'}}));
 assert.match(h.opened.at(-1).title,/조직을 삭제/);assert.match(h.opened.at(-1).html,/&lt;img/);assert.doesNotMatch(h.opened.at(-1).html,/<img/);
 assert.match(h.opened.at(-1).html,/휴지통/);assert.match(h.opened.at(-1).html,/연결된 사용자/);assert.equal(h.nodes['#ws-taxonomy-delete-target'].value,'');assert.equal(h.nodes['[data-action="taxonomy-confirm-delete"]'].disabled,true);
 await h.c.confirmTaxonomyDeletion();assert.equal(h.requests.length,1);assert.match(h.nodes['#ws-taxonomy-delete-error'].textContent,/선택/);
});
test('cancel after preview never sends a deletion request',async()=>{
 const h=setup();await open(h);h.c.actions['taxonomy-delete-cancel']();assert.equal(h.dialog.open,false);assert.equal(h.requests.length,1);await h.c.confirmTaxonomyDeletion();assert.equal(h.requests.length,1);
});
test('in-use deletion submits explicit selection once, then replaces the deleted filter',async()=>{
 const h=setup();await open(h);h.select('next');assert.equal(h.nodes['[data-action="taxonomy-confirm-delete"]'].disabled,false);
 const save=h.c.confirmTaxonomyDeletion();await h.c.confirmTaxonomyDeletion();assert.equal(h.requests.length,2);assert.deepEqual(JSON.parse(JSON.stringify(h.requests[1].body)),{confirmed:true,targetId:'next'});assert.equal(h.nodes['#ws-taxonomy-delete-target'].disabled,true);
 h.requests[1].resolve({ok:true,deleted:true});await save;assert.equal(h.dialog.open,false);assert.equal(h.c.state.org,'새 조직');assert.equal(h.c.state.page,0);assert.equal(h.refreshCount,1);assert.equal(h.persisted,1);
});
test('empty category deletion needs confirmation but no transfer target',async()=>{
 const h=setup();h.c.state.category='기타';await open(h,preview({item:{id:'old',name:'기타',kind:'category'},usage:{tools:0,ideas:0,users:0,total:0},targets:[]}));
 assert.match(h.opened.at(-1).title,/업무 분류를/);assert.equal(h.nodes['#ws-taxonomy-delete-target'],undefined);assert.equal(h.requests.length,1);
 const save=h.c.confirmTaxonomyDeletion();assert.deepEqual(JSON.parse(JSON.stringify(h.requests[1].body)),{confirmed:true});h.requests[1].resolve({deleted:true});await save;assert.equal(h.c.state.category,'모든 업무');
});
test('no target and protected common item cannot be deleted',async()=>{
 const h=setup();await open(h,preview({targets:[]}));assert.match(h.opened.at(-1).html,/먼저 다른 조직 항목을 추가/);await h.c.confirmTaxonomyDeletion();assert.equal(h.requests.length,1);
 await open(h,preview({item:{id:'organization-0',kind:'organization',name:'공통'},protected:true,reason:'공통 조직은 유지해 주세요.'}));assert.match(h.opened.at(-1).html,/공통 조직은 유지/);assert.equal(h.nodes['[data-action="taxonomy-confirm-delete"]'],undefined);await h.c.confirmTaxonomyDeletion();assert.equal(h.requests.length,2);
});
test('server conflict preserves selection and offers a fresh usage preview',async()=>{
 const h=setup();await open(h);h.select('next');const save=h.c.confirmTaxonomyDeletion();h.requests[1].reject(Object.assign(Error('다른 등록 내용을 확인하세요.'),{status:409}));await save;
 assert.equal(h.nodes['#ws-taxonomy-delete-target'].value,'next');assert.equal(h.nodes['[data-action="taxonomy-confirm-delete"]'].disabled,false);assert.equal(h.nodes['#ws-taxonomy-delete-recovery'].hidden,false);
 const again=h.c.actions['taxonomy-delete-reload']();h.requests[2].resolve(preview({usage:{tools:4,users:1,ideas:0,total:5}}));await again;assert.equal(h.nodes['#ws-taxonomy-delete-target'].value,'next');assert.match(h.opened.at(-1).html,/>4<small>/);
});
test('uncertain completion locks the selected target and retries the same deletion',async()=>{
 const h=setup();await open(h);h.select('next');const save=h.c.confirmTaxonomyDeletion();h.requests[1].reject(Object.assign(Error('연결 끊김'),{uncertain:true}));await save;
 assert.equal(h.nodes['#ws-taxonomy-delete-target'].disabled,true);assert.match(h.nodes['#ws-taxonomy-delete-error'].textContent,/같은 내용/);assert.equal(h.nodes['[data-action="taxonomy-confirm-delete"]'].textContent,'삭제 마무리');
 h.nodes['#ws-taxonomy-delete-target'].value='untrusted-target';const retry=h.c.confirmTaxonomyDeletion();assert.equal(h.requests[2].body.targetId,'next');h.requests[2].resolve({deleted:true,replayed:true});await retry;
});
test('server pending preview resumes only its recorded transfer target',async()=>{
 const h=setup();await open(h,preview({pending:true,lockedTargetId:'next'}));assert.equal(h.nodes['#ws-taxonomy-delete-target'].value,'next');assert.equal(h.nodes['#ws-taxonomy-delete-target'].disabled,true);assert.match(h.opened.at(-1).html,/변경할 수 없습니다/);
 const save=h.c.confirmTaxonomyDeletion();assert.equal(h.requests[1].body.targetId,'next');h.requests[1].resolve({deleted:true});await save;
});
test('late preview success or failure cannot replace another dialog or account',async()=>{
 const h=setup(),first=h.c.openTaxonomyDeletion('old');h.c.openModal('다른 화면','','유지');h.requests[0].resolve(preview());await first;assert.equal(h.opened.at(-1).html,'유지');
 const second=h.c.openTaxonomyDeletion('old');h.c.closeModal();h.requests[1].reject(Error('오래된 실패'));await second;assert.equal(h.dialog.open,false);
 const third=h.c.openTaxonomyDeletion('old');h.c.server.user.id='other-admin';h.requests[2].resolve(preview());await third;assert.doesNotMatch(h.opened.at(-1).html,/이관할 조직/);
});
test('a deletion response after account switch never changes filters or closes the new dialog',async()=>{
 const h=setup();await open(h);h.select('next');const save=h.c.confirmTaxonomyDeletion();h.c.server.user.id='other-admin';h.c.openModal('다른 사용자','','새 창');h.requests[1].resolve({deleted:true});await save;
 assert.equal(h.c.state.org,'이전 조직');assert.equal(h.refreshCount,0);assert.equal(h.opened.at(-1).html,'새 창');assert.equal(h.dialog.open,true);
});
test('confirmed deletion followed by refresh failure reports saved status without retrying mutation',async()=>{
 const h=setup();await open(h);h.select('next');h.failRefresh(Error('목록 조회 실패'));const save=h.c.confirmTaxonomyDeletion();h.requests[1].resolve({deleted:true});await save;
 assert.equal(h.errors.length,1);assert.equal(h.errors[0].saved,true);assert.match(h.errors[0].message,/서버에 저장/);await h.c.confirmTaxonomyDeletion();assert.equal(h.requests.length,2);
});
test('completed preview offers read-only refresh and clears a deleted filter',async()=>{
 const h=setup();await open(h,preview({deleted:true,lockedTargetId:'next'}));assert.match(h.opened.at(-1).title,/이미 삭제/);assert.equal(h.nodes['[data-action="taxonomy-confirm-delete"]'],undefined);
 await h.c.actions['taxonomy-delete-refresh']();assert.equal(h.requests.length,1);assert.equal(h.refreshCount,1);assert.equal(h.c.state.org,'새 조직');assert.equal(h.dialog.open,false);
});
test('preview failure is retryable and regular users cannot enter the workflow',async()=>{
 const h=setup(),load=h.c.openTaxonomyDeletion('old');h.requests[0].reject(Error('조회 실패'));await load;assert.match(h.opened.at(-1).html,/taxonomy-delete-retry/);
 const retry=h.c.actions['taxonomy-delete-retry']();h.requests[1].resolve(preview());await retry;assert.match(h.opened.at(-1).title,/삭제할까요/);
 h.c.server.user.role='member';await h.c.openTaxonomyDeletion('old');assert.equal(h.requests.length,2);
});
test('pending empty deletion and its admin row provide a completion path without editing',async()=>{
 const h=setup();await open(h,preview({pending:true,usage:{tools:0,ideas:0,users:0,total:0},targets:[]}));assert.match(h.opened.at(-1).html,/남은 삭제를 마무리/);assert.equal(h.nodes['[data-action="taxonomy-confirm-delete"]'].textContent,'삭제 마무리');
 h.c.organizations=[{id:'old',name:'이전 조직',enabled:false,deletionPending:true,order:3}];h.c.server.categories=[];
 vm.runInContext(workspace.split('\n').find(line=>line.startsWith('function taxonomyPanel()')),h.c);
 const html=h.c.taxonomyPanel();assert.match(html,/삭제 처리 중/);assert.match(html,/data-action="taxonomy-edit"[^>]*disabled/);assert.match(html,/data-action="taxonomy-delete"[^>]*>.*마무리/);
});
