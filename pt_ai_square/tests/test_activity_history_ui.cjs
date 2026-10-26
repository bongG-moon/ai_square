const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_activity.js'),'utf8');
const workspaceSource=fs.readFileSync(path.join(__dirname,'../frontend/frontend_workspace.js'),'utf8');
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
const tick=()=>new Promise(setImmediate);
const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const event=(id,extra={})=>({id,created:1793030400,kind:'download',tool:1,toolName:'문서 도구 '+id,user:'10001',userName:'김동료',version:2,counted:false,imported:false,channel:'api',...extra});
function setup(){
 const requests=[],downloads=[],listeners={},timers=[],links=[],revoked=[],blobs=[];
 const panel={html:'',renders:0,set outerHTML(value){this.html=value;this.renders++;},contains:()=>false};
 const nodes={'#ws-activity':panel,'#ws-activity-draft-note':{hidden:true},'#ws-activity-start':{focused:false,focus(){this.focused=true;}}};
 class FixedDate extends Date {static now(){return Date.parse('2026-10-26T16:00:00Z');}}
 const context={actions:{},state:{route:'admin'},work:{tab:'activity',scope:'all'},server:{user:{role:'admin'}},Date:FixedDate,URLSearchParams,AbortController,
  root:{addEventListener(name,callback,capture){(listeners[name]??=[]).push({callback,capture});}},
  document:{activeElement:null,body:{append(link){link.appended=true;}},createElement(tag){assert.equal(tag,'a');const link={click(){this.clicked=true;},remove(){this.removed=true;}};links.push(link);return link;}},
  URL:{createObjectURL(blob){blobs.push(blob);return 'blob:activity-test';},revokeObjectURL(url){revoked.push(url);}},
  $:selector=>nodes[selector]||null,$$:()=>[],esc,icon:name=>`<svg data-icon="${name}"></svg>`,
  button:(action,label,cls='',extra='')=>`<button class="${cls}" data-action="${action}" ${extra}>${label}</button>`,
  mountIcons(){},enhanceSelects(){},renderWorkspace(){panel.outerHTML=context.activityPanel();},
  closeModal(){},navigate(route){context.state.route=route;context.renderWorkspace();},
  setTimeout(callback,delay){const timer={callback,delay,cancelled:false};timers.push(timer);return timer;},clearTimeout(timer){timer.cancelled=true;},
  requestAPI(url,method,body,options){const pending=deferred();requests.push({...pending,url,method,body,options});return pending.promise;},
  fetch(url,options){const pending=deferred();downloads.push({...pending,url,options});return pending.promise;},
 };
 vm.createContext(context);vm.runInContext(source,context,{filename:'frontend_activity.js'});
 const state=()=>context.activityHistoryState();
 const change=(field,value)=>listeners.change[0].callback({target:{dataset:{activityFilter:field},value}});
 return {context,requests,downloads,listeners,timers,links,revoked,blobs,panel,nodes,state,change,
  result(index,events=[event('a')],extra={}){requests[index].resolve({events,nextCursor:null,total:events.length,pageSize:25,...extra});},
  async ready(events=[event('a')],extra={}){const promise=context.openActivityHistory();this.result(requests.length-1,events,extra);await promise;},
 };
}

test('initial history request uses 30 inclusive KST days and 25 rows',async()=>{
 const h=setup(),promise=h.context.openActivityHistory();
 const url=new URL(h.requests[0].url,'https://test.invalid');
 assert.equal(url.pathname,'/api/activity');assert.equal(url.searchParams.get('start'),'2026-09-28');assert.equal(url.searchParams.get('end'),'2026-10-27');assert.equal(url.searchParams.get('limit'),'25');assert.equal(url.searchParams.get('kind'),'all');
 assert.match(h.panel.html,/aria-busy="true"/);assert.match(h.panel.html,/불러오고 있습니다/);
 h.result(0);await promise;
 assert.match(h.panel.html,/<table class="ws-activity-table">/);assert.match(h.panel.html,/scope="col">도구 \/ 버전/);assert.match(h.panel.html,/총 1건/);assert.doesNotMatch(h.panel.html,/sq-activity-row|activity-more/);
});

test('next and previous pages replace rows and prevent double pagination requests',async()=>{
 const h=setup();await h.ready([event('first')],{total:52,nextCursor:'signed-first'});
 const next=h.context.actions['activity-next']();h.context.actions['activity-next']();assert.equal(h.requests.length,2);
 assert.equal(new URL(h.requests[1].url,'https://test.invalid').searchParams.get('before'),'signed-first');
 assert.doesNotMatch(h.panel.html,/문서 도구 first/);h.result(1,[event('second')],{total:52,nextCursor:'signed-second'});await next;
 assert.equal(h.state().rows.length,1);assert.equal(h.state().rows[0].id,'second');assert.equal(h.state().page,1);assert.match(h.panel.html,/26–26 \/ 52건/);
 const third=h.context.actions['activity-next']();h.result(2,[event('third')],{total:52});await third;
 const previous=h.context.actions['activity-previous']();assert.equal(new URL(h.requests[3].url,'https://test.invalid').searchParams.get('before'),'signed-first');h.result(3,[event('second')],{total:52,nextCursor:'signed-second'});await previous;
 assert.equal(h.state().page,1);assert.deepEqual(Array.from(h.state().rows,x=>x.id),['second']);
});

