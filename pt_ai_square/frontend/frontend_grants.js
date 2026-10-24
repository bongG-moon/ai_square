// Owner/admin access management. All matching and authorization happen on the server.
let grantState=null,grantSequence=0;
function grantLive(s){return grantState===s&&$('#sq-dialog').open&&runtime.detailLoadToken===s.dialogToken;}
function grantCandidateKey(row){return row.code?'code:'+row.code:'name:'+row.name;}
function grantTargets(s){return s.mode==='users'?(s.preview?.users||[]):(s.preview?.departments||[]);}
function grantSelected(s){return grantTargets(s).filter(row=>s.selected.has(s.mode==='users'?row.id:grantCandidateKey(row)));}
function grantCanSave(s){return !!s.preview&&!s.busy&&!(s.preview.unknown||[]).length&&grantSelected(s).length>0;}
function grantResultRows(s){
 if(!s.preview)return '';
 const rows=grantTargets(s),unknown=s.preview.unknown||[];
 return `${unknown.length?`<p class="ws-grant-warning" role="alert">확인되지 않은 사번: ${unknown.map(esc).join(', ')}. 로그인 이력이 있는 사번인지 확인한 뒤 다시 입력해 주세요.</p>`:''}<div class="ws-grant-preview-head"><strong>확인한 대상 ${rows.length}${s.mode==='users'?'명':'개 부서'}</strong><span>추가할 대상을 선택하세요.</span></div><div class="ws-grant-candidates">${rows.map(row=>{const key=s.mode==='users'?row.id:grantCandidateKey(row);return `<label class="ws-grant-candidate"><input type="checkbox" data-grant-select="${esc(key)}" ${s.selected.has(key)?'checked':''} ${s.busy?'disabled':''}><span><strong>${esc(row.name)}${s.mode==='users'?` <small>${esc(row.id)}</small>`:''}</strong><small>${s.mode==='users'?esc(row.dept||'부서 정보 없음'):`${row.code?'부서 코드 '+esc(row.code):'부서명 정확히 일치'} · 현재 ${row.memberCount}명`}</small></span>${s.mode==='department'?icon('building-2'):icon('user-round')}</label>`;}).join('')||'<p class="sq-note">일치하는 대상이 없습니다. 정확한 사번 또는 부서 이름·코드를 확인해 주세요.</p>'}</div>`;
}
function renderGrantManager(s){
 if(!grantLive(s))return;
 const snap=s.snapshot||{users:[],departments:[]},count=snap.users.length+snap.departments.length;
 $('#sq-dialog-body').innerHTML=`<section class="ws-grant-manager"><div class="ws-grant-intro"><span>${icon('shield-check')}</span><div><strong>함께 사용할 동료를 추가하세요.</strong><p>개인 또는 부서에 조회·다운로드 권한을 부여합니다. 등록자와 관리자는 기본으로 조회할 수 있습니다.</p></div></div>${!getItem(s.tool)?.approval?'<p class="ws-grant-info">현재 전체 공개된 기능입니다. 아래 설정은 ‘승인 후 조회’를 사용하는 동안 적용됩니다.</p>':''}<div class="ws-segment ws-grant-modes" role="group" aria-label="권한 추가 방식">${button('grant-mode',icon('users')+' 사번으로 추가','',`data-mode="users" aria-pressed="${s.mode==='users'}" ${s.busy?'disabled':''}`)}${button('grant-mode',icon('building-2')+' 팀·부서로 추가','',`data-mode="department" aria-pressed="${s.mode==='department'}" ${s.busy?'disabled':''}`)}</div><form data-grant-form="preview"><label class="sq-field"><span>${s.mode==='users'?'사번 여러 개':'팀명 또는 부서 코드'}</span>${s.mode==='users'?`<textarea name="value" data-grant-input rows="3" maxlength="12000" placeholder="1000001, 1000002&#10;1000003" required ${s.busy?'disabled':''}>${esc(s.value)}</textarea>`:`<input name="value" data-grant-input value="${esc(s.value)}" maxlength="100" placeholder="예: 융합기술팀 또는 D12345" required ${s.busy?'disabled':''}>`}<small>${s.mode==='users'?'쉼표·공백·줄바꿈으로 구분해 최대 100명까지 입력하세요. 중복 사번은 한 번만 반영합니다.':'로그인 이력이 있는 구성원의 SSO 부서를 검색합니다. 이름이 같으면 부서 코드를 확인해 선택하세요.'}</small></label><div class="ws-grant-check"><span>${s.mode==='users'?'확인 후 추가할 사람을 선택할 수 있어요.':'부서 코드를 우선 적용하며, 부서 변경은 다음 SSO 로그인 때 반영됩니다.'}</span><button class="sq-secondary" type="submit" ${s.busy?'disabled':''}>${s.busy?'처리 중…':'대상 확인'}</button></div></form><div id="ws-grant-preview">${grantResultRows(s)}</div><div class="ws-grant-save"><p id="ws-grant-notice" role="status">${esc(s.notice||'')}</p>${button('grant-save','선택한 대상 추가','sq-primary',`id="ws-grant-save" ${grantCanSave(s)?'':'disabled'}`)}</div><details class="ws-grant-existing" ${count?'open':''}><summary>현재 부여한 권한 <span>${count}</span>${icon('chevron-down')}</summary><p class="ws-grant-info">개인 권한과 부서 권한 중 하나라도 있으면 조회할 수 있습니다. 개인 권한을 회수해도 부서 권한이 있으면 유지됩니다.</p><h3>부서 권한 <small>${snap.departments.length}</small></h3>${snap.departments.map(row=>`<div class="ws-grant-member"><span class="ws-grant-member-icon">${icon('building-2')}</span><div><strong>${esc(row.name)}</strong><small>${row.code?'부서 코드 '+esc(row.code):'부서명 일치'} · 현재 ${row.memberCount}명</small></div>${button('grant-revoke-department','회수','sq-secondary',`data-rule="${esc(row.id)}" ${s.busy?'disabled':''}`)}</div>`).join('')||'<p class="sq-note">추가된 부서가 없습니다.</p>'}<h3>개인 권한 <small>${snap.users.length}</small></h3>${snap.users.map(row=>`<div class="ws-grant-member"><span class="ws-grant-member-icon">${icon('user-round')}</span><div><strong>${esc(row.name)} <small>${esc(row.id)}</small></strong><small>${esc(row.dept||'부서 정보 없음')} · ${esc(row.source||'직접 추가')}</small></div>${button('grant-revoke-user','회수','sq-secondary',`data-request="${esc(row.requestId)}" ${s.busy?'disabled':''}`)}</div>`).join('')||'<p class="sq-note">추가된 개인 권한이 없습니다.</p>'}</details></section>`;
 mountIcons();updateGrantSaveButton(s);
}
function updateGrantSaveButton(s){const b=$('#ws-grant-save');if(b&&grantLive(s)){b.disabled=!grantCanSave(s);const count=grantSelected(s).length;b.textContent=s.busy?'처리 중…':count?`선택한 ${count}${s.mode==='users'?'명':'개 부서'} 추가`:'선택한 대상 추가';}}
async function openGrantManager(id){
 const tool=+id,x=getItem(tool);if(!x?.canManage)throw Error('등록자 또는 관리자만 권한을 변경할 수 있습니다.');
 openModal('조회 권한 관리',x.name,'<p class="sq-note" role="status">권한 정보를 불러오고 있습니다.</p>');
 const s=grantState={tool,mode:'users',value:'',preview:null,selected:new Set(),busy:false,notice:'',sequence:++grantSequence,dialogToken:runtime.detailLoadToken,snapshot:null};
 try{const result=await requestAPI(`/api/tools/${tool}/grants`);if(!grantLive(s))return;s.snapshot=result;renderGrantManager(s);}catch(error){if(grantLive(s))throw error;}
}
async function previewGrantTargets(s){
 if(!grantLive(s)||s.busy)return;
 const sequence=++grantSequence,mode=s.mode,value=s.value.trim();s.sequence=sequence;s.preview=null;s.selected.clear();
 if(!value){s.notice='사번 또는 부서를 입력해 주세요.';renderGrantManager(s);return;}
 s.notice='대상을 확인하고 있습니다.';renderGrantManager(s);
 try{const result=await requestAPI(`/api/tools/${s.tool}/grants/preview`,'POST',{mode,value});if(!grantLive(s)||s.sequence!==sequence)return;s.preview=result;s.selected=new Set(mode==='users'?(result.users||[]).map(x=>x.id):[]);s.notice='';renderGrantManager(s);}
 catch(error){if(!grantLive(s)||s.sequence!==sequence)return;s.notice=error.message;renderGrantManager(s);}
}
async function reloadSavedGrants(s,message){
 s.notice=message;
 try{const snapshot=await requestAPI(`/api/tools/${s.tool}/grants`);if(grantLive(s))s.snapshot=snapshot;await refresh();}
 catch(error){if(grantLive(s))s.notice=message+' 목록을 갱신하지 못했습니다. 권한 창을 다시 열어 현재 반영 여부를 확인해 주세요.';}
}
async function saveGrantTargets(){
 const s=grantState;if(!s||!grantLive(s)||!grantCanSave(s))return;
 const selected=grantSelected(s);s.busy=true;s.notice='권한을 추가하고 있습니다.';renderGrantManager(s);
 try{
  const result=await requestAPI(`/api/tools/${s.tool}/grants${s.mode==='department'?'/departments':''}`,'POST',s.mode==='users'?{users:selected.map(x=>x.id)}:{departments:selected.map(x=>({code:x.code,name:x.name})),expectedRevision:s.snapshot.revision});
  if(!grantLive(s))return;
  const failed=result.failed||[],saved=(result.saved||[]).length,existing=(result.alreadyGranted||[]).length;
  let message=s.mode==='users'?`${saved}명 추가${existing?`, ${existing}명은 이미 권한이 있습니다`:''}.`:`${selected.length}개 부서 권한을 적용했습니다.`;
  if(failed.length){const ids=new Set(failed.map(x=>x.id));s.preview={mode:'users',users:selected.filter(x=>ids.has(x.id)),unknown:[]};s.selected=ids;message+=` ${failed.length}명은 저장 결과를 확인하지 못했습니다: ${failed.map(x=>x.id).join(', ')}. 현재 권한 목록을 확인한 뒤 이 대상만 다시 추가하세요.`;}
  else{s.preview=null;s.selected.clear();s.value='';}
  await reloadSavedGrants(s,message);
 }catch(error){if(grantLive(s))s.notice=error.uncertain?'서버 응답을 확인하지 못했습니다. 권한 창을 다시 열어 반영 여부를 확인한 뒤 재시도해 주세요.':error.message;}
 finally{s.busy=false;if(grantLive(s))renderGrantManager(s);}
}
async function revokeGrant(kind,id){
 const s=grantState;if(!s||!grantLive(s)||s.busy)return;
 ask(kind==='department'?'이 부서의 조회 권한을 회수할까요?':'이 개인의 조회 권한을 회수할까요?',kind==='department'?'이 부서의 구성원은 부서 권한으로 조회할 수 없게 됩니다. 별도로 받은 개인 권한은 유지됩니다.':'부서 권한이 있다면 개인 권한을 회수해도 조회할 수 있습니다.',async()=>{
  if(!grantLive(s)||s.busy)return;s.busy=true;renderGrantManager(s);
  try{await requestAPI(kind==='department'?`/api/tools/${s.tool}/grants/departments/${encodeURIComponent(id)}`:`/api/requests/${encodeURIComponent(id)}/decision`,kind==='department'?'DELETE':'POST',kind==='department'?{expectedRevision:s.snapshot.revision}:{status:'회수',reason:'권한 관리에서 직접 회수'});if(grantLive(s))await reloadSavedGrants(s,'권한을 회수했습니다.');}
  catch(error){if(grantLive(s))s.notice=error.uncertain?'서버 응답을 확인하지 못했습니다. 권한 창을 다시 열어 회수 여부를 확인해 주세요.':error.message;}
  finally{s.busy=false;if(grantLive(s))renderGrantManager(s);}
 },'권한 회수');
}
actions['grant-users']=b=>openGrantManager(b.dataset.id);
actions['grant-mode']=b=>{const s=grantState;if(!s||s.busy||!grantLive(s))return;s.mode=b.dataset.mode;s.value='';s.preview=null;s.selected.clear();s.notice='';s.sequence=++grantSequence;renderGrantManager(s);};
actions['grant-save']=saveGrantTargets;
actions['grant-revoke-department']=b=>revokeGrant('department',b.dataset.rule);
actions['grant-revoke-user']=b=>revokeGrant('user',b.dataset.request);
actions['grant-tools']=()=>{const rows=items.filter(x=>!x.deleted&&x.canManage);openModal('기능별 권한 설정','권한 관리',`<div class="ws-grant-tool-list">${rows.map(x=>`<button class="ws-row ws-click" data-action="grant-users" data-id="${x.id}"><span class="sq-tool-icon" data-type="${esc(x.type)}">${icon(x.icon)}</span><span class="ws-row-main"><strong>${esc(x.name)}</strong><span>${esc(x.org)} · ${x.approval?'승인 후 조회':'전체 공개'}</span></span>${icon('chevron-right')}</button>`).join('')||blank('package-open','등록한 기능이 없습니다.','먼저 기능을 등록해 주세요.')}</div>`);};
root.addEventListener('submit',e=>{if(!e.target.matches('[data-grant-form="preview"]'))return;e.preventDefault();e.stopImmediatePropagation();const s=grantState;if(s)previewGrantTargets(s).catch(showError);},true);
root.addEventListener('input',e=>{if(!e.target.matches('[data-grant-input]'))return;const s=grantState;if(!s||s.busy||!grantLive(s))return;s.value=e.target.value;s.sequence=++grantSequence;s.preview=null;s.selected.clear();s.notice='';$('#ws-grant-preview').innerHTML='';$('#ws-grant-notice').textContent='';updateGrantSaveButton(s);});
root.addEventListener('change',e=>{if(!e.target.matches('[data-grant-select]'))return;const s=grantState;if(!s||s.busy||!grantLive(s))return;const key=e.target.dataset.grantSelect;e.target.checked?s.selected.add(key):s.selected.delete(key);updateGrantSaveButton(s);});
