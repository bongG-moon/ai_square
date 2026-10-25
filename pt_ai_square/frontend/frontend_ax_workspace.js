// Administrator-published downloads are kept separate from community tool rankings.
const axCategories={workspace:'AX Workspace',plugin:'확장 프로그램',integration:'연동 도구'};
function axCategory(value){return Object.keys(axCategories).includes(value)?value:'integration';}
function axNextRelease(item){return item?(Number.isSafeInteger(item.release)&&item.release>0?item.release:1)+1:1;}
let axFiles=[],axFilter='all',axFile=null,axLoadToken=0,axUploadBusy=false,axMaxFileBytes=128*1048576-65536;
let axVersionTarget=null,axHighlightId=null,axMutationToken=0,axCatalogGeneration=0,axSubscriptionRead=null,axSubscriptionCheckedAt=0,axDownloadTimer=null;
const axSubscriptionBusy=new Set();
// A KEY-page link can open this catalog after the first completed bootstrap.
// The existing navigation/dialog generation preserves any choice made while it loads.
const axInitialViews=new URLSearchParams(typeof location==='undefined'?'':location.search).getAll('view');
const axInitialNavigationToken=runtime.detailLoadToken,baseAxRefresh=refresh;
let axInitialViewPending=axInitialViews.length===1&&axInitialViews[0]==='ax';
refresh=async function(){
 const result=await baseAxRefresh();
 // authMode is supplied by a completed bootstrap, including read-only dummy mode.
 if(axInitialViewPending&&server.authMode){
  axInitialViewPending=false;
  if(runtime.detailLoadToken===axInitialNavigationToken)await actions['ax-workspace']();
 }
 return result;
};
async function loadAxWorkspace(){
 const token=++axLoadToken,mutation=axMutationToken,result=await requestAPI('/api/ax-workspace');
 if(token!==axLoadToken||mutation!==axMutationToken)return false;
 axFiles=result.files.map(row=>axSubscriptionBusy.has(row.id)?{...row,subscribed:axFiles.find(x=>x.id===row.id)?.subscribed===true}:row);axCatalogGeneration++;
 if(Number.isSafeInteger(result.maxFileBytes)&&result.maxFileBytes>=0)axMaxFileBytes=result.maxFileBytes;return true;
}
function axSubscriptionLabel(row){return icon(row.subscribed?'bell-ring':'bell')+(row.subscribed?' 업데이트 알림 켜짐':' 업데이트 알림 꺼짐');}
function updateAxSubscriptionControls(){
 if(state.route!=='ax')return;
 $$('[data-action="ax-subscription"]').forEach(b=>{const row=axFiles.find(x=>x.id===b.dataset.id);if(!row)return;b.disabled=axSubscriptionBusy.has(row.id);b.setAttribute('aria-pressed',String(row.subscribed===true));b.setAttribute('aria-label',row.name+' 업데이트 알림 '+(row.subscribed?'끄기':'켜기'));b.innerHTML=axSubscriptionLabel(row);});mountIcons();
}
async function toggleAxSubscription(id){
 const row=axFiles.find(x=>x.id===id);if(!row||axSubscriptionBusy.has(id))return;
 const token=runtime.detailLoadToken;axSubscriptionBusy.add(id);axMutationToken++;updateAxSubscriptionControls();
 try{const result=await requestAPI(`/api/ax-workspace/${encodeURIComponent(id)}/subscription`,'PUT',{enabled:row.subscribed!==true});
  if(typeof result.subscribed!=='boolean')throw Error('알림 설정 응답을 확인하지 못했습니다. 목록을 다시 열어 현재 상태를 확인해 주세요.');
  const current=axFiles.find(x=>x.id===id);if(current)current.subscribed=result.subscribed;
 }catch(error){if(token===runtime.detailLoadToken&&state.route==='ax')throw error;}
 finally{axMutationToken++;axSubscriptionBusy.delete(id);updateAxSubscriptionControls();}
}
async function refreshAxSubscriptions(force=false){
 if(state.route!=='ax'||document.hidden||$('#sq-dialog').open||axSubscriptionBusy.size||axSubscriptionRead||(!force&&Date.now()-axSubscriptionCheckedAt<5000))return;
 const token=runtime.detailLoadToken,generation=axCatalogGeneration,mutation=axMutationToken;
 const pending=(async()=>{const result=await requestAPI('/api/ax-workspace');
  if(token!==runtime.detailLoadToken||state.route!=='ax'||generation!==axCatalogGeneration||mutation!==axMutationToken)return;
  let changed=false;for(const row of result.files||[]){const current=axFiles.find(x=>x.id===row.id);if(current&&typeof row.subscribed==='boolean'&&current.subscribed!==row.subscribed){current.subscribed=row.subscribed;changed=true;}}
  axSubscriptionCheckedAt=Date.now();if(changed)updateAxSubscriptionControls();
 })();axSubscriptionRead=pending;try{await pending;}finally{if(axSubscriptionRead===pending)axSubscriptionRead=null;}
}
function focusAxWorkspaceFile(){
 if(!axHighlightId||state.route!=='ax')return;
 const card=$$('[data-ax-card]').find(x=>x.dataset.axCard===axHighlightId);if(card){card.focus({preventScroll:true});card.scrollIntoView({block:'center',behavior:'auto'});}
}
async function showAxWorkspace(id=null){
 axHighlightId=id===null?null:String(id);if(id!==null)axFilter='all';
 closeModal();navigate('ax');const token=runtime.detailLoadToken;
 try{await loadAxWorkspace();if(token===runtime.detailLoadToken&&state.route==='ax'){renderAxWorkspace();focusAxWorkspaceFile();}}
 catch(error){if(token===runtime.detailLoadToken&&state.route==='ax')throw error;}
}
function openAxWorkspaceFile(id){return showAxWorkspace(id);}
function renderAxWorkspace(){
 const admin=server.user.role==='admin',rows=axFiles.filter(x=>axFilter==='all'||axCategory(x.category)===axFilter);
 workspace.innerHTML=`<div class="ws-ax-intro"><span class="ws-ax-symbol">${icon('monitor-down')}</span><div><h2>설치부터 연결까지, 한곳에서.</h2><p>관리자가 등록한 AX Workspace 설치 파일과 확장 프로그램·연동 도구를 찾아보세요.</p></div>${admin?button('ax-register',icon('plus')+' 파일 등록','sq-primary'):''}</div><div class="ws-board-head"><div class="ws-segment ws-ax-filters">${Object.entries({all:'전체',...axCategories}).map(([key,label])=>button('ax-filter',label,'',`data-category="${key}" aria-pressed="${axFilter===key}"`)).join('')}</div><span class="ws-ax-count">${rows.length}개 파일</span></div><div class="ws-ax-grid">${rows.map(x=>`<article class="ws-ax-card${axHighlightId===String(x.id)?' is-highlighted':''}" data-ax-card="${esc(x.id)}" tabindex="-1"><div class="ws-ax-card-top"><span class="ws-ax-symbol">${icon(x.category==='workspace'?'monitor-down':x.category==='plugin'?'blocks':'cable')}</span>${badge(axCategories[axCategory(x.category)])}</div><h2>${esc(x.name)}</h2><p>${esc(x.description)}</p><div class="ws-ax-file"><strong>${esc(x.fileName)}</strong><span>${esc(x.version?'v'+x.version:'버전 미입력')} · ${fileSize(x.size)}</span></div><div class="ws-ax-card-footer"><small>${dated(x.updated||x.created)} ${x.release>1?'업데이트':'등록'}</small><a class="sq-primary" href="${esc(x.downloadUrl)}" data-ax-download="${esc(x.id)}" download aria-label="${esc(x.name)} 다운로드">${icon('download')} 다운로드</a></div><div class="ws-ax-card-actions">${button('ax-subscription',axSubscriptionLabel(x),'ws-ax-subscription',`data-id="${esc(x.id)}" aria-pressed="${x.subscribed===true}" aria-label="${esc(x.name)} 업데이트 알림 ${x.subscribed?'끄기':'켜기'}" ${axSubscriptionBusy.has(x.id)?'disabled':''}`)}${admin?button('ax-version','새 버전 등록','sq-link',`data-id="${esc(x.id)}"`):''}</div></article>`).join('')||blank('folder-down',axFilter==='all'?'아직 등록된 파일이 없습니다.':'이 분류에 등록된 파일이 없습니다.',admin?'파일 등록을 눌러 설치 파일이나 확장 프로그램을 공유하세요.':'관리자가 파일을 등록하면 이곳에서 내려받을 수 있습니다.')}</div>`;
 mountIcons();
}
function axUploadArea(){
 return `<section class="ws-upload-area" data-ax-drop><div class="ws-drop-zone"><span class="ws-upload-icon">${icon('cloud-upload')}</span><h3>배포할 파일을 여기에 놓으세요</h3><p>ZIP · AX 확장 · EXE · MSI · PS1 · MD · 최대 ${fileSize(axMaxFileBytes)}</p><button type="button" class="sq-secondary" data-action="ax-pick">${icon('plus')} 파일 선택</button><input class="sq-sr" type="file" id="sq-ax-file" aria-label="AX Workspace 배포 파일 선택" accept=".zip,.axextension,.exe,.msi,.ps1,.md"></div><div class="ws-selected-files" aria-live="polite">${axFile?`<div class="ws-selected-file">${icon('file')}<span><strong>${esc(axFile.name)}</strong><small>${fileSize(axFile.size)}</small></span>${button('ax-remove',icon('x'),'sq-icon','type="button" aria-label="선택한 파일 취소"')}</div>`:''}</div></section>`;
}
function chooseAxFile(files){
 if(axUploadBusy)return;
 if(!files.length)return;
 if(files.length!==1||!files[0].size||files[0].size>axMaxFileBytes||!(/\.(zip|axextension|exe|msi|ps1|md)$/i.test(files[0].name)))throw Error(`ZIP·AX 확장(.axextension)·EXE·MSI·PS1·MD 파일을 하나 선택하세요. 빈 파일은 등록할 수 없고 최대 ${fileSize(axMaxFileBytes)}입니다.`);
 axFile=files[0];refreshAxFile();
}
function refreshAxFile(){const area=$('[data-ax-drop]');if(area){area.outerHTML=axUploadArea();mountIcons();}}
Object.assign(actions,{
 'ax-workspace':()=>showAxWorkspace(),
 'ax-filter':b=>{axFilter=b.dataset.category==='all'? 'all':axCategory(b.dataset.category);renderAxWorkspace();},
 'ax-register':()=>openAxUpload(),
 'ax-version':b=>openAxUpload(b.dataset.id),
 'ax-subscription':b=>toggleAxSubscription(b.dataset.id),
 'ax-pick':()=>$('#sq-ax-file')?.click(),
 'ax-remove':()=>{if(!axUploadBusy){axFile=null;refreshAxFile();}}
});
function openAxUpload(id=null){
 if(server.user.role!=='admin'||axUploadBusy)return;
 const item=id===null?null:axFiles.find(x=>x.id===id);if(id!==null&&!item)return;
 axFile=null;axVersionTarget=item?{id:item.id,revision:item.revision||1}:null;
 openModal(item?'새 버전 등록':'배포 파일 등록','AX Workspace · 관리자',`<form id="sq-ax-form"><div class="sq-form-grid"><label class="sq-field wide"><span>이름 *</span><input name="name" maxlength="100" required value="${esc(item?.name||'')}" placeholder="예: AX Workspace Windows 설치 파일"></label><label class="sq-field wide"><span>설명 *</span><textarea name="description" maxlength="2000" required placeholder="어떤 파일인지, 설치 전에 알아둘 내용을 적어주세요.">${esc(item?.description||'')}</textarea></label><label class="sq-field"><span>분류</span><select name="category">${Object.entries(axCategories).map(([key,label])=>`<option value="${key}" ${(item?axCategory(item.category):'workspace')===key?'selected':''}>${label}</option>`).join('')}</select></label><div class="sq-field"><span>배포 버전</span><output class="ws-ax-version">v${axNextRelease(item)} · 자동</output></div></div>${axUploadArea()}<p class="sq-note">${item?'기존 카드의 파일을 새 버전으로 바꾸고, 업데이트 알림을 켠 사용자에게 소식을 전합니다.':'등록하면 사내 사용자가 바로 내려받을 수 있습니다. 선택한 파일 형식 그대로 배포됩니다.'}</p><div class="sq-actions"><button class="sq-primary">${item?'새 버전 등록':'파일 등록'}</button></div></form>`);
}
// Keep browser streaming downloads intact. Only a later API read confirms auto-subscription.
root.addEventListener('click',e=>{if(!e.target.closest('a[data-ax-download]'))return;clearTimeout(axDownloadTimer);axDownloadTimer=setTimeout(()=>refreshAxSubscriptions(true).catch(()=>{}),1500);});
window.addEventListener('focus',()=>refreshAxSubscriptions().catch(()=>{}));
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshAxSubscriptions().catch(()=>{});});
root.addEventListener('change',e=>{if(e.target.id!=='sq-ax-file')return;try{chooseAxFile([...e.target.files]);}catch(error){e.target.value='';showError(error);}});
for(const type of ['dragenter','dragover','dragleave','drop'])root.addEventListener(type,e=>{
 const area=e.target.closest('[data-ax-drop]');if(!area)return;e.preventDefault();if(axUploadBusy)return;
 area.classList.toggle('is-dragging',type==='dragenter'||type==='dragover');
 if(type==='drop')try{chooseAxFile([...e.dataTransfer.files]);}catch(error){showError(error);}
});
root.addEventListener('submit',e=>{
 const form=e.target;if(form.id!=='sq-ax-form')return;e.preventDefault();e.stopImmediatePropagation();
 if(axUploadBusy||form.dataset.saved)return;
 if(!axFile){showError(Error('등록할 파일을 선택해 주세요.'));return;}
 const token=runtime.detailLoadToken,target=axVersionTarget,body=new FormData(),metadata=Object.fromEntries(new FormData(form));let errorToken=token;
 delete metadata.version;
 if(target)metadata.expectedRevision=target.revision;body.append('metadata',JSON.stringify(metadata));body.append('file',axFile);
 axUploadBusy=true;form.querySelectorAll('button,input,textarea,select').forEach(x=>x.disabled=true);
 (async()=>{
  await requestAPI(target?`/api/ax-workspace/${encodeURIComponent(target.id)}/versions`:'/api/ax-workspace','POST',body);form.dataset.saved='true';
  if(token!==runtime.detailLoadToken)return;
  axFile=null;axFilter='all';closeModal();navigate('ax');const listToken=runtime.detailLoadToken;errorToken=listToken;
  await afterWorkspaceSave(async()=>{await loadAxWorkspace();if(listToken===runtime.detailLoadToken&&state.route==='ax'){renderAxWorkspace();announce(target?'새 버전을 등록했습니다.':'배포 파일을 등록했습니다.');}},form);
 })().catch(error=>{if(errorToken===runtime.detailLoadToken)showError(error);}).finally(()=>{axUploadBusy=false;form.querySelectorAll('button,input,textarea,select').forEach(x=>x.disabled=!!form.dataset.saved);});
},true);