test('date presets only edit the draft until apply; changed filters reset pagination',async()=>{
 const h=setup();await h.ready([event('old')],{total:51,nextCursor:'old-cursor'});
 h.context.actions['activity-preset']({dataset:{period:'7'}});h.change('kind','like');
 assert.equal(h.requests.length,1);assert.equal(h.state().draft.start,'2026-10-21');assert.equal(h.state().applied.start,'2026-09-28');assert.equal(h.nodes['#ws-activity-draft-note'].hidden,false);
 const promise=h.context.applyActivityFilters(),url=new URL(h.requests[1].url,'https://test.invalid');assert.equal(url.searchParams.get('kind'),'like');assert.equal(url.searchParams.has('before'),false);
 h.result(1,[event('new',{kind:'like',channel:'unknown'})]);await promise;assert.equal(h.state().page,0);assert.equal(h.state().applied.start,'2026-10-21');assert.doesNotMatch(h.panel.html,/문서 도구 old/);
});

test('invalid dates and inverted ranges never reach the API',async()=>{
 const h=setup();for(const filters of [{start:'2026-02-30',end:'2026-03-01',kind:'all'},{start:'',end:'2026-03-01',kind:'all'},{start:'2026-03-02',end:'2026-03-01',kind:'all'},{start:'2026-03-01',end:'2026-03-01',kind:'unknown'}]){
  assert.equal(await h.context.loadActivityHistory(filters),false);assert.match(h.panel.html,/role="alert"/);
 }
 assert.equal(h.requests.length,0);
});

test('the latest query wins when responses arrive out of order',async()=>{
 const h=setup(),first=h.context.openActivityHistory();h.change('kind','like');const second=h.context.applyActivityFilters();
 h.result(1,[event('latest',{kind:'like'})]);await second;h.result(0,[event('stale')]);assert.equal(await first,false);
 assert.equal(h.state().rows[0].id,'latest');assert.equal(h.state().applied.kind,'like');assert.equal(h.state().loading,false);assert.doesNotMatch(h.panel.html,/문서 도구 stale/);
});

test('editing the draft while an initial request is pending cannot relabel its results',async()=>{
 const h=setup(),pending=h.context.openActivityHistory();h.change('start','2020-01-01');h.change('kind','like');h.result(0);await pending;
 assert.equal(h.state().applied.start,'2026-09-28');assert.equal(h.state().applied.kind,'all');assert.equal(h.state().draft.start,'2020-01-01');assert.equal(h.context.activityFiltersChanged(),true);
});

test('late completion after leaving the tab does not navigate, redraw or publish its rows',async()=>{
 const h=setup(),pending=h.context.openActivityHistory(),renders=h.panel.renders;h.context.state.route='home';h.result(0,[event('late')]);await pending;
 assert.equal(h.context.state.route,'home');assert.equal(h.panel.renders,renders);assert.equal(h.state().ready,false);assert.equal(h.state().rows.length,0);
});

test('a failed query hides previous rows, blocks export, and retry uses that query',async()=>{
 const h=setup();await h.ready([event('old')]);h.change('kind','unlike');const pending=h.context.applyActivityFilters();h.requests[1].reject(Error('연결 오류'));await pending;
 assert.match(h.panel.html,/연결 오류/);assert.doesNotMatch(h.panel.html,/문서 도구 old/);await h.context.actions['activity-export']();assert.equal(h.downloads.length,0);
 const retry=h.context.actions['activity-retry']();assert.equal(new URL(h.requests[2].url,'https://test.invalid').searchParams.get('kind'),'unlike');h.result(2,[]);await retry;
 assert.equal(h.state().error,'');assert.match(h.panel.html,/선택한 조건의 이력이 없습니다/);
});

test('page size changes fetch first page with applied filters; refresh resets cursor',async()=>{
 const h=setup();await h.ready([event('old')],{nextCursor:'next',total:120});h.change('start','2026-01-01');h.change('limit','50');
 const url=new URL(h.requests[1].url,'https://test.invalid');assert.equal(url.searchParams.get('limit'),'50');assert.equal(url.searchParams.get('start'),'2026-09-28');assert.equal(url.searchParams.has('before'),false);h.result(1,[event('new')],{total:120,pageSize:50,nextCursor:'next50'});await tick();assert.equal(h.state().limit,50);
 const refresh=h.context.actions['activity-refresh']();assert.equal(new URL(h.requests[2].url,'https://test.invalid').searchParams.has('before'),false);h.result(2);await refresh;assert.equal(h.state().page,0);
});

