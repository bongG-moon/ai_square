async function publish(){
 if(runtime.publishBusy)return;
 const d=runtime.draft;if(!d)return;
 const error=packageBlockingError(d)||Core.validate(d,1)||Core.validate(d,2);if(runtime.step!==3||error){if(error)throw Error(error);return;}
 runtime.publishBusy=true;
 try{
 const metadata=JSON.stringify({...d,file:undefined,sample:undefined,packageInspection:undefined}),target=runtime.releaseId||null,file=d.mode==='file'?d.file:null;
 // Match the API's publish identity fields; preview state and revision checks are not content.
 const identity=Object.fromEntries(['name','desc','owner','platform','type','guide','environment','changes','org','orgId','category','categoryId'].map(key=>[key,String(d[key]??'').trim()]));
 identity.approval=!!d.approval;identity.workflow=d.workflow||null;identity.installProfile=d.installProfile||null;
 identity.workTags=[...new Set((Array.isArray(d.workTags)?d.workTags:String(d.workTags||'').split(/[,，\n]/)).map(tag=>tag.trim().replace(/\s+/g,' ')).filter(Boolean))];
 identity.mode=d.mode;identity.url=d.mode==='url'?String(d.url||'').trim():'';
 identity.commands=d.mode==='command'?{project:String(d.commandProject||'').trim(),user:String(d.commandUser||'').trim()}:{};
 const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])])):value;
 const signature=JSON.stringify(canonical(identity));
 let attempt=runtime.publishAttempt;
 if(!attempt||attempt.signature!==signature||attempt.target!==target||attempt.file!==file){
  const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const hex=[...bytes].map(b=>b.toString(16).padStart(2,'0')).join('');
  attempt=runtime.publishAttempt={signature,target,file,id:`${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`};
 }
 const progress=typeof $==='function'?$('#sq-register-error'):null;
 const validResult=value=>Number.isInteger(value?.id)&&value.id>0&&Number.isInteger(value?.version)&&value.version>0&&(!target||value.id===target);
 const recover=async()=>{
  if(progress){progress.textContent='연결이 끊겨 서버의 게시 결과를 확인하고 있습니다…';progress.setAttribute('role','status');progress.setAttribute('aria-live','polite');}
  // Check only: the first POST may still be committing. Never repeat an upload automatically.
  for(let check=0;check<3;check++){
   if(check)await new Promise(resolve=>setTimeout(resolve,check*750));
   let receipt;
   try{receipt=await requestAPI(`/api/publish-requests/${attempt.id}`,'GET',undefined,{timeoutMs:4000,redirectOnAuth:false});}
   catch(error){if(error.uncertain&&check<2)continue;throw error;}
   if(receipt.status==='confirmed'&&validResult(receipt))return receipt;
   if(receipt.status!=='unconfirmed')throw Error('게시 결과를 확인하지 못했습니다.');
  }
  return null;
 };
 const unresolved=cause=>{
  const message=cause?.status===401?'로그인이 만료되어 게시 결과를 확인하지 못했습니다. 다시 로그인한 뒤 등록 관리에서 확인해 주세요.':`게시 완료 여부를 아직 확인하지 못했습니다. 입력한 내용과 파일은 유지했습니다. 잠시 후 다시 게시를 누르면 같은 요청 번호로 확인합니다. [요청 번호: ${attempt.id}]`;
  const error=Error(message);error.uncertain=true;return error;
 };
 let result;
 if(attempt.uncertain){try{result=await recover();}catch(error){throw unresolved(error);}}
 if(!result){
  const form=new FormData();form.append('metadata',JSON.stringify({...JSON.parse(metadata),clientRequestId:attempt.id}));if(file)form.append('artifact',file);
  try{result=await requestAPI(target?`/api/tools/${target}/versions`:'/api/tools','POST',form);if(!validResult(result)){const error=Error('게시 응답 형식을 확인하지 못했습니다.');error.uncertain=true;throw error;}}
  catch(error){
   if(!error.uncertain)throw error;
   attempt.uncertain=true;
   try{result=await recover();}catch(recoveryError){throw unresolved(recoveryError);}
   if(!result)throw unresolved(error);
  }
 }
 runtime.newId=result.id;runtime.draft=null;runtime.publishAttempt=null;
 let refreshNotice='';try{await refresh();}catch{refreshNotice='게시가 완료되었습니다. 목록을 갱신하지 못했으므로 새로고침 후 확인해 주세요.';}
 openModal('공유할 준비가 되었습니다.','게시 완료',`<div class="sq-success"><span class="sq-feature-icon">${icon('check')}</span><h3>${esc(getItem(result.id)?.name||d.name)}</h3><p>v${result.version}을 서버에 저장했습니다.<br>설치·연결 안내와 공개 범위를 확인해 주세요.</p>${refreshNotice?`<p role="status">${refreshNotice}</p>`:''}${result.pending?'<p role="status">게시가 완료되었습니다. 이력·알림은 다음 조회 시 동기화됩니다.</p>':''}${result.packageWarning?`<div class="ws-package"><strong>파일은 게시되었습니다. 배포 정보는 읽지 못했습니다.</strong><p>${esc(result.packageWarning)}</p><p>직접 입력한 등록 정보로 제공됩니다.</p></div>`:''}${result.deploymentUrl?`<div class="ws-package"><strong>도구 ID ${result.id} · 배포 v${result.version}</strong><p>배포 정보에 원본 파일·버전 확인 주소를 연결했습니다.</p><a class="sq-link" href="${esc(result.deploymentUrl)}" download>배포 정보 JSON 받기</a></div>`:''}<div class="sq-actions" style="justify-content:center">${button('published-detail','상세 화면 보기','sq-primary')}${button('manage','등록 도구 관리')}</div></div>`);
 }finally{runtime.publishBusy=false;}
}
