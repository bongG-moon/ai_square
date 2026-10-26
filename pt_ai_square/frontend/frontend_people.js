// People, connection entry and declared workflows share the existing page shell.
let peopleRanks=null,peopleRanksError='',peopleRanksLoading=false,peopleLoadSerial=0,profileSignature='';
const baseRankItems=rankItems,baseRankRow=rankRowHTML,baseRenderRanks=renderRanks;
const basePeopleRender=render,basePeopleRefresh=refresh;
const peopleModes=$('.sq-rank-modes');
peopleModes.setAttribute('aria-label','도구·구성원 순위');
peopleModes.insertAdjacentHTML('beforeend',button('rank-mode','함께 만드는 사람들','','type="button" data-mode="people" aria-pressed="false"'));
$('.sq-chart-controls').insertAdjacentHTML('beforeend','<span id="sq-my-rank" class="sq-my-rank" hidden></span>');
$('#sq-session').classList.add('sq-profile');
$('#sq-session').insertAdjacentHTML('afterend',`<a id="sq-connection-key" class="sq-quiet sq-key-link" href="/local-access" aria-label="내 연결 KEY 발급·관리" title="연결 KEY 발급·관리">${icon('key-round')}</a>`);
// Equal hitboxes and one shared gap keep all personal action icons evenly spaced.
const headerIconGroup=document.createElement('div');
headerIconGroup.className='sq-header-icon-group';
headerIconGroup.setAttribute('role','group');headerIconGroup.setAttribute('aria-label','개인 도구');
$('#sq-session').after(headerIconGroup);
headerIconGroup.append($('.ws-bell'),$('#sq-connection-key'),...$$('.sq-header-actions>[data-action="fullscreen"],.sq-header-actions>[data-action="logout"]'));
$('#sq-connection-key').addEventListener('click',event=>{
 if(server.dataMode==='dummy'){
  event.preventDefault();openModal('나의 연결 KEY','개인 연결',`<div class="sq-detail-hero"><h3>내 사번으로, 안전하게 연결.</h3><p>실제 데이터 모드에서 연결 KEY를 발급할 수 있습니다. 사번당 활성 키는 하나이며 재발급하면 이전 키는 즉시 사용할 수 없습니다.</p></div>`);
 }
});
root.addEventListener('error',event=>{
 if(event.target.matches?.('.sq-profile-photo,.sq-person-photo')){event.target.hidden=true;event.target.dataset.photoFailedAt=String(Date.now());delete event.target.dataset.photoRetrying;event.target.closest('.sq-profile-avatar,.sq-person-avatar')?.classList.add('is-fallback');}
},true);
root.addEventListener('load',event=>{
 if(event.target.matches?.('.sq-profile-photo,.sq-person-photo')){event.target.hidden=false;delete event.target.dataset.photoFailedAt;delete event.target.dataset.photoRetrying;event.target.closest('.sq-profile-avatar,.sq-person-avatar')?.classList.remove('is-fallback');}
},true);
function retryFailedProfilePhoto(photo){
 const image=$('#sq-session .sq-profile-photo');
 // The server caches failures for 30 seconds. Retry only after a successful
 // app refresh, never from a timer or ordinary rank/card rendering.
 if(!photo||!image?.hidden||image.dataset.photoRetrying||!image.dataset.photoFailedAt)return;
 const failedAt=Number(image.dataset.photoFailedAt);
 if(!Number.isFinite(failedAt)||Date.now()-failedAt<31000)return;
 image.dataset.photoRetrying='true';image.src=`${photo}?retry=${Date.now()}`;
}
function renderProfile(retryFailedPhoto=false){
 const u=server.user||{},name=u.emp_name||u.name||'사용자',org=u.dept||u.org||'공통';
 const photo=server.dataMode!=='dummy'&&u.photoUrl==='/api/me/photo'?u.photoUrl:'';
 const signature=JSON.stringify([u.id,name,org,photo]);
 // Base refresh writes the session label, so rebuild only if that text replaced the profile.
 if(signature===profileSignature&&$('#sq-session .sq-profile-name')){if(retryFailedPhoto)retryFailedProfilePhoto(photo);return;}
 profileSignature=signature;
 $('#sq-session').innerHTML=`<span class="sq-profile-copy"><strong class="sq-profile-name">${esc(name)}${/\bTL$/.test(name)?'':' <span>TL</span>'}</strong><small>${esc(org)}</small></span><span class="sq-profile-avatar"><span aria-hidden="true">${esc([...name][0]||'?')}</span>${photo?`<img class="sq-profile-photo" src="${photo}" width="34" height="34" alt="" referrerpolicy="no-referrer">`:''}</span>`;
 $('#sq-session').setAttribute('aria-label',`${name} · ${org}`);
}
async function loadPeopleRanks(){
 const serial=++peopleLoadSerial;peopleRanksLoading=true;peopleRanksError='';
 try{const result=await requestAPI('/api/people/ranking');if(serial===peopleLoadSerial)peopleRanks=result;}
 catch(error){if(serial===peopleLoadSerial){peopleRanks=null;peopleRanksError=error.message;}}
 finally{if(serial===peopleLoadSerial)peopleRanksLoading=false;}
}
rankItems=function(){return state.rankMode==='people'?(peopleRanks?.items||[]):baseRankItems();};
rankRowHTML=function(row,rank){
 if(state.rankMode!=='people')return baseRankRow(row,rank);
 const name=row.name||'구성원',dept=row.org||'공통';
 const photo=server.dataMode!=='dummy'&&/^\/api\/people\/[0-9]{1,20}\/photo$/.test(row.photoUrl||'')?row.photoUrl:'';
 return `<div class="sq-rank-row sq-person-rank${row.isMe?' is-me':''}" data-rank="${rank}"><span class="sq-rank-number">${rank}</span><div class="sq-person-info"><div class="sq-person-identity"><span class="sq-person-dept" title="${esc(dept)}">${esc(dept)}</span><span class="sq-person-name-group"><strong class="sq-person-name" title="${esc(name)}">${esc(name)}</strong>${row.isMe?'<span class="sq-me-badge">나</span>':''}<span class="sq-person-avatar" aria-hidden="true"><span>${esc([...name][0]||'?')}</span>${photo?`<img class="sq-person-photo" src="${photo}" width="28" height="28" alt="" referrerpolicy="no-referrer">`:''}</span></span></div><span class="sq-person-counts"><span title="등록한 도구">${icon('package')}${num(row.registered)}</span><span title="받은 좋아요">${icon('heart')}${num(row.likes)}</span><span title="고유 다운로드">${icon('arrow-down-to-line')}${num(row.downloads)}</span></span></div><span class="sq-person-score"><strong>${num(row.score)}</strong><small>점</small></span></div>`;
};
renderRanks=function(){
 baseRenderRanks();const isPeople=state.rankMode==='people';
 $('.sq-chart').dataset.rankType=isPeople?'people':'tools';
 $('#sq-chart-title').textContent=isPeople?'함께 만드는 사람들':'동료들이 많이 찾는 도구';
 $('.sq-chart-labels>span:last-child').textContent=isPeople?'공유 기여도':'좋아요 · 다운로드';
 const me=$('#sq-my-rank');me.hidden=!isPeople;
 if(!isPeople)return;
 $('#sq-rank-range').textContent='함께 만드는 사람들';$('#sq-rank-period').textContent='전체 기간 · 공유 기여도';
 const own=peopleRanks?.me;me.textContent=own?.rank?`내 순위 ${num(own.rank)}위 · ${num(own.score)}점`:'도구를 공유하고 함께 성장해요';
 if(peopleRanks?.asOf)$('#sq-chart-time').textContent=new Date(peopleRanks.asOf*1000).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',timeZone:'Asia/Seoul'});
 if(peopleRanksLoading&&!peopleRanks)$('#sq-rank-list').innerHTML='<div class="sq-empty" role="status">공유 기여도를 집계하고 있어요.</div>';
 else if(peopleRanksError)$('#sq-rank-list').innerHTML=`<div class="sq-empty" role="status"><p>${esc(peopleRanksError)}</p>${button('rank-retry','다시 불러오기','sq-link')}</div>`;
 else if(!peopleRanks?.items?.length)$('#sq-rank-list').innerHTML='<div class="sq-empty">첫 번째 도구를 공유하고<br>함께 성장해요.</div>';
};
render=function(){basePeopleRender();renderProfile();};
refresh=async function(){
 if(state.rankMode==='people')await loadPeopleRanks();
 const refreshed=await basePeopleRefresh();
 if(refreshed!==false)renderProfile(true);
 return refreshed;
};
actions['rank-mode']=async b=>{
 const mode=b.dataset.mode;if(!['recent','total','people'].includes(mode)||mode===state.rankMode)return;
 runtime.token++;runtime.busy=false;stopAuto();state.rankMode=mode;state.rankPage=0;
 if(mode==='people'){
  const pending=loadPeopleRanks();render();await pending;
  if(state.rankMode==='people')render();
 }else render();
};
actions['rank-retry']=async()=>{const pending=loadPeopleRanks();render();await pending;render();};
actions['rank-info']=()=>{
 const people=state.rankMode==='people';
 const weights=peopleRanks?.weights||{registered:5,likes:2,downloads:1};
 const score=(label,weight,symbol,unit)=>`<div class="sq-score-tile"><span class="sq-score-symbol" aria-hidden="true">${icon(symbol)}</span><span class="sq-score-label">${label}</span><strong>${esc(weight)}<small>점</small></strong><span class="sq-score-unit">${unit}</span></div>`;
 const rule=(title,copy)=>`<li><span aria-hidden="true">${icon('check')}</span><div><strong>${title}</strong><p>${copy}</p></div></li>`;
 const formula=people?score('등록한 도구',weights.registered,'package','도구 1개당')+score('받은 좋아요',weights.likes,'heart','좋아요 1개당')+score('고유 다운로드',weights.downloads,'arrow-down-to-line','사용자·도구당 최초 1회'):score('좋아요',2,'heart','한 사람·한 도구당')+score('다운로드',1,'arrow-down-to-line','사용자·도구당 최초 1회');
 const periods=people?'<div class="sq-ranking-period-note">전체 기간에 쌓인 공유 활동을 합산합니다.</div>':`<div class="sq-ranking-periods" aria-label="집계 기간 안내"><div${state.rankMode==='recent'?' class="is-current"':''}><strong>실시간</strong><span>집계 시각부터 최근 7일</span></div><div${state.rankMode==='total'?' class="is-current"':''}><strong>누적</strong><span>전체 기간</span></div></div>`;
 const rules=people?rule('버전이 늘어도, 도구는 한 번만','등록한 도구 수와 동료들이 보낸 좋아요·다운로드를 더합니다.')+rule('반복 활동은 추가 점수 없이','본인 도구에 대한 반응, 반복 다운로드와 업데이트는 제외합니다.')+rule('현재 유효한 공유 활동만','취소한 좋아요, 삭제된 도구와 비활성 사용자는 반영하지 않습니다.'):rule('좋아요는 한 번씩 반영','취소하면 점수가 빠지고, 다시 눌러도 최초 좋아요 날짜를 유지합니다.')+rule('처음 받은 다운로드만 반영','같은 사람이 같은 도구를 다시 받거나 업데이트해도 점수가 늘지 않습니다.');
 const details=people?`<li>조회 승인이 필요한 도구의 개별 정보는 이 화면에 표시하지 않습니다.</li><li>${esc(peopleRanks?.tieBreak||'동점이면 등록 도구 수 → 받은 좋아요 수 → 고유 다운로드 수 → 사번 순으로 정렬합니다.')}</li>`:'<li>실시간 다운로드 점수에는 전체 기간 최초 수신일이 최근 7일인 경우만 반영합니다. URL 클릭은 다운로드 점수에 포함하지 않습니다.</li><li>동점이면 해당 기간의 다운로드 수 → 좋아요 수 → 최근 도구 등록일 순입니다. 순위에 표시된 활동 수도 선택한 기간 기준입니다.</li><li>접속·새로고침·좋아요·다운로드 후 재집계합니다. 5초마다 1–5위와 6–10위를 전환하는 애니메이션은 재집계와 별개입니다.</li><li>다운로드 수는 서버의 파일 응답 기준이며 PC 설치 완료 수가 아닙니다.</li>';
 openModal(people?'함께 만드는 사람들 · 집계 기준':'동료들이 많이 찾는 도구 · 집계 기준','순위 안내',`<section class="sq-ranking-guide"><p class="sq-ranking-intro">${people?'도구를 나눈 동료들을 소개합니다. 등록한 도구와 동료들의 반응을 바탕으로 공유 기여도 상위 10명을 보여드립니다.':'동료들의 좋아요와 다운로드를 모아 상위 10개 도구를 보여드립니다. 최근의 관심은 실시간으로, 꾸준한 이용은 누적으로 살펴보세요.'}</p><div class="sq-score-grid${people?' sq-score-grid-three':''}">${formula}</div>${periods}<div class="sq-ranking-rules"><h3>이렇게 반영해요</h3><ul>${rules}</ul></div><details class="sq-ranking-details"><summary>세부 집계 기준<span aria-hidden="true">${icon('chevron-down')}</span></summary><ul>${details}</ul></details><footer class="sq-ranking-footer"><span>${icon('refresh-cw')} 최신 활동으로 다시 확인할 수 있어요.</span>${button('rank-refresh','집계 새로고침','sq-secondary')}</footer></section>`);
};
function workflowDiagram(workflow){
 const steps=Array.isArray(workflow?.steps)?workflow.steps.slice(0,8):[];
 if(!steps.length)return '';
 return `<details class="sq-workflow" aria-labelledby="sq-workflow-title"><summary class="sq-workflow-heading"><span class="sq-workflow-heading-copy"><span class="sq-workflow-eyebrow" lang="en">HOW IT WORKS</span><strong id="sq-workflow-title">이렇게 동작해요.</strong></span><span class="sq-workflow-toggle"><span class="sq-workflow-count">${steps.length}단계</span><span class="sq-workflow-expand">펼치기</span><span class="sq-workflow-collapse">접기</span><span class="sq-workflow-chevron" aria-hidden="true">${icon('chevron-down')}</span></span></summary><div class="sq-workflow-body"><ol class="sq-workflow-steps" aria-label="동작 순서">${steps.map((step,i)=>`<li><span class="sq-workflow-number" aria-hidden="true">${String(i+1).padStart(2,'0')}</span><div class="sq-workflow-step"><strong>${esc(step.title)}</strong>${step.description?`<p>${esc(step.description)}</p>`:''}</div></li>`).join('')}</ol><p class="sq-note"><span class="sq-workflow-source">배포 정보 기반</span>등록자가 정리한 동작 순서입니다. 실제 실행 상태를 표시하지 않습니다.</p></div></details>`;
}
const basePeopleDetail=detail;
detail=async function(id,tab='intro'){
 const rendered=await basePeopleDetail(id,tab);
 if(!rendered||tab!=='intro'||!$('#sq-dialog').open||runtime.detailId!==+id||runtime.detailTab!=='intro')return;
 const x=getItem(id);if(x?.access!=='approved')return;
 $('#sq-workflow-title')?.closest('.sq-workflow').remove();
 const diagram=workflowDiagram(x.workflow);
 if(diagram){const anchor=$('#sq-dialog-body .sq-detail-hero');anchor?.insertAdjacentHTML('afterend',diagram);mountIcons();}
};
