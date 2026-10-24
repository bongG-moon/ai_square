// Administrator-published downloads are kept separate from community tool rankings.
const axCategories={workspace:'AX Workspace',plugin:'플러그인',integration:'연동 도구',other:'기타'};
let axFiles=[],axFilter='all',axFile=null,axLoadToken=0,axUploadBusy=false,axMaxFileBytes=128*1048576-65536;
async function loadAxWorkspace(){
 const token=++axLoadToken,result=await requestAPI('/api/ax-workspace');
 if(token!==axLoadToken)return false;
 axFiles=result.files;if(Number.isSafeInteger(result.maxFileBytes)&&result.maxFileBytes>=0)axMaxFileBytes=result.maxFileBytes;return true;
}
function renderAxWorkspace(){
 const admin=server.user.role==='admin',rows=axFiles.filter(x=>axFilter==='all'||x.category===axFilter);
 workspace.innerHTML=`<div class="ws-ax-intro"><span class="ws-ax-symbol">${icon('monitor-down')}</span><div><h2>설치부터 연결까지, 한곳에서.</h2><p>AX Workspace 설치 파일과 업무에 필요한 플러그인·연동 도구를 내려받으세요.</p></div>${admin?button('ax-register',icon('plus')+' 파일 등록','sq-primary'):''}</div><div class="ws-board-head"><div class="ws-segment ws-ax-filters">${Object.entries({all:'전체',...axCategories}).map(([key,label])=>button('ax-filter',label,'',`data-category="${key}" aria-pressed="${axFilter===key}"`)).join('')}</div><span class="ws-ax-count">${rows.length}개 파일</span></div><div class="ws-ax-grid">${rows.map(x=>`<article class="ws-ax-card"><div class="ws-ax-card-top"><span class="ws-ax-symbol">${icon(x.category==='workspace'?'monitor-down':x.category==='plugin'?'blocks':'cable')}</span>${badge(axCategories[x.category]||'기타')}</div><h2>${esc(x.name)}</h2><p>${esc(x.description)}</p><div class="ws-ax-file"><strong>${esc(x.fileName)}</strong><span>${esc(x.version?'v'+x.version:'버전 미입력')} · ${fileSize(x.size)}</span></div><div class="ws-ax-card-footer"><small>${dated(x.created)} 등록</small><a class="sq-primary" href="${esc(x.downloadUrl)}" download aria-label="${esc(x.name)} 다운로드">${icon('download')} 다운로드</a></div></article>`).join('')||blank('folder-down',axFilter==='all'?'아직 등록된 파일이 없습니다.':'이 분류에 등록된 파일이 없습니다.',admin?'파일 등록을 눌러 설치 파일이나 플러그인을 공유하세요.':'관리자가 파일을 등록하면 이곳에서 내려받을 수 있습니다.')}</div>`;
 mountIcons();
}
function axUploadArea(){
 return `<section class="ws-upload-area" data-ax-drop><div class="ws-drop-zone"><span class="ws-upload-icon">${icon('cloud-upload')}</span><h3>배포할 파일을 여기에 놓으세요</h3><p>ZIP · EXE · MSI · PS1 · MD · 최대 ${fileSize(axMaxFileBytes)}</p><button type="button" class="sq-secondary" data-action="ax-pick">${icon('plus')} 파일 선택</button><input class="sq-sr" type="file" id="sq-ax-file" aria-label="AX Workspace 배포 파일 선택" accept=".zip,.exe,.msi,.ps1,.md"></div><div class="ws-selected-files" aria-live="polite">${axFile?`<div class="ws-selected-file">${icon('file')}<span><strong>${esc(axFile.name)}</strong><small>${fileSize(axFile.size)}</small></span>${button('ax-remove',icon('x'),'sq-icon','type="button" aria-label="선택한 파일 취소"')}</div>`:''}</div></section>`;
}
function chooseAxFile(files){
 if(!files.length)return;
 if(files.length!==1||!files[0].size||files[0].size>axMaxFileBytes||!(/\.(zip|exe|msi|ps1|md)$/i.test(files[0].name)))throw Error(`ZIP·EXE·MSI·PS1·MD 파일을 하나 선택하세요. 빈 파일은 등록할 수 없고 최대 ${fileSize(axMaxFileBytes)}입니다.`);
 axFile=files[0];refreshAxFile();
}
function refreshAxFile(){const area=$('[data-ax-drop]');if(area){area.outerHTML=axUploadArea();mountIcons();}}
Object.assign(actions,{
 'ax-workspace':async()=>{closeModal();navigate('ax');const token=runtime.detailLoadToken;try{await loadAxWorkspace();if(token===runtime.detailLoadToken&&state.route==='ax')renderAxWorkspace();}catch(error){if(token===runtime.detailLoadToken&&state.route==='ax')throw error;}},
 'ax-filter':b=>{axFilter=b.dataset.category;renderAxWorkspace();},
 'ax-register':()=>{
  if(server.user.role!=='admin')return;axFile=null;
  openModal('배포 파일 등록','AX Workspace · 관리자',`<form id="sq-ax-form"><div class="sq-form-grid"><label class="sq-field wide"><span>이름 *</span><input name="name" maxlength="100" required placeholder="예: AX Workspace Windows 설치 파일"></label><label class="sq-field wide"><span>설명 *</span><textarea name="description" maxlength="2000" required placeholder="어떤 파일인지, 설치 전에 알아둘 내용을 적어주세요."></textarea></label><label class="sq-field"><span>분류</span><select name="category">${Object.entries(axCategories).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select></label><label class="sq-field"><span>배포 버전 *</span><input name="version" required maxlength="40" placeholder="예: 1.0.0"></label></div>${axUploadArea()}<p class="sq-note">등록하면 사내 사용자가 바로 내려받을 수 있습니다. 선택한 파일 형식 그대로 배포됩니다.</p><div class="sq-actions"><button class="sq-primary">파일 등록</button></div></form>`);
 },
 'ax-pick':()=>$('#sq-ax-file')?.click(),
 'ax-remove':()=>{if(!axUploadBusy){axFile=null;refreshAxFile();}}
});
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
 const token=runtime.detailLoadToken,body=new FormData();let errorToken=token;body.append('metadata',JSON.stringify(Object.fromEntries(new FormData(form))));body.append('file',axFile);
 axUploadBusy=true;form.querySelectorAll('button,input,textarea,select').forEach(x=>x.disabled=true);
 (async()=>{
  await requestAPI('/api/ax-workspace','POST',body);form.dataset.saved='true';
  if(token!==runtime.detailLoadToken)return;
  axFile=null;axFilter='all';closeModal();navigate('ax');const listToken=runtime.detailLoadToken;errorToken=listToken;
  await afterWorkspaceSave(async()=>{await loadAxWorkspace();if(listToken===runtime.detailLoadToken&&state.route==='ax'){renderAxWorkspace();announce('배포 파일을 등록했습니다.');}},form);
 })().catch(error=>{if(errorToken===runtime.detailLoadToken)showError(error);}).finally(()=>{axUploadBusy=false;form.querySelectorAll('button,input,textarea,select').forEach(x=>x.disabled=!!form.dataset.saved);});
},true);
