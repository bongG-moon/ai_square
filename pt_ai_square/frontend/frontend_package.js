// Inspect a declaration, never run or transform uploaded code.
function packagePanel(d){
 const p=d.packageInspection;if(!p)return '';
 if(p.state==='loading')return '<div class="ws-package" role="status"><strong>배포 정보를 확인하고 있습니다.</strong><p>파일을 임시 전송하여 확인합니다. 게시 전에는 보관하지 않습니다.</p></div>';
 if(p.state==='error')return `<div class="ws-package is-error" role="alert"><strong>배포 정보를 읽지 못했습니다.</strong><p>${esc(p.error)}</p><p>입력 항목을 직접 작성하면 그대로 게시할 수 있습니다. 게시 시 기본 파일 검사는 다시 진행합니다.</p><button type="button" class="sq-link" data-package-retry>다시 검사</button></div>`;
 if(!p.result.recognized)return `<div class="ws-package"><strong>${p.result.warning?'배포 정보를 읽지 못했습니다':'일반 파일 등록'}</strong><p>${esc(p.result.warning||p.result.notice)}</p><p>이름·유형·설치 안내를 직접 입력하고 게시하세요.</p></div>`;
 const info=p.result.package;
 return `<div class="ws-package"><div class="ws-package-heading">${icon('file-check-2')}<strong>배포 정보 확인 완료</strong><span class="ws-badge">${esc(info.type)}</span></div><p>${esc(info.name)} · ${esc(info.platform)}</p><small>필수 파일 확인 · 원본 그대로 배포 · 실행 검증 제외</small><div class="ws-package-facts"><span>시작 파일 <b>${esc(info.entryPoint)}</b></span><span>필요 환경 <b>${esc(info.requirements.join(' · ')||'별도 기재 없음')}</b></span></div><button type="button" class="sq-link" data-package-apply>${p.applied?'ZIP 정보 다시 적용':'ZIP 정보를 입력란에 적용'}</button><small>이름·소개·유형·설치 안내 등이 바뀝니다. 조직·업무 분야·담당자·조회 권한은 유지됩니다.</small></div>`;
}
function decoratePackageForm(form){
 if(form.id!=='sq-register-form')return;
 const d=runtime.draft;
 if(runtime.step===1){
  form.insertAdjacentHTML('afterbegin',`<div class="ws-package-import"><div>${icon('package-open')}<strong>배포 Skill로 준비하셨나요?</strong><p>ZIP의 배포 정보로 유형과 설명을 채워드려요. 읽지 못해도 직접 입력하여 등록할 수 있어요.</p></div><label class="sq-secondary">ZIP에서 불러오기<input type="file" name="artifact" accept=".zip" class="sq-sr" data-package-import aria-label="배포 ZIP에서 정보 불러오기"></label></div>`);
 }
 if(d.mode==='file'&&d.file){
  const anchor=form.querySelector('[data-upload="artifact"]')||form.querySelector('.ws-package-import');
  if(anchor)anchor.insertAdjacentHTML('afterend',packagePanel(d));
  else form.insertAdjacentHTML('afterbegin',packagePanel(d));
 }
}
function applyPackageFields(d,result){
 for(const key of ['name','desc','platform','type','environment','changes','guide'])d[key]=result.metadata[key];
 d.workTags=result.metadata.workTags.join(', ');
 d.mode='file';d.packageInspection.applied=true;
}
async function inspectSelectedPackage(file){
 const d=runtime.draft;
 const check={state:'loading'};d.packageInspection=check;
 if($('#sq-register-form'))wizard();
 const body=new FormData();body.append('artifact',file);
 try{
  const result=await requestAPI('/api/packages/inspect','POST',body);
  if(runtime.draft!==d||d.file!==file||d.packageInspection!==check)return;
  // Keep edits entered while the request was in flight.
  captureDraft();check.state='ready';check.result=result;
  if(result.recognized&&!runtime.releaseId&&!d.name.trim()&&!d.desc.trim())applyPackageFields(d,result);
 }catch(error){
  if(runtime.draft!==d||d.file!==file||d.packageInspection!==check)return;
  check.state='error';check.error=error.message;
 }
 if(runtime.draft===d&&$('#sq-register-form'))wizard();
}
function packageBlockingError(d){
 // Metadata inspection is advisory. Publish validates the actual file independently.
 return '';
}
root.addEventListener('change',e=>{
 if(!e.target.matches('[data-package-import]'))return;e.stopImmediatePropagation();
 try{selectFiles('artifact',[...e.target.files]);}catch(error){showError(error);}
},true);
root.addEventListener('click',e=>{
 if(e.target.closest('[data-package-retry]')){e.preventDefault();captureDraft();inspectSelectedPackage(runtime.draft.file);}
 if(e.target.closest('[data-package-apply]')){e.preventDefault();captureDraft();applyPackageFields(runtime.draft,runtime.draft.packageInspection.result);wizard();}
});
function deploymentLinks(x,tab){
 const versions=tab==='versions'?x.versions.filter(v=>v.deploymentUrl):x.versions.filter(v=>v.n===x.active&&v.deploymentUrl);
 if(!versions.length||!['connect','versions'].includes(tab))return;
 $('#sq-dialog-body').insertAdjacentHTML('beforeend',`<section class="ws-package"><strong>배포 정보</strong><p>파일은 원본 그대로 제공됩니다. 아래 JSON에는 도구 ID·배포 번호·필수 파일·버전 확인 주소가 연결되어 있습니다.</p>${versions.map(v=>`<a class="sq-link" href="${esc(v.deploymentUrl)}" download>v${v.n} 배포 정보 JSON 받기</a>`).join(' ')}<small>이 정보만으로 PC 설치나 실행 시 버전 확인 코드가 자동 적용되지는 않습니다.</small></section>`);
}
