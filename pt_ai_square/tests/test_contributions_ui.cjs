const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_contributions.js'),'utf8');
const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function response(extra={}){return {summary:{registered:3,likes:4,downloads:6,score:29},weights:{registered:5,likes:2,downloads:1},items:[{id:1,name:'업무 보고서',status:'active',registered:1,likes:2,downloads:3,score:12}],totalItems:3,page:1,pageSize:20,totalPages:1,asOf:1793116800,...extra};}
function setup(){
 const requests=[],panel={html:'',renders:0};
 const c={actions:{},state:{route:'manage'},work:{tab:'contributions'},server:{user:{id:'owner',role:'member'}},esc,icon:n=>`<svg data-icon="${n}"></svg>`,
  button:(action,label,cls='',extra='')=>`<button class="${cls}" data-action="${action}" ${extra}>${label}</button>`,
  renderWorkspace(){panel.html=c.contributionPanel();panel.renders++;c.ensureContributions();},
  navigate(route){c.state.route=route;c.renderWorkspace();},
  requestAPI(url){const pending=deferred();requests.push({...pending,url});return pending.promise;}
 };
 vm.createContext(c);vm.runInContext(source,c,{filename:'frontend_contributions.js'});
 return {c,requests,panel,get state(){return c.contributionState();},async ready(data=response()){const p=c.openContributions();requests.at(-1).resolve(data);await p;}};
}

test('opening the personal tab fetches one page only and renders loading state',async()=>{
 const h=setup();assert.equal(h.requests.length,0);
 const p=h.c.openContributions();h.c.renderWorkspace();h.c.renderWorkspace();
 assert.equal(h.requests.length,1);assert.equal(h.requests[0].url,'/api/me/contributions?page=1&pageSize=20');
 assert.match(h.panel.html,/aria-busy="true"/);assert.match(h.panel.html,/불러오고 있어요/);
 h.requests[0].resolve(response());await p;
 assert.match(h.panel.html,/전체 기여도/);assert.match(h.panel.html,/<strong>29<small>점/);
 assert.match(h.panel.html,/3 × 5점 <b>15점/);assert.match(h.panel.html,/4 × 2점 <b>8점/);assert.match(h.panel.html,/6 × 1점 <b>6점/);
 assert.match(h.panel.html,/<table class="ws-contribution-table">/);assert.match(h.panel.html,/도구 #1/);assert.match(h.panel.html,/scope="col">합계/);
});

test('own restricted names are escaped and deletion snapshots have no detail links',async()=>{
 const h=setup();await h.ready(response({items:[
  {id:1,name:'<img src=x onerror=alert(1)>',status:'active',registered:1,likes:2,downloads:0,score:9},
  {id:2,name:'휴지통 도구',status:'trash',registered:1,likes:0,downloads:2,score:7},
  {id:3,name:'예전 도구',status:'deleted',registered:1,likes:2,downloads:4,score:13}
 ]}));
 assert.doesNotMatch(h.panel.html,/<img src=x/);assert.match(h.panel.html,/&lt;img src=x/);
 for(const text of ['사용 중','휴지통','삭제됨','삭제 시점의 점수'])assert.ok(h.panel.html.includes(text));
 assert.doesNotMatch(h.panel.html,/href=|data-action="(?:detail|open-tool)"/);
 assert.match(h.panel.html,/도구를 삭제해도 기여도는 유지됩니다/);
});

test('pagination replaces rows, keeps full summary and prevents duplicate requests',async()=>{
 const h=setup();await h.ready(response({totalItems:41,totalPages:3}));
 const p=h.c.actions['contribution-next']();h.c.actions['contribution-next']();h.c.actions['contribution-refresh']();
 assert.equal(h.requests.length,2);assert.match(h.requests[1].url,/page=2&/);assert.doesNotMatch(h.panel.html,/업무 보고서/);
 h.requests[1].resolve(response({items:[{id:21,name:'두 번째 페이지',status:'deleted',registered:1,likes:0,downloads:0,score:5}],page:2,totalItems:41,totalPages:3}));await p;
 assert.match(h.panel.html,/두 번째 페이지/);assert.match(h.panel.html,/<strong>29<small>점/);assert.match(h.panel.html,/2 \/ 3/);
 const prev=h.c.actions['contribution-previous']();assert.match(h.requests[2].url,/page=1&/);h.requests[2].resolve(response());await prev;
 assert.equal(h.state.page,1);assert.equal(h.c.actions['contribution-previous'](),undefined);assert.equal(h.c.actions['contribution-next'](),undefined);
});

test('a failed page hides previous rows and retries the exact requested page',async()=>{
 const h=setup();await h.ready(response({totalItems:41,totalPages:3}));const p=h.c.actions['contribution-next']();
 h.requests[1].reject(new TypeError('private network details'));await p;
 assert.match(h.panel.html,/role="alert"/);assert.match(h.panel.html,/잠시 후 다시 시도/);assert.doesNotMatch(h.panel.html,/private network|업무 보고서/);
 const retry=h.c.actions['contribution-retry']();assert.equal(h.requests[2].url,h.requests[1].url);h.requests[2].resolve(response({page:2,totalItems:41,totalPages:3}));await retry;
 assert.equal(h.state.error,'');assert.equal(h.state.page,2);
});

test('a newer open wins even if an older request finishes later',async()=>{
 const h=setup(),old=h.c.openContributions(),latest=h.c.openContributions();assert.equal(h.requests.length,2);
 h.requests[1].resolve(response({items:[{id:5,name:'최신 도구',status:'active',registered:1,likes:0,downloads:0,score:5}]}));await latest;
 h.requests[0].resolve(response());assert.equal(await old,false);assert.match(h.panel.html,/최신 도구/);assert.doesNotMatch(h.panel.html,/업무 보고서/);
});

test('leaving the tab prevents a late response from rendering or becoming fresh cache',async()=>{
 const h=setup(),p=h.c.openContributions();h.c.work.tab='tools';const renders=h.panel.renders;
 h.requests[0].resolve(response());assert.equal(await p,false);assert.equal(h.panel.renders,renders);assert.equal(h.state.data,null);assert.equal(h.state.requested,false);
});

test('changing signed-in user clears the previous owner and ignores its response',async()=>{
 const h=setup(),old=h.c.openContributions();h.c.server.user.id='second-owner';h.c.renderWorkspace();
 assert.equal(h.requests.length,2);assert.equal(h.state.user,'second-owner');assert.equal(h.state.data,null);
 h.requests[0].resolve(response());assert.equal(await old,false);assert.doesNotMatch(h.panel.html,/업무 보고서/);
 h.requests[1].resolve(response({items:[],summary:{registered:0,likes:0,downloads:0,score:0},totalItems:0,totalPages:0}));
 await new Promise(setImmediate);assert.match(h.panel.html,/아직 등록한 도구가 없습니다/);assert.match(h.panel.html,/첫 도구 등록하기/);assert.doesNotMatch(h.panel.html,/<table/);
});

test('refresh always starts at page one and errors stay in the panel',async()=>{
 const h=setup();await h.ready(response({page:3,totalItems:41,totalPages:3}));const p=h.c.actions['contribution-refresh']();
 assert.match(h.requests[1].url,/page=1&/);h.requests[1].reject(Object.assign(Error('<로그인이 필요합니다>'),{status:401}));await p;
 assert.match(h.panel.html,/&lt;로그인이 필요합니다&gt;/);assert.doesNotMatch(h.panel.html,/<로그인이/);
});
