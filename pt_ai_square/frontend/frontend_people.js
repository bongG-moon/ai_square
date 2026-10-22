// People, connection entry and declared workflows share the existing page shell.
let peopleRanks=null,peopleRanksError='',peopleRanksLoading=false,peopleLoadSerial=0,profileSignature='';
const baseRankItems=rankItems,baseRankRow=rankRowHTML,baseRenderRanks=renderRanks;
const basePeopleRender=render,basePeopleRefresh=refresh,baseRankInfo=actions['rank-info'];
const peopleModes=$('.sq-rank-modes');
peopleModes.setAttribute('aria-label','도구·개발자 순위');
peopleModes.insertAdjacentHTML('beforeend',button('rank-mode','POWER USER','','type="button" data-mode="people" aria-pressed="false"'));
$('.sq-chart-controls').insertAdjacentHTML('beforeend','<span id="sq-my-rank" class="sq-my-rank" hidden></span>');
$('#sq-session').classList.add('sq-profile');
$('#sq-session').insertAdjacentHTML('afterend',`<a id="sq-connection-key" class="sq-quiet sq-key-link" href="/local-access" aria-label="내 연결 KEY 발급·관리" title="연결 KEY 발급·관리">${icon('key-round')}</a>`);
$('#sq-connection-key').addEventListener('click',event=>{
 if(server.dataMode==='dummy'){
  event.preventDefault();openModal('나의 연결 KEY','개인 연결',`<div class="sq-detail-hero"><h3>내 사번으로, 안전하게 연결.</h3><p>실제 데이터 모드에서 연결 KEY를 발급할 수 있습니다. 사번당 활성 키는 하나이며 재발급하면 이전 키는 즉시 사용할 수 없습니다.</p></div>`);
 }
});
root.addEventListener('error',event=>{
 if(event.target.matches?.('.sq-profile-photo')){event.target.hidden=true;event.target.closest('.sq-profile-avatar')?.classList.add('is-fallback');}
},true);
function renderProfile(){
 const u=server.user||{},name=u.emp_name||u.name||'사용자',org=u.dept||u.org||'공통';
 const photo=server.dataMode!=='dummy'&&u.photoUrl==='/api/me/photo'?u.photoUrl:'';
 const signature=JSON.stringify([u.id,name,org,photo]);
 // Base refresh writes the session label, so rebuild only if that text replaced the profile.
 if(signature===profileSignature&&$('#sq-session .sq-profile-name'))return;
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
 return `<div class="sq-rank-row sq-person-rank${row.isMe?' is-me':''}" data-rank="${rank}"><span class="sq-rank-number">${rank}</span><div class="sq-person-info"><strong>${esc(row.name)}${row.isMe?'<span class="sq-me-badge">나</span>':''}</strong><small>${esc(row.org)}</small><span class="sq-person-counts"><span title="등록한 도구">${icon('package')}${num(row.registered)}</span><span title="받은 좋아요">${icon('heart')}${num(row.likes)}</span><span title="고유 다운로드">${icon('arrow-down-to-line')}${num(row.downloads)}</span></span></div><span class="sq-person-score"><strong>${num(row.score)}</strong><small>점</small></span></div>`;
};
renderRanks=function(){
 baseRenderRanks();const isPeople=state.rankMode==='people';
 $('.sq-chart').dataset.rankType=isPeople?'people':'tools';
 $('#sq-chart-title').innerHTML=isPeople?'함께 만드는 <span lang="en">TOP 10</span>':'인기 <span lang="en">TOP 10</span>';
 $('.sq-chart-labels>span:last-child').textContent=isPeople?'공유 기여도':'좋아요 · 다운로드';
 const me=$('#sq-my-rank');me.hidden=!isPeople;
 if(!isPeople)return;
 $('#sq-rank-range').textContent='POWER USER · 전체 기간';$('#sq-rank-period').textContent='전체 기간 · 개발자 순위';
 const own=peopleRanks?.me;me.textContent=own?.rank?`내 순위 ${num(own.rank)}위 · ${num(own.score)}점`:'도구를 공유하고 함께 성장해요';
 if(peopleRanks?.asOf)$('#sq-chart-time').textContent=new Date(peopleRanks.asOf*1000).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',timeZone:'Asia/Seoul'});
 if(peopleRanksLoading&&!peopleRanks)$('#sq-rank-list').innerHTML='<div class="sq-empty" role="status">공유 기여도를 집계하고 있어요.</div>';
 else if(peopleRanksError)$('#sq-rank-list').innerHTML=`<div class="sq-empty" role="status"><p>${esc(peopleRanksError)}</p>${button('rank-retry','다시 불러오기','sq-link')}</div>`;
 else if(!peopleRanks?.items?.length)$('#sq-rank-list').innerHTML='<div class="sq-empty">첫 번째 도구를 공유하고<br>POWER USER가 되어 보세요.</div>';
};
render=function(){basePeopleRender();renderProfile();};
refresh=async function(){
 if(state.rankMode==='people')await loadPeopleRanks();
 await basePeopleRefresh();
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
 if(state.rankMode!=='people')return baseRankInfo();
 const weights=peopleRanks?.weights||{registered:5,likes:2,downloads:1};
 openModal('함께 쓰는 도구를 만든 사람들.','POWER USER · 전체 기간',`<div class="sq-detail-hero"><h3>나눈 노하우가 쌓이는 순위.</h3><p>등록한 도구와 그 도구를 이용한 동료들의 반응을 모아 공유 기여도를 보여드립니다.</p></div><div class="sq-power-formula"><span>등록 도구 <strong>× ${weights.registered}</strong></span><span>받은 좋아요 <strong>× ${weights.likes}</strong></span><span>고유 다운로드 <strong>× ${weights.downloads}</strong></span></div><div class="sq-callout">전체 기간을 기준으로 집계합니다. 도구는 버전 수와 관계없이 한 번만 반영합니다. 좋아요 취소·삭제된 도구·비활성 사용자는 순위에 반영하지 않습니다.<br><br>본인 도구에 대한 좋아요·다운로드, 같은 사람이 같은 도구를 반복 다운로드하거나 업데이트한 이력은 추가 점수가 없습니다. 조회 승인이 필요한 도구의 개별 정보는 이 화면에 표시하지 않습니다.</div><p class="sq-note">${esc(peopleRanks?.tieBreak||'동점이면 등록 도구 수 → 받은 좋아요 수 → 고유 다운로드 수 → 사번 순으로 정렬합니다.')}</p>${button('rank-refresh','집계 새로고침','sq-primary')}`);
};
function workflowDiagram(workflow){
 const steps=Array.isArray(workflow?.steps)?workflow.steps.slice(0,8):[];
 if(!steps.length)return '';
 return `<section class="sq-workflow" aria-labelledby="sq-workflow-title"><div class="sq-workflow-heading"><div><span>HOW IT WORKS</span><h3 id="sq-workflow-title">이렇게 동작해요.</h3></div><span class="sq-workflow-source">배포 정보 기반</span></div><ol class="sq-workflow-steps">${steps.map((step,i)=>`<li><span class="sq-workflow-number">${String(i+1).padStart(2,'0')}</span><div><strong>${esc(step.title)}</strong>${step.description?`<p>${esc(step.description)}</p>`:''}</div>${i<steps.length-1?`<span class="sq-workflow-arrow" aria-hidden="true">${icon('arrow-right')}</span>`:''}</li>`).join('')}</ol><p class="sq-note">등록자가 배포 Skill로 정리한 동작 흐름입니다. 실제 실행 상태를 표시하는 화면은 아닙니다.</p></section>`;
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
