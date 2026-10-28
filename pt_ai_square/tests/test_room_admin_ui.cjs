const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_room_admin.js'),'utf8');
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};}
function row(extra={}){return {id:'r1',title:'신청 제목',purpose:'함께 할 일',startDate:'2026-11-01',endDate:'2026-11-02',slot:'am',owner:{id:'1',name:'신청자',org:'기술팀'},status:'pending',revision:1,canApprove:true,canReject:true,canCancel:true,...extra};}
function setup(){
 const requests=[],opened=[],dialog={open:false},reason={value:''},confirmation=[];
 const c={work:{tab:'room-admin'},state:{route:'admin'},server:{user:{id:'admin',role:'admin'}},runtime:{detailLoadToken:0},actions:{},roomSlots:{all:'종일',am:'오전',pm:'오후'},roomStatuses:{pending:'승인 대기',approved:'예약 확정',rejected:'반려',cancelled:'취소'},
 esc:v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),icon:n=>`<svg>${n}</svg>`,button:(a,l,k='',x='')=>`<button data-action="${a}" ${x}>${l}</button>`,
 roomPill:r=>`<span>${r.status}</span>`,roomPeriod:r=>r.startDate===r.endDate?r.startDate:`${r.startDate} ~ ${r.endDate}`,
 renderWorkspace(){},navigate(route){c.state.route=route;c.runtime.detailLoadToken++},openModal(title,kicker,html){c.runtime.detailLoadToken++;dialog.open=true;opened.push({title,kicker,html})},closeModal(){c.runtime.detailLoadToken++;dialog.open=false},
 ask(title,copy,cb,label){confirmation.push({title,copy,cb,label})},$:s=>s==='#sq-dialog'?dialog:s==='#room-admin-reason'?reason:s==='#sq-dialog-body'?{querySelectorAll:()=>[]}:null,
 requestAPI(url,method='GET',body){let d=deferred();requests.push({...d,url,method,body});return d.promise;},
 roomDate:x=>/^\d{4}-\d{2}-\d{2}$/.test(x||''),roomState(){return room},roomCurrent:s=>s===room,roomVisible:()=>c.state.route==='immersion-room',roomRender(){},async loadImmersionRoom(){room.loadToken=(room.loadToken||0)+1;return true},openRoomDetail:id=>{c.openedRoom=id},
 };const room={user:'admin',draft:{},reservations:[]};
 vm.createContext(c);vm.runInContext(source,c);return {c,requests,opened,dialog,reason,confirmation,room};
}
test('admin list loads pending and escapes untrusted content',async()=>{
 const h=setup(),p=h.c.openAdminRoom();assert.match(h.requests[0].url,/status=pending&page=1/);
 h.requests[0].resolve({reservations:[row({title:'<script>'})],total:1,page:1,totalPages:1});await p;
 let html=h.c.adminRoomPanel();assert.match(html,/&lt;script&gt;/);assert.match(html,/승인 대기/);assert.doesNotMatch(html,/<script>/);
});
test('changing filters disregards stale list responses',async()=>{
 const h=setup(),first=h.c.openAdminRoom(),second=h.c.actions['room-admin-filter']({dataset:{filter:'history'}});
 h.requests[1].resolve({reservations:[row({id:'new'})],total:1,page:1,totalPages:1});await second;
 h.requests[0].resolve({reservations:[row({id:'old'})],total:1,page:1,totalPages:1});await first;
 assert.equal(h.c.adminRoomState().data.reservations[0].id,'new');
});
test('confirmation preserves reason and revision and refreshes after approval',async()=>{
 const h=setup(),p=h.c.openAdminRoom();h.requests[0].resolve({reservations:[row()],total:1,page:1,totalPages:1});await p;
 h.c.openAdminRoomDetail('r1');h.reason.value='확인했습니다';h.c.confirmAdminRoomDecision('approved');assert.equal(h.confirmation.length,1);
 const action=h.confirmation[0].cb();assert.equal(h.requests[1].method,'PATCH');assert.equal(h.requests[1].body.expectedRevision,1);assert.equal(h.requests[1].body.reason,'확인했습니다');
 h.requests[1].resolve({reservation:row({status:'approved'})});await new Promise(setImmediate);h.requests[2].resolve({reservations:[],total:0,page:1,totalPages:1});await action;
 assert.match(h.c.adminRoomState().notice,/예약 확정/);
});
test('cancel is clearly described and conflict preserves reason',async()=>{
 const h=setup(),p=h.c.openAdminRoom();h.requests[0].resolve({reservations:[row()],total:1,page:1,totalPages:1});await p;
 h.c.openAdminRoomDetail('r1');h.reason.value='일정 조정';h.c.confirmAdminRoomDecision('cancelled');assert.match(h.confirmation[0].copy,/취소/);
 const action=h.confirmation[0].cb();h.requests[1].reject(Object.assign(Error('다른 사용자가 변경했습니다.'),{status:409}));await action;
 assert.match(h.opened.at(-1).html,/일정 조정/);assert.match(h.opened.at(-1).html,/다른 사용자가 변경/);
});
test('room notification opens actual reservation even if calendar history omitted it',async()=>{
 const h=setup(),p=h.c.openRoomNotification({id:'r1',startDate:'2026-11-01'});
 assert.equal(h.c.state.route,'immersion-room');assert.equal(h.room.month,'2026-11');
 h.requests[0].resolve({reservation:row({status:'rejected'})});await p;
 assert.equal(h.c.openedRoom,'r1');assert.equal(h.room.reservations[0].status,'rejected');
});

