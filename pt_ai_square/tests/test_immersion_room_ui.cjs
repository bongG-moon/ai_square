const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_immersion_room.js'),'utf8');
const tick=()=>new Promise(setImmediate);
const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function reservation(extra={}){return {id:'reservation-1',startDate:'2026-10-28',endDate:'2026-10-29',slot:'all',title:'보고서 자동화 개발',purpose:'보고서를 만드는 과정을 정리합니다.',status:'pending',owner:{id:'owner',name:'동료',org:'기술팀'},revision:1,canCancel:true,canApprove:false,canReject:false,...extra};}
function setup({role='member',clock='2026-10-28T02:00:00Z'}={}){
 const requests=[],listeners={},documents={},opened=[],cells=[],focus=[];
 const dialog={open:false},reason={value:''},buttons=[{disabled:false},{disabled:false}];
 class FixedDate extends Date {constructor(...args){super(...(args.length?args:[clock]));}static now(){return new Date(clock).getTime();}}
 const c={work:{},state:{route:'immersion-room'},server:{user:{id:'owner',role}},runtime:{detailLoadToken:0},workspace:{innerHTML:''},actions:{},Date:FixedDate,Intl,crypto:webcrypto,Uint8Array,
  esc,icon:n=>`<svg data-icon="${n}"></svg>`,button:(a,l,cls='',extra='')=>`<button data-action="${a}" class="${cls}" ${extra}>${l}</button>`,mountIcons(){},
  root:{addEventListener(name,fn){(listeners[name]??=[]).push(fn);}},document:{addEventListener(name,fn){(documents[name]??=[]).push(fn);}},
  $:selector=>selector==='#sq-dialog'?dialog:selector==='#ir-decision-reason'?reason:selector==='#sq-dialog-body'?{querySelectorAll:()=>buttons}:selector.startsWith('[data-action="room-day"]')?{focus:()=>focus.push(selector)}:null,
  $$:selector=>selector==='[data-room-date]'?cells:[],
  openModal(title,kicker,html){c.runtime.detailLoadToken++;dialog.open=true;opened.push({title,kicker,html});},closeModal(){c.runtime.detailLoadToken++;dialog.open=false;},
  navigate(route){c.runtime.detailLoadToken++;c.state.route=route;c.renderImmersionRoom();},
  requestAPI(url,method='GET',body){const pending=deferred();requests.push({...pending,url,method,body});return pending.promise;}
 };
 vm.createContext(c);vm.runInContext(source,c,{filename:'frontend_immersion_room.js'});
 return {c,requests,listeners,documents,opened,dialog,reason,buttons,cells,focus,get s(){return c.roomState();},
  answerCalendar(index,rows=[],extra={}){requests[index].resolve({reservations:rows,today:'2026-10-28',canManage:role==='admin',...extra});requests[index+1].resolve({holidays:[{date:'2026-10-03',name:'개천절'}],coverage:{startYear:2026,endYear:2027},sources:[{title:'한국천문연구원',url:'https://astro.kasi.re.kr/test'}]});},
  async ready(rows=[],extra={}){const p=c.openImmersionRoom();this.answerCalendar(requests.length-2,rows,extra);await p;},
  draft(extra={}){this.s.draft={startDate:'2026-10-28',endDate:'2026-10-29',slot:'all',title:'보고서 자동화',purpose:'동료와 보고서 만들기를 개선합니다.',...extra};},
  event(name,target,extra={}){const e={target,preventDefault(){this.prevented=true;},stopImmediatePropagation(){this.stopped=true;},...extra};for(const f of listeners[name]||[])f(e);return e;}
 };
}

test('today and inclusive grid dates use Korean civil dates across UTC midnight',()=>{
 const h=setup({clock:'2026-10-27T16:00:00Z'});assert.equal(h.s.today,'2026-10-28');
 assert.equal(h.c.roomAddDays('2028-02-28',1),'2028-02-29');assert.equal(h.c.roomAddDays('2028-02-29',1),'2028-03-01');assert.equal(h.c.roomDate('2027-02-29'),null);
 assert.equal(h.c.roomBounds('2026-10').start,'2026-09-27');assert.equal(h.c.roomBounds('2026-10').end,'2026-11-07');
});

