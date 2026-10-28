// AI 몰입룸: dates are civil dates in Korea, never the browser's local timezone.
const roomSlots={all:'종일',am:'오전',pm:'오후'};
const roomStatuses={pending:'승인 대기',approved:'예약 확정',rejected:'반려',cancelled:'취소'};
function roomToday(){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()).filter(p=>['year','month','day'].includes(p.type)).reduce((parts,p)=>({...parts,[p.type]:p.value}),{});}
function roomTodayString(){const d=roomToday();return `${d.year}-${d.month}-${d.day}`;}
function roomDate(value){if(!/^\d{4}-\d{2}-\d{2}$/.test(value||''))return null;const d=new Date(value+'T00:00:00Z');return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===value?d:null;}
function roomAddDays(value,days){const d=roomDate(value);if(!d)return '';d.setUTCDate(d.getUTCDate()+days);return d.toISOString().slice(0,10);}
function roomBounds(month){const first=roomDate(month+'-01');const start=roomAddDays(month+'-01',-first.getUTCDay());return {start,end:roomAddDays(start,41)};}
function roomMonthLabel(month){const [y,m]=month.split('-');return `${y}년 ${Number(m)}월`;}
function roomPeriod(row){return row.startDate===row.endDate?row.startDate:`${row.startDate} ~ ${row.endDate}`;}
function roomState(){
 const user=String(server.user.id);
 if(!work.immersionRoom||work.immersionRoom.user!==user){const today=roomTodayString();work.immersionRoom={user,today,month:today.slice(0,7),loadToken:0,mutation:0,loading:false,loadedMonth:null,reservations:[],holidays:[],sources:[],holidayNotice:'',error:'',notice:'',saving:false,patching:false,draft:{startDate:today,endDate:today,slot:'all',title:'',purpose:''},attempt:null,formError:'',selectionAnchor:today,detailId:null};}
 return work.immersionRoom;
}
function roomCurrent(s){return work.immersionRoom===s&&String(server.user.id)===s.user;}
function roomVisible(){return state.route==='immersion-room';}
function roomRender(){if(roomVisible())renderImmersionRoom();}
async function loadImmersionRoom(){
 const s=roomState(),token=++s.loadToken,month=s.month,mutation=s.mutation,{start,end}=roomBounds(month);
 s.loading=true;s.error='';roomRender();
 const query=`?start=${start}&end=${end}`;
 const [reservations,holidays]=await Promise.allSettled([requestAPI('/api/immersion-room'+query,'GET',undefined,{timeoutMs:10000}),requestAPI('/api/immersion-room/holidays'+query,'GET',undefined,{timeoutMs:10000})]);
 if(!roomCurrent(s)||token!==s.loadToken||month!==s.month||mutation!==s.mutation)return false;
 s.loading=false;
 if(reservations.status==='fulfilled'){
  const data=reservations.value;s.reservations=data.reservations;s.loadedMonth=month;s.canManage=data.canManage;s.historyTruncated=data.historyTruncated===true;
  if(roomDate(data.today))s.today=data.today;
 }else{s.error='예약 현황을 불러오지 못했습니다. 새로고침으로 다시 확인해 주세요.';}
 if(holidays.status==='fulfilled'){s.holidays=holidays.value.holidays||[];s.holidayNotice=holidays.value.notice||'';s.sources=holidays.value.sources||[];s.coverage=holidays.value.coverage;}
 else{s.holidays=[];s.sources=[];s.holidayNotice='공휴일 정보를 불러오지 못했습니다. 예약 현황은 그대로 확인할 수 있습니다.';}
 roomRender();return reservations.status==='fulfilled';
}
function openImmersionRoom(){closeModal();const s=roomState();s.error='';navigate('immersion-room');return loadImmersionRoom();}
function roomSetMonth(offset){const s=roomState(),d=roomDate(s.month+'-01');d.setUTCMonth(d.getUTCMonth()+offset);s.month=d.toISOString().slice(0,7);s.reservations=[];s.holidays=[];s.loadedMonth=null;s.notice='';return loadImmersionRoom();}
function roomSelect(start,end=start){const s=roomState();if(s.saving)return;if(!roomDate(start)||!roomDate(end))return;[start,end]=[start,end].sort();s.draft.startDate=start;s.draft.endDate=end;s.formError='';roomRender();}
function roomActive(row){return row.status==='pending'||row.status==='approved';}
function roomPill(row){return `<span class="ir-status" data-status="${esc(row.status)}">${esc(roomStatuses[row.status]||row.status)}</span>`;}
function roomCalendar(s){
 const {start}=roomBounds(s.month),holidays=new Map(s.holidays.map(h=>[h.date,h.name]));
 let weeks='';
 for(let week=0;week<6;week++){
  let cells='';
  for(let weekday=0;weekday<7;weekday++){
   const date=roomAddDays(start,week*7+weekday),other=date.slice(0,7)!==s.month,selected=date>=s.draft.startDate&&date<=s.draft.endDate,holiday=holidays.get(date),rows=s.reservations.filter(r=>roomActive(r)&&r.startDate<=date&&r.endDate>=date);
   cells+=`<div class="ir-day${other?' is-outside':''}${selected?' is-selected':''}${date===s.today?' is-today':''}" role="gridcell" data-room-date="${date}" data-weekday="${weekday}"${holiday?' data-holiday="true"':''}><button type="button" class="ir-date" data-action="room-day" data-date="${date}" aria-label="${date}${holiday?' '+esc(holiday):''} 선택" aria-pressed="${selected}"${date===s.today?' aria-current="date"':''}><span>${Number(date.slice(-2))}</span>${holiday?`<small title="${esc(holiday)}">${esc(holiday)}</small>`:''}</button><div class="ir-day-bookings">${rows.map(row=>`<button type="button" class="ir-booking" data-action="room-detail" data-id="${esc(row.id)}" data-status="${esc(row.status)}" title="${esc(row.title)} / ${roomSlots[row.slot]} / ${roomStatuses[row.status]}" aria-label="${esc(row.title)}, ${roomSlots[row.slot]}, ${roomStatuses[row.status]}"><span>${roomSlots[row.slot]}</span><strong>${esc(row.title)}</strong></button>`).join('')}</div></div>`;
  }
  weeks+=`<div class="ir-week" role="row">${cells}</div>`;
 }
 return `<div class="ir-calendar" role="grid" aria-label="${roomMonthLabel(s.month)} 예약 달력" aria-busy="${s.loading}"><div class="ir-weekdays" role="row">${['일','월','화','수','목','금','토'].map((day,i)=>`<span role="columnheader" data-weekday="${i}">${day}</span>`).join('')}</div>${weeks}</div>`;
}
function roomRequestForm(s){const d=s.draft,disabled=s.saving?'disabled':'';return `<aside class="ir-request"><div class="ir-section-label">나의 몰입 시간</div><h2>${s.canManage?'예약 등록':'예약 신청'}</h2><p class="ir-help">달력에서 날짜나 기간을 선택하거나 직접 입력하세요.</p><form id="ir-request-form"><fieldset ${disabled}><div class="ir-date-fields"><label><span>시작일</span><input type="date" name="startDate" min="${s.today}" value="${esc(d.startDate)}" required></label><label><span>종료일</span><input type="date" name="endDate" min="${esc(d.startDate||s.today)}" value="${esc(d.endDate)}" required></label></div><div class="ir-slot-field"><span>이용 시간</span><div class="ir-slot-options">${Object.entries(roomSlots).map(([value,label])=>`<label><input type="radio" name="slot" value="${value}" ${d.slot===value?'checked':''}><span>${label}</span></label>`).join('')}</div></div><label class="ir-field"><span>예약 제목</span><input name="title" value="${esc(d.title)}" required maxlength="100" placeholder="예: 보고서 자동화 과제 개발"></label><label class="ir-field"><span>이용 목적</span><textarea name="purpose" rows="3" required maxlength="2000" placeholder="어떤 과제나 교육을 진행할 예정인가요?">${esc(d.purpose)}</textarea></label></fieldset>${s.formError?`<p class="ir-form-error" role="alert">${esc(s.formError)}</p>`:''}<button class="sq-primary ir-submit" type="submit" ${disabled||s.loading||s.loadedMonth!==s.month?'disabled':''}>${s.saving?'예약 저장 중…':s.canManage?'예약 등록':'예약 신청'}</button><p class="ir-form-note">${s.canManage?'관리자가 등록한 예약은 바로 확정됩니다.':'신청 후 관리자가 승인하면 예약이 확정됩니다.'} 승인 대기 중인 시간도 다른 예약과 겹칠 수 없습니다.</p></form></aside>`;}
function roomSelectionSummary(s){const selected=s.reservations.filter(r=>roomActive(r)&&r.startDate<=s.draft.endDate&&r.endDate>=s.draft.startDate);return `<section class="ir-selection-summary"><h3>선택한 기간의 예약 <small>${selected.length}건</small></h3>${selected.length?`<div class="ir-summary-list">${selected.map(row=>`<button type="button" data-action="room-detail" data-id="${esc(row.id)}" class="ir-summary-row"><span><strong>${esc(row.title)}</strong><small>${esc(roomPeriod(row))} / ${roomSlots[row.slot]} / ${esc(row.owner.name)}</small></span>${roomPill(row)}${icon('chevron-right')}</button>`).join('')}</div>`:'<p>선택한 기간에 등록된 예약이 없습니다.</p>'}</section>`;}
function renderImmersionRoom(){
 const s=roomState(),inactive=s.reservations.filter(r=>!roomActive(r));
 workspace.innerHTML=`${s.notice?`<p class="ir-notice" role="status">${icon('check-circle-2')}${esc(s.notice)}</p>`:''}<div class="ir-layout"><section class="ir-calendar-panel"><header class="ir-calendar-head"><div><span class="ir-section-label">공간 예약</span><h2>${roomMonthLabel(s.month)}</h2></div><nav aria-label="달력 월 이동">${button('room-previous',icon('chevron-left'),'ir-icon-button','aria-label="이전 달"')}${button('room-today','오늘','ir-today')}${button('room-next',icon('chevron-right'),'ir-icon-button','aria-label="다음 달"')}${button('room-refresh',icon('refresh-cw'),'ir-icon-button',`aria-label="예약 현황 새로고침" ${s.loading?'disabled':''}`)}</nav></header><div class="ir-calendar-meta"><div class="ir-legend"><span data-status="approved">예약 확정</span><span data-status="pending">승인 대기</span></div><p>${s.loading?'예약 현황을 불러오는 중…':'날짜 선택 또는 드래그로 기간 지정'}</p></div>${s.error?`<div class="ir-load-error" role="alert"><p>${esc(s.error)}</p>${button('room-refresh','다시 시도','sq-secondary')}</div>`:''}${roomCalendar(s)}${s.holidayNotice?`<p class="ir-holiday-notice" role="status">${esc(s.holidayNotice)}</p>`:''}</section><div class="ir-sidebar">${roomRequestForm(s)}${roomSelectionSummary(s)}</div></div>${inactive.length?`<details class="ir-history"><summary>${s.canManage?'반려 및 취소 내역':'내 신청 처리 내역'}<span>${inactive.length}건${s.historyTruncated?' 이상':''}${icon('chevron-down')}</span></summary>${inactive.map(row=>`<button type="button" data-action="room-detail" data-id="${esc(row.id)}" class="ir-summary-row"><span><strong>${esc(row.title)}</strong><small>${esc(roomPeriod(row))} / ${roomSlots[row.slot]} / ${esc(row.owner.name)}</small></span>${roomPill(row)}${icon('chevron-right')}</button>`).join('')}${s.historyTruncated?'<p class="ir-help">한 번에 최근 처리 내역 100건까지 표시합니다.</p>':''}</details>`:''}`;
 mountIcons();
}
function roomUUID(){const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;const hex=Array.from(bytes,x=>x.toString(16).padStart(2,'0')).join('');return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;}
function roomDraftError(d,today){
 if(!roomDate(d.startDate)||!roomDate(d.endDate))return '시작일과 종료일을 확인해 주세요.';
 if(d.startDate<today)return '오늘 이후의 날짜를 선택해 주세요.';
 if(d.endDate<d.startDate)return '종료일은 시작일보다 빠를 수 없습니다.';
 if((roomDate(d.endDate)-roomDate(d.startDate))/86400000>=31)return '한 번에 최대 31일까지 신청할 수 있습니다.';
 if(!Object.hasOwn(roomSlots,d.slot))return '이용 시간을 선택해 주세요.';
 if(!d.title.trim()||d.title.trim().length>100)return '예약 제목을 100자 이내로 입력해 주세요.';
 if(!d.purpose.trim()||d.purpose.trim().length>2000)return '이용 목적을 2,000자 이내로 입력해 주세요.';
 return '';
}
async function submitImmersionRoom(){
 const s=roomState();if(s.saving||s.loading||s.loadedMonth!==s.month)return false;
 const d={...s.draft,title:s.draft.title.trim(),purpose:s.draft.purpose.trim()};s.formError=roomDraftError(d,s.today);if(s.formError){roomRender();return false;}
 const fingerprint=JSON.stringify(d);if(s.attempt?.fingerprint!==fingerprint)s.attempt={fingerprint,id:roomUUID()};
 s.saving=true;s.formError='';s.notice='';roomRender();
 try{
  const result=await requestAPI('/api/immersion-room/reservations','POST',{...d,clientRequestId:s.attempt.id});
  if(!roomCurrent(s))return false;
  s.mutation++;s.loadToken++;s.loading=false;s.draft.title='';s.draft.purpose='';s.attempt=null;
  s.notice=result.reservation.status==='approved'?'예약이 확정되었습니다.':result.reservation.status==='pending'?'신청이 접수되었습니다. 관리자 승인을 기다려 주세요.':`이 신청은 이미 ${roomStatuses[result.reservation.status]||'처리 완료'} 상태입니다. 달력 아래 처리 내역에서 확인해 주세요.`;
  if(roomVisible()){const loaded=await loadImmersionRoom();if(!loaded&&roomCurrent(s))s.notice+=' 예약은 저장되었지만 달력을 새로 불러오지 못했습니다.';}
  return true;
 }catch(error){if(roomCurrent(s))s.formError=error.status?error.message:'서버 응답을 확인하지 못했습니다. 같은 내용으로 다시 신청하면 중복 등록 없이 결과를 확인합니다.';return false;}
 finally{if(roomCurrent(s)){s.saving=false;roomRender();}}
}
function openRoomDetail(id){
 const s=roomState(),row=s.reservations.find(r=>String(r.id)===String(id));if(!row)return;s.detailId=row.id;s.detailError='';s.detailReason='';renderRoomDetail();
}
function renderRoomDetail(){
 const s=roomState(),row=s.reservations.find(r=>r.id===s.detailId);if(!row)return;
 openModal(row.title,'AI 몰입룸 예약',`<section class="ir-detail">${roomPill(row)}<dl><div><dt>이용 기간</dt><dd>${esc(roomPeriod(row))}</dd></div><div><dt>이용 시간</dt><dd>${roomSlots[row.slot]}</dd></div><div><dt>신청자</dt><dd>${esc(row.owner.name)}<small>${esc(row.owner.org||'')}</small></dd></div></dl><div class="ir-purpose"><h3>이용 목적</h3><p>${esc(row.purpose)}</p></div>${row.reason?`<div class="ir-decision-reason"><h3>처리 사유</h3><p>${esc(row.reason)}</p></div>`:''}${row.canApprove||row.canReject||row.canCancel?`<label class="ir-field"><span>처리 사유 (선택)</span><textarea id="ir-decision-reason" maxlength="500" rows="2" placeholder="신청자에게 전달할 내용이 있으면 적어주세요." ${s.patching?'disabled':''}>${esc(s.detailReason||'')}</textarea></label>`:''}${s.detailError?`<p class="ir-form-error" role="alert">${esc(s.detailError)}</p>`:''}<div class="ir-detail-actions">${row.canCancel?button('room-cancel','예약 취소','sq-secondary',s.patching?'disabled':''):''}${row.canReject?button('room-reject','반려','sq-secondary',s.patching?'disabled':''):''}${row.canApprove?button('room-approve','승인','sq-primary',s.patching?'disabled':''):''}</div></section>`);
 s.detailDialogToken=runtime.detailLoadToken;
}
async function changeRoomStatus(status){
 const s=roomState(),row=s.reservations.find(r=>r.id===s.detailId);
 if(!row||s.patching||(status==='approved'&&!row.canApprove)||(status==='rejected'&&!row.canReject)||(status==='cancelled'&&!row.canCancel))return false;
 const reason=$('#ir-decision-reason')?.value||'',id=row.id,token=s.detailDialogToken;s.detailReason=reason;
 if(reason.length>500){s.detailError='처리 사유는 500자 이내로 입력해 주세요.';renderRoomDetail();return false;}
 s.patching=true;s.detailError='';$('#sq-dialog-body')?.querySelectorAll('.ir-detail button').forEach(b=>b.disabled=true);
 try{
  const result=await requestAPI('/api/immersion-room/reservations/'+encodeURIComponent(id),'PATCH',{status,expectedRevision:row.revision,reason});
  if(!roomCurrent(s))return false;s.mutation++;s.loadToken++;s.loading=false;
  const index=s.reservations.findIndex(r=>r.id===id);if(index>=0)s.reservations[index]=result.reservation;
  s.notice=`예약을 ${roomStatuses[status]} 상태로 변경했습니다.`;
  if(runtime.detailLoadToken===token&&$('#sq-dialog').open)closeModal();
  if(roomVisible()){const loaded=await loadImmersionRoom();if(!loaded&&roomCurrent(s))s.notice+=' 변경은 저장되었지만 달력을 새로 불러오지 못했습니다.';}
  return true;
 }catch(error){
  if(roomCurrent(s)&&runtime.detailLoadToken===token&&$('#sq-dialog').open){s.detailError=error.status?error.message:'변경 결과를 확인하지 못했습니다. 창을 닫고 예약 현황을 새로고침해 주세요.';s.patching=false;renderRoomDetail();}
  return false;
 }finally{if(roomCurrent(s)){s.patching=false;roomRender();}}
}
Object.assign(actions,{
 'immersion-room':()=>openImmersionRoom(),
 'room-previous':()=>roomSetMonth(-1),'room-next':()=>roomSetMonth(1),
 'room-today':()=>{const s=roomState();s.month=s.today.slice(0,7);s.selectionAnchor=s.today;roomSelect(s.today);return loadImmersionRoom();},
 'room-refresh':()=>{if(!roomState().loading)return loadImmersionRoom();},
 'room-day':b=>{if(Date.now()<roomSuppressClick)return;const s=roomState();s.selectionAnchor=b.dataset.date;roomSelect(b.dataset.date);$(`[data-action="room-day"][data-date="${b.dataset.date}"]`)?.focus();},
 'room-detail':b=>openRoomDetail(b.dataset.id),
 'room-approve':()=>changeRoomStatus('approved'),'room-reject':()=>changeRoomStatus('rejected'),'room-cancel':()=>changeRoomStatus('cancelled')
});
let roomDrag=null,roomSuppressClick=0;
function roomPaintRange(start,end){[start,end]=[start,end].sort();$$('[data-room-date]').forEach(cell=>{const selected=cell.dataset.roomDate>=start&&cell.dataset.roomDate<=end;cell.classList.toggle('is-selected',selected);cell.querySelector('.ir-date')?.setAttribute('aria-pressed',String(selected));});}
root.addEventListener('pointerdown',e=>{const cell=e.target.closest('[data-room-date]');if(!cell||e.target.closest('[data-action="room-detail"]')||e.button!==0||e.pointerType!=='mouse'||!roomVisible()||roomState().saving)return;roomDrag={start:cell.dataset.roomDate,end:cell.dataset.roomDate,user:roomState().user};});
root.addEventListener('pointermove',e=>{if(!roomDrag)return;const cell=e.target.closest('[data-room-date]');if(cell&&roomVisible()){roomDrag.end=cell.dataset.roomDate;roomPaintRange(roomDrag.start,roomDrag.end);}});
document.addEventListener('pointerup',()=>{if(!roomDrag)return;const range=roomDrag;roomDrag=null;if(roomVisible()&&range.user===roomState().user){roomSuppressClick=Date.now()+350;roomState().selectionAnchor=range.start;roomSelect(range.start,range.end);}});
document.addEventListener('pointercancel',()=>{roomDrag=null;roomRender();});
root.addEventListener('click',e=>{const cell=e.target.closest('[data-room-date]');if(!cell||e.target.closest('button, a, input, select, textarea, [data-action]')||Date.now()<roomSuppressClick||!roomVisible()||roomState().saving)return;const s=roomState();s.selectionAnchor=cell.dataset.roomDate;roomSelect(cell.dataset.roomDate);});
root.addEventListener('keydown',e=>{
 const b=e.target.closest('[data-action="room-day"]');if(!b||!roomVisible())return;
 const offsets={ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7};if(!Object.hasOwn(offsets,e.key))return;e.preventDefault();
 const date=roomAddDays(b.dataset.date,offsets[e.key]),s=roomState(),{start,end}=roomBounds(s.month);if(date<start||date>end)return;
 if(e.shiftKey)roomSelect(s.selectionAnchor||b.dataset.date,date);
 $(`[data-action="room-day"][data-date="${date}"]`)?.focus();
});
root.addEventListener('input',e=>{const form=e.target.closest('#ir-request-form');if(!form)return;const s=roomState();if(s.saving)return;const {name,value}=e.target;if(Object.hasOwn(s.draft,name))s.draft[name]=value;if(['startDate','endDate'].includes(name))roomPaintRange(s.draft.startDate,s.draft.endDate);});
root.addEventListener('change',e=>{if(!e.target.closest('#ir-request-form'))return;const s=roomState();if(s.saving)return;if(Object.hasOwn(s.draft,e.target.name))s.draft[e.target.name]=e.target.value;if(['startDate','endDate'].includes(e.target.name)){roomPaintRange(s.draft.startDate,s.draft.endDate);const end=$('#ir-request-form [name="endDate"]');if(end)end.min=s.draft.startDate||s.today;const summary=$('.ir-selection-summary');if(summary){summary.outerHTML=roomSelectionSummary(s);mountIcons();}}});
root.addEventListener('submit',e=>{if(e.target.id!=='ir-request-form')return;e.preventDefault();e.stopImmediatePropagation();void submitImmersionRoom();},true);
