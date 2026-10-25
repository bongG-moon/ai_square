// Notification reads may finish after a user navigates or opens another dialog.
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const {test}=require('node:test');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_workspace.js'),'utf8');
const block=source.slice(source.indexOf('function renderUnreadCount(){'),source.indexOf('\nObject.assign(actions,{',source.indexOf('function renderUnreadCount(){')));
function deferred(){let resolve,reject;const promise=new Promise((ok,no)=>{resolve=ok;reject=no;});return {promise,resolve,reject};}
function fixture(){
 const requests=[],modals=[],details=[],workspaceFiles=[],badge={hidden:true,textContent:''},bell={setAttribute(k,v){this[k]=v;}};
 const c={work:{notifications:[],unreadOnly:false},runtime:{detailLoadToken:0,requestBusy:0},server:{authMode:'mock',unread:0},document:{hidden:false},now:10000,
  $:s=>s==='#ws-unread'?badge:bell,Date:{now:()=>c.now},
  requestAPI:(url,method,body)=>{const job=deferred();requests.push({...job,url,method,body});c.runtime.requestBusy++;return job.promise.finally(()=>c.runtime.requestBusy--);},
  openModal:(title,kicker,html)=>{c.runtime.detailLoadToken++;modals.push({title,html});},
  render:()=>{throw Error('Inbox should not rebuild the catalog');},
  esc:s=>String(s??'').replaceAll('<','&lt;').replaceAll('"','&quot;'),dated:String,
  button:(action,label,cls,extra)=>`<button data-action="${action}" ${extra||''}>${label}</button>`,icon:()=>'',blank:(i,t,b)=>`<p>${t} ${b}</p>`,
  afterWorkspaceSave:fn=>fn(),refresh:async()=>{},detail:async(id,tab)=>details.push({id,tab}),openAxWorkspaceFile:async id=>workspaceFiles.push(id),
 };
 vm.createContext(c);vm.runInContext(block+'\nglobalThis.api={inbox,checkNotifications};',c);
 const action=source.split('\n').find(line=>line.trim().startsWith("'notification-open':"));
 c.openNotice=vm.runInContext('({'+action.trim()+'})["notification-open"]',c);
 return {c,requests,modals,details,workspaceFiles,badge,bell,...c.api};
}
const notice={id:'event:owner',title:'동료가 도구에 의견을 남겼습니다.',kind:'feedback',created:1,read:false,target:{type:'feedback',id:7,feedbackId:12}};
const response=(unread=1)=>({notifications:[notice],unread,nextCursor:null});

