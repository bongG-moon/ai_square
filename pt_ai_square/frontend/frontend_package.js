// Inspect a declaration, never run or transform uploaded code.
// Keep import history outside submitted metadata. Removing a file does not make
// previously imported fields an empty first import again.
const packageMetadataDrafts=new WeakSet();
function hasImportedPackageMetadata(d){return !!d&&packageMetadataDrafts.has(d);}
function updatePackageIdentity(){
 const item=runtime.releaseId?getItem(runtime.releaseId):null;if(!item)return null;
 // A platform identity survives replacement ZIPs, manual releases and rollback.
 // Legacy responses without the fixed field use the first recognized release.
 const version=[...(item.versions||[])].filter(v=>v.package?.packageId).sort((a,b)=>a.n-b.n)[0];
 return {toolId:item.id,name:item.name||'',packageId:item.packageId||version?.package.packageId||''};
}
function packageIdentityField(label,value,kind){
 return `<div class="sq-field" data-package-identity-field><span>${label}</span><input type="text" readonly value="${esc(value)}" aria-label="${label}" spellcheck="false"><button type="button" class="sq-link" data-package-copy="${kind}">${icon('copy')} ${label} 복사</button></div>`;
}
function updatePackagePanel(){
 const identity=updatePackageIdentity();if(!identity)return '';
 return `<section class="ws-package" aria-label="업데이트할 도구의 식별 정보"><div class="ws-package-heading">${icon('package')}<strong>${esc(identity.name)} · 기존 도구의 새 버전을 등록합니다.</strong></div><div class="sq-form-grid">${packageIdentityField('도구 ID',String(identity.toolId),'tool')}${identity.packageId?packageIdentityField('플랫폼 packageId',identity.packageId,'package'):'<div class="sq-field"><span>플랫폼 packageId</span><p>처음 정상적으로 읽힌 배포 파일의 식별자를 사용합니다.</p></div>'}</div><p>선택한 도구에 새 배포 번호가 추가됩니다. ${identity.packageId?'도구 ID와 최초 packageId는 유지되며 새 ZIP의 식별자가 달라도 등록할 수 있습니다. ZIP을 수정하거나 다시 압축할 필요가 없습니다.':'배포 정보가 없는 일반 파일도 등록할 수 있습니다.'} 파일명·코드·시작 파일이 바뀌었다면 새 파일에 맞는 설치 안내도 확인해 주세요.</p></section>`;
}
function packageIdentityDifference(d){
 const identity=updatePackageIdentity(),check=d.packageInspection;
 if(!identity?.packageId||d.mode!=='file'||!d.file||check?.state!=='ready'||!check.result?.recognized)return null;
 const received=check.result.package?.packageId;
 return received&&received!==identity.packageId?{...identity,received}:null;
}
async function copyPackageIdentity(button){
 const field=button.closest('[data-package-identity-field]')?.querySelector('input');if(!field?.value)return;
 try{await navigator.clipboard.writeText(field.value);button.textContent='복사 완료';announce('식별자를 복사했습니다.');}
 catch{field.focus();field.select();announce('값을 선택했습니다. Ctrl+C 또는 복사 메뉴로 복사하세요.');}
}
function packagePanel(d){
 const p=d.packageInspection;if(!p)return '';
 if(p.state==='loading')return '<div class="ws-package" role="status"><strong>배포 정보를 확인하고 있습니다.</strong><p>파일을 임시 전송하여 확인합니다. 게시 전에는 보관하지 않습니다.</p></div>';
 if(p.state==='error')return `<div class="ws-package is-error" role="alert"><strong>배포 정보를 읽지 못했습니다.</strong><p>${esc(p.error)}</p><p>입력 항목을 직접 작성하면 그대로 게시할 수 있습니다. 게시 시 기본 파일 검사는 다시 진행합니다.</p><button type="button" class="sq-link" data-package-retry>다시 검사</button></div>`;
 if(!p.result.recognized)return `<div class="ws-package"><strong>${p.result.warning?'배포 정보를 읽지 못했습니다':'일반 파일 등록'}</strong><p>${esc(p.result.warning||p.result.notice)}</p><p>이름·유형·설치 안내를 직접 입력하고 게시하세요.</p></div>`;
 const info=p.result.package;
 const difference=packageIdentityDifference(d);
 const identityNotice=difference?`<div class="ws-package-facts" role="status"><strong>기존 도구의 새 버전으로 연결됩니다.</strong><span>유지할 플랫폼 packageId <b>${esc(difference.packageId)}</b></span><span>새 파일의 원본 packageId <b>${esc(difference.received)}</b></span><small>파일의 식별자가 달라도 게시할 수 있습니다. 원본 ZIP은 그대로 보관합니다.</small></div>`:'';
 return `<div class="ws-package"><div class="ws-package-heading">${icon('file-check-2')}<strong>배포 정보 확인 완료</strong><span class="ws-badge">${esc(info.type)}</span></div><p>${esc(info.name)} · ${esc(info.platform)}</p><small>필수 파일 확인 · 원본 그대로 배포 · 실행 검증 제외</small>${identityNotice}${info.workflow?.steps?.length?`<p>동작 흐름 ${info.workflow.steps.length}단계가 상세 화면에 함께 표시됩니다.</p>`:''}<div class="ws-package-facts"><span>파일의 원본 packageId <b>${esc(info.packageId||'')}</b></span><span>시작 파일 <b>${esc(info.entryPoint)}</b></span><span>필요 환경 <b>${esc(info.requirements.join(' · ')||'별도 기재 없음')}</b></span></div><button type="button" class="sq-link" data-package-apply>${p.applied?'배포 정보 다시 적용':'배포 정보를 입력란에 적용'}</button><small>이름·소개·유형·설치 안내 등이 바뀝니다. 조직·업무 분야·담당자·조회 권한은 유지됩니다.</small></div>`;
}
function decoratePackageForm(form){
 if(form.id!=='sq-register-form')return;
 const d=runtime.draft;
 if(runtime.step===1){
  form.insertAdjacentHTML('afterbegin',`<section class="ws-package-import" data-upload="artifact" aria-label="배포 파일 첨부"><div class="ws-package-import-main"><span class="ws-package-import-icon">${icon('cloud-upload')}</span><div><strong>배포 파일을 여기에 놓으세요</strong><p>배포 Skill로 만든 파일은 이름과 설명을 불러옵니다. 일반 파일도 첨부할 수 있어요.</p><small>ZIP, AX 확장, EXE, MSI, PS1, MD / 최대 128MB</small></div><button type="button" class="sq-secondary" data-file-pick="artifact">${icon('plus')} 배포 파일에서 불러오기</button><input type="file" name="artifact" accept=".zip,.axextension,.exe,.msi,.ps1,.md" class="sq-sr" aria-label="배포 파일 선택"></div>${d.file?`<div class="ws-selected-file" aria-live="polite">${icon('file')}<span><strong>${esc(d.file.name)}</strong><small>${fileSize(d.file.size)} / 게시할 때 업로드</small></span><button type="button" class="sq-icon" data-file-remove="artifact" aria-label="선택한 배포 파일 취소">${icon('x')}</button></div>`:''}</section>`);
 }
 if(d.mode==='file'&&d.file){
  const anchor=form.querySelector('[data-upload="artifact"]')||form.querySelector('.ws-package-import');
  if(anchor)anchor.insertAdjacentHTML('afterend',packagePanel(d));
  else form.insertAdjacentHTML('afterbegin',packagePanel(d));
 }
 if(runtime.releaseId)form.insertAdjacentHTML('afterbegin',updatePackagePanel());
}
function applyPackageFields(d,result){
 if(runtime.publishBusy)return;
 for(const key of ['name','desc','platform','type','environment','changes','guide'])d[key]=result.metadata[key];
 d.workflow=result.metadata.workflow||null;
 d.workTags=result.metadata.workTags.join(', ');
 d.mode='file';d.packageInspection.applied=true;d.packageInspection.awaitingConfirmation=false;packageMetadataDrafts.add(d);
}
function packageFormVisible(){return !!$('#sq-register-form')&&$('#sq-dialog')?.open!==false;}
function clearPackageApplyConfirmation(){
 const confirmation=runtime.packageApplyConfirmation;if(!confirmation)return;
 confirmation.packageInspection.awaitingConfirmation=false;
 if(runtime.confirm===confirmation){runtime.confirm=null;const dialog=$('#sq-confirm');if(dialog?.open)dialog.close();}
 runtime.packageApplyConfirmation=null;
}
function confirmPackageReplacement(d,file,check){
 if(runtime.publishBusy||!packageFormVisible())return;
 const apply=()=>{
  check.awaitingConfirmation=false;
  if(runtime.packageApplyConfirmation===apply)runtime.packageApplyConfirmation=null;
  // A stale confirmation must never apply metadata from a different file or draft.
  if(runtime.publishBusy||runtime.draft!==d||d.file!==file||d.mode!=='file'||d.packageInspection!==check||!packageFormVisible())return;
  captureDraft();applyPackageFields(d,check.result);wizard();
 };
 apply.packageInspection=check;check.awaitingConfirmation=true;runtime.packageApplyConfirmation=apply;
 ask('신규 파일 내용을 적용하시겠습니까?',
  '이름, 소개, 유형, 설치 안내와 동작 흐름을 새 파일의 내용으로 바꿉니다. 조직, 업무 분야, 담당자와 조회 권한은 유지합니다. 취소하면 선택한 파일은 유지하고 입력한 내용은 바꾸지 않습니다.',
  apply,'새 파일 내용 적용',`<div class="ws-package-replacement"><span>${icon('file-check-2')} ${esc(file.name)}</span><strong>${esc(check.result.metadata.name)}</strong><p>${esc(check.result.metadata.desc)}</p></div>`);
}
async function inspectSelectedPackage(file,{replacement=runtime.draft?.packageInspection?.replacement||false}={}){
 const d=runtime.draft;
 if(runtime.publishBusy||!d||d.file!==file)return;
 clearPackageApplyConfirmation();
 const check={state:'loading',replacement};d.packageInspection=check;
 if(packageFormVisible())wizard();
 const body=new FormData();body.append('artifact',file);
 try{
  const result=await requestAPI('/api/packages/inspect','POST',body);
  if(runtime.draft!==d||d.file!==file||d.packageInspection!==check)return;
  // A different mode may have been posted while this file preview was in flight.
  if(runtime.publishBusy){check.state='ready';check.result=result;return;}
  // Keep edits entered while the request was in flight.
  captureDraft();check.state='ready';check.result=result;
  if(result.recognized&&d.mode==='file'&&!replacement&&!runtime.releaseId&&!d.name.trim()&&!d.desc.trim())applyPackageFields(d,result);
 }catch(error){
  if(runtime.draft!==d||d.file!==file||d.packageInspection!==check)return;
  check.state='error';check.error=error.message;
 }
 if(!runtime.publishBusy&&runtime.draft===d&&packageFormVisible()){
  wizard();
  if(d.mode==='file'&&replacement&&check.state==='ready'&&check.result.recognized)confirmPackageReplacement(d,file,check);
 }
}
function packageBlockingError(d){
 // Wait for an in-flight preview/decision so metadata cannot change after POST.
 // A finished inspection failure remains advisory; manual publication is allowed.
 if(d.mode!=='file'||!d.file)return '';
 if(d.packageInspection?.state==='loading')return '배포 정보를 확인하고 있습니다. 검사가 끝난 뒤 다시 진행해 주세요.';
 if(d.packageInspection?.awaitingConfirmation)return '새 파일의 내용을 적용할지 확인창에서 선택해 주세요.';
 return '';
}
// Cancel, Escape and dismissal all keep current metadata and release the decision
// guard. Ignore a delayed close event if the same dialog has already reopened.
root.addEventListener('click',e=>{if(e.target.closest('[data-action="cancel-confirm"]'))clearPackageApplyConfirmation();},true);
$('#sq-confirm')?.addEventListener?.('cancel',()=>clearPackageApplyConfirmation());
$('#sq-confirm')?.addEventListener?.('close',()=>{if(!$('#sq-confirm').open)clearPackageApplyConfirmation();});
root.addEventListener('click',e=>{
 const copy=e.target.closest('[data-package-copy]');if(copy){e.preventDefault();copyPackageIdentity(copy);return;}
 if(e.target.closest('[data-package-retry]')){e.preventDefault();if(runtime.publishBusy)return;captureDraft();inspectSelectedPackage(runtime.draft.file);}
 if(e.target.closest('[data-package-apply]')){e.preventDefault();if(runtime.publishBusy)return;captureDraft();applyPackageFields(runtime.draft,runtime.draft.packageInspection.result);wizard();}
});
function deploymentLinks(x,tab){
 const versions=tab==='versions'?x.versions.filter(v=>v.deploymentUrl):x.versions.filter(v=>v.n===x.active&&v.deploymentUrl);
 if(!versions.length||!['connect','versions'].includes(tab))return;
 $('#sq-dialog-body').insertAdjacentHTML('beforeend',`<section class="ws-package"><strong>배포 정보</strong><p>파일은 원본 그대로 제공됩니다. 아래 JSON에는 도구 ID·배포 번호·필수 파일·버전 확인 주소가 연결되어 있습니다.</p>${versions.map(v=>`<a class="sq-link" href="${esc(v.deploymentUrl)}" download>v${v.n} 배포 정보 JSON 받기</a>`).join(' ')}<small>이 정보만으로 PC 설치나 실행 시 버전 확인 코드가 자동 적용되지는 않습니다.</small></section>`);
}
