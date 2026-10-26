const server={csrf:'',user:{},rankAsOf:0,storage:null,ideas:[]};
function showError(error,target){
 const message=error?.message||'처리 중 오류가 발생했습니다.',body=$('#sq-dialog')?.open?$('#sq-dialog-body'):null;
 if(!target?.isConnected)target=body?.querySelector('#sq-register-error,#sq-edit-error,#sq-org-error')||(!body?$('#ws-capacity-message'):null);
 if(!target&&body){target=$('#ws-dialog-error');if(!target){target=document.createElement('p');target.id='ws-dialog-error';target.className='sq-error';body.prepend(target);}}
 if(!target){target=$('#sq-server-error');if(!target){target=document.createElement('p');target.id='sq-server-error';target.className='sq-server-error';$('.sq-shell').prepend(target);}}
 // The alert is also the accessible announcement; announce() would add a second blue message.
 $$('#sq-server-error,#ws-dialog-error,#sq-register-error,#sq-edit-error,#sq-org-error,#ws-capacity-message,#sq-status,#sq-modal-status').forEach(node=>{if(node!==target){node.textContent='';if(node.id==='sq-server-error')node.hidden=true;}});
 target.hidden=false;target.setAttribute('role','alert');target.setAttribute('aria-live','assertive');target.textContent=message;
 if(body)target.scrollIntoView?.({block:'nearest'});
}
async function requestAPI(url,method='GET',body,options={}){
 runtime.requestBusy=(runtime.requestBusy||0)+1;
 const controller=options.timeoutMs?new AbortController():null;
 const timer=controller?setTimeout(()=>controller.abort(),options.timeoutMs):null;
 try{const headers={'X-CSRF-Token':server.csrf};if(body&&!(body instanceof FormData))headers['Content-Type']='application/json';
 let response;
 try{response=await fetch(url,{method,credentials:'same-origin',headers,body:body instanceof FormData?body:body?JSON.stringify(body):undefined,...(controller?{signal:controller.signal}:{})});}
 catch(cause){if(!['TypeError','AbortError'].includes(cause?.name))throw cause;const error=Error('서버 응답을 받지 못했습니다. 연결 상태를 확인해 주세요.');error.code='NETWORK_ERROR';error.uncertain=true;throw error;}
 let result;
 try{result=await response.json();}
 catch{const error=Error(response.status===413?'파일 크기가 서버의 업로드 한도를 초과했습니다.':'서버 응답을 확인하지 못했습니다. 저장 결과를 확인해 주세요.');error.status=response.status;error.code='INVALID_RESPONSE';error.uncertain=response.ok||response.status>=500;throw error;}
 if(!response.ok){if(response.status===401&&options.redirectOnAuth!==false)location.assign(result?.login||'/login');const error=Error(result?.error||'요청을 처리하지 못했습니다.');error.status=response.status;error.uncertain=response.status>=500;throw error;}
 if(!result||typeof result!=='object'||Array.isArray(result)){const error=Error('서버 응답 형식을 확인하지 못했습니다.');error.code='INVALID_RESPONSE';error.uncertain=true;throw error;}
 return result;
 }finally{if(timer!==null)clearTimeout(timer);runtime.requestBusy--;}
}
async function refresh(){
 const token=runtime.refreshToken=(runtime.refreshToken||0)+1;let data;
 const notificationToken=runtime.notificationGeneration=(runtime.notificationGeneration||0)+1;
 try{data=await requestAPI('/api/bootstrap');}catch(error){if(token!==runtime.refreshToken)return false;throw error;}
 // Every caller shares this generation; a slower earlier request cannot overwrite newer data.
 if(token!==runtime.refreshToken)return false;
 // A later inbox read or a confirmed read-mark is authoritative for the badge.
 if(notificationToken!==runtime.notificationGeneration)data={...data,unread:server.unread};
 Object.assign(server,data);items.splice(0,items.length,...data.items.map(x=>({...x,likes:x.likes-(x.liked?1:0)})));state.liked=new Set(data.items.filter(x=>x.liked).map(x=>x.id));
 if($('#sq-server-error'))$('#sq-server-error').hidden=true;
 organizations.splice(0,organizations.length,...data.organizations);requests.splice(0,requests.length,...data.requests);Object.assign(policy,data.policy);audit.splice(0,audit.length,...data.audit);
 // renderProfile updates identity changes; keep an unchanged photo node alive.
 if(!$('#sq-session .sq-profile-name'))$('#sq-session').textContent=data.user.name+' · '+data.user.org;
 $('.sq-demo').textContent=data.dataMode==='dummy'?'샘플 데이터 · 조회 전용':data.authMode==='mock'?'SSO 미사용':'SSO 사용';
 $('[data-action=logout]').hidden=data.authMode==='mock';render();return true;
}
async function mutate(url,method,body,after){
 await requestAPI(url,method,body);
 try{await refresh();return await after?.();}
 catch(error){throw Error(`변경 내용은 저장되었습니다. 화면을 갱신하지 못했습니다. ${error.message}`);}
}
async function downloadVersion(id,n){
 if(server.dataMode==='dummy')throw Error('샘플 데이터는 조회 전용입니다. 실제 데이터 모드에서 다운로드해 주세요.');
 const x=getItem(id);if(x.approval&&x.access!=='approved'){requestAccess();return;}
 const v=x.versions.find(v=>v.n===n);if(v?.deleted||v?.withdrawn)throw Error('배포가 중단된 버전입니다.');if(v?.commands&&Object.values(v.commands).some(Boolean)){openModal(`v${n} 명령어 설치`,x.name,commandScopePanel(x,v));return;}if(!v?.filename){if(v?.url)openModal(`v${n} 연결 안내`,x.name,`<div class="sq-callout"><a href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">${esc(v.url)}</a></div><p class="sq-note">이 버전에 저장된 연결 주소입니다. 원격 서버 프로그램의 버전을 되돌리는 기능은 아닙니다.</p>`);else detail(id,'connect');return;}
 // HEAD checks access without counting an event; browser streams the GET to disk.
 const check=await fetch(`/download/${id}/${n}`,{method:'HEAD'});if(!check.ok)throw Error('파일을 받을 수 없습니다. 권한 또는 배포 상태를 확인해 주세요.');
 const a=document.createElement('a');a.href=`/download/${id}/${n}`;a.download=v.filename;document.body.append(a);a.click();a.remove();setTimeout(()=>refresh().catch(showError),1500);
}
function setLikeBusy(id,busy){$$(`[data-action="like"][data-id="${id}"]`).forEach(control=>{control.disabled=busy;if(busy)control.setAttribute('aria-busy','true');else control.removeAttribute('aria-busy');});}
function applyLikeResult(id,liked,count){
 const x=getItem(id);if(x)x.likes=count-(liked?1:0);liked?state.liked.add(id):state.liked.delete(id);
 $$(`[data-action="like"][data-id="${id}"]`).forEach(control=>{control.setAttribute('aria-pressed',String(liked));const counter=control.querySelector('[data-like-count]')||(control.classList.contains('sq-like')?control.querySelector('span'):null);if(counter)counter.textContent=num(count);const label=control.querySelector('[data-like-label]');if(label)label.textContent=liked?'좋아요 취소':'좋아요';});
 if(x&&$('#sq-dialog').open&&runtime.detailId===id){const summary=$('.sq-detail-id p');if(summary)summary.textContent=`다운로드 ${num(x.downloads)} · 좋아요 ${num(count)}`;}
}
// Catalog/rank rendering or opening a detail can create another control during the request.
new MutationObserver(()=>{runtime.likeRequests?.forEach((_,id)=>setLikeBusy(id,true));}).observe(root,{childList:true,subtree:true});
actions.like=b=>{
 const id=+b.dataset.id,pending=runtime.likeRequests||(runtime.likeRequests=new Map());
 if(pending.has(id))return pending.get(id).promise;
 const operation={},previousLiked=state.liked.has(id),liked=!previousLiked;
 const previousBase=Number(getItem(id)?.likes);
 const previousCount=Math.max(previousLiked?1:0,(Number.isFinite(previousBase)?Math.floor(previousBase):0)+(previousLiked?1:0));
 pending.set(id,operation);setLikeBusy(id,true);
 operation.promise=(async()=>{
 const result=await requestAPI(`/api/tools/${id}/like`,'PUT',{liked}),savedLiked=result.liked??liked;
 // A confirmed state write can succeed even when the separate count query is unavailable.
 const savedCount=Math.max(savedLiked?1:0,Number.isFinite(result.count)?Math.floor(result.count):previousCount+(savedLiked?1:0)-(previousLiked?1:0));
 applyLikeResult(id,savedLiked,savedCount);
 const heart=b.querySelector('svg');if(savedLiked&&!motion.matches&&heart?.animate)heart.animate([{transform:'scale(1)'},{transform:'scale(1.3)'},{transform:'scale(1)'}],{duration:330});
 // Keep concurrent cards independent, but do not apply older bootstrap responses last.
 runtime.likeRefresh=(runtime.likeRefresh||Promise.resolve()).catch(()=>{}).then(()=>refresh());
 try{await runtime.likeRefresh;}catch(error){applyLikeResult(id,savedLiked,savedCount);showError({message:`좋아요 ${savedLiked?'추가':'취소'}는 저장되었습니다. 목록·순위를 새로고침하지 못했습니다. ${error.message}`});return;}
 const historyPending=result.historyPending??(result.countsPending==null&&result.pending);
 announce(historyPending&&result.countsPending?'좋아요는 저장되었습니다. 이력·집계는 다음 조회 시 다시 확인합니다.':historyPending?'좋아요는 저장되었습니다. 이력은 다음 조회 시 동기화됩니다.':result.countsPending?'좋아요는 저장되었습니다. 집계는 목록 조회 시 다시 확인합니다.':savedLiked?'좋아요를 추가하고 순위를 갱신했습니다.':'좋아요를 취소하고 순위를 갱신했습니다.');
 })().finally(()=>{pending.delete(id);setLikeBusy(id,false);});
 return operation.promise;
};
actions['published-detail']=async()=>{
 const id=runtime.newId,token=invalidateDetailLoad();
 const viewError=error=>Error(`게시한 도구는 저장되어 있습니다. 상세 화면을 불러오지 못했습니다. ${error.message}`);
 // Only guard the bootstrap recovery; detail() starts and owns its own load token.
 try{if(!getItem(id))await refresh();}
 catch(error){if(token!==runtime.detailLoadToken)return false;throw viewError(error);}
 if(token!==runtime.detailLoadToken)return false;
 try{
  if(!getItem(id))throw Error('목록에서 게시한 도구를 찾지 못했습니다.');
  return await detail(id);
 }catch(error){throw viewError(error);}
};
actions['rank-refresh']=async()=>{await refresh();closeModal();announce('서버 집계 기준으로 갱신했습니다.');};
actions['download-file']=()=>downloadVersion(runtime.detailId,getItem(runtime.detailId).active);
actions['version-download']=b=>downloadVersion(runtime.detailId,+b.dataset.version);
actions['connection-check']=()=>detail(runtime.detailId,'connect');
actions['toggle-hidden']=b=>{const x=getItem(b.dataset.id);ask(x.hidden?'다시 공개할까요?':'공개를 중단할까요?',x.name+' · 설치된 PC의 파일은 변경하지 않습니다.',()=>mutate(`/api/tools/${x.id}`,'PATCH',{hidden:!x.hidden,expectedRevision:x.revision},()=>manage()));};
actions.rollback=b=>{const x=getItem(runtime.detailId),n=+b.dataset.version;ask(`v${n}으로 복구할까요?`,`${x.name}의 현재 배포를 중단하고 선택한 버전을 배포합니다. PC 자동 복구는 아직 지원하지 않습니다.`,()=>mutate(`/api/tools/${x.id}/rollback`,'POST',{version:n,expectedRevision:x.revision},()=>versionManager(x.id)),'이 버전으로 복구');};
actions['delete-version']=b=>{const x=getItem(runtime.detailId),n=+b.dataset.version;ask(`v${n} 파일을 삭제할까요?`,'파일 삭제는 되돌릴 수 없습니다. 배포 이력은 보존합니다.',()=>mutate(`/api/tools/${x.id}/versions/${n}`,'DELETE',null,()=>versionManager(x.id)),'파일 삭제');};
actions.approve=b=>ask('사용 신청을 승인할까요?','도구 사용만 승인합니다. 원본 데이터 권한은 별도입니다.',()=>mutate(`/api/requests/${b.dataset.request}/decision`,'POST',{status:'승인',reason:''},()=>manage('requests')),'승인');
actions['cleanup-preview']=async()=>{const data=await requestAPI('/api/storage/candidates');runtime.cleanupServer=data.candidates;openModal('이전 버전 정리','삭제 전 대상 확인',`<div class="sq-callout">현재 배포·복구용 버전은 보호됩니다. 아래 파일은 삭제 후 복구할 수 없습니다.</div><div class="sq-version-list">${data.candidates.map(c=>`<div class="sq-version"><strong>${esc(getItem(c.tool).name)} · v${c.version}</strong><span>${(c.bytes/1048576).toFixed(2)} MB</span></div>`).join('')||'<p>새 정리 대상이 없습니다. 삭제 대기 파일이 있으면 아래 버튼으로 재시도할 수 있습니다.</p>'}</div><div class="sq-actions">${button('admin-tab','돌아가기','sq-secondary','data-tab="storage"')}${button('cleanup-confirm','선택 파일 삭제','sq-primary',data.candidates.length||server.storage?.pending?'':'disabled')}</div>`);};
actions['cleanup-confirm']=()=>ask('선택한 이전 파일을 삭제할까요?',`${runtime.cleanupServer.length}개 파일을 정리합니다.`,async()=>{const r=await requestAPI('/api/storage/cleanup','POST',{candidates:runtime.cleanupServer});await refresh();manage('storage');announce(r.pending?'일부 파일은 사용 중이어서 삭제 대기 중입니다. 다시 정리하면 재시도합니다.':'파일 정리를 완료했습니다.');},'삭제');
actions['admin-tab']=async b=>{if(b.dataset.tab==='ideas')server.ideas=(await requestAPI('/api/ideas')).ideas;manage(b.dataset.tab);if(b.dataset.tab==='activity')return openActivityHistory();};
actions['download-skill']=async()=>{
 const url='/resources/distribution-skill.zip';let response;
 try{response=await fetch(url,{method:'HEAD',credentials:'same-origin',redirect:'error',cache:'no-store'});}
 catch{throw Error('파일 배포 Skill을 받지 못했습니다. 서버 연결과 로그인 상태를 확인한 뒤 다시 시도해 주세요.');}
 if(!response.ok)throw Error(response.status===401||response.status===403?'로그인 상태 또는 다운로드 권한을 확인해 주세요.':'파일 배포 Skill 파일을 받을 수 없습니다. 운영자에게 최신 배포 파일 반영을 요청해 주세요.');
 const mime=(response.headers.get('Content-Type')||'').split(';')[0].trim().toLowerCase();
 if(!['application/zip','application/x-zip-compressed','application/octet-stream'].includes(mime))throw Error('다운로드 파일 대신 다른 화면이 응답했습니다. 로그인 상태와 운영 서버 배포 경로를 확인해 주세요.');
 const link=document.createElement('a');link.href=url;link.download='pt-file-distribution.zip';link.click();
};
actions['download-guide']=async()=>{
 const url='/static/guides/pt-ai-square-user-guide.html';let response;
 try{response=await fetch(url,{method:'HEAD',credentials:'same-origin',redirect:'error',cache:'no-store'});}
 catch{throw Error('등록 가이드를 받지 못했습니다. 서버 연결과 로그인 상태를 확인한 뒤 다시 시도해 주세요.');}
 if(!response.ok)throw Error(response.status===401||response.status===403?'로그인 상태 또는 다운로드 권한을 확인해 주세요.':'등록 가이드를 받을 수 없습니다. 운영자에게 최신 배포 파일 반영을 요청해 주세요.');
 const mime=(response.headers.get('Content-Type')||'').split(';')[0].trim().toLowerCase();
 if(mime!=='text/html')throw Error('등록 가이드 대신 다른 응답이 도착했습니다. 운영 서버 배포 경로를 확인해 주세요.');
 const link=document.createElement('a');link.href=url;link.download='pt-ai-square-user-guide.html';link.click();
};
actions.fullscreen=async()=>{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();};
actions.logout=()=>ask('로그아웃할까요?',server.authMode==='sso'?'웹 세션을 종료합니다. 회사 SSO 세션이 남아 있으면 다시 접속할 때 자동 인증됩니다.':'현재 웹 로그인 세션을 종료합니다.',async()=>{await requestAPI('/api/logout','POST',{});location.assign('/login');},'로그아웃');