test('inbox opens immediately, then shows the comment and badge without rebuilding hidden catalog',async()=>{
 const h=fixture(),p=h.inbox();assert.match(h.modals[0].html,/확인하고 있어요/);
 h.requests[0].resolve(response());await p;
 assert.match(h.modals[1].html,/동료가 도구에 의견/);assert.match(h.modals[1].html,/notification-open/);
 assert.equal(h.badge.textContent,1);assert.equal(h.badge.hidden,false);assert.match(h.bell['aria-label'],/1개/);
});
test('a closed or replaced inbox is not reopened by its late response or error',async()=>{
 for(const fails of [false,true]){
  const h=fixture(),p=h.inbox();h.c.runtime.detailLoadToken++;
  fails?h.requests[0].reject(Error('late')):h.requests[0].resolve(response());await p;
  assert.equal(h.modals.length,1);assert.equal(h.c.server.unread,0);
 }
});
test('newer inbox filter wins over a slower older response',async()=>{
 const h=fixture(),old=h.inbox();h.c.work.unreadOnly=true;const current=h.inbox();
 h.requests[1].resolve(response(2));await current;h.requests[0].resolve(response(9));await old;
 assert.equal(h.c.server.unread,2);assert.equal(h.modals.length,3);assert.match(h.requests[1].url,/unread=true/);
});
test('a newer catalog badge refresh does not leave a current inbox stuck loading',async()=>{
 const h=fixture(),p=h.inbox();h.c.runtime.notificationGeneration++;h.c.server.unread=3;
 h.requests[0].resolve(response(1));await p;
 assert.equal(h.c.server.unread,3);assert.match(h.modals[1].html,/동료가 도구에 의견/);
});
test('current inbox errors propagate to the existing accessible error handler',async()=>{
 const h=fixture(),p=h.inbox();h.requests[0].reject(Error('read unavailable'));await assert.rejects(p,/read unavailable/);
 assert.equal(h.modals.length,1);
});
test('visible idle checks update badge, throttle focus storms and retry after a later failure',async()=>{
 const h=fixture(),first=h.checkNotifications();await h.checkNotifications();assert.equal(h.requests.length,1);
 h.requests[0].resolve(response(108));await first;assert.equal(h.badge.textContent,'99+');assert.match(h.bell['aria-label'],/108개/);
 await h.checkNotifications();assert.equal(h.requests.length,1);
 h.c.now+=6000;const failed=h.checkNotifications();h.requests[1].reject(Error('offline'));await assert.rejects(failed,/offline/);
 const retry=h.checkNotifications();h.requests[2].resolve(response(0));await retry;assert.equal(h.badge.hidden,true);
});
test('background tabs, in-progress requests and uninitialized sessions do not poll',async()=>{
 const h=fixture();h.c.document.hidden=true;await h.checkNotifications();h.c.document.hidden=false;
 h.c.runtime.requestBusy=1;await h.checkNotifications();h.c.runtime.requestBusy=0;
 h.c.server.authMode='';await h.checkNotifications();assert.equal(h.requests.length,0);
});
test('a background badge response cannot replace a newer inbox count',async()=>{
 const h=fixture(),poll=h.checkNotifications(),inbox=h.inbox();
 h.requests[1].resolve(response(1));await inbox;h.requests[0].resolve(response(8));await poll;
 assert.equal(h.c.server.unread,1);
});
test('opening a feedback notification marks it read then opens the tool comments',async()=>{
 const h=fixture();h.c.work.notifications=[notice];const opened=h.c.openNotice({dataset:{id:notice.id}});
 assert.equal(h.requests[0].url,'/api/notifications/read');assert.equal(h.requests[0].body.id,notice.id);
 h.requests[0].resolve({ok:true});await opened;assert.deepEqual(h.details,[{id:7,tab:'comments'}]);
});
test('an older background response cannot restore unread count after opening a notification',async()=>{
 const h=fixture();h.c.work.notifications=[notice];h.c.refresh=async()=>{h.c.server.unread=0;};
 const poll=h.checkNotifications(),opened=h.c.openNotice({dataset:{id:notice.id}});
 h.requests[1].resolve({ok:true});await opened;assert.equal(h.c.server.unread,0);
 h.requests[0].resolve(response(8));await poll;assert.equal(h.c.server.unread,0);
});

test('workspace release notification opens its stable AX file card instead of a tool detail',async()=>{
 const h=fixture(),notification={...notice,kind:'release',target:{type:'workspace',id:'b'.repeat(32)}};h.c.work.notifications=[notification];
 const opened=h.c.openNotice({dataset:{id:notification.id}});assert.equal(h.requests[0].body.id,notification.id);
 h.requests[0].resolve({ok:true});await opened;assert.deepEqual(h.workspaceFiles,[notification.target.id]);assert.deepEqual(h.details,[]);
});

test('workspace notification read completion cannot redirect a user who has opened another view',async()=>{
 const h=fixture();h.c.work.notifications=[{...notice,target:{type:'workspace',id:'file-a'}}];
 const opened=h.c.openNotice({dataset:{id:notice.id}});h.c.runtime.detailLoadToken++;h.requests[0].resolve({ok:true});await opened;
 assert.deepEqual(h.workspaceFiles,[]);assert.deepEqual(h.details,[]);
});

test('workspace notification refresh completion cannot redirect a newer dialog',async()=>{
 const h=fixture(),refresh=deferred();h.c.refresh=()=>refresh.promise;h.c.work.notifications=[{...notice,target:{type:'workspace',id:'file-a'}}];
 const opened=h.c.openNotice({dataset:{id:notice.id}});h.requests[0].resolve({ok:true});await new Promise(setImmediate);h.c.runtime.detailLoadToken++;
 refresh.resolve();await opened;assert.deepEqual(h.workspaceFiles,[]);assert.deepEqual(h.details,[]);
});