test('stale failed filter request cannot overwrite the current list',async()=>{
 const h=setup(),first=h.c.openAdminRoom(),second=h.c.actions['room-admin-filter']({dataset:{filter:'history'}});
 h.requests[1].resolve({reservations:[row({id:'new'})],total:1,page:1,totalPages:1});await second;
 h.requests[0].reject(Object.assign(Error('outdated failure'),{status:500}));await first;
 assert.equal(h.c.adminRoomState().error,'');assert.equal(h.c.adminRoomState().data.reservations[0].id,'new');
});
test('failed room notification detail gives a recoverable calendar error',async()=>{
 const h=setup(),p=h.c.openRoomNotification({id:'missing',startDate:'2026-11-01'});
 h.requests[0].reject(Object.assign(Error('timeout'),{code:'NETWORK_ERROR'}));await p;
 assert.match(h.room.error,/불러오지 못했습니다/);assert.equal(h.c.openedRoom,undefined);
});
test('stale notification detail never opens after leaving the room',async()=>{
 const h=setup(),p=h.c.openRoomNotification({id:'r1',startDate:'2026-11-01'});
 h.c.state.route='home';h.requests[0].resolve({reservation:row()});await p;
 assert.equal(h.c.openedRoom,undefined);
});
test('admin can reject overdue pending reservations even if approval is disabled',async()=>{
 const h=setup(),p=h.c.openAdminRoom();h.requests[0].resolve({reservations:[row({canApprove:false,canReject:true})],total:1,page:1,totalPages:1});await p;
 h.c.openAdminRoomDetail('r1');assert.match(h.opened.at(-1).html,/room-admin-reject/);assert.doesNotMatch(h.opened.at(-1).html,/room-admin-approve/);
 h.c.confirmAdminRoomDecision('rejected');assert.equal(h.confirmation.length,1);
});
test('notification action routes room targets and retains other target behavior',async()=>{
 const workspace=fs.readFileSync(path.join(__dirname,'../frontend/frontend_workspace.js'),'utf8');
 const action=workspace.split('\n').find(line=>line.includes("'notification-open':async b=>"));
 assert.ok(action);const calls=[];
 const c={roomNotificationGeneration:0,actions:{},work:{notifications:[{id:'notice',target:{type:'room',id:'reservation',startDate:'2026-11-01'}}]},runtime:{detailLoadToken:0},server:{user:{role:'member'}},requestAPI:async(...a)=>calls.push(['request',...a]),nextNotificationRead:()=>calls.push(['read']),afterWorkspaceSave:async fn=>fn(),openRoomNotification:async target=>calls.push(['room',target]),refresh:async()=>calls.push(['refresh']),detail:(...a)=>calls.push(['detail',...a])};
 vm.createContext(c);vm.runInContext(`Object.assign(actions,{${action.replace(/,\s*$/, '')}});`,c);await c.actions['notification-open']({dataset:{id:'notice'}});
 assert.equal(calls[0][1],'/api/notifications/read');assert.equal(calls[2][0],'room');assert.ok(!calls.some(x=>x[0]==='refresh'));
 c.work.notifications[0].target={type:'feedback',id:'tool'};calls.length=0;await c.actions['notification-open']({dataset:{id:'notice'}});
 assert.ok(calls.some(x=>x[0]==='refresh'));assert.deepEqual(calls.find(x=>x[0]==='detail').slice(1),['tool','comments']);
});


