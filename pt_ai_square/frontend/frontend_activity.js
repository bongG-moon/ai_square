function activityPanel(){
 const s=activityHistoryState(),f=s.draft,hasRows=s.ready&&s.rows.length>0;
 const start=s.page*s.limit+1,end=start+s.rows.length-1;
 const range=s.applied?`${s.applied.start.replaceAll('-','.')} — ${s.applied.end.replaceAll('-','.')}`:'최근 30일';
 const summary=s.loading?'이력을 불러오고 있습니다.':s.error?'조회 결과를 확인하지 못했습니다.':s.ready?`총 ${s.total.toLocaleString('ko-KR')}건`:'기간을 선택해 이력을 확인하세요.';
 return `<section id="ws-activity" class="ws-activity" aria-label="도구 사용 이력">
  <div class="ws-activity-head"><div><span class="ws-activity-eyebrow">ACTIVITY LOG</span><h2>도구 사용 이력</h2><p>도구 다운로드와 좋아요 활동을 기간별로 확인하세요.</p></div><div class="ws-activity-export"><div>${button('activity-refresh',icon('refresh-cw')+' 새로고침','sq-secondary',s.loading?'disabled':'')}${button('activity-export',icon('download')+(s.exporting?'파일 준비 중…':'CSV 다운로드'),'sq-secondary',s.exporting||s.loading||!s.ready||!s.total||s.error?'disabled':'')}</div><small>조회한 조건의 전체 이력 · 최대 50,000건</small></div></div>
  <form id="ws-activity-filter" class="ws-activity-filters" aria-label="사용 이력 조회 조건">
   <div class="ws-activity-presets" role="group" aria-label="조회 기간 빠른 선택">${[['7','최근 7일'],['30','최근 30일'],['90','최근 90일'],['custom','직접 선택']].map(([value,label])=>button('activity-preset',label,'',`type="button" data-period="${value}" aria-pressed="${s.preset===value}"`)).join('')}<span>한국 시간 (KST)</span></div>
   <div class="ws-activity-filter-fields"><label><span>시작일</span><input id="ws-activity-start" data-activity-filter="start" type="date" value="${esc(f.start)}" required></label><label><span>종료일</span><input id="ws-activity-end" data-activity-filter="end" type="date" value="${esc(f.end)}" required></label><label class="ws-activity-kind"><span>활동 유형</span><select id="ws-activity-kind" data-activity-filter="kind" aria-label="활동 유형">${Object.entries(activityKindLabels).map(([value,label])=>`<option value="${value}" ${f.kind===value?'selected':''}>${label}</option>`).join('')}</select></label><div class="ws-activity-filter-actions"><button type="submit" class="sq-primary">조회하기</button>${button('activity-reset','초기화','sq-link','type="button"')}</div></div>
   ${s.validation?`<p class="ws-activity-inline-error" role="alert">${esc(s.validation)}</p>`:''}
   <p id="ws-activity-draft-note" class="ws-activity-draft-note" ${activityFiltersChanged()?'':'hidden'}>조회하기를 눌러 변경한 조건을 적용하세요. CSV는 마지막으로 조회한 조건으로 저장됩니다.</p>
  </form>
  <div class="ws-activity-result-head"><div><strong role="status" aria-live="polite">${esc(summary)}</strong>${s.ready&&!s.loading&&!s.error?`<span>${esc(range)} · ${esc(activityKindLabels[s.applied.kind])}</span>`:''}</div><label class="ws-activity-page-size"><span>페이지당</span><select data-activity-filter="limit" aria-label="페이지당 이력 수">${[25,50,100].map(n=>`<option value="${n}" ${s.limit===n?'selected':''}>${n}개</option>`).join('')}</select></label></div>
  <div class="ws-activity-table-wrap" tabindex="0" role="region" aria-label="사용 이력 표, 가로로 스크롤할 수 있습니다" aria-busy="${s.loading}"><table class="ws-activity-table"><caption class="ws-activity-sr">한국 시간 기준 도구 사용 이력, 최신순</caption><colgroup><col class="activity-time"><col class="activity-kind"><col class="activity-tool"><col class="activity-user"><col class="activity-channel"><col class="activity-result"></colgroup><thead><tr><th scope="col">일시 <span>KST</span></th><th scope="col">활동</th><th scope="col">도구 / 버전</th><th scope="col">사용자</th><th scope="col">이용 경로</th><th scope="col">기록 구분</th></tr></thead><tbody>${s.loading?Array.from({length:6},()=>'<tr class="ws-activity-skeleton" aria-hidden="true">'+Array.from({length:6},()=>'<td><span></span></td>').join('')+'</tr>').join(''):s.error?`<tr><td colspan="6"><div class="ws-activity-empty is-error">${icon('circle-alert')}<strong>이력을 불러오지 못했습니다.</strong><p role="alert">${esc(s.error)}</p>${button('activity-retry','다시 시도','sq-secondary')}</div></td></tr>`:hasRows?s.rows.map(activityHistoryRow).join(''):`<tr><td colspan="6"><div class="ws-activity-empty">${icon('list-filter')}<strong>${s.ready?'선택한 조건의 이력이 없습니다.':'사용 이력을 확인해 보세요.'}</strong><p>기간을 넓히거나 활동 유형을 변경해 보세요.</p></div></td></tr>`}</tbody></table></div>
  <div class="ws-activity-pagination"><span>${hasRows&&!s.loading&&!s.error?`${start.toLocaleString('ko-KR')}–${end.toLocaleString('ko-KR')} / ${s.total.toLocaleString('ko-KR')}건`:'한 페이지씩 표시합니다.'}</span><nav aria-label="사용 이력 페이지">${button('activity-previous',icon('chevron-left')+' 이전','sq-secondary',s.loading||s.error||!s.ready||s.page===0?'disabled':'')}<span>${s.page+1} 페이지</span>${button('activity-next','다음 '+icon('chevron-right'),'sq-secondary',s.loading||s.error||!s.ready||!s.nextCursor?'disabled':'')}</nav></div>
  ${s.exportError?`<p class="ws-activity-inline-error" role="alert">${esc(s.exportError)}</p>`:''}${s.exportNotice?`<p class="ws-activity-export-notice" role="status">${esc(s.exportNotice)}</p>`:''}
  <details class="ws-activity-explainer"><summary>${icon('info')}기록과 순위 집계의 차이${icon('chevron-down')}</summary><p>반복 다운로드와 업데이트도 이력에 남습니다. 다운로드 순위는 같은 사용자·도구의 최초 다운로드만 반영하며, 업데이트는 제외합니다. 좋아요 취소는 현재 좋아요 수에서 빠집니다. 이전 자료는 당시 남아 있던 집계 정보만 포함하며, 기록에 없는 이용 경로는 ‘—’로 표시합니다.</p></details>
 </section>`;
}

