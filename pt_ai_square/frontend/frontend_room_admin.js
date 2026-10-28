// 관리자 몰입룸 예약: 상태 변경은 기존 예약 API와 revision 검사를 사용합니다.
function adminRoomState(){
 const user=String(server.user.id);
 if(!work.adminRoom||work.adminRoom.user!==user)work.adminRoom={user,filter:'pending',page:1,token:0,requested:false,loading:false,data:null,error:'',busy:false,notice:''};
 return work.adminRoom;
}
function adminRoomVisible(){return state.route==='admin'&&work.tab==='room-admin'&&server.user.role==='admin';}
function adminRoomRender(){if(adminRoomVisible())renderWorkspace();}
function ensureAdminRoom(){const s=adminRoomState();if(!s.requested){s.requested=true;void loadAdminRoom(1);}}
async function loadAdminRoom(page=1){
 const s=adminRoomState(),token=++s.token,filter=s.filter;
 s.requested=true;s.loading=true;s.error='';s.page=Math.max(1,Number(page)||1);adminRoomRender();
 try{
  const data=await requestAPI(`/api/immersion-room/admin/reservations?status=${filter}&page=${s.page}&pageSize=20`);
  if(work.adminRoom!==s||String(server.user.id)!==s.user||s.token!==token||!adminRoomVisible())return false;
  s.data=data;s.page=data.page;return true;
 }catch(error){
  if(work.adminRoom===s&&s.token===token&&adminRoomVisible()){s.error=error.status?error.message:'예약 신청 내역을 불러오지 못했습니다. 다시 시도해 주세요.';s.data=null;}
  return false;
 }finally{if(work.adminRoom===s&&s.token===token){s.loading=false;adminRoomRender();}}
}
function openAdminRoom(){
 if(server.user.role!=='admin')return;
 work.tab='room-admin';const s=adminRoomState();s.requested=true;
 if(state.route!=='admin')navigate('admin');return loadAdminRoom(1);
}
function adminRoomPanel(){
 const s=adminRoomState(),data=s.data;
 const heading=`<header class="room-admin-head"><div><h2>몰입룸 신청 관리</h2><p>신청 내용을 확인하고 예약을 승인하거나 반려할 수 있습니다.</p></div>${button('room-admin-refresh',icon('refresh-cw')+' 새로고침','sq-secondary',s.loading?'disabled':'')}</header>`;
 const filters=`<div class="room-admin-toolbar"><div class="ws-segment" aria-label="신청 상태">${[['pending','승인 대기'],['history','처리 내역'],['all','전체']].map(([value,label])=>button('room-admin-filter',label,'',`data-filter="${value}" aria-pressed="${s.filter===value}"`)).join('')}</div>${data?`<span>총 ${Number(data.total)||0}건</span>`:''}</div>`;
 let body='';
 if(s.notice)body+=`<p class="room-admin-notice" role="status">${esc(s.notice)}</p>`;
 if(s.error)body+=`<div class="room-admin-empty" role="alert"><strong>내역을 불러오지 못했어요.</strong><p>${esc(s.error)}</p>${button('room-admin-refresh','다시 시도','sq-secondary')}</div>`;
 else if(s.loading&&!data)body+='<div class="room-admin-empty" role="status">신청 내역을 불러오고 있습니다.</div>';
 else if(!data||!data.reservations.length)body+=`<div class="room-admin-empty"><strong>${s.filter==='pending'?'승인 대기 중인 신청이 없습니다.':'표시할 신청 내역이 없습니다.'}</strong><p>새로운 신청이 접수되면 여기에서 확인할 수 있습니다.</p></div>`;
 else{
  body+=`<div class="room-admin-list" aria-busy="${s.loading}">${data.reservations.map(r=>`<article class="room-admin-row"><div class="room-admin-row-main"><div class="room-admin-row-title"><strong>${esc(r.title)}</strong>${roomPill(r)}</div><p>${esc(roomPeriod(r))} / ${esc(roomSlots[r.slot]||'')} <span aria-hidden="true">·</span> ${esc(r.owner.name)}${r.owner.org?' / '+esc(r.owner.org):''}</p><p class="room-admin-purpose">${esc(r.purpose)}</p></div>${button('room-admin-detail','상세 보기','sq-secondary',`data-id="${esc(r.id)}"`)}</article>`).join('')}</div><footer class="room-admin-pages"><span>20개씩 표시</span><nav aria-label="몰입룸 신청 페이지">${button('room-admin-prev','이전','sq-secondary',s.page<=1||s.loading?'disabled':'')}<span>${Number(data.page)||1} / ${Number(data.totalPages)||1}</span>${button('room-admin-next','다음','sq-secondary',s.page>=data.totalPages||s.loading?'disabled':'')}</nav></footer>`;
 }
 return `<section class="room-admin" aria-label="몰입룸 신청 관리">${heading}${filters}${body}</section>`;
}
function openAdminRoomDetail(id){
 const s=adminRoomState(),row=s.data?.reservations.find(x=>String(x.id)===String(id));if(!row)return;
 s.detail=row;s.detailReason='';s.detailError='';renderAdminRoomDetail();
}
function renderAdminRoomDetail(){
 const s=adminRoomState(),r=s.detail;if(!r)return;
 openModal(r.title,'AI 몰입룸 신청',`<section class="ir-detail room-admin-detail">${roomPill(r)}<dl><div><dt>이용 기간</dt><dd>${esc(roomPeriod(r))}</dd></div><div><dt>이용 시간</dt><dd>${esc(roomSlots[r.slot]||'')}</dd></div><div><dt>신청자</dt><dd>${esc(r.owner.name)}<small>${esc(r.owner.org||'')}</small></dd></div></dl><div class="ir-purpose"><h3>이용 목적</h3><p>${esc(r.purpose)}</p></div>${r.reason?`<div class="ir-decision-reason"><h3>처리 사유</h3><p>${esc(r.reason)}</p></div>`:''}${r.canApprove||r.canReject||r.canCancel?`<label class="ir-field"><span>처리 사유 (선택)</span><textarea id="room-admin-reason" maxlength="500" rows="2" placeholder="신청자에게 전달할 내용을 적어주세요." ${s.busy?'disabled':''}>${esc(s.detailReason)}</textarea></label>`:''}${s.detailError?`<p class="ir-form-error" role="alert">${esc(s.detailError)}</p>`:''}<div class="ir-detail-actions">${r.canCancel?button('room-admin-cancel','예약 삭제','sq-secondary ws-danger',s.busy?'disabled':''):''}${r.canReject?button('room-admin-reject','반려','sq-secondary',s.busy?'disabled':''):''}${r.canApprove?button('room-admin-approve','승인','sq-primary',s.busy?'disabled':''):''}</div>${r.canCancel?'<p class="room-admin-detail-note">예약 삭제 시 해당 시간이 비워지며 처리 내역은 보관됩니다.</p>':''}</section>`);
 s.detailToken=runtime.detailLoadToken;
}
function confirmAdminRoomDecision(status){
 const s=adminRoomState(),r=s.detail;if(!r||s.busy||!adminRoomVisible()||(status==='approved'&&!r.canApprove)||(status==='rejected'&&!r.canReject)||(status==='cancelled'&&!r.canCancel))return;
 const reason=$('#room-admin-reason')?.value||'';s.detailReason=reason;
 if(reason.length>500){s.detailError='처리 사유는 500자 이내로 입력해 주세요.';renderAdminRoomDetail();return;}
 const label={approved:'승인',rejected:'반려',cancelled:'예약 삭제'}[status];
 const copy=status==='cancelled'?'예약 시간이 비워지고 신청 내역에는 취소로 남습니다.':'신청자에게 처리 결과가 전달됩니다.';
 ask(`${label}할까요?`,copy,()=>commitAdminRoomDecision(status,r.id,r.revision,reason),label);
}
async function commitAdminRoomDecision(status,id,revision,reason){
 const s=adminRoomState(),token=s.detailToken;if(s.busy||!adminRoomVisible())return;
 s.busy=true;s.detailError='';
 $('#sq-dialog-body')?.querySelectorAll('.ir-detail-actions button').forEach(b=>b.disabled=true);
 try{
  const result=await requestAPI('/api/immersion-room/reservations/'+encodeURIComponent(id),'PATCH',{status,expectedRevision:revision,reason});
  if(work.adminRoom!==s||String(server.user.id)!==s.user)return;
  s.notice=`${roomStatuses[result.reservation.status]||'처리'}되었습니다.`;
  if(runtime.detailLoadToken===token&&$('#sq-dialog')?.open)closeModal();
  s.data=null;const loaded=await loadAdminRoom(s.page);
  if(!loaded&&adminRoomVisible())s.notice+=' 처리 결과는 저장되었지만 목록을 새로 불러오지 못했습니다.';
 }catch(error){
  if(work.adminRoom===s&&adminRoomVisible()&&runtime.detailLoadToken===token&&$('#sq-dialog')?.open){s.detailError=error.status?error.message:'처리 결과를 확인하지 못했습니다. 목록을 새로고침해 주세요.';s.busy=false;renderAdminRoomDetail();}
 }finally{if(work.adminRoom===s){s.busy=false;adminRoomRender();}}
}
let roomNotificationGeneration=0;
async function openRoomNotification(target,generation=++roomNotificationGeneration){
 const id=String(target.id||'');if(!id||generation!==roomNotificationGeneration)return;
 closeModal();const s=roomState(),user=s.user;
 if(roomDate(target.startDate)){s.month=target.startDate.slice(0,7);s.selectionAnchor=target.startDate;s.draft.startDate=target.startDate;s.draft.endDate=target.startDate;}
 navigate('immersion-room');
 const viewToken=runtime.detailLoadToken,month=s.month;
 const calendar=loadImmersionRoom(),calendarToken=s.loadToken;
 const [,detail]=await Promise.allSettled([calendar,requestAPI('/api/immersion-room/reservations/'+encodeURIComponent(id),'GET',undefined,{timeoutMs:10000})]);
 if(generation!==roomNotificationGeneration||viewToken!==runtime.detailLoadToken||!roomCurrent(s)||user!==String(server.user.id)||!roomVisible()||s.month!==month||s.loadToken!==calendarToken)return;
 if(detail.status==='fulfilled'&&detail.value.reservation){const row=detail.value.reservation;const index=s.reservations.findIndex(r=>r.id===row.id);if(index<0)s.reservations.push(row);else s.reservations[index]=row;openRoomDetail(row.id);}
 else{s.error='예약 상세를 불러오지 못했습니다. 달력에서 다시 확인해 주세요.';roomRender();}
}
Object.assign(actions,{
 'room-admin-refresh':()=>{const s=adminRoomState();if(!s.loading){s.notice='';return loadAdminRoom(s.page);}},
 'room-admin-filter':b=>{const s=adminRoomState();if(!['pending','history','all'].includes(b.dataset.filter))return;s.filter=b.dataset.filter;s.data=null;s.notice='';return loadAdminRoom(1);},
 'room-admin-prev':()=>{const s=adminRoomState();if(!s.loading&&s.page>1)return loadAdminRoom(s.page-1);},
 'room-admin-next':()=>{const s=adminRoomState();if(!s.loading&&s.data&&s.page<s.data.totalPages)return loadAdminRoom(s.page+1);},
 'room-admin-detail':b=>openAdminRoomDetail(b.dataset.id),
 'room-admin-approve':()=>confirmAdminRoomDecision('approved'),
 'room-admin-reject':()=>confirmAdminRoomDecision('rejected'),
 'room-admin-cancel':()=>confirmAdminRoomDecision('cancelled')
});