test('a later room notification wins over an earlier detail response',async()=>{
 const h=setup(),first=h.c.openRoomNotification({id:'one',startDate:'2026-11-01'}),second=h.c.openRoomNotification({id:'two',startDate:'2026-11-02'});
 h.requests[1].resolve({reservation:row({id:'two'})});await second;
 h.requests[0].resolve({reservation:row({id:'one'})});await first;
 assert.equal(h.c.openedRoom,'two');assert.deepEqual(h.room.reservations.map(r=>r.id),['two']);
});
test('another modal or later navigation prevents stale detail from reopening',async()=>{
 const h=setup(),p=h.c.openRoomNotification({id:'one',startDate:'2026-11-01'});
 h.c.openModal('다른 상세','', '');h.requests[0].resolve({reservation:row({id:'one'})});await p;
 assert.equal(h.c.openedRoom,undefined);
 const second=h.c.openRoomNotification({id:'two',startDate:'2026-11-01'});
 h.c.navigate('home');h.c.navigate('immersion-room');h.requests[1].resolve({reservation:row({id:'two'})});await second;
 assert.equal(h.c.openedRoom,undefined);
});
test('changing month or refreshing calendar prevents stale notification detail',async()=>{
 const h=setup(),p=h.c.openRoomNotification({id:'one',startDate:'2026-11-01'});
 h.room.month='2026-12';h.requests[0].resolve({reservation:row({id:'one'})});await p;assert.equal(h.c.openedRoom,undefined);
 const second=h.c.openRoomNotification({id:'two',startDate:'2026-11-01'});await h.c.loadImmersionRoom();
 h.requests[1].resolve({reservation:row({id:'two'})});await second;assert.equal(h.c.openedRoom,undefined);
});
test('notification clicks remain ordered when earlier mark-read completes last',async()=>{
 const workspace=fs.readFileSync(path.join(__dirname,'../frontend/frontend_workspace.js'),'utf8');
 const action=workspace.split('\n').find(line=>line.includes("'notification-open':async b=>"));
 const marks=[],opened=[];
 const c={roomNotificationGeneration:0,actions:{},work:{notifications:[{id:'n1',target:{type:'room',id:'one'}},{id:'n2',target:{type:'room',id:'two'}}]},runtime:{detailLoadToken:0},server:{user:{role:'member'}},requestAPI(){const d=deferred();marks.push(d);return d.promise;},nextNotificationRead(){},afterWorkspaceSave:async fn=>fn(),openRoomNotification:async t=>opened.push(t.id)};
 vm.createContext(c);vm.runInContext(`Object.assign(actions,{${action.replace(/,\s*$/, '')}});`,c);
 const first=c.actions['notification-open']({dataset:{id:'n1'}}),second=c.actions['notification-open']({dataset:{id:'n2'}});
 marks[1].resolve({});await second;marks[0].resolve({});await first;assert.deepEqual(opened,['two']);
});