test('choosing a date restores keyboard focus after rebuilding the calendar',()=>{
 const h=setup();h.c.actions['room-day']({dataset:{date:'2026-10-29'}});
 assert.equal(h.s.draft.startDate,'2026-10-29');assert.equal(h.s.draft.endDate,'2026-10-29');
 assert.match(h.focus.at(-1),/2026-10-29/);
});

test('date and time field changes preserve form nodes while updating selected dates',()=>{
 const h=setup();h.c.renderImmersionRoom();const before=h.c.workspace.innerHTML;
 h.event('change',{name:'startDate',value:'2026-11-03',closest:()=>({})});
 h.event('change',{name:'endDate',value:'2026-11-04',closest:()=>({})});
 h.event('change',{name:'slot',value:'pm',closest:()=>({})});
 assert.equal(h.s.draft.startDate,'2026-11-03');assert.equal(h.s.draft.endDate,'2026-11-04');
 assert.equal(h.s.draft.slot,'pm');assert.equal(h.c.workspace.innerHTML,before);
});

test('initial load requests bounded calendar and holidays and renders only active bookings on grid',async()=>{
 const h=setup(),p=h.c.openImmersionRoom();assert.equal(h.requests.length,2);
 assert.equal(h.requests[0].url,'/api/immersion-room?start=2026-09-27&end=2026-11-07');assert.match(h.requests[1].url,/\/holidays\?/);assert.match(h.c.workspace.innerHTML,/aria-busy="true"/);
 h.answerCalendar(0,[reservation(),reservation({id:'cancelled',status:'cancelled',title:'취소된 세미나'})]);await p;
 const html=h.c.workspace.innerHTML,grid=html.slice(html.indexOf('class="ir-calendar"'),html.indexOf('class="ir-selection-summary"'));
 assert.equal((grid.match(/data-room-date=/g)||[]).length,42);assert.equal((grid.match(/data-id="reservation-1"/g)||[]).length,2);assert.doesNotMatch(grid,/취소된 세미나/);
 assert.match(html,/내 신청 처리 내역/);assert.match(html,/취소된 세미나/);assert.match(html,/개천절/);assert.doesNotMatch(html,/공휴일 출처|한국 시간 기준|class="ir-intro"/);
});

test('newer month load wins and does not overwrite drafted booking details',async()=>{
 const h=setup(),old=h.c.openImmersionRoom();h.draft({title:'유지할 제목'});const latest=h.c.roomSetMonth(1);
 h.answerCalendar(2,[reservation({id:'nov',startDate:'2026-11-10',endDate:'2026-11-10',title:'11월 예약'})]);await latest;
 h.answerCalendar(0,[reservation({title:'늦은 이전 응답'})]);assert.equal(await old,false);
 assert.equal(h.s.month,'2026-11');assert.match(h.c.workspace.innerHTML,/11월 예약/);assert.doesNotMatch(h.c.workspace.innerHTML,/늦은 이전 응답/);assert.equal(h.s.draft.title,'유지할 제목');
});

test('holiday failure leaves bookings usable; reservation failure offers retry without fake empty success',async()=>{
 const h=setup(),p=h.c.openImmersionRoom();h.requests[0].resolve({reservations:[reservation()],today:'2026-10-28',canManage:false});h.requests[1].reject(Error('failed'));await p;
 assert.match(h.c.workspace.innerHTML,/공휴일 정보를 불러오지 못했습니다/);assert.equal(h.s.loadedMonth,h.s.month);
 const refresh=h.c.loadImmersionRoom();h.requests[2].reject(Error('failed'));h.requests[3].resolve({holidays:[]});assert.equal(await refresh,false);assert.match(h.c.workspace.innerHTML,/role="alert"/);assert.match(h.c.workspace.innerHTML,/다시 시도/);
});

test('mouse reverse dragging selects inclusive period; touch keeps native scrolling',async()=>{
 const h=setup();await h.ready();const day=date=>({dataset:{date},closest:s=>s==='[data-room-date]'?{dataset:{roomDate:date}}:null});
 const begin=day('2026-10-31');h.event('pointerdown',begin,{button:0,pointerType:'mouse'});
 h.event('pointermove',{closest:()=>({dataset:{roomDate:'2026-10-28'}})});h.documents.pointerup[0]();
 assert.equal(h.s.draft.startDate,'2026-10-28');assert.equal(h.s.draft.endDate,'2026-10-31');
 const e=h.event('pointerdown',day('2026-11-01'),{button:0,pointerType:'touch'});assert.equal(e.prevented,undefined);h.documents.pointerup[0]();assert.equal(h.s.draft.endDate,'2026-10-31');
});

