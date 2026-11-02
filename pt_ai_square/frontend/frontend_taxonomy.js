// Administrative taxonomy deletion is previewed before any write. The popup
// owns its async responses; leaving it never lets an older response reopen it.
let taxonomyDeletion=null;
function taxonomyDeletionCurrent(s){return !!s&&taxonomyDeletion===s&&s.user===String(server.user.id)&&server.user.role==='admin';}
function taxonomyDeletionVisible(s){return taxonomyDeletionCurrent(s)&&s.view===runtime.detailLoadToken&&$('#sq-dialog')?.open;}
function taxonomyDeleteError(s,message){
 if(!taxonomyDeletionVisible(s))return;
 const node=$('#ws-taxonomy-delete-error');if(node){node.hidden=false;node.textContent=message;node.focus?.();}
 const recovery=$('#ws-taxonomy-delete-recovery');if(recovery)recovery.hidden=false;
}
function taxonomyDeleteControls(s){
 if(!taxonomyDeletionVisible(s))return;
 const select=$('#ws-taxonomy-delete-target'),confirm=$('[data-action="taxonomy-confirm-delete"]');
 if(select){select.disabled=s.busy||!!s.lockedTargetId;const trigger=select.nextElementSibling;if(trigger?.classList.contains('ws-select'))trigger.disabled=select.disabled;}
 if(confirm){confirm.disabled=s.busy||s.done||s.preview?.protected||!!s.preview?.usage.total&&!s.selected;confirm.textContent=s.busy?'처리 중…':(s.lockedTargetId||s.preview?.pending)?'삭제 마무리':s.preview?.usage.total?'이관하고 삭제':'삭제';confirm.setAttribute('aria-busy',String(s.busy));}
}
function renderTaxonomyDeletion(s){
 const p=s.preview,kind=p.item.kind==='organization'?'조직':'업무 분류',used=p.usage.total>0;
 const usage=[['tools','등록된 도구','개'],['ideas','기능 요청','건'],['users','연결된 사용자','명']].filter(([key])=>p.usage[key]>0);
 const targets=p.targets.filter(row=>row.id!==p.item.id);
 const transfer=(used||s.lockedTargetId)&&!p.protected?targets.length?`<label class="sq-field"><span>이관할 ${kind} <small>필수</small></span><select id="ws-taxonomy-delete-target" aria-label="이관할 ${kind}" required><option value="" disabled ${s.selected?'':'selected'}>이관할 ${kind} 선택</option>${targets.map(row=>`<option value="${esc(row.id)}" ${s.selected===row.id?'selected':''}>${esc(row.name)}</option>`).join('')}</select><small>${s.lockedTargetId?'이미 시작한 이관을 선택했던 항목으로 마무리합니다. 이관 대상은 변경할 수 없습니다.':'선택한 항목으로 기존 연결을 옮긴 뒤 삭제합니다.'}</small></label>`:`<p class="sq-callout" role="status">선택할 수 있는 이관 대상이 없습니다. 먼저 다른 ${kind} 항목을 추가하거나 사용 상태로 바꾼 뒤 다시 시도해 주세요.</p>`:'';
 const html=`<div class="ws-taxonomy-delete"><div class="ws-taxonomy-delete-summary"><span class="ws-taxonomy-delete-icon">${icon('trash-2')}</span><div><strong>${esc(p.item.name)}</strong><p>${p.protected?esc(p.reason||'기본 항목은 삭제할 수 없습니다.'):'이 분류를 목록에서 삭제합니다. 등록된 도구와 파일은 삭제되지 않습니다.'}</p></div></div>${used?`<div><div class="ws-taxonomy-usage" aria-label="이관할 연결 항목">${usage.map(([key,label,suffix])=>`<div><span>${label}</span><strong>${p.usage[key]}<small>${suffix}</small></strong></div>`).join('')}</div>${p.usage.tools?'<p class="ws-taxonomy-usage-note">도구 수에는 휴지통에 있는 도구도 포함됩니다.</p>':''}</div>`:p.protected?'':p.pending?'<p class="sq-note">이관이 진행 중입니다. 남은 삭제를 마무리해 주세요.</p>':'<p class="sq-note">연결된 항목이 없어 바로 삭제할 수 있습니다.</p>'}${transfer}<div><p id="ws-taxonomy-delete-error" class="sq-error" role="alert" tabindex="-1" hidden></p><div id="ws-taxonomy-delete-recovery" hidden>${button('taxonomy-delete-reload','연결된 항목 다시 확인','sq-link','type="button"')}</div></div><div class="sq-actions ws-taxonomy-delete-actions">${button('taxonomy-delete-cancel',p.protected?'닫기':'취소','sq-secondary','type="button"')}${p.protected?'':button('taxonomy-confirm-delete',used?'이관하고 삭제':'삭제','sq-primary ws-taxonomy-delete-confirm',`type="button" ${used&&!s.selected?'disabled':''}`)}</div></div>`;
 openModal(p.protected?'삭제할 수 없는 항목입니다':p.item.kind==='organization'?'조직을 삭제할까요?':'업무 분류를 삭제할까요?','조직과 업무 분류',html);s.view=runtime.detailLoadToken;
 taxonomyDeleteControls(s);
}
async function openTaxonomyDeletion(id,preferredTarget=''){
 if(server.user.role!=='admin')return;
 if(taxonomyDeletion?.busy){announce('삭제 결과를 확인하고 있습니다. 잠시 기다려 주세요.');return;}
 const s={id:String(id),user:String(server.user.id),preview:null,selected:'',busy:false};taxonomyDeletion=s;
 openModal('삭제할 항목 확인','조직과 업무 분류','<div class="ws-empty" role="status"><h3>연결된 항목을 확인하고 있습니다.</h3><p>잠시만 기다려 주세요.</p></div>');s.view=runtime.detailLoadToken;
 try{
  const p=await requestAPI(`/api/taxonomy/${encodeURIComponent(s.id)}/deletion-preview`,'GET',undefined,{timeoutMs:10000,redirectOnAuth:false});
  if(!taxonomyDeletionVisible(s))return;
  if(p.item?.id!==s.id||!['organization','category'].includes(p.item?.kind)||!p.usage||!['tools','ideas','users','total'].every(key=>Number.isSafeInteger(p.usage[key])&&p.usage[key]>=0)||!Array.isArray(p.targets))throw Error('삭제 정보를 확인하지 못했습니다. 다시 확인해 주세요.');
  s.preview=p;s.lockedTargetId=p.lockedTargetId||null;s.selected=s.lockedTargetId||(p.targets.some(row=>row.id===preferredTarget)?preferredTarget:'');
  if(p.deleted){s.done=true;openModal('이미 삭제한 항목입니다','조직과 업무 분류',`<p class="sq-note">${esc(p.item.name)} 삭제가 완료되었습니다. 목록을 새로 불러와 확인해 주세요.</p><div class="sq-actions">${button('taxonomy-delete-cancel','닫기','sq-secondary')}${button('taxonomy-delete-refresh','목록 새로고침','sq-primary')}</div>`);s.view=runtime.detailLoadToken;return;}
  renderTaxonomyDeletion(s);
 }catch(error){
  if(!taxonomyDeletionVisible(s))return;
  openModal('삭제 정보를 불러오지 못했습니다','조직과 업무 분류',`<p class="sq-error" role="alert">${esc(error.message||'다시 시도해 주세요.')}</p><div class="sq-actions">${button('taxonomy-delete-cancel','취소','sq-secondary')}${button('taxonomy-delete-retry','다시 확인','sq-primary')}</div>`);s.view=runtime.detailLoadToken;
 }
}
function taxonomyDeletedFilters(s,selected){
 const p=s.preview,target=p.targets.find(row=>row.id===selected);
 if(p.item.kind==='organization'&&state.org===p.item.name)state.org=target?.name||'전체 조직';
 if(p.item.kind==='category'&&state.category===p.item.name)state.category=target?.name||'모든 업무';
 state.page=0;persist();
}
async function confirmTaxonomyDeletion(){
 const s=taxonomyDeletion;if(!s?.preview||!taxonomyDeletionVisible(s)||s.busy||s.done||s.preview.protected)return;
 const p=s.preview,selected=s.lockedTargetId||$('#ws-taxonomy-delete-target')?.value||s.selected;
 if(p.usage.total&&!p.targets.some(row=>row.id===selected&&row.id!==s.id)){taxonomyDeleteError(s,'이관할 항목을 선택해 주세요.');return;}
 s.selected=selected;s.busy=true;taxonomyDeleteControls(s);
 try{
  const result=await requestAPI(`/api/taxonomy/${encodeURIComponent(s.id)}/delete`,'POST',{confirmed:true,...(selected?{targetId:selected}:{})},{timeoutMs:30000,redirectOnAuth:false});
  if(!result.deleted)throw Error('삭제를 완료하지 못했습니다. 같은 항목으로 다시 시도해 주세요.');
  s.done=true;
  if(!taxonomyDeletionCurrent(s))return;
  taxonomyDeletedFilters(s,selected);
  const visible=taxonomyDeletionVisible(s);if(visible)closeModal();s.completionView=runtime.detailLoadToken;
  await afterWorkspaceSave(async()=>{await refresh();if(s.user===String(server.user.id)&&s.completionView===runtime.detailLoadToken&&!$('#sq-dialog')?.open)announce(`${p.item.name} ${selected?'이관과 삭제를':'삭제를'} 완료했습니다.`);});
 }catch(error){
  if(!taxonomyDeletionCurrent(s))return;
  if(s.done){if(s.completionView===runtime.detailLoadToken&&!$('#sq-dialog')?.open)showError(error);return;}
  if(error.uncertain&&selected)s.lockedTargetId=selected;
  const message=error.uncertain?'서버 응답을 확인하지 못했습니다. 선택한 이관 대상은 유지됩니다. 같은 내용으로 다시 시도하면 삭제 상태를 확인하고 남은 처리를 이어갑니다.':error.message||'삭제를 완료하지 못했습니다. 다시 시도해 주세요.';
  taxonomyDeleteError(s,message);
 }finally{s.busy=false;taxonomyDeleteControls(s);}
}
actions['taxonomy-delete']=b=>openTaxonomyDeletion(b.dataset.id);
actions['taxonomy-delete-retry']=()=>taxonomyDeletion&&!taxonomyDeletion.busy&&openTaxonomyDeletion(taxonomyDeletion.id);
actions['taxonomy-delete-reload']=()=>taxonomyDeletion&&!taxonomyDeletion.busy&&openTaxonomyDeletion(taxonomyDeletion.id,taxonomyDeletion.selected);
actions['taxonomy-delete-cancel']=()=>{if(taxonomyDeletionVisible(taxonomyDeletion))closeModal();};
actions['taxonomy-delete-refresh']=async()=>{const s=taxonomyDeletion;if(!taxonomyDeletionVisible(s)||s.busy)return;s.busy=true;try{taxonomyDeletedFilters(s,s.lockedTargetId);await refresh();if(taxonomyDeletionVisible(s))closeModal();}catch(error){if(taxonomyDeletionVisible(s))showError(error);}finally{s.busy=false;}};
actions['taxonomy-confirm-delete']=confirmTaxonomyDeletion;
root.addEventListener('change',event=>{
 const s=taxonomyDeletion;if(event.target.id!=='ws-taxonomy-delete-target'||!s||!taxonomyDeletionVisible(s)||s.busy||s.lockedTargetId)return;
 s.selected=event.target.value;const error=$('#ws-taxonomy-delete-error');if(error){error.hidden=true;error.textContent='';}taxonomyDeleteControls(s);
});
