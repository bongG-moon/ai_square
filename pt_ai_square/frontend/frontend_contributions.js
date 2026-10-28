// Personal contribution detail is fetched only when this management tab opens.
function contributionState(){
 const user=String(server.user.id);
 if(!work.contribution||work.contribution.user!==user)work.contribution={user,token:0,requested:false,loading:false,data:null,error:'',page:1};
 return work.contribution;
}
function contributionVisible(){return state.route==='manage'&&work.tab==='contributions';}
function renderContributions(){if(contributionVisible())renderWorkspace();}
function ensureContributions(){const s=contributionState();if(!s.requested){s.requested=true;void loadContributions(1);}}
async function loadContributions(page=1){
 const s=contributionState(),token=++s.token;
 s.requested=true;s.loading=true;s.error='';s.page=Math.max(1,Number(page)||1);s.data=null;renderContributions();
 try{
  const data=await requestAPI(`/api/me/contributions?page=${s.page}&pageSize=20`);
  if(work.contribution!==s||String(server.user.id)!==s.user||token!==s.token)return false;
  if(!contributionVisible()){s.requested=false;return false;}
  s.data=data;s.page=data.page;return true;
 }catch(error){
  if(work.contribution!==s||String(server.user.id)!==s.user||token!==s.token)return false;
  if(!contributionVisible()){s.requested=false;return false;}
  s.error=error.status?error.message:'기여도 내역을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.';return false;
 }finally{
  if(work.contribution===s&&token===s.token){s.loading=false;renderContributions();}
 }
}
function openContributions(){
 work.tab='contributions';
 // Mark before navigating: rendering the new tab must not start a second request.
 contributionState().requested=true;
 if(state.route!=='manage')navigate('manage');
 return loadContributions(1);
}
function contributionPanel(){
 const s=contributionState(),data=s.data,n=value=>Math.max(0,Number(value)||0).toLocaleString('ko-KR');
 const heading=`<header class="ws-contribution-head"><div><h2>내 기여도</h2><p>내가 나눈 도구가 동료들의 업무에 얼마나 쓰였는지 확인해 보세요.</p></div>${button('contribution-refresh',icon('refresh-cw')+' 새로고침','sq-secondary',s.loading?'disabled':'')}</header>`;
 let body;
 if(s.error)body=`<div class="ws-contribution-empty is-error" role="alert">${icon('circle-alert')}<strong>내역을 확인하지 못했어요.</strong><p>${esc(s.error)}</p>${button('contribution-retry','다시 시도','sq-secondary')}</div>`;
 else if(!data)body=`<div class="ws-contribution-empty" role="status">${icon('chart-no-axes-combined')}<strong>기여도 내역을 불러오고 있어요.</strong><p>등록한 도구와 동료들의 반응을 모아 확인합니다.</p></div>`;
 else{
  const summary=data.summary,weights=data.weights;
  const metrics=[['registered','등록한 도구','개','package'],['likes','받은 좋아요','개','heart'],['downloads','다운로드 수','회','download']];
  body=`<div class="ws-contribution-overview"><div class="ws-contribution-total"><span>전체 기여도</span><strong>${n(summary.score)}<small>점</small></strong><p>전체 기간 기준</p></div><div class="ws-contribution-metrics">${metrics.map(([key,label,unit,symbol])=>`<div><span>${icon(symbol)}${label}</span><strong>${n(summary[key])}<small>${unit}</small></strong><p>${n(summary[key])} × ${n(weights[key])}점 <b>${n(summary[key]*weights[key])}점</b></p></div>`).join('')}</div></div><div class="ws-contribution-retention">${icon('history')}<p>도구를 삭제해도 기여도는 유지됩니다. 영구 삭제한 도구는 삭제 시점의 점수를 보관합니다.</p></div>`;
  if(!data.totalItems)body+=`<div class="ws-contribution-empty">${icon('package-open')}<strong>아직 등록한 도구가 없습니다.</strong><p>도구를 공유하면 등록 점수와 동료들의 반응을 여기서 확인할 수 있어요.</p>${button('register','첫 도구 등록하기','sq-primary')}</div>`;
  else{
   const statuses={active:'사용 중',trash:'휴지통',deleted:'삭제됨'};
   const cell=(row,key)=>`<td><strong>${n(row[key]*weights[key])}<small>점</small></strong><span>${n(row[key])}${key==='registered'?'개':key==='likes'?'개':'회'} × ${n(weights[key])}점</span></td>`;
   body+=`<div class="ws-contribution-table-head"><h3>도구별 점수</h3><span>총 ${n(data.totalItems)}개</span></div><div class="ws-contribution-table-wrap" role="region" aria-label="도구별 기여도" tabindex="0"><table class="ws-contribution-table"><caption class="ws-activity-sr">내가 등록한 도구별 등록 점수, 받은 좋아요 점수, 다운로드 수 점수와 합계</caption><thead><tr><th scope="col">도구</th><th scope="col">상태</th><th scope="col">등록</th><th scope="col">좋아요</th><th scope="col">다운로드</th><th scope="col">합계</th></tr></thead><tbody>${data.items.map(row=>`<tr><th scope="row"><strong title="${esc(row.name)}">${esc(row.name)}</strong><span>도구 #${esc(row.id)}${row.status==='deleted'?' / 삭제 시점의 점수':''}</span></th><td><span class="ws-contribution-status" data-status="${esc(row.status)}">${statuses[row.status]||'확인 중'}</span></td>${cell(row,'registered')}${cell(row,'likes')}${cell(row,'downloads')}<td class="ws-contribution-row-total"><strong>${n(row.score)}<small>점</small></strong></td></tr>`).join('')}</tbody></table></div><footer class="ws-contribution-pagination"><span>20개씩 표시</span><nav aria-label="기여도 내역 페이지">${button('contribution-previous','이전','sq-secondary',data.page<=1?'disabled':'')}<span>${n(data.page)} / ${n(data.totalPages)}</span>${button('contribution-next','다음','sq-secondary',data.page>=data.totalPages?'disabled':'')}</nav></footer>`;
  }
  body+=`<details class="ws-contribution-rules"><summary>점수는 어떻게 계산하나요?${icon('chevron-down')}</summary><ul><li>도구 1개당 ${n(weights.registered)}점입니다. 새 버전을 올려도 등록 점수가 중복되지 않습니다.</li><li>받은 좋아요 1개당 ${n(weights.likes)}점, 같은 동료가 같은 도구를 처음 내려받으면 ${n(weights.downloads)}점입니다.</li><li>내 도구에 대한 내 반응, 반복 다운로드와 업데이트는 점수에 포함하지 않습니다. 사용 중인 도구의 좋아요를 취소하면 해당 점수는 빠집니다.</li><li>휴지통에 있는 도구와 삭제된 도구도 합산합니다. 이 기능 적용 전에 영구 삭제되어 기록이 남아 있지 않은 도구는 복구할 수 없습니다.</li></ul></details>`;
 }
 return `<section class="ws-contribution" aria-label="내 기여도 내역" aria-busy="${s.loading}">${heading}${body}</section>`;
}
actions['contribution-open']=()=>openContributions();
actions['contribution-refresh']=()=>{const s=contributionState();if(!s.loading)return loadContributions(1);};
actions['contribution-retry']=()=>{const s=contributionState();if(!s.loading)return loadContributions(s.page);};
actions['contribution-previous']=()=>{const s=contributionState();if(!s.loading&&s.data&&s.page>1)return loadContributions(s.page-1);};
actions['contribution-next']=()=>{const s=contributionState();if(!s.loading&&s.data&&s.page<s.data.totalPages)return loadContributions(s.page+1);};