test('empty date cells select and drag while booking controls remain independent',async()=>{
 const h=setup();await h.ready();
 const blank=date=>({closest:s=>s==='[data-room-date]'?{dataset:{roomDate:date}}:null});
 h.event('pointerdown',blank('2026-10-31'),{button:0,pointerType:'mouse'});
 h.event('pointermove',blank('2026-10-29'));h.documents.pointerup[0]();
 assert.equal(h.s.draft.startDate,'2026-10-29');assert.equal(h.s.draft.endDate,'2026-10-31');
 const booking={closest:s=>s==='[data-room-date]'?{dataset:{roomDate:'2026-11-01'}}:s==='[data-action="room-detail"]'?{}:null};
 h.event('pointerdown',booking,{button:0,pointerType:'mouse'});h.documents.pointerup[0]();
 assert.equal(h.s.draft.startDate,'2026-10-29');assert.equal(h.s.draft.endDate,'2026-10-31');
 const tap=setup();await tap.ready();tap.event('pointerdown',blank('2026-11-02'),{button:0,pointerType:'touch'});tap.documents.pointerup[0]();tap.event('click',blank('2026-11-02'));
 assert.equal(tap.s.draft.startDate,'2026-11-02');assert.equal(tap.s.draft.endDate,'2026-11-02');
});

test('keyboard shift arrows extend selection and focus destination date',async()=>{
 const h=setup();await h.ready();h.s.selectionAnchor='2026-10-28';const b={dataset:{date:'2026-10-28'}};
 const e=h.event('keydown',{closest:()=>b},{key:'ArrowDown',shiftKey:true});assert.equal(e.prevented,true);assert.equal(h.s.draft.startDate,'2026-10-28');assert.equal(h.s.draft.endDate,'2026-11-04');assert.match(h.focus[0],/2026-11-04/);
});

test('date input fallback updates draft without resetting title, slot defaults all and rejects invalid periods',async()=>{
 const h=setup();await h.ready();h.draft();
 h.event('input',{closest:()=>({id:'ir-request-form'}),name:'title',value:'사용자 제목'});
 h.event('change',{closest:()=>({id:'ir-request-form'}),name:'startDate',value:'2026-11-03'});assert.equal(h.s.draft.title,'사용자 제목');assert.equal(h.s.draft.slot,'all');
 const base={startDate:'2026-10-28',endDate:'2026-10-29',slot:'all',title:'제목',purpose:'목적'};
 for(const d of [{startDate:'2026-10-27'},{endDate:'2026-10-27'},{endDate:'2026-12-01'},{slot:'night'},{title:' '},{purpose:' '}])assert.ok(h.c.roomDraftError({...base,...d},'2026-10-28'));
 assert.equal(h.c.roomDraftError({...base,endDate:'2026-11-27'},'2026-10-28'),'');
 assert.ok(h.c.roomDraftError({...base,endDate:'2026-11-28'},'2026-10-28'));
});

