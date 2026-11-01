// Execute the production registration, capture, publication and draft controller
// against a small form/dialog adapter. No browser, account, or real upload needed.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
const base=path.join(__dirname,'..'),app=fs.readFileSync(path.join(base,'static/app.js'),'utf8');
const source=name=>fs.readFileSync(path.join(base,'frontend',name),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
let phase='initial';const watchdog=setTimeout(()=>{console.error('Draft test stalled at '+phase);process.exit(1);},5000);
function setup(storage=new Map(),user='employee-a'){
 const events={},dialogEvents={},windowEvents={},prompts=[],notices=[],requests=[];
 let form=null,rendered='',storageFailure=false;
 const dialog={open:false,addEventListener:(name,fn)=>(dialogEvents[name]??=[]).push(fn),close(){this.open=false;for(const f of dialogEvents.close||[])f();}};
 const c={runtime:{step:1},server:{user:{id:user,name:'등록자',org:'제조팀'}},
  root:{addEventListener:(name,fn)=>(events[name]??=[]).push(fn)},window:{addEventListener:(name,fn)=>(windowEvents[name]??=[]).push(fn)},
  sessionStorage:{setItem(k,v){if(storageFailure)throw Error('quota');storage.set(k,v);},getItem:k=>storage.get(k)||null,removeItem:k=>storage.delete(k)},
  $:s=>s==='#sq-dialog'?dialog:s==='#sq-register-form'?form:s==='#sq-register-error'?{setAttribute(){},textContent:''}:null,
  esc:s=>String(s).replaceAll('<','&lt;'),icon:()=>'',button:(action,label)=>`<button type="button" data-action="${action}">${label}</button>`,
  getItem:id=>({id,name:'기존 도구 '+id,desc:'기존 소개',revision:3,active:1,versions:[],owner:'등록자',org:'제조팀'}),
  announce:s=>notices.push(s),showError:e=>{throw e;},refresh:async()=>{},crypto:webcrypto,setTimeout:fn=>{fn();return 1;},clearTimeout(){},
  Core:{validate:(d,step)=>step===2&&d.mode==='file'&&!d.file?'파일을 선택하세요.':''},packageBlockingError:()=>'',
  requestAPI:(url,method,body)=>new Promise((resolve,reject)=>requests.push({url,method,body,resolve,reject})),
  ask:(title,copy,callback)=>prompts.push({title,copy,callback}),
  navigate(route){c.route=route;},
  openModal(_title,_kicker,html){rendered=html;form=null;dialog.open=true;},closeModal(){dialog.close();},
  wizard(){c.openModal('등록','',c.runtime.draft.name);const d=c.runtime.draft;form={id:'sq-register-form',dataset:{},values:{...d},elements:{approval:{checked:d.approval}},querySelectorAll:()=>[],insertAdjacentHTML:(_p,html)=>{rendered+=html;}};},
  FormData:class{constructor(f){this.parts=f?Object.entries(f.values).filter(([k,v])=>!['file','audience','approval','workflow','installProfile','packageInspection'].includes(k)&&v!==undefined):[];}entries(){return this.parts[Symbol.iterator]();}append(...v){this.parts.push(v);}}
 };
 vm.createContext(c);
 vm.runInContext(app.slice(app.indexOf('function freshDraft('),app.indexOf('function wizard(){')),c);
 vm.runInContext(source('frontend_publish.js'),c);c.actions={publish:c.publish};
 vm.runInContext(source('frontend_registration_draft.js'),c);
 return {c,storage,dialog,requests,prompts,notices,get form(){return form;},get html(){return rendered;},
  input(name,value){form.values[name]=value;for(const fn of events.input||[])fn({target:{name,value,type:'text',closest:()=>form}});},
  escape(){for(const fn of dialogEvents.cancel||[])fn({});dialog.close();},
  unload(){const e={preventDefault(){this.prevented=true;}};for(const fn of windowEvents.beforeunload||[])fn(e);return e;},
  failStorage(){storageFailure=true;}};
}
(async()=>{
 const h=setup();h.c.register();assert.match(h.html,/이 탭에 임시 보관/);
 h.input('name','품질 월간 보고서');h.input('desc','표를 정리합니다');h.input('workTags','보고서, 품질');
 h.c.captureDraft();h.c.runtime.step=2;h.c.wizard();h.input('guide','압축을 풀어 사용하세요');
 const file={name:'배포.zip',size:400};h.c.runtime.draft.file=file;h.c.wizard();h.c.closeModal();
 h.c.register();assert.equal(h.c.runtime.step,2);assert.equal(h.c.runtime.draft.name,'품질 월간 보고서');assert.equal(h.c.runtime.draft.file,file);assert.equal(h.c.runtime.draft.guide,'압축을 풀어 사용하세요');
 h.input('guide','닫기 전 마지막 입력');h.escape();h.c.register();assert.equal(h.c.runtime.draft.guide,'닫기 전 마지막 입력');
 h.input('guide','다른 화면 이동 전 입력');h.c.navigate('manage');h.c.openModal('다른 화면','','');h.c.register();assert.equal(h.c.runtime.draft.guide,'다른 화면 이동 전 입력');
 h.input('guide','직접 close 호출 전 입력');h.dialog.close();h.c.register();assert.equal(h.c.runtime.draft.guide,'직접 close 호출 전 입력');
 // No key, File bytes, or package inspection response is persisted.
 h.c.runtime.draft.apiKey='secret-not-for-storage';h.c.runtime.draft.packageInspection={result:{raw:'not-for-storage'}};h.c.saveRegistrationDraft();
 const stored=[...h.storage.values()][0];assert.doesNotMatch(stored,/secret-not-for-storage|not-for-storage|"size"/);
 const reload=setup(h.storage);reload.c.register();assert.equal(reload.c.runtime.draft.name,'품질 월간 보고서');assert.equal(reload.c.runtime.draft.file,null);assert.equal(reload.c.runtime.step,2);assert.match(reload.html,/첨부파일은 다시 선택/);
 // Identity and release targets never cross, even within the same tab storage.
 const other=setup(h.storage,'employee-b');other.c.register();assert.equal(other.c.runtime.draft.name,'');
 const switched=setup(new Map(h.storage));switched.c.register();switched.c.server.user.id='employee-b';await assert.rejects(switched.c.actions.publish(),/사용자가 바뀌었습니다/);assert.equal(switched.requests.length,0);switched.c.actions['resume-draft']();assert.equal(switched.c.runtime.draft,null);assert.equal(switched.dialog.open,false);
 h.c.register(12);assert.equal(h.c.runtime.draft.name,'기존 도구 12');h.input('name','12번 새 버전');h.c.closeModal();h.c.register(13);assert.equal(h.c.runtime.draft.name,'기존 도구 13');h.c.register(12);assert.equal(h.c.runtime.draft.name,'12번 새 버전');h.c.register();assert.equal(h.c.runtime.draft.name,'품질 월간 보고서');
 // Discard is explicit. Cancel leaves data; confirmation starts fresh.
 h.c.actions['registration-discard']();assert.equal(h.c.runtime.draft.name,'품질 월간 보고서');h.prompts.pop().callback();assert.equal(h.c.runtime.draft.name,'');assert.equal(h.c.runtime.draft.file,null);
 const clear=setup();clear.c.register();clear.input('name','지울 내용');assert.equal(clear.storage.size,1);clear.input('name','');assert.equal(clear.storage.size,0);const clearReload=setup(clear.storage);clearReload.c.register();assert.equal(clearReload.c.runtime.draft.name,'');
 // Storage denial cannot lose the in-memory draft and is disclosed on reload.
 const denied=setup();denied.failStorage();denied.c.register();denied.input('name','메모리 보관');denied.c.closeModal();denied.c.register();assert.equal(denied.c.runtime.draft.name,'메모리 보관');assert.match(denied.html,/저장 공간을 사용할 수 없어/);assert.equal(denied.unload().prevented,true);
 // A started POST is persisted before awaiting I/O, warns on reload, and cannot
 // be replaced by opening a different registration.
 const posting=setup();posting.c.register();posting.input('name','게시할 이름');posting.input('desc','게시할 소개');posting.c.runtime.draft.guide='안내';posting.c.runtime.draft.file=file;posting.c.runtime.step=3;posting.c.wizard();
 phase='publish';const publish=posting.c.actions.publish();assert.equal(posting.requests[0].method,'POST');const requestId=posting.c.runtime.publishAttempt.id;
 assert.equal(posting.unload().prevented,true);posting.c.register(12);assert.equal(posting.c.runtime.releaseId,null);
 const pendingStorage=new Map(posting.storage);
 posting.requests.shift().resolve({id:41,version:1});await publish;assert.equal(posting.storage.size,0);assert.equal(posting.c.runtime.draft,null);
 // Reloaded uncertain upload first checks receipt. If absent, file reselection
 // retries the SAME request ID; server fingerprint validation prevents duplicates.
 phase='pending';const pending=setup(new Map(pendingStorage));pending.c.register();assert.equal(pending.c.runtime.publishAttempt.id,requestId);assert.match(pending.html,/같은 요청 번호/);
 await assert.rejects(pending.c.actions.publish(),/파일을 선택/);assert.equal(pending.requests.length,0);
 pending.c.runtime.draft.file={...file};pending.c.runtime.step=3;pending.c.wizard();
 phase='retry';const retry=pending.c.actions.publish();
 for(let i=0;i<3;i++){assert.equal(pending.requests[0].url,`/api/publish-requests/${requestId}`);pending.requests.shift().resolve({status:'unconfirmed'});await tick();}
 const retried=pending.requests.shift();assert.equal(retried.method,'POST');const metadata=JSON.parse(retried.body.parts.find(([k])=>k==='metadata')[1]);assert.equal(metadata.clientRequestId,requestId);
 retried.resolve({id:41,version:1});await retry;assert.equal(pending.storage.size,0);
 // The previously published storage format is migrated once, without inventing
 // files or letting a cleared old entry resurrect after the new draft is deleted.
 phase='legacy migration';const legacyStorage=new Map([['ptai.registration-drafts.v1:employee-a',JSON.stringify({new:{at:Date.now(),step:2,data:{name:'이전 클라이언트 초안',desc:'기본 정보',mode:'file',approval:true}}})]]);
 const legacy=setup(legacyStorage);legacy.c.register();assert.equal(legacy.c.runtime.draft.name,'이전 클라이언트 초안');assert.equal(legacy.c.runtime.draft.file,null);assert.equal(legacyStorage.has('ptai.registration-drafts.v1:employee-a'),false);
 legacy.c.actions['registration-discard']();legacy.prompts.pop().callback();const legacyReload=setup(legacyStorage);legacyReload.c.register();assert.equal(legacyReload.c.runtime.draft.name,'');
 // A closed pending publication can be reopened and edited. The old completion
 // must keep those newer edits, including their saved copy, and clear its receipt.
 phase='pending newer edits';const editing=setup();editing.c.register();editing.input('name','원래 게시');editing.input('desc','원래 소개');editing.c.runtime.draft.file=file;editing.c.runtime.step=3;editing.c.wizard();
 const editedPublish=editing.c.actions.publish();editing.c.closeModal();editing.c.register();editing.c.runtime.step=1;editing.c.wizard();editing.input('name','다음 작성');
 editing.requests.shift().resolve({id:99,version:1});await editedPublish;assert.equal(editing.c.runtime.draft.name,'다음 작성');assert.equal(JSON.parse([...editing.storage.values()][0]).pending,null);
 const editingReload=setup(editing.storage);editingReload.c.register();assert.equal(editingReload.c.runtime.draft.name,'다음 작성');assert.equal(editingReload.c.runtime.publishAttempt,null);
 // Receipt recovery obeys the same late-response rule as the upload itself.
 phase='receipt newer edits';const receiptEdit=setup(new Map(pendingStorage));receiptEdit.c.register();const receiptCheck=receiptEdit.c.actions['registration-check-result']();receiptEdit.input('name','결과 확인 중 다음 초안');
 receiptEdit.requests.shift().resolve({status:'confirmed',id:41,version:1});await receiptCheck;assert.equal(receiptEdit.c.runtime.draft.name,'결과 확인 중 다음 초안');assert.equal(JSON.parse([...receiptEdit.storage.values()][0]).pending,null);
 phase='receipt another modal';const receiptModal=setup(new Map(pendingStorage));receiptModal.c.register();const modalCheck=receiptModal.c.actions['registration-check-result']();receiptModal.c.runtime.detailLoadToken=10;receiptModal.c.openModal('다른 도구','','다른 모달');
 receiptModal.requests.shift().resolve({status:'confirmed',id:41,version:1});await modalCheck;assert.equal(receiptModal.html,'다른 모달');assert.equal(receiptModal.storage.size,0);
 phase='receipt account switch';const receiptAccount=setup(new Map(pendingStorage));receiptAccount.c.register();const accountCheck=receiptAccount.c.actions['registration-check-result']();receiptAccount.c.server.user.id='employee-b';
 const beforeAccountReceipt=[...receiptAccount.storage.values()][0];receiptAccount.requests.shift().resolve({status:'confirmed',id:41,version:1});await accountCheck;
 assert.equal([...receiptAccount.storage.values()][0],beforeAccountReceipt);assert.notEqual(receiptAccount.c.runtime.draft,null);assert.doesNotMatch(receiptAccount.html,/게시를 완료했습니다/);
 // Changed restored metadata cannot silently allocate a different request ID.
 phase='changed';const changed=setup(new Map(pendingStorage));changed.c.register();changed.c.runtime.draft.file=file;changed.c.runtime.draft.name='다른 내용';changed.c.runtime.step=3;
 await assert.rejects(changed.c.actions.publish(),/입력 내용이 달라졌습니다/);assert.equal(changed.requests.length,0);assert.equal(changed.c.runtime.publishAttempt.id,requestId);
 const checked=changed.c.actions['registration-check-result']();changed.requests.shift().resolve({status:'confirmed',id:41,version:1});await checked;assert.equal(changed.c.runtime.draft,null);assert.equal(changed.storage.size,0);
 // A definite validation failure after reload permits corrected input, while
 // retaining the request ID so even a concurrent original cannot duplicate it.
 phase='validation';const invalid=setup(new Map(pendingStorage));invalid.c.register();invalid.c.runtime.draft.file=file;invalid.c.runtime.step=3;
 const firstRetry=invalid.c.actions.publish();
 for(let i=0;i<3;i++){invalid.requests.shift().resolve({status:'unconfirmed'});await tick();}
 invalid.requests.shift().reject(Object.assign(Error('등록 조직을 확인하세요.'),{status:400,uncertain:false}));await assert.rejects(firstRetry,/등록 조직/);
 invalid.c.runtime.draft.org='공통';const corrected=invalid.c.actions.publish();
 for(let i=0;i<3;i++){invalid.requests.shift().resolve({status:'unconfirmed'});await tick();}
 const correctedPost=invalid.requests.shift();assert.equal(JSON.parse(correctedPost.body.parts[0][1]).clientRequestId,requestId);assert.equal(JSON.parse(correctedPost.body.parts[0][1]).org,'공통');correctedPost.resolve({id:42,version:1});await corrected;
 // The same-page close/resume path obeys the same invariant as reload. Editing
 // an unresolved publication must never silently allocate a second request ID.
 phase='same-page uncertain';const uncertain=setup();uncertain.c.register();uncertain.input('name','불확실한 게시');uncertain.input('desc','응답 끊김');uncertain.c.runtime.draft.file=file;uncertain.c.runtime.step=3;
 const unresolved=uncertain.c.actions.publish(),unresolvedId=uncertain.c.runtime.publishAttempt.id,expectedUnresolved=assert.rejects(unresolved,/완료 여부/);
 uncertain.requests.shift().reject(Object.assign(Error('network'),{uncertain:true}));await tick();
 for(let i=0;i<3;i++){uncertain.requests.shift().resolve({status:'unconfirmed'});await tick();}
 await expectedUnresolved;uncertain.c.closeModal();uncertain.c.register();assert.match(uncertain.html,/data-action="registration-check-result"/);uncertain.c.runtime.step=1;uncertain.c.wizard();uncertain.input('name','바뀐 제목');uncertain.c.runtime.step=3;
 await assert.rejects(uncertain.c.actions.publish(),/입력 내용이 달라졌습니다/);assert.equal(uncertain.requests.length,0);assert.equal(uncertain.c.runtime.publishAttempt.id,unresolvedId);
 const uncertainReceipt=uncertain.c.actions['registration-check-result']();assert.equal(uncertain.requests[0].url,`/api/publish-requests/${unresolvedId}`);uncertain.requests.shift().resolve({status:'confirmed',id:52,version:1});await uncertainReceipt;assert.equal(uncertain.c.runtime.draft,null);assert.equal(uncertain.storage.size,0);
 console.log('Registration drafts passed: close/Escape/navigation/raw-close, reload/reselect, identity/target isolation, discard, clear, quota failure, publish cleanup, uncertain same-id retry and receipt recovery.');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>clearTimeout(watchdog));