const activityKindLabels={all:'모든 활동',download:'다운로드',like:'좋아요',unlike:'좋아요 취소'};
let activityHistory=null;
function activityDateRange(days=30){
 const today=new Date(Date.now()+9*60*60*1000).toISOString().slice(0,10);
 return {start:new Date(Date.parse(today+'T00:00:00Z')-(days-1)*86400000).toISOString().slice(0,10),end:today,kind:'all'};
}
function activityHistoryState(){
 if(!activityHistory)activityHistory={draft:activityDateRange(),preset:'30',applied:null,rows:[],total:0,limit:25,page:0,cursors:[null],nextCursor:null,sequence:0,loading:false,ready:false,error:'',validation:'',exporting:false,exportError:'',exportNotice:''};
 return activityHistory;
}
function activityHistoryVisible(){return state.route==='admin'&&work.tab==='activity'&&server.user.role==='admin';}
function activityFiltersChanged(){const s=activityHistoryState();return !!s.applied&&['start','end','kind'].some(key=>s.draft[key]!==s.applied[key]);}
function renderActivityHistory(){
 if(!activityHistoryVisible())return;
 const panel=$('#ws-activity');
 if(panel){
  const active=document.activeElement,inside=panel.contains?.(active),control=active?.classList?.contains('ws-select')?active.previousElementSibling:active;
  const focusId=inside&&/^[a-z0-9-]+$/.test(control?.id||'')?control.id:null,action=inside&&/^[a-z0-9-]+$/.test(control?.dataset?.action||'')?control.dataset.action:null,period=control?.dataset?.period;
  panel.outerHTML=activityPanel();mountIcons();enhanceSelects();
  if(inside){let target=focusId?$('#'+focusId):action?$(`[data-action="${action}"]${['7','30','90','custom'].includes(period)?`[data-period="${period}"]`:''}`):null;if(target?.classList?.contains('ws-native'))target=target.nextElementSibling;if(!target||target.disabled)target=$('.ws-activity-table-wrap');target?.focus?.({preventScroll:true});}
 }
 else renderWorkspace();
}
function activityHistoryRow(e){
 const date=new Date(e.created*1000),valid=Number.isFinite(date.getTime());
 const dateText=valid?date.toLocaleDateString('ko-KR',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}):'—';
 const timeText=valid?date.toLocaleTimeString('ko-KR',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}):'';
 const kind=['like','unlike','download'].includes(e.kind)?e.kind:'unknown';
 const note=e.imported?'기존 집계 이전':e.kind==='download'?(e.counted?'최초 다운로드':'반복 / 업데이트'):e.kind==='unlike'?'좋아요 취소':'좋아요 추가';
 const channel=e.channel==='api'?'API 연결':e.channel==='web'?'웹':'—';
 return `<tr><td><time ${valid?`datetime="${date.toISOString()}"`:''}>${esc(dateText)}<small>${esc(timeText)}</small></time></td><td><span class="ws-activity-kind-badge" data-kind="${kind}">${icon(kind==='download'?'download':kind==='unlike'?'heart-off':'heart')}${esc(activityKindLabels[kind]||e.kind)}</span></td><td><strong class="ws-activity-tool-name" title="${esc(e.toolName)}">${esc(e.toolName)}</strong><small>${e.version?`v${esc(e.version)} · `:''}도구 #${esc(e.tool)}</small></td><td><strong class="ws-activity-user-name" title="${esc(e.userName)}">${esc(e.userName)}</strong><small>${esc(e.user)}</small></td><td><span class="ws-activity-channel" ${channel==='—'?'title="기존 기록에 이용 경로가 없습니다."':''}>${channel}</span></td><td><span class="ws-activity-note">${esc(note)}</span></td></tr>`;
}
function validActivityDate(value){return /^\d{4}-\d{2}-\d{2}$/.test(value)&&Number.isFinite(Date.parse(value+'T00:00:00Z'))&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;}
function validateActivityFilters(filters){
 if(!validActivityDate(filters.start)||!validActivityDate(filters.end))return '시작일과 종료일을 올바르게 입력해 주세요.';
 if(filters.start>filters.end)return '종료일은 시작일과 같거나 이후여야 합니다.';
 if(!Object.hasOwn(activityKindLabels,filters.kind))return '활동 유형을 다시 선택해 주세요.';
 return '';
}
function activityQuery(filters,limit,before){
 const query=new URLSearchParams({start:filters.start,end:filters.end,kind:filters.kind});
 if(limit)query.set('limit',String(limit));if(before)query.set('before',before);return query.toString();
}
async function loadActivityHistory(filters,{page=0,cursors=[null],limit=activityHistoryState().limit}={}){
 filters={...filters};
 const s=activityHistoryState(),validation=validateActivityFilters(filters);
 if(validation){s.validation=validation;renderActivityHistory();return false;}
 const sequence=++s.sequence,query={filters:{...filters},page,cursors:[...cursors],limit};
 s.lastQuery=query;s.loading=true;s.ready=false;s.rows=[];s.error='';s.validation='';s.exportError='';s.exportNotice='';renderActivityHistory();
 try{
  const result=await requestAPI('/api/activity?'+activityQuery(filters,limit,cursors[page]),'GET',undefined,{timeoutMs:20000,redirectOnAuth:false});
  if(sequence!==s.sequence||!activityHistoryVisible())return false;
  s.rows=Array.isArray(result.events)?result.events:[];s.total=Number.isFinite(result.total)?result.total:s.rows.length;s.applied={...filters};s.limit=limit;s.page=page;s.cursors=[...cursors];s.nextCursor=result.nextCursor||null;s.ready=true;
  return true;
 }catch(error){if(sequence===s.sequence&&activityHistoryVisible())s.error=error.message||'서버 연결을 확인한 뒤 다시 시도해 주세요.';return false;}
 finally{if(sequence===s.sequence){s.loading=false;renderActivityHistory();}}
}
function openActivityHistory(){
 const s=activityHistoryState();return loadActivityHistory(s.applied||s.draft);
}
function applyActivityFilters(){const s=activityHistoryState();return loadActivityHistory({...s.draft});}
actions['activity-preset']=b=>{
 const s=activityHistoryState(),period=b.dataset.period;if(!['7','30','90','custom'].includes(period))return;
 s.preset=period;s.validation='';if(period!=='custom')s.draft={...activityDateRange(Number(period)),kind:s.draft.kind};renderActivityHistory();if(period==='custom')$('#ws-activity-start')?.focus();
};
actions['activity-reset']=()=>{const s=activityHistoryState();s.draft=activityDateRange();s.preset='30';return applyActivityFilters();};
actions['activity-refresh']=()=>{const s=activityHistoryState();if(s.loading)return;return loadActivityHistory(s.applied||s.draft);};
actions['activity-next']=()=>{const s=activityHistoryState();if(s.loading||!s.ready||!s.nextCursor)return;return loadActivityHistory(s.applied,{page:s.page+1,cursors:[...s.cursors.slice(0,s.page+1),s.nextCursor]});};
actions['activity-previous']=()=>{const s=activityHistoryState();if(s.loading||!s.ready||s.page<1)return;return loadActivityHistory(s.applied,{page:s.page-1,cursors:s.cursors});};
actions['activity-retry']=()=>{const s=activityHistoryState(),q=s.lastQuery;return q?loadActivityHistory(q.filters,q):openActivityHistory();};
actions['activity-export']=async()=>{
 const s=activityHistoryState();if(s.exporting||s.loading||!s.ready||s.error||!s.total||!s.applied)return;
 const filters={...s.applied};s.exporting=true;s.exportError='';s.exportNotice='';renderActivityHistory();
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),60000);
 try{
  const response=await fetch('/api/activity/export?'+activityQuery(filters),{credentials:'same-origin',cache:'no-store',redirect:'error',signal:controller.signal});
  if(!response.ok){let data;try{data=await response.json();}catch{}throw Error(data?.error||(response.status===401||response.status===403?'로그인 상태와 관리자 권한을 확인해 주세요.':'이력 파일을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.'));}
  if(!(response.headers.get('Content-Type')||'').toLowerCase().startsWith('text/csv'))throw Error('CSV 파일 대신 다른 응답을 받았습니다. 로그인 상태를 확인해 주세요.');
  const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');
  try{link.href=url;link.download=`activity-${filters.start.replaceAll('-','')}-${filters.end.replaceAll('-','')}.csv`;document.body.append(link);link.click();}finally{link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  s.exportNotice=`${filters.start} ~ ${filters.end} · ${activityKindLabels[filters.kind]} 전체 이력 파일을 준비했습니다.`;
 }catch(error){const message=['TypeError','AbortError'].includes(error?.name)?'파일을 받지 못했습니다. 연결 상태를 확인하거나 조회 기간을 줄인 뒤 다시 시도해 주세요.':error.message;s.exportError=`${filters.start} ~ ${filters.end} · ${message}`;}
 finally{clearTimeout(timer);s.exporting=false;renderActivityHistory();}
};
root.addEventListener('submit',e=>{if(e.target.id!=='ws-activity-filter')return;e.preventDefault();e.stopImmediatePropagation();void applyActivityFilters();},true);
root.addEventListener('change',e=>{
 const field=e.target.dataset?.activityFilter;if(!field)return;const s=activityHistoryState();
 if(field==='limit'){const limit=Number(e.target.value);if([25,50,100].includes(limit))void loadActivityHistory(s.applied||s.draft,{limit});return;}
 if(['start','end','kind'].includes(field)){s.draft[field]=e.target.value;s.validation='';if(field!=='kind'){s.preset='custom';$$('[data-action="activity-preset"]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.period==='custom')));}const note=$('#ws-activity-draft-note');if(note)note.hidden=!activityFiltersChanged();}
});
