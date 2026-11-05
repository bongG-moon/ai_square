const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_recommendations.js'),'utf8');
const workspace=fs.readFileSync(path.join(__dirname,'../frontend/frontend_workspace.js'),'utf8');
const bundle=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
const plain=x=>JSON.parse(JSON.stringify(x));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {resolve,reject,promise};};
const badge=(extra={})=>({active:true,status:'active',reason:'반복 보고서 정리에 유용합니다.',reviewedVersion:2,updatedAt:42,...extra});
const item=(extra={})=>({id:7,name:'보고서 정리',type:'Skill',org:'기술팀',platform:'Claude',icon:'file-text',desc:'표를 정리합니다.',access:'approved',active:2,revision:4,editorial:2,likes:5,downloads:7,workTags:[],recommendationBadge:badge(),...extra});
function setup(){
 const requests=[],opened=[],errors=[],notices=[],nodes={},inserted=[],dialog={open:false},listeners={};let refreshCount=0,refreshFailure=null,detailImpl=null;
 const c={actions:{},runtime:{detailLoadToken:0},server:{user:{id:'admin',role:'admin'}},state:{route:'browse',query:'',liked:new Set()},activeDetailView:null,root:{addEventListener:(name,handler)=>{listeners[name]=handler;},contains:()=>true},
 items:[item()],esc:v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),
 icon:n=>`<i data-lucide="${n}" aria-hidden="true"></i>`,num:String,typeLabel:x=>x==='Skill'?'SKILL':x,tagChips:()=>'',
 button:(action,label,css='',attrs='')=>`<button data-action="${action}" class="${css}" ${attrs}>${label}</button>`,
 Core:{sort:(rows,order)=>[...rows].sort((a,b)=>order==='downloads'?b.downloads-a.downloads:order==='recent'?b.created-a.created:order==='name'?a.name.localeCompare(b.name,'ko'):a.editorial-b.editorial)},
 $:selector=>selector==='#sq-dialog'?dialog:nodes[selector]||null,getItem:id=>c.items.find(x=>x.id===Number(id)),mountIcons(){},
 async detail(id,tab){if(detailImpl)return detailImpl(id,tab);c.runtime.detailId=Number(id);c.runtime.detailTab=tab;c.activeDetailView=Number(id);dialog.open=true;},
 openModal(title,kicker,html){c.runtime.detailLoadToken++;c.activeDetailView=null;dialog.open=true;opened.push({title,kicker,html});for(const key of Object.keys(nodes))delete nodes[key];
  const match=html.match(/<textarea id="ws-recommendation-reason"[^>]*>([\s\S]*?)<\/textarea>/);
  if(match)nodes['#ws-recommendation-reason']=node({value:match[1]});
  for(const [,action] of html.matchAll(/data-action="(recommendation-[^"]+)"/g))nodes[`[data-action="${action}"]`]=node({dataset:{action},isConnected:true});
  if(html.includes('id="ws-recommendation-error"'))nodes['#ws-recommendation-error']=node({hidden:true,textContent:''});
  if(html.includes('id="ws-recommendation-recovery"'))nodes['#ws-recommendation-recovery']=node({hidden:true});
 },
 closeModal(){c.runtime.detailLoadToken++;c.activeDetailView=null;dialog.open=false;},
 requestAPI(url,method='GET',body){const d=deferred();requests.push({...d,url,method,body});return d.promise;},
 async refresh(){refreshCount++;if(refreshFailure)throw refreshFailure;return true;},showError:e=>errors.push(e),announce:message=>notices.push(message)};
 function node(extra={}){return {disabled:false,hidden:false,setAttribute(name,value){this[name]=value;},focus(){this.focused=true;},scrollIntoView(){this.scrolled=true;},remove(){this.removed=true;},...extra};}
 vm.createContext(c);vm.runInContext(bundle.split('\n').find(line=>line.startsWith('function card(')),c);
 vm.runInContext(workspace.slice(workspace.indexOf('async function afterWorkspaceSave('),workspace.indexOf('const originalRender=')),c);
 vm.runInContext(source,c);
 return {c,requests,opened,errors,notices,nodes,dialog,inserted,get refreshCount(){return refreshCount;},failRefresh(error){refreshFailure=error;},detail(handler){detailImpl=handler;},click(action){const b=nodes[`[data-action="${action}"]`],event={target:{closest:()=>b},preventDefault(){this.prevented=true;},stopImmediatePropagation(){this.stopped=true;}};return {event,promise:listeners.click(event)};},hero(){nodes['#sq-dialog-body .sq-detail-hero']={insertAdjacentHTML(where,html){inserted.push({where,html});nodes['#sq-recommendation-reason']=node();}};}};
}
async function open(h,row=item()){const pending=h.c.openRecommendationEditor(row.id);h.requests.at(-1).resolve(row);await pending;}
function reply(request,extra={}){request.resolve({ok:true,revision:5,recommendationBadge:badge(),pending:false,...extra});}

