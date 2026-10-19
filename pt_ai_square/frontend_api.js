const server={csrf:'',user:{},rankAsOf:0,storage:null,ideas:[]};
function showError(error){const message=error.message||'처리 중 오류가 발생했습니다.';const target=$('#sq-register-error')||$('#sq-edit-error')||$('#sq-org-error');if(target)target.textContent=message;else {let banner=$('#sq-server-error');if(!banner){banner=document.createElement('p');banner.id='sq-server-error';banner.className='sq-server-error';banner.setAttribute('role','alert');$('.sq-shell').prepend(banner);}banner.hidden=false;banner.textContent=message;}announce(message);}
async function requestAPI(url,method='GET',body){
 runtime.requestBusy=(runtime.requestBusy||0)+1;
 try{const headers={'X-CSRF-Token':server.csrf};if(body&&!(body instanceof FormData))headers['Content-Type']='application/json';
 const response=await fetch(url,{method,credentials:'same-origin',headers,body:body instanceof FormData?body:body?JSON.stringify(body):undefined});
 const result=await response.json();if(!response.ok){if(response.status===401)location.assign(result.login||'/login');throw Error(result.error||'요청을 처리하지 못했습니다.');}return result;
 }finally{runtime.requestBusy--;}
}
async function refresh(){
 const data=await requestAPI('/api/bootstrap');Object.assign(server,data);items.splice(0,items.length,...data.items.map(x=>({...x,likes:x.likes-(x.liked?1:0)})));state.liked=new Set(data.items.filter(x=>x.liked).map(x=>x.id));
 if($('#sq-server-error'))$('#sq-server-error').hidden=true;
 organizations.splice(0,organizations.length,...data.organizations);requests.splice(0,requests.length,...data.requests);Object.assign(policy,data.policy);audit.splice(0,audit.length,...data.audit);
 $('#sq-session').textContent=data.user.name+' · '+data.user.org;$('.sq-demo').textContent=data.authMode==='mock'?'SSO 미사용':'SSO 사용';
 $('[data-action=logout]').hidden=data.authMode==='mock';render();
}
async function mutate(url,method,body,after){await requestAPI(url,method,body);await refresh();after?.();}
async function downloadVersion(id,n){
 const x=getItem(id);if(x.approval&&x.access!=='approved'){requestAccess();return;}
 const v=x.versions.find(v=>v.n===n);if(!v?.filename){if(v?.url)openModal(`v${n} 연결 안내`,x.name,`<div class="sq-callout"><a href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">${esc(v.url)}</a></div><p class="sq-note">이 버전에 저장된 연결 주소입니다. 원격 서버 프로그램의 버전을 되돌리는 기능은 아닙니다.</p>`);else detail(id,'connect');return;}
 // HEAD checks access without counting an event; browser streams the GET to disk.
 const check=await fetch(`/download/${id}/${n}`,{method:'HEAD'});if(!check.ok)throw Error('파일을 받을 수 없습니다. 권한 또는 배포 상태를 확인해 주세요.');
 const a=document.createElement('a');a.href=`/download/${id}/${n}`;a.download=v.filename;document.body.append(a);a.click();a.remove();announce('다운로드를 시작했습니다. 브라우저 다운로드 목록을 확인하세요.');setTimeout(()=>refresh().catch(showError),1500);
}
actions.like=async b=>{const id=+b.dataset.id,liked=!state.liked.has(id);const result=await requestAPI(`/api/tools/${id}/like`,'PUT',{liked});const x=getItem(id);x.likes=result.count-(liked?1:0);liked?state.liked.add(id):state.liked.delete(id);
 $$(`[data-action="like"][data-id="${id}"]`).forEach(control=>{control.setAttribute('aria-pressed',String(liked));const count=control.querySelector('[data-like-count]')||(control.classList.contains('sq-like')?control.querySelector('span'):null);if(count)count.textContent=num(result.count);const label=control.querySelector('[data-like-label]');if(label)label.textContent=liked?'좋아요 취소':'좋아요';});
 if($('#sq-dialog').open&&runtime.detailId===id){const summary=$('.sq-detail-id p');if(summary)summary.textContent=`다운로드 ${num(x.downloads)} · 좋아요 ${num(result.count)}`;}
 const heart=b.querySelector('svg');if(liked&&!motion.matches&&heart?.animate)heart.animate([{transform:'scale(1)'},{transform:'scale(1.3)'},{transform:'scale(1)'}],{duration:330});
 if(result.pending){showError({message:result.notice});return;}
 await refresh();announce(liked?'좋아요를 추가하고 순위를 갱신했습니다.':'좋아요를 취소하고 순위를 갱신했습니다.');};
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
actions['admin-tab']=async b=>{if(b.dataset.tab==='ideas')server.ideas=(await requestAPI('/api/ideas')).ideas;if(b.dataset.tab==='activity'){const r=await requestAPI('/api/activity');server.activityEvents=r.events;server.activityCursor=r.nextCursor;}manage(b.dataset.tab);};
actions['download-skill']=()=>location.assign('/static/guides/PT_AI_SQUARE_파일배포_Skill.zip');
actions['download-guide']=()=>{const a=document.createElement('a');a.href='/static/guides/PT_AI_SQUARE_등록가이드.html';a.download='PT_AI_SQUARE_등록가이드.html';a.click();};
actions.fullscreen=async()=>{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();};
actions.logout=()=>ask('로그아웃할까요?',server.authMode==='sso'?'웹 세션을 종료합니다. 회사 SSO 세션이 남아 있으면 다시 접속할 때 자동 인증됩니다.':'현재 웹 로그인 세션을 종료합니다.',async()=>{await requestAPI('/api/logout','POST',{});location.assign('/login');},'로그아웃');
