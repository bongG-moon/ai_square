const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_catalog.js'),'utf8');
function setup(){
 const nodes=new Map(),requests=[];let localRenders=0;
 const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'보고서를 만들고 싶어요',innerHTML:'',textContent:'',attributes:{},classList:{add(){}},setAttribute(k,v){this.attributes[k]=v;},removeAttribute(k){delete this.attributes[k];},focus(){this.focused=true;},select(){this.selected=true;}});return nodes.get(id);};
 const c={URLSearchParams,JSON,Number,Set,Promise,state:{route:'browse',query:'보고서를 만들고 싶어요',sort:'discovery',type:'전체',org:'전체 조직',category:'모든 업무',page:0,liked:new Set()},server:{user:{id:'member'},categories:[{id:'cat-a',name:'보고'}]},runtime:{refreshToken:1},items:[{id:1,name:'Old',likes:0,downloads:0}],organizations:[{id:'org-a',name:'개발팀',enabled:true},{id:'org-b',name:'운영팀',enabled:true}],toolTypes:['전체','Skill'],actions:{},$:node,
  renderCatalog(){localRenders++;},renderFilterTabs(){},render(){return c.renderCatalog();},persist(){},detail(id){c.opened=id;},invalidateDetailLoad(){return c.runtime.detailLoadToken=(c.runtime.detailLoadToken||0)+1;},async refresh(){c.items.push({id:2,versions:[{n:3}],canManage:false});},typeLabel:x=>x,esc:x=>String(x??'').replaceAll('<','&lt;').replaceAll('"','&quot;'),num:x=>String(x),icon:x=>x,button:(action,label,_class,attrs='')=>`<button data-action="${action}" ${attrs}>${label}</button>`,card:x=>`<article data-id="${x.id}">${x.name}:${x.downloads}</article>`,getItem:id=>c.items.find(x=>x.id===+id),scheduleOrgFilter(){},revealElements(){},mountIcons(){},requestAPI:url=>new Promise((resolve,reject)=>requests.push({url,resolve,reject}))};
 vm.createContext(c);vm.runInContext(source,c);return {c,nodes,node,requests,local:()=>localRenders,search:()=>vm.runInContext('catalogSearch',c)};
}
const row=(id=1,name='보고서 만들기')=>({id,name,type:'Skill',org:'개발팀',access:'approved',liked:false,statistics:{likes:3,downloads:7}});
const response=(items=[row()],extra={})=>({items,total:items.length,evaluatedCount:items.length,nextOffset:null,facets:{total:2,organizations:[{id:'org-a',name:'개발팀',count:1},{id:'org-b',name:'운영팀',count:1}]},...extra});
test('web sends natural sentence and taxonomy IDs; uses API order and server facets',async()=>{
 const t=setup(),{c}=t;c.state.org='개발팀';c.state.category='보고';const promise=c.renderCatalog();
 const url=new URL(t.requests[0].url,'https://square.test');assert.equal(url.searchParams.get('q'),c.state.query);assert.equal(url.searchParams.get('sort'),'recommended');assert.equal(url.searchParams.get('orgId'),'org-a');assert.equal(url.searchParams.get('categoryId'),'cat-a');
 assert.equal(t.node('#sq-catalog').attributes['aria-busy'],'true');assert.doesNotMatch(t.node('#sq-filter-tabs').innerHTML,/\(0\)/);
 t.requests[0].resolve(response([row(2,'HTML report'),row(1)]));await promise;
 assert.ok(t.node('#sq-catalog').innerHTML.indexOf('data-id="2"')<t.node('#sq-catalog').innerHTML.indexOf('data-id="1"'));
 assert.match(t.node('#sq-filter-tabs').innerHTML,/운영팀.*\(1\)/);assert.equal(c.getItem(2),undefined);assert.equal(c.getItem(1).downloads,0);
 await c.detail(2);assert.equal(c.opened,2);assert.equal(c.getItem(2).versions[0].n,3);
});
test('slow success and failure cannot overwrite a newer search or another account',async()=>{
 const t=setup(),{c}=t;const first=c.renderCatalog();c.state.query='엑셀';t.node('#sq-query').value='엑셀';const second=c.renderCatalog();
 t.requests[1].resolve(response([row(4,'Excel 비교')]));await second;t.requests[0].reject(Error('old failure'));await first;assert.match(t.node('#sq-catalog').innerHTML,/Excel 비교/);assert.doesNotMatch(t.node('#sq-catalog').innerHTML,/old failure/);
 c.state.query='메일';t.node('#sq-query').value='메일';const third=c.renderCatalog();c.server.user.id='another';t.requests[2].resolve(response([row(8,'private account result')]));await third;assert.doesNotMatch(t.node('#sq-catalog').innerHTML,/private account/);
});
test('search failure is not empty, retry clears failure, empty has useful recovery',async()=>{
 const t=setup(),{c}=t;const first=c.renderCatalog();t.requests[0].reject(Error('연결 오류'));await first;assert.match(t.node('#sq-result-count').textContent,/불러오지 못/);assert.match(t.node('#sq-catalog').innerHTML,/catalog-retry/);assert.equal(t.node('#sq-catalog').attributes['aria-busy'],undefined);
 const retry=c.actions['catalog-retry']();t.requests[1].resolve(response([],{total:0,evaluatedCount:0}));await retry;assert.doesNotMatch(t.node('#sq-catalog').innerHTML,/연결 오류/);assert.match(t.node('#sq-catalog').innerHTML,/필요한 업무를 짧게/);assert.doesNotMatch(t.node('#sq-catalog').innerHTML,/catalog-reset-filters/);
 c.state.org='개발팀';const filtered=c.renderCatalog();t.requests[2].resolve(response([],{total:0,evaluatedCount:0}));await filtered;assert.match(t.node('#sq-catalog').innerHTML,/catalog-reset-filters/);
});
test('pagination bounds evaluated candidates and preserves distinct sort meanings',async()=>{
 const t=setup(),{c}=t;c.state.sort='downloads';c.state.page=1;const first=c.renderCatalog();assert.match(t.requests[0].url,/sort=downloads/);assert.match(t.requests[0].url,/offset=12/);
 t.requests[0].resolve(response([row()],{total:9000,evaluatedCount:13,warning:'일부 후보만 평가',nextOffset:null}));await first;assert.match(t.node('#sq-catalog-pages').innerHTML,/2 \/ 2/);assert.match(t.node('#sq-catalog-pages').innerHTML,/catalog-next" disabled/);assert.match(t.node('#sq-catalog').innerHTML,/일부 후보만 평가/);
 c.state.sort='name';const next=c.renderCatalog();assert.match(t.requests[1].url,/sort=name/);t.requests[1].resolve(response([row()],{total:13,evaluatedCount:13}));await next;
});
test('demo and unsearched home/browse keep local editorial path without server reads',()=>{
 const t=setup(),{c}=t;c.server.dataMode='dummy';c.renderCatalog();assert.equal(t.local(),1);delete c.server.dataMode;c.state.query='';c.renderCatalog();assert.equal(t.local(),2);c.state.route='home';c.state.query='report';c.renderCatalog();assert.equal(t.local(),3);assert.equal(t.requests.length,0);
});
test('same request deduplicates, refresh invalidates, transient edits cannot leave loading stuck',async()=>{
 const t=setup(),{c}=t;const a=c.renderCatalog();assert.equal(c.renderCatalog(),a);assert.equal(t.requests.length,1);t.node('#sq-query').value='new pending input';t.requests[0].resolve(response([row(9,'applied query result')]));await a;t.node('#sq-query').value=c.state.query;await c.renderCatalog();assert.match(t.node('#sq-catalog').innerHTML,/applied query result/);assert.equal(t.search().phase,'ready');
 c.state.query='new pending input';const b=c.renderCatalog();c.runtime.refreshToken++;t.requests[1].resolve(response());await b;assert.equal(t.search().phase,'ready');c.server.rankAsOf=2;const d=c.renderCatalog();assert.equal(t.requests.length,3);t.requests[2].resolve(response());await d;
});