test('pending request is deduplicated, failed retry reuses UUID and content change gets a new UUID',async()=>{
 const h=setup();await h.ready();h.draft();const first=h.c.submitImmersionRoom();h.c.submitImmersionRoom();assert.equal(h.requests.length,3);
 const id=h.requests[2].body.clientRequestId;assert.match(id,/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
 h.c.roomSelect('2026-11-04');assert.equal(h.s.draft.startDate,'2026-10-28');h.requests[2].reject(new TypeError('private data'));await first;
 assert.match(h.c.workspace.innerHTML,/같은 내용으로 다시 신청/);assert.doesNotMatch(h.c.workspace.innerHTML,/private data/);
 const retry=h.c.submitImmersionRoom();assert.equal(h.requests[3].body.clientRequestId,id);h.requests[3].reject(Object.assign(Error('이미 예약된 시간입니다.'),{status:409}));await retry;assert.match(h.c.workspace.innerHTML,/이미 예약된 시간/);
 h.s.draft.title='다른 제목';const changed=h.c.submitImmersionRoom();assert.notEqual(h.requests[4].body.clientRequestId,id);h.requests[4].reject(Error('failed'));await changed;
});

test('successful member booking shows pending approval while refresh failure cannot invite duplicate booking',async()=>{
 const h=setup();await h.ready();h.draft();const p=h.c.submitImmersionRoom();h.requests[2].resolve({reservation:reservation(),created:true});await tick();
 assert.equal(h.requests.length,5);h.requests[3].reject(Error('refresh failed'));h.requests[4].resolve({holidays:[]});assert.equal(await p,true);
 assert.match(h.s.notice,/신청이 접수/);assert.match(h.s.notice,/예약은 저장되었지만/);assert.equal(h.s.draft.title,'');assert.equal(h.s.attempt,null);
});

test('replayed cancelled booking is reported as cancelled rather than newly pending',async()=>{
 const h=setup();await h.ready();h.draft();const p=h.c.submitImmersionRoom();h.requests[2].resolve({reservation:reservation({status:'cancelled'}),created:false});await tick();h.answerCalendar(3);await p;
 assert.match(h.s.notice,/이미 취소 상태/);assert.doesNotMatch(h.s.notice,/신청이 접수/);
});

test('detail escapes content and only exposes server-authorized decisions',async()=>{
 const h=setup();await h.ready([reservation({title:'<img src=x>',purpose:'<script>bad</script>',owner:{id:'owner',name:'<동료>',org:'기술 & 팀'}})]);h.c.openRoomDetail('reservation-1');
 const html=h.opened.at(-1).html;assert.doesNotMatch(html,/<script>/);assert.match(html,/&lt;script&gt;/);assert.match(html,/&lt;동료&gt;/);assert.match(html,/room-cancel/);assert.doesNotMatch(html,/room-approve|room-reject/);
 assert.equal(await h.c.changeRoomStatus('approved'),false);assert.equal(h.requests.length,2);
});

test('admin status mutation includes revision, deduplicates, and preserves reason on conflict',async()=>{
 const h=setup({role:'admin'});await h.ready([reservation({canApprove:true,canReject:true})]);h.c.openRoomDetail('reservation-1');h.reason.value='다른 일정과 조정해 주세요.';
 const p=h.c.changeRoomStatus('rejected');h.c.changeRoomStatus('rejected');assert.equal(h.requests.length,3);assert.equal(h.requests[2].method,'PATCH');assert.equal(h.requests[2].body.expectedRevision,1);assert.equal(h.requests[2].body.reason,h.reason.value);
 h.requests[2].reject(Object.assign(Error('다른 변경이 있습니다.'),{status:409}));assert.equal(await p,false);assert.match(h.opened.at(-1).html,/다른 일정과 조정해 주세요/);assert.match(h.opened.at(-1).html,/다른 변경이 있습니다/);
});

test('closing detail while request is pending never reopens it on a failure',async()=>{
 const h=setup();await h.ready([reservation()]);h.c.openRoomDetail('reservation-1');const p=h.c.changeRoomStatus('cancelled');h.c.closeModal();const opened=h.opened.length;
 h.requests[2].reject(Error('failed'));await p;assert.equal(h.dialog.open,false);assert.equal(h.opened.length,opened);
});

test('user switch and leaving room prevent late responses rendering private detail',async()=>{
 const h=setup(),p=h.c.openImmersionRoom();h.c.server.user.id='second-user';const next=h.c.openImmersionRoom();h.answerCalendar(2,[]);await next;h.answerCalendar(0,[reservation({title:'이전 계정 기록'})]);assert.equal(await p,false);assert.doesNotMatch(h.c.workspace.innerHTML,/이전 계정 기록/);
 const late=h.c.loadImmersionRoom();h.c.state.route='home';const html=h.c.workspace.innerHTML;h.answerCalendar(4,[reservation()]);await late;assert.equal(h.c.workspace.innerHTML,html);
});


test('past pending reservation can be rejected without permitting approval',async()=>{
 const h=setup({role:'admin'});await h.ready([reservation({canApprove:false,canReject:true})]);
 h.c.openRoomDetail('reservation-1');const html=h.opened.at(-1).html;
 assert.match(html,/room-reject/);assert.doesNotMatch(html,/room-approve/);
 const action=h.c.changeRoomStatus('rejected');
 assert.equal(h.requests[2].body.status,'rejected');h.requests[2].resolve({reservation:reservation({status:'rejected'})});await tick();h.answerCalendar(3);await action;
});