test('native badge button leads footer metadata, uses outlined star, and leaks no reason',()=>{
 const h=setup(),html=h.c.card(item({name:'<script>unsafe</script>',org:'긴 조직 이름'}));
 const footer=html.slice(html.indexOf('<div class="sq-tool-footer">'));
 assert.ok(footer.indexOf('sq-recommendation-badge')<footer.indexOf('sq-tool-type'));assert.ok(footer.indexOf('sq-tool-type')<footer.indexOf('sq-tool-organization'));
 assert.match(footer,/<button type="button"[^>]*aria-label="&lt;script&gt;unsafe&lt;\/script&gt; 추천 이유 보기"[^>]*aria-haspopup="dialog"/);
 assert.match(footer,/data-lucide="star"/);assert.doesNotMatch(footer,/관리자|반복 보고서 정리/);
 assert.ok(html.indexOf('</button>')<html.indexOf('sq-recommendation-badge'),'badge is outside the main card button');
 assert.equal((html.match(/sq-type-label/g)||[]).length,1);assert.match(html,/data-action="like"/);
 assert.doesNotMatch(h.c.card(item({recommendationBadge:badge({active:false,status:'needs_review'})})),/sq-recommendation-badge/);
});
test('recommendations first only for default browse; editorial order, explicit sorts and home ranks remain',()=>{
 const h=setup(),rows=[item({id:1,editorial:1,downloads:100,created:9,recommendationBadge:badge({active:false})}),item({id:2,editorial:3,downloads:2,created:3}),item({id:3,editorial:2,downloads:10,created:6}),item({id:4,editorial:4,downloads:1,created:1,recommendationBadge:badge({active:false})})];
 const ids=order=>plain(h.c.Core.sort(rows,order).map(x=>x.id));
 assert.deepEqual(ids('discovery'),[3,2,1,4]);assert.deepEqual(rows.map(x=>x.id),[1,2,3,4]);
 assert.deepEqual(ids('downloads'),[1,3,2,4]);assert.deepEqual(ids('recent'),[1,3,2,4]);
 h.c.state.query='보고서';assert.deepEqual(ids('discovery'),[1,3,2,4]);h.c.state.query='';h.c.state.route='home';assert.deepEqual(ids('discovery'),[1,3,2,4]);
});
test('reason requires full detail permission and checked version and escapes all free text',()=>{
 const h=setup(),html=h.c.recommendationDetailHTML(item({recommendationBadge:badge({reason:'<img onerror="bad">\n유용합니다.'})}));
 assert.match(html,/추천하는 이유/);assert.match(html,/확인한 버전 v2/);assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<img|관리자/);
 for(const row of [item({access:'pending'}),item({access:'none'}),item({recommendationBadge:badge({reason:'',reviewedVersion:null})}),item({recommendationBadge:badge({active:false})})])assert.equal(h.c.recommendationDetailHTML(row),'');
});
test('badge activation revalidates detail and focuses reason; locked or stale detail never inserts it',async()=>{
 const h=setup();h.hero();await h.c.actions['recommendation-info']({dataset:{id:'7'}});assert.equal(h.inserted.length,1);assert.equal(h.nodes['#sq-recommendation-reason'].focused,true);
 h.c.items[0].access='pending';h.inserted.length=0;await h.c.detail(7,'intro');assert.equal(h.inserted.length,0);
 h.c.items[0].access='approved';const d=deferred();h.detail(async()=>{await d.promise;});const pending=h.c.detail(7,'intro');h.c.server.user.id='changed';d.resolve();await pending;assert.equal(h.inserted.length,0);
});
test('admin action appears only in admin live tool list; new versions show recheck state',()=>{
 const h=setup();assert.equal(h.c.recommendationAdminControl(item()),'');h.c.state.route='admin';assert.match(h.c.recommendationAdminControl(item()),/추천 설정/);assert.match(h.c.recommendationAdminControl(item({recommendationBadge:badge({active:false,status:'needs_review'})})),/재확인 필요/);
 h.c.server.user.role='member';assert.equal(h.c.recommendationAdminControl(item()),'');h.c.server.user.role='admin';assert.equal(h.c.recommendationAdminControl(item({deleted:true})), '');
 assert.match(workspace,/isAdmin\?recommendationAdminControl\(x\):''/);
});
test('editor freshly loads version, requires reason and blocks duplicate saves',async()=>{
 const h=setup();await open(h,item({active:3,revision:9,recommendationBadge:badge({active:false,status:'needs_review'})}));
 assert.equal(h.requests[0].url,'/api/tools/7');assert.match(h.opened.at(-1).html,/현재 버전 v3/);assert.match(h.opened.at(-1).html,/새 버전이 등록/);assert.match(h.opened.at(-1).html,/maxlength="300"/);
 h.nodes['#ws-recommendation-reason'].value='   ';await h.c.saveRecommendation(true);assert.equal(h.requests.length,1);assert.match(h.nodes['#ws-recommendation-error'].textContent,/1~300자/);
 h.nodes['#ws-recommendation-reason'].value='  설명을 확인했습니다.  ';const save=h.c.saveRecommendation(true);await h.c.saveRecommendation(true);assert.equal(h.requests.length,2);assert.deepEqual(plain(h.requests[1].body),{enabled:true,reason:'설명을 확인했습니다.',expectedRevision:9});assert.equal(h.nodes['#ws-recommendation-reason'].disabled,true);
 reply(h.requests[1],{revision:10,pending:true});await save;assert.equal(h.dialog.open,false);assert.equal(h.refreshCount,1);assert.equal(h.c.items[0].revision,10);assert.match(h.notices.at(-1),/추천을 저장/);
});
test('closing before save never mutates and removing recommendation requires its own confirmation',async()=>{
 const h=setup();await open(h);h.c.actions['recommendation-cancel']();await h.c.saveRecommendation(true);assert.equal(h.requests.length,1);
 await open(h);await h.c.saveRecommendation(false);assert.equal(h.requests.length,2);h.c.actions['recommendation-remove']();assert.match(h.opened.at(-1).title,/해제할까요/);assert.equal(h.requests.length,2);
 h.c.actions['recommendation-remove-cancel']();assert.match(h.opened.at(-1).title,/추천 설정/);h.c.actions['recommendation-remove']();const save=h.c.actions['recommendation-remove-confirm']();assert.deepEqual(plain(h.requests[2].body),{enabled:false,reason:'',expectedRevision:4});reply(h.requests[2],{recommendationBadge:badge({active:false,status:'none'})});await save;assert.match(h.notices.at(-1),/해제/);
});
test('late editor load cannot reopen a cancelled dialog or replace another user view',async()=>{
 const h=setup(),load=h.c.openRecommendationEditor(7);h.c.closeModal();h.requests[0].resolve(item());await load;assert.equal(h.dialog.open,false);
 const next=h.c.openRecommendationEditor(7);h.c.openModal('다른 화면','','유지');h.requests[1].reject(Error('늦은 오류'));await next;assert.equal(h.opened.at(-1).html,'유지');
 const switched=h.c.openRecommendationEditor(7);h.c.server.user.id='another';h.requests[2].resolve(item());await switched;assert.doesNotMatch(h.opened.at(-1).html,/ws-recommendation-reason/);
});
test('a cancelled in-flight read never blocks reopening and its late result cannot replace the newer editor',async()=>{
 const h=setup(),first=h.c.openRecommendationEditor(7);h.c.closeModal();const second=h.c.openRecommendationEditor(7);
 assert.equal(h.requests.length,2);h.requests[1].resolve(item({revision:8,active:3}));await second;assert.match(h.opened.at(-1).html,/현재 버전 v3/);
 h.requests[0].resolve(item({revision:4,active:2}));await first;assert.match(h.opened.at(-1).html,/현재 버전 v3/);
 const save=h.c.saveRecommendation(true);assert.equal(h.requests[2].body.expectedRevision,8);reply(h.requests[2],{revision:9});await save;
});
test('account switch during write does not mutate local items, close modal or refresh new account',async()=>{
 const h=setup();await open(h);const save=h.c.saveRecommendation(true);h.c.server.user.id='another';h.c.openModal('다른 계정','','다른 화면');reply(h.requests[1]);await save;assert.equal(h.c.items[0].revision,4);assert.equal(h.refreshCount,0);assert.equal(h.opened.at(-1).html,'다른 화면');assert.equal(h.dialog.open,true);
});
test('late successful save refreshes data but never closes an unrelated modal',async()=>{
 const h=setup();await open(h);const save=h.c.saveRecommendation(true);h.c.openModal('다른 화면','','이 화면 유지');reply(h.requests[1]);await save;assert.equal(h.refreshCount,1);assert.equal(h.opened.at(-1).html,'이 화면 유지');assert.equal(h.dialog.open,true);assert.equal(h.notices.length,0);
});
test('conflict and uncertain completion require read-only latest-state check before another write',async()=>{
 for(const error of [Object.assign(Error('충돌'),{status:409}),Object.assign(Error('연결 끊김'),{uncertain:true})]){
  const h=setup();await open(h);const save=h.c.saveRecommendation(true);h.requests[1].reject(error);await save;
  assert.equal(h.nodes['[data-action="recommendation-save"]'].disabled,true);assert.equal(h.nodes['#ws-recommendation-recovery'].hidden,false);await h.c.saveRecommendation(true);assert.equal(h.requests.length,2);
  const reload=h.c.actions['recommendation-reload']();assert.equal(h.requests[2].method,'GET');h.requests[2].resolve(item({revision:8,recommendationBadge:badge({reason:'서버에서 확인한 이유'})}));await reload;assert.equal(h.nodes['#ws-recommendation-reason'].value,'서버에서 확인한 이유');assert.equal(h.nodes['[data-action="recommendation-save"]'].disabled,false);
 }
});
test('delegated native button activation keeps uncertain saves disabled after the click promise settles',async()=>{
 const h=setup();await open(h);const click=h.click('recommendation-save');await Promise.resolve();assert.equal(click.event.prevented,true);assert.equal(click.event.stopped,true);
 h.requests[1].reject(Object.assign(Error('네트워크 끊김'),{uncertain:true}));await click.promise;
 assert.equal(h.nodes['[data-action="recommendation-save"]'].disabled,true);assert.equal(h.click('recommendation-save').promise,undefined);assert.equal(h.requests.length,2);
});
test('confirmed write plus refresh failure is reported as saved and cannot write again',async()=>{
 const h=setup();await open(h);h.failRefresh(Error('목록 불러오기 실패'));const save=h.c.saveRecommendation(true);reply(h.requests[1]);await save;
 assert.equal(h.errors.length,1);assert.equal(h.errors[0].saved,true);assert.match(h.errors[0].message,/서버에 저장/);await h.c.saveRecommendation(true);assert.equal(h.requests.length,2);
});
test('nonadmin never opens editor and failed detail read offers safe retry',async()=>{
 const h=setup();h.c.server.user.role='member';await h.c.openRecommendationEditor(7);assert.equal(h.requests.length,0);
 h.c.server.user.role='admin';const load=h.c.openRecommendationEditor(7);h.requests[0].reject(Error('접속 실패'));await load;assert.match(h.opened.at(-1).html,/recommendation-reload/);await h.c.saveRecommendation(true);assert.equal(h.requests.length,1);
});
test('maintained build includes recommendation module and compact CSS preserves footer flow',()=>{
 const build=fs.readFileSync(path.join(__dirname,'../scripts/build_workspace.py'),'utf8'),css=fs.readFileSync(path.join(__dirname,'../static/workspace.css'),'utf8');
 assert.match(build,/'frontend_recommendations.js'/);assert.match(css,/\.sq-tool-metadata\{[^}]*display:flex[^}]*min-width:0/);assert.match(css,/\.sq-recommendation-badge svg\{[^}]*fill:none/);assert.match(css,/\.sq-recommendation-badge:focus-visible/);
 assert.doesNotMatch(css.slice(css.indexOf('/* Recommendation metadata')),/position:absolute/);
});
