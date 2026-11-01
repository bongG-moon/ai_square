// Registration drafts belong to one signed-in user and one target tool in this tab.
// File objects and inspection responses stay in memory; only allowlisted form data
// goes to sessionStorage. Nothing is published by saving or restoring a draft.
const registrationDrafts=new Map();
const registrationFields=['name','desc','workTags','platform','type','org','orgId','category','categoryId','owner','visibility','audience','approval','mode','commandProject','commandUser','url','expectedRevision','guide','changes','environment','workflow','installProfile'];
let registrationContext=null,registrationRendering=false;
const registrationBase={register,captureDraft,wizard,openModal,closeModal,navigate};
function registrationUser(){return String(server.user?.id||'');}
function registrationDraftMatchesUser(){return !registrationContext||registrationContext.user===registrationUser();}
function registrationKey(user,target){return `sq-registration-v1:${encodeURIComponent(user)}:${target||'new'}`;}
function removeLegacyRegistrationDraft(user,target){
 const key='ptai.registration-drafts.v1:'+String(user);
 try{const saved=JSON.parse(sessionStorage.getItem(key)||'null');if(!saved||typeof saved!=='object'||Array.isArray(saved))return;delete saved[String(target||'new')];if(Object.keys(saved).length)sessionStorage.setItem(key,JSON.stringify(saved));else sessionStorage.removeItem(key);}catch{}
}
function registrationDraftRevision(){return registrationContext?.revision??null;}
function clearRegistrationDraft(user=registrationUser(),target=runtime.releaseId,expectedRevision=undefined){
 const key=registrationKey(String(user),target||null),entry=registrationDrafts.get(key);
 let stored;try{stored=JSON.parse(sessionStorage.getItem(key)||'null');}catch{}
 const context=entry?.context||(registrationContext?.key===key?registrationContext:null);
 const revision=context?.revision??stored?.revision??null;
 if(expectedRevision!==undefined&&revision!==expectedRevision)return false;
 registrationDrafts.delete(key);try{sessionStorage.removeItem(key);}catch{}
 removeLegacyRegistrationDraft(user,target);
 if(registrationContext?.key===key)registrationContext=null;
 return true;
}
function settleRegistrationAttempt(user,target,id){
 const key=registrationKey(String(user),target||null),entry=registrationDrafts.get(key);
 const context=entry?.context||(registrationContext?.key===key?registrationContext:null);
 if(entry?.attempt?.id===id)entry.attempt=null;
 if(context?.pending===id){context.pending=null;context.signature=null;}
 try{const stored=JSON.parse(sessionStorage.getItem(key)||'null');if(stored?.pending?.id===id){stored.pending=null;sessionStorage.setItem(key,JSON.stringify(stored));}}catch{}
}
function registrationData(d){
 const data={};for(const key of registrationFields)if(d[key]!==undefined)data[key]=d[key];
 return JSON.parse(JSON.stringify(data));
}
function registrationVisible(){return !!$('#sq-register-form')&&$('#sq-dialog')?.open!==false;}
function saveRegistrationDraft(){
 const c=registrationContext,d=runtime.draft;if(!c||!d||c.user!==registrationUser())return;
 const data=registrationData(d),pending=runtime.publishAttempt?(runtime.publishBusy||runtime.publishAttempt.uncertain?runtime.publishAttempt.id:null):c.pending;
 c.pending=pending||null;c.signature=pending?(runtime.publishAttempt?.signature||c.signature):null;
 if(!d.file&&!pending&&JSON.stringify(data)===c.baseline&&!c.restored){registrationDrafts.delete(c.key);try{sessionStorage.removeItem(c.key);}catch{}return;}
 const identity=JSON.stringify([data,runtime.step,runtime.draftChangeSequence||0]);
 if(identity!==c.savedIdentity||d.file!==c.savedFile){c.revision=Math.max(Date.now(),(c.revision||0)+1);c.savedIdentity=identity;c.savedFile=d.file;}
 const entry={draft:d,step:runtime.step,attempt:runtime.publishAttempt||null,context:c};registrationDrafts.set(c.key,entry);
 const stored={schema:1,user:c.user,target:c.target,savedAt:Date.now(),revision:c.revision,data,step:runtime.step,fileName:d.file?.name||c.fileName||'',pending:pending?{id:pending,signature:runtime.publishAttempt?.signature||c.signature,canCorrect:runtime.publishAttempt?.canCorrect===true}:null};
 try{sessionStorage.setItem(c.key,JSON.stringify(stored));removeLegacyRegistrationDraft(c.user,c.target);c.storageFailed=false;}
 catch{c.storageFailed=true;}
 const note=$('#sq-registration-save-note');if(note)note.textContent=registrationDraftNotice();
}
function registrationDraftNotice(){
 const c=registrationContext;if(!c)return '';
 if(c.pending)return '이전 게시 결과를 확인할 수 있습니다. 다시 게시하려면 같은 입력 내용과 파일을 사용해 주세요. 같은 요청 번호로 확인하고 재시도하므로 중복 등록되지 않습니다.';
 if(c.storageFailed)return '입력 내용과 파일은 이 화면에서 보관 중입니다. 브라우저 저장 공간을 사용할 수 없어 새로고침하면 사라질 수 있습니다.';
 if(c.restored&&c.fileName&&!runtime.draft?.file)return `입력 내용을 복원했습니다. 첨부파일은 다시 선택해 주세요: ${c.fileName}`;
 return '입력 내용은 이 탭에 임시 보관됩니다. 창을 닫아도 이어서 작성할 수 있습니다. 새로고침한 뒤에는 파일을 다시 선택해 주세요.';
}
function forgetRegistrationDraft(){
 const c=registrationContext;if(!c)return;
 clearRegistrationDraft(c.user,c.target);
}
function restoreRegistrationDraft(user,target){
 const key=registrationKey(user,target),memory=registrationDrafts.get(key);
 if(memory){registrationContext=memory.context;runtime.draft=memory.draft;runtime.step=memory.step;runtime.publishAttempt=memory.attempt;return true;}
 let stored;try{stored=JSON.parse(sessionStorage.getItem(key)||'null');}catch{return false;}
 if(!stored){
  // Preserve descriptive drafts made by the previously published client. The
  // old format never saved files or publication receipts, so do not invent any.
  try{const legacy=JSON.parse(sessionStorage.getItem('ptai.registration-drafts.v1:'+user)||'null')?.[String(target||'new')];if(legacy)stored={schema:1,user,target,savedAt:legacy.at,revision:legacy.at,data:legacy.data,step:legacy.step};}catch{}
 }
 if(!stored||stored.schema!==1||stored.user!==user||stored.target!==target||!stored.data||typeof stored.data!=='object'||Array.isArray(stored.data)||!Number.isFinite(stored.savedAt)||Date.now()-stored.savedAt>86400000)return false;
 if(stored.data.audience!==undefined&&(!Array.isArray(stored.data.audience)||stored.data.audience.some(v=>typeof v!=='string')))return false;
 for(const field of registrationFields)if(Object.hasOwn(stored.data,field)&&!['audience','approval','expectedRevision','workflow','installProfile'].includes(field)&&typeof stored.data[field]!=='string')return false;
 const d=freshDraft(target?getItem(target):null);
 for(const field of registrationFields)if(Object.hasOwn(stored.data,field))d[field]=stored.data[field];
 // Browser form values are text, booleans or JSON metadata; never hydrate File,
 // auth material, inspection state, or arbitrary runtime fields from storage.
 d.file=null;d.sample=false;d.packageInspection=null;
 const pending=stored.pending&&/^[a-f0-9-]{36}$/i.test(stored.pending.id||'')&&typeof stored.pending.signature==='string'?stored.pending:null;
 registrationContext={key,user,target,baseline:'',restored:true,revision:Number.isFinite(stored.revision)?stored.revision:stored.savedAt,fileName:String(stored.fileName||''),pending:pending?.id||null,signature:pending?.signature};
 runtime.draft=d;runtime.step=d.mode==='file'?Math.min(Number(stored.step)||1,2):Math.max(1,Math.min(Number(stored.step)||1,3));
 runtime.publishAttempt=pending?{id:pending.id,signature:pending.signature,target,file:null,uncertain:true,restored:true,canCorrect:pending.canCorrect===true}:null;
 return true;
}
captureDraft=function(){
 if(registrationRendering||!runtime.draft)return;
 registrationBase.captureDraft();saveRegistrationDraft();
};
register=function(id){
 const target=id?Number(id):null;
 if(runtime.publishBusy&&target!==(runtime.releaseId||null)){announce('게시 결과를 확인하고 있습니다. 잠시 기다려 주세요.');return;}
 if(registrationVisible())captureDraft();else saveRegistrationDraft();
 const user=registrationUser();runtime.releaseId=target;
 if(!user){announce('로그인 정보를 불러온 뒤 다시 등록해 주세요.');return;}
 runtime.draftOwner=server.user.id;
 if(!restoreRegistrationDraft(user,target)){
  runtime.draft=freshDraft(target?getItem(target):null);runtime.step=1;runtime.publishAttempt=null;
  registrationContext={key:registrationKey(user,target),user,target,baseline:JSON.stringify(registrationData(runtime.draft))};
 }
 wizard();
};
wizard=function(){
 if(!runtime.draft)return;
 if(registrationContext&&registrationContext.user!==registrationUser()){
  runtime.draft=null;runtime.publishAttempt=null;registrationContext=null;registrationBase.closeModal();announce('로그인한 사용자가 바뀌었습니다. 도구 등록을 다시 열어 주세요.');return;
 }
 registrationRendering=true;
 try{registrationBase.wizard();}finally{registrationRendering=false;}
 const form=$('#sq-register-form');
 if(form&&registrationContext){
  form.insertAdjacentHTML('afterbegin',`<div class="sq-callout" data-registration-draft><p id="sq-registration-save-note" role="status">${esc(registrationDraftNotice())}</p><div class="sq-actions">${registrationContext.pending?button('registration-check-result','게시 결과 확인','sq-secondary'):button('registration-discard','작성 내용 지우기','sq-link','type="button"')}</div></div>`);
 }
 saveRegistrationDraft();
};
openModal=function(...args){
 if(!registrationRendering&&registrationVisible())captureDraft();
 return registrationBase.openModal(...args);
};
closeModal=function(){if(registrationVisible())captureDraft();return registrationBase.closeModal();};
navigate=function(...args){if(registrationVisible())captureDraft();return registrationBase.navigate(...args);};
actions['close-dialog']=closeModal;
actions['resume-draft']=()=>wizard();
actions['registration-discard']=()=>{
 if(runtime.publishBusy||runtime.publishAttempt?.uncertain||registrationContext?.pending){announce('게시 결과를 먼저 확인해 주세요. 작성 내용은 보관하고 있습니다.');return;}
 const original=registrationContext;
 ask('작성 중인 내용을 지울까요?','이 탭에 보관된 입력 내용과 첨부파일 선택을 지웁니다. 이미 게시한 도구에는 영향을 주지 않습니다.',()=>{
  if(original!==registrationContext||runtime.publishBusy||runtime.publishAttempt?.uncertain||registrationContext?.pending)return;
  const target=runtime.releaseId;forgetRegistrationDraft();runtime.draft=null;runtime.publishAttempt=null;register(target);
 },'내용 지우기');
};
actions['registration-check-result']=async()=>{
 const c=registrationContext;if(!c?.pending||runtime.registrationChecking)return;
 if(!registrationDraftMatchesUser())throw Error('로그인한 사용자가 바뀌었습니다. 도구 등록을 다시 열어 주세요.');
 const draft=runtime.draft,revision=registrationDraftRevision(),viewToken=runtime.detailLoadToken,requestId=c.pending;
 runtime.registrationChecking=true;
 try{
  const result=await requestAPI(`/api/publish-requests/${encodeURIComponent(requestId)}`,'GET',undefined,{timeoutMs:5000,redirectOnAuth:false});
  if(c.user!==registrationUser())return;
  if(result.status!=='confirmed'||!Number.isInteger(result.id)||result.id<1||c.target&&result.id!==c.target)throw Error('게시 완료 여부를 아직 확인하지 못했습니다. 잠시 후 다시 확인하거나 등록 관리에서 결과를 확인해 주세요. 입력 내용은 보관하고 있습니다.');
  const ownsDraft=c===registrationContext&&runtime.draft===draft&&registrationDraftRevision()===revision;
  clearRegistrationDraft(c.user,c.target,revision);
  if(runtime.publishAttempt?.id===requestId)runtime.publishAttempt=null;
  settleRegistrationAttempt(c.user,c.target,requestId);
  if(ownsDraft){runtime.draft=null;runtime.newId=result.id;}
  if(!ownsDraft||viewToken!==runtime.detailLoadToken||c.user!==registrationUser()){announce('게시가 완료되었습니다. 등록 관리에서 확인할 수 있습니다.');return;}
  openModal('게시를 완료했습니다.','게시 결과 확인',`<div class="sq-callout">도구 ID ${result.id}의 게시 결과를 확인했습니다. 임시 작성 내용은 정리했습니다.</div>${button('published-detail','게시한 도구 보기','sq-primary')}`);
 }finally{runtime.registrationChecking=false;saveRegistrationDraft();}
};
for(const eventName of ['input','change'])root.addEventListener(eventName,event=>{if(event.target.closest?.('#sq-register-form')){runtime.draftChangeSequence=(runtime.draftChangeSequence||0)+1;if(event.target.type!=='file')captureDraft();}});
$('#sq-dialog').addEventListener('cancel',()=>{if(registrationVisible())captureDraft();});
$('#sq-dialog').addEventListener('close',()=>{if(!$('#sq-dialog').open&&$('#sq-register-form'))captureDraft();});
window.addEventListener('beforeunload',event=>{
 if(registrationVisible())captureDraft();else saveRegistrationDraft();
 if(runtime.publishBusy||runtime.publishAttempt?.uncertain||registrationContext?.storageFailed){event.preventDefault();event.returnValue='';}
});