test('CSV exports applied filters across pages, uses an ASCII filename and cleans its URL',async()=>{
 const h=setup();await h.ready([event('a')],{total:50,nextCursor:'cursor'});h.change('start','2020-01-01');
 const pending=h.context.actions['activity-export']();h.context.actions['activity-export']();assert.equal(h.downloads.length,1);
 const request=h.downloads[0],url=new URL(request.url,'https://test.invalid');assert.equal(url.pathname,'/api/activity/export');assert.equal(url.searchParams.get('start'),'2026-09-28');assert.equal(url.searchParams.has('before'),false);assert.equal(url.searchParams.has('limit'),false);assert.equal(request.options.credentials,'same-origin');assert.equal(request.options.redirect,'error');
 const blob={csv:true};request.resolve({ok:true,headers:{get:()=> 'text/csv; charset=utf-8'},blob:async()=>blob});await pending;
 assert.equal(h.links[0].download,'activity-20260928-20261027.csv');assert.equal(h.links[0].clicked,true);assert.equal(h.links[0].removed,true);assert.equal(h.blobs[0],blob);assert.equal(h.state().exporting,false);
 assert.match(h.state().exportNotice,/2026-09-28 ~ 2026-10-27/);h.timers.find(t=>t.delay===1000).callback();assert.deepEqual(h.revoked,['blob:activity-test']);
});

test('JSON errors, login HTML and failed network never save a fake CSV',async()=>{
 for(const mode of ['json','html','network']){
  const h=setup();await h.ready();const pending=h.context.actions['activity-export']();
  if(mode==='json')h.downloads[0].resolve({ok:false,status:400,json:async()=>({error:'50,000건을 초과했습니다.'})});
  if(mode==='html')h.downloads[0].resolve({ok:true,headers:{get:()=> 'text/html'},blob:async()=>assert.fail('HTML must not be read as a blob')});
  if(mode==='network')h.downloads[0].reject(new TypeError('private network detail'));
  await pending;assert.equal(h.links.length,0);assert.equal(h.blobs.length,0);assert.equal(h.state().exporting,false);assert.ok(h.state().exportError);assert.doesNotMatch(h.panel.html,/private network detail/);
 }
});

test('malicious names, identifiers and API errors are rendered as text',async()=>{
 const h=setup();await h.ready([event('x',{toolName:'<img src=x onerror=bad()>',userName:'"<script>bad</script>',user:'<svg>',tool:'<iframe>',version:'<b>'})]);
 assert.doesNotMatch(h.panel.html,/<img|<script|<iframe|<b>/);assert.match(h.panel.html,/&lt;img/);assert.match(h.panel.html,/&quot;&lt;script/);
 const next=h.context.actions['activity-refresh']();h.requests[1].reject(Error('<script>failure</script>'));await next;assert.doesNotMatch(h.panel.html,/<script>/);assert.match(h.panel.html,/&lt;script&gt;failure/);
});

test('legacy unknown sources stay unknown and record labels do not imply current ranks',async()=>{
 const h=setup();await h.ready([event('like',{kind:'like',channel:'unknown',counted:true}),event('old',{imported:true,channel:'unknown'}),event('unlike',{kind:'unlike',channel:'unknown'})]);
 assert.match(h.panel.html,/기존 기록에 이용 경로가 없습니다/);assert.match(h.panel.html,/좋아요 추가/);assert.match(h.panel.html,/기존 집계 이전/);assert.doesNotMatch(h.panel.html,/현재 순위 반영/);
});

test('filter submit owns the event and never invokes unrelated form handlers',async()=>{
 const h=setup(),listener=h.listeners.submit[0];assert.equal(listener.capture,true);let prevented=0,stopped=0;
 listener.callback({target:{id:'ws-activity-filter'},preventDefault(){prevented++;},stopImmediatePropagation(){stopped++;}});assert.equal(prevented,1);assert.equal(stopped,1);assert.equal(h.requests.length,1);h.result(0);await tick();
 listener.callback({target:{id:'other-form'},preventDefault(){assert.fail();},stopImmediatePropagation(){assert.fail();}});
});

test('both live workspace entry actions initialize history through its loader',async()=>{
 const h=setup();h.context.work.tab='tools';
 const handlers=workspaceSource.match(/ 'workspace-tab':[^\n]+/)[0]+workspaceSource.match(/ 'admin-tab':[^\n]+/)[0];
 vm.runInContext('Object.assign(actions,{'+handlers+'});',h.context);
 const first=h.context.actions['workspace-tab']({dataset:{tab:'activity'}});assert.equal(h.requests.length,1);h.result(0);await first;
 h.context.work.tab='storage';const second=h.context.actions['admin-tab']({dataset:{tab:'activity'}});assert.equal(h.requests.length,2);h.result(1);await second;
 assert.equal(h.context.state.route,'admin');assert.equal(h.state().ready,true);
});

test('optional fields omitted by read-only dummy mode produce a clear empty table',async()=>{
 const h=setup(),pending=h.context.openActivityHistory();h.requests[0].resolve({events:[],nextCursor:null,backend:'dummy'});await pending;assert.equal(h.state().total,0);assert.match(h.panel.html,/선택한 조건의 이력이 없습니다/);
});
