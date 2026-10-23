async function publish(){
 if(runtime.publishBusy)return;
 const d=runtime.draft;if(!d)return;
 const error=packageBlockingError(d)||Core.validate(d,1)||Core.validate(d,2);if(runtime.step!==3||error){if(error)throw Error(error);return;}
 runtime.publishBusy=true;
 try{
 const metadata=JSON.stringify({...d,file:undefined,sample:undefined,packageInspection:undefined}),target=runtime.releaseId||null,file=d.mode==='file'?d.file:null;
 // Match the API's publish identity fields; preview state and revision checks are not content.
 const identity=Object.fromEntries(['name','desc','owner','platform','type','guide','environment','changes','org','orgId','category','categoryId'].map(key=>[key,String(d[key]??'').trim()]));
 identity.approval=!!d.approval;identity.workflow=d.workflow||null;
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
 const form=new FormData();form.append('metadata',JSON.stringify({...JSON.parse(metadata),clientRequestId:attempt.id}));if(file)form.append('artifact',file);
 const result=await requestAPI(runtime.releaseId?`/api/tools/${runtime.releaseId}/versions`:'/api/tools','POST',form);
 runtime.newId=result.id;runtime.draft=null;runtime.publishAttempt=null;
 let refreshNotice='';try{await refresh();}catch{refreshNotice='게시가 완료되었습니다. 목록을 갱신하지 못했으므로 새로고침 후 확인해 주세요.';}
 openModal('공유할 준비가 되었습니다.','게시 완료',`<div class="sq-success"><span class="sq-feature-icon">${icon('check')}</span><h3>${esc(getItem(result.id)?.name||d.name)}</h3><p>v${result.version}을 서버에 저장했습니다.<br>설치·연결 안내와 공개 범위를 확인해 주세요.</p>${refreshNotice?`<p role="status">${refreshNotice}</p>`:''}${result.pending?'<p role="status">게시가 완료되었습니다. 이력·알림은 다음 조회 시 동기화됩니다.</p>':''}${result.packageWarning?`<div class="ws-package"><strong>파일은 게시되었습니다. 배포 정보는 읽지 못했습니다.</strong><p>${esc(result.packageWarning)}</p><p>직접 입력한 등록 정보로 제공됩니다.</p></div>`:''}${result.deploymentUrl?`<div class="ws-package"><strong>도구 ID ${result.id} · 배포 v${result.version}</strong><p>배포 정보에 원본 파일·버전 확인 주소를 연결했습니다.</p><a class="sq-link" href="${esc(result.deploymentUrl)}" download>배포 정보 JSON 받기</a></div>`:''}<div class="sq-actions" style="justify-content:center">${button('published-detail','상세 화면 보기','sq-primary')}${button('manage','등록 도구 관리')}</div></div>`);
 }finally{runtime.publishBusy=false;}
}
