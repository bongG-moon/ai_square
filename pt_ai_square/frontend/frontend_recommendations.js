// A recommendation belongs to a checked release. Public summaries may disclose
// the badge alone; the authenticated detail remains the source for its reason.
function recommendationActive(item){return item?.recommendationBadge?.active===true;}
function recommendationBadgeHTML(item){
 if(!recommendationActive(item))return '';
 return `<button type="button" class="sq-recommendation-badge cursor-interaction" data-action="recommendation-info" data-id="${Number(item.id)}" aria-label="${esc(item.name)} 추천 이유 보기" aria-haspopup="dialog">${icon('star')}<span>추천</span></button>`;
}
const recommendationCard=card;
card=function(item,...args){
 const markup=recommendationCard(item,...args);
 // Keep the existing card body, metric controls and layout. Put all compact
 // metadata in one row, without nesting an interactive badge in the main button.
 const meta=`<div class="sq-tool-metadata">${recommendationBadgeHTML(item)}<span class="sq-tool-type sq-type-label" data-type="${esc(item.type)}">${esc(typeLabel(item.type))}</span><span class="sq-tool-organization" title="${esc(item.org)}">${esc(item.org)}</span></div>`;
 return markup.replace(`<div class="sq-tool-footer"><span>${esc(item.org)}</span>`,`<div class="sq-tool-footer">${meta}`)
  .replace(`<span class="sq-tool-kind">${esc(item.platform)} · <span class="sq-type-label" data-type="${esc(item.type)}">${esc(item.type)}</span></span>`,`<span class="sq-tool-kind">${esc(item.platform)}</span>`);
};
const recommendationOriginalSort=Core.sort;
Core.sort=function(rows,order){
 const sorted=recommendationOriginalSort(rows,order);
 if(state.route!=='browse'||String(state.query||'').trim()||order!=='discovery')return sorted;
 // Stable partition after the established editorial ordering, before pagination.
 return [...sorted.filter(recommendationActive),...sorted.filter(item=>!recommendationActive(item))];
};
function recommendationDetailHTML(item){
 const data=item?.recommendationBadge;
 if(item?.access!=='approved'||!data?.active||!data.reason||!Number.isSafeInteger(data.reviewedVersion))return '';
 return `<section id="sq-recommendation-reason" class="sq-recommendation-reason" aria-labelledby="sq-recommendation-title" tabindex="-1"><div class="sq-recommendation-heading"><span>${icon('star')}<h3 id="sq-recommendation-title">추천하는 이유</h3></span><small>확인한 버전 v${data.reviewedVersion}</small></div><p>${esc(data.reason)}</p></section>`;
}
const recommendationOriginalDetail=detail;
detail=async function(id,tab='intro'){
 const user=String(server.user.id);
 await recommendationOriginalDetail(id,tab);
 if(user!==String(server.user.id)||tab!=='intro'||!$('#sq-dialog')?.open||runtime.detailId!==Number(id)||runtime.detailTab!=='intro'||activeDetailView!==Number(id))return;
 const html=recommendationDetailHTML(getItem(id));
 $('#sq-recommendation-reason')?.remove();
 if(html){$('#sq-dialog-body .sq-detail-hero')?.insertAdjacentHTML('afterend',html);mountIcons();}
};
actions['recommendation-info']=async b=>{
 const id=Number(b.dataset.id),user=String(server.user.id);
 await detail(id,'intro');
 if(user===String(server.user.id)&&activeDetailView===id&&runtime.detailId===id&&$('#sq-dialog')?.open){$('#sq-recommendation-reason')?.focus({preventScroll:true});$('#sq-recommendation-reason')?.scrollIntoView({block:'nearest'});}
};

function recommendationAdminControl(item){
 if(server.user.role!=='admin'||state.route!=='admin'||item.deleted)return '';
 const data=item.recommendationBadge||{},status=data.status==='needs_review'?'재확인 필요':data.active?'추천 중':'';
 return `<span class="ws-recommendation-control">${status?`<span class="ws-recommendation-status" data-status="${data.status==='needs_review'?'needs_review':'active'}">${esc(status)}</span>`:''}${button('recommendation-settings',icon('star')+' 추천 설정','sq-link',`type="button" data-id="${Number(item.id)}" aria-label="${esc(item.name)} 추천 설정"`)}</span>`;
}
let recommendationEditor=null;
function recommendationCurrent(s){return !!s&&recommendationEditor===s&&s.user===String(server.user.id)&&server.user.role==='admin';}
function recommendationVisible(s){return recommendationCurrent(s)&&s.view===runtime.detailLoadToken&&$('#sq-dialog')?.open;}
function recommendationControls(s){
 if(!recommendationVisible(s))return;
 for(const selector of ['#ws-recommendation-reason','[data-action="recommendation-save"]','[data-action="recommendation-remove"]','[data-action="recommendation-remove-confirm"]']){
  const node=$(selector);if(node){node.disabled=!!(s.busy||s.done||s.reloadRequired);node.setAttribute?.('aria-busy',String(s.busy));}
 }
 const reload=$('[data-action="recommendation-reload"]');if(reload)reload.disabled=s.busy;
}
function recommendationError(s,message,reload=false){
 if(!recommendationVisible(s))return;
 const error=$('#ws-recommendation-error');if(error){error.hidden=false;error.textContent=message;error.focus?.();}
 const recovery=$('#ws-recommendation-recovery');if(recovery)recovery.hidden=!reload;
}
function renderRecommendationEditor(s){
 const item=s.item,data=item.recommendationBadge||{},review=data.status==='needs_review',hasRecommendation=data.active||review;
 const body=s.removal?`<p class="sq-note">${esc(item.name)}의 추천 표시를 해제합니다. 도구와 파일은 그대로 유지됩니다.</p>`:`<div class="ws-recommendation-summary"><span class="ws-recommendation-symbol">${icon('star')}</span><div><strong>${esc(item.name)}</strong><span>현재 버전 v${Number(item.active)}${hasRecommendation&&Number.isSafeInteger(data.reviewedVersion)?` / 이전 확인 v${data.reviewedVersion}`:''}</span></div></div>${review?'<p class="sq-callout" role="status">새 버전이 등록되어 추천 표시가 잠시 해제되었습니다. 현재 버전의 내용을 확인한 뒤 다시 추천해 주세요.</p>':''}<label class="sq-field"><span>추천하는 이유 <small>필수</small></span><textarea id="ws-recommendation-reason" rows="4" maxlength="300" required placeholder="어떤 업무에 유용하고, 어떤 점을 확인했는지 적어 주세요.">${esc(s.reason)}</textarea><small>이 도구를 조회할 수 있는 사용자에게 표시됩니다. 현재 버전 v${Number(item.active)}에 대한 추천으로 저장됩니다.</small></label>`;
 const save=s.removal?button('recommendation-remove-confirm','추천 해제','sq-primary','type="button"'):button('recommendation-save',review?'현재 버전 다시 추천':'추천 저장','sq-primary','type="button"');
 const cancel=s.removal?button('recommendation-remove-cancel','돌아가기','sq-secondary','type="button"'):button('recommendation-cancel','취소','sq-secondary','type="button"');
 openModal(s.removal?'추천을 해제할까요?':'추천 설정','도구 관리',`<div class="ws-recommendation-editor">${body}<div><p id="ws-recommendation-error" class="sq-error" role="alert" tabindex="-1" hidden></p><div id="ws-recommendation-recovery" hidden>${button('recommendation-reload','최신 상태 확인','sq-link','type="button"')}</div></div><div class="sq-actions ws-recommendation-actions">${!s.removal&&hasRecommendation?button('recommendation-remove','추천 해제','sq-link ws-danger','type="button"'):''}<span></span>${cancel}${save}</div></div>`);
 s.view=runtime.detailLoadToken;recommendationControls(s);
}
async function openRecommendationEditor(id){
 if(server.user.role!=='admin')return;
 // A dismissed read can be replaced immediately. Only an in-flight mutation
 // blocks another editor until its outcome is known.
 if(recommendationCurrent(recommendationEditor)&&recommendationEditor.saving){announce('추천 저장 결과를 확인하고 있습니다. 잠시 기다려 주세요.');return;}
 const s={id:Number(id),user:String(server.user.id),busy:true,done:false,item:null};recommendationEditor=s;
 openModal('추천 설정','도구 관리','<div class="ws-empty" role="status"><h3>현재 버전을 확인하고 있습니다.</h3></div>');s.view=runtime.detailLoadToken;
 try{
  const item=await requestAPI(`/api/tools/${s.id}`,'GET',null,{timeoutMs:10000,redirectOnAuth:false});
  if(!recommendationVisible(s))return;
  if(item.id!==s.id||item.deleted||!Number.isSafeInteger(item.revision)||!Number.isSafeInteger(item.active)||!item.recommendationBadge)throw Error('현재 도구 정보를 확인하지 못했습니다. 최신 상태를 다시 확인해 주세요.');
  s.item=item;s.reason=item.recommendationBadge.reason||'';s.busy=false;renderRecommendationEditor(s);
 }catch(error){
  if(!recommendationVisible(s))return;
  s.busy=false;openModal('추천 정보를 불러오지 못했습니다','도구 관리',`<p class="sq-error" role="alert">${esc(error.message||'다시 시도해 주세요.')}</p><div class="sq-actions">${button('recommendation-cancel','닫기','sq-secondary')}${button('recommendation-reload','최신 상태 확인','sq-primary')}</div>`);s.view=runtime.detailLoadToken;
 }finally{s.busy=false;}
}
async function saveRecommendation(enabled){
 const s=recommendationEditor;if(!s?.item||!recommendationVisible(s)||s.busy||s.done||s.reloadRequired)return;
 if(!enabled&&!s.removal)return;
 const reason=enabled?String($('#ws-recommendation-reason')?.value||'').trim():'';
 if(enabled&&(!reason||reason.length>300)){recommendationError(s,'추천하는 이유를 1~300자로 입력해 주세요.');$('#ws-recommendation-reason')?.focus();return;}
 s.reason=reason;s.busy=true;s.saving=true;recommendationControls(s);
 try{
  const result=await requestAPI(`/api/tools/${s.id}/recommendation`,'PUT',{enabled,reason,expectedRevision:s.item.revision},{timeoutMs:15000,redirectOnAuth:false});
  // pending only describes audit delivery; the recommendation is committed.
  if(!result.ok||!Number.isSafeInteger(result.revision)||!result.recommendationBadge){const error=Error('저장 결과를 다시 확인해야 합니다.');error.uncertain=true;throw error;}
  s.done=true;
  if(!recommendationCurrent(s))return;
  const item=getItem(s.id);if(item&&result.revision>=item.revision){item.revision=result.revision;item.recommendationBadge=result.recommendationBadge;}
  if(recommendationVisible(s))closeModal();s.completionView=runtime.detailLoadToken;
  await afterWorkspaceSave(async()=>{await refresh();if(recommendationCurrent(s)&&s.completionView===runtime.detailLoadToken&&!$('#sq-dialog')?.open)announce(enabled?'추천을 저장했습니다.':'추천을 해제했습니다.');});
 }catch(error){
  if(!recommendationCurrent(s))return;
  if(s.done){if(s.completionView===runtime.detailLoadToken&&!$('#sq-dialog')?.open)showError(error);return;}
  s.reloadRequired=!!error.uncertain||error.status===409;
  recommendationError(s,error.uncertain?'저장 응답을 확인하지 못했습니다. 다시 저장하기 전에 최신 상태를 확인해 주세요.':error.status===409?'다른 변경사항이 먼저 저장되었습니다. 최신 버전과 추천 상태를 확인한 뒤 다시 설정해 주세요.':error.message||'추천을 저장하지 못했습니다.',s.reloadRequired);
 }finally{s.busy=false;s.saving=false;recommendationControls(s);}
}
actions['recommendation-settings']=b=>openRecommendationEditor(b.dataset.id);
actions['recommendation-save']=()=>saveRecommendation(true);
actions['recommendation-remove-confirm']=()=>saveRecommendation(false);
actions['recommendation-cancel']=()=>{if(recommendationVisible(recommendationEditor))closeModal();};
actions['recommendation-reload']=()=>{const s=recommendationEditor;if(recommendationVisible(s)&&!s.busy&&!s.done)return openRecommendationEditor(s.id);};
actions['recommendation-remove']=()=>{const s=recommendationEditor;if(!recommendationVisible(s)||s.busy||s.done||s.reloadRequired)return;s.reason=$('#ws-recommendation-reason')?.value||s.reason;s.removal=true;renderRecommendationEditor(s);};
actions['recommendation-remove-cancel']=()=>{const s=recommendationEditor;if(!recommendationVisible(s)||s.busy||s.done||s.reloadRequired)return;s.removal=false;renderRecommendationEditor(s);};
// The shared click handler re-enables its button after every request. Own this
// small action group so an uncertain save stays locked until its read-only check.
root.addEventListener('click',event=>{
 const b=event.target.closest('button'),action=b?.dataset.action;
 if(!action?.startsWith('recommendation-')||!root.contains(b)||b.disabled||typeof actions[action]!=='function')return;
 event.preventDefault();event.stopImmediatePropagation();b.disabled=true;
 return Promise.resolve().then(()=>actions[action](b)).catch(showError).finally(()=>{if(b.isConnected)b.disabled=false;recommendationControls(recommendationEditor);});
},true);
