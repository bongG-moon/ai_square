const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../ui/store.js'),'utf8');
class Node {
 constructor(tag='div',cls='',text=''){this.tag=tag;this.className=cls;this.text=text;this.children=[];this.dataset={};this.attributes={};this.style={};this.hidden=false;this.disabled=false;this.value='';this.classList={toggle:()=>{},add:()=>{}};}
 get textContent(){return this.text+this.children.map(n=>n.textContent).join('');}set textContent(v){this.text=String(v);this.children=[];}
 append(...nodes){for(const n of nodes){n.parent=this;this.children.push(n);}}
 replaceChildren(...nodes){this.text='';this.children=[];this.append(...nodes);}
 setAttribute(k,v){this.attributes[k]=String(v);}removeAttribute(k){delete this.attributes[k];}
 remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);}
 querySelectorAll(selector){return this.children.flatMap(n=>[...(selector==='[data-list-notice]'&&n.dataset.listNotice?[n]:[]),...n.querySelectorAll(selector)]);}
}
function setup(){
 const ids=['results','results-label','more','catalog-toolbar','catalog-note','search','type-filter','org-filter','sort','feedback','catalog-view'];
 const nodes=Object.fromEntries(ids.map(id=>[id,new Node()]));nodes.feedback.textContent='설치 파일 확인이 필요해요.';nodes.more.hidden=true;
 const tabs=['catalog','installed','updates'].map(tab=>{const n=new Node();n.dataset.tab=tab;return n;}),calls=[],feedback=[];
 const c={$:id=>nodes[id],el:(...args)=>new Node(...args),button:(label,cls,fn)=>{const b=new Node('button',cls,label);b.run=fn;return b;},
  state:{tab:'catalog',generation:0,connectionGeneration:1,baseUrl:'https://platform.example',offset:null,connected:true,records:[]},
  document:{querySelectorAll:()=>tabs},clearTimeout(){},debounce:null,closeDetail(){},show(){},revealPanel(){},
  feedback:(...args)=>feedback.push(args),recoveryCards:()=>[],reconcileInstallation(){},
  recordName:r=>r.name||'설치 기능',recordCard:r=>{const n=new Node('article','install-record',r.name);n.dataset.record=r.installationId;return n;},
  toolCard:r=>{const n=new Node('article','tool-card',r.name);n.dataset.toolId=r.id;return n;},
  rpc:(action,payload,current)=>new Promise((resolve,reject)=>calls.push({action,payload,current,resolve,reject}))};
 vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('  function empty('),source.indexOf('  function recoveryCards(')),c);
 vm.runInContext(source.slice(source.indexOf('  let listRequest ='),source.indexOf('  function symbol(')),c);
 return {c,nodes,calls,feedback};
}
const response=(items=[],nextOffset=null)=>({items,total:items.length,nextOffset});
const item=(id)=>({id,name:'기능 '+id});
test('first failure replaces every loading state, retry distinguishes successful empty and preserves installation feedback',async()=>{
 const h=setup(),load=h.c.loadTab('catalog');assert.equal(h.nodes.results.dataset.listState,'loading');assert.equal(h.nodes.results.attributes['aria-busy'],'true');assert.match(h.nodes['results-label'].textContent,/불러오는 중/);
 h.calls.shift().reject(Error('서버에 연결하지 못했어요.'));await load;
 assert.equal(h.nodes.results.dataset.listState,'error');assert.equal(h.nodes.results.attributes['aria-busy'],'false');assert.equal(h.nodes.more.hidden,true);assert.equal(h.nodes.more.disabled,false);assert.match(h.nodes['results-label'].textContent,/불러오지 못/);assert.doesNotMatch(h.nodes.results.textContent,/불러오는 중/);
 const retry=h.nodes.results.children[0].children.at(-1).run();assert.equal(h.nodes.results.dataset.listState,'loading');h.calls.shift().resolve(response());await retry;
 assert.equal(h.nodes.results.dataset.listState,'empty');assert.equal(h.nodes.results.attributes['aria-busy'],'false');assert.equal(h.nodes['results-label'].textContent,'등록된 기능 0개');assert.match(h.nodes.results.textContent,/조건에 맞는 기능이 없어요/);
 assert.equal(h.nodes.feedback.textContent,'설치 파일 확인이 필요해요.');assert.deepEqual(h.feedback,[]);
});
test('installed and updates failures reset heading and aria state, with list-specific timeout advice',async()=>{
 for(const tab of ['installed','updates']){
  const h=setup(),load=h.c.loadTab(tab);assert.equal(h.calls[0].action,tab==='installed'?'installations':'checkUpdates');
  h.calls.shift().reject(Object.assign(Error('같은 설치를 다시 실행하지 않습니다.'),{code:'response_timeout'}));await load;
  assert.equal(h.nodes.results.dataset.listState,'error');assert.equal(h.nodes.results.attributes['aria-busy'],'false');assert.match(h.nodes.results.textContent,/목록 응답을 제시간에/);assert.doesNotMatch(h.nodes.results.textContent,/같은 설치/);assert.doesNotMatch(h.nodes['results-label'].textContent,/확인하고/);
  const retry=h.c.loadTab(tab);h.calls.shift().resolve({items:[],complete:true});await retry;assert.equal(h.nodes.results.dataset.listState,'empty');assert.equal(h.nodes.more.hidden,true);
 }
});
test('append failure keeps earlier cards and cursor, duplicate pending clicks do not enqueue, retry uses same offset',async()=>{
 const h=setup(),first=h.c.loadTab('catalog');h.calls.shift().resolve({...response([item(1)],20),total:3});await first;
 const card=h.nodes.results.children[0],append=h.c.catalog(true);assert.equal(h.calls[0].payload.offset,20);assert.equal(h.nodes.more.disabled,true);await h.c.catalog(true);assert.equal(h.calls.length,1);
 h.calls.shift().reject(Error('다음 페이지 응답 없음'));await append;assert.equal(h.nodes.results.children[0],card);assert.equal(h.c.state.offset,20);assert.equal(h.nodes.more.hidden,false);assert.equal(h.nodes.more.textContent,'다시 불러오기');assert.equal(h.nodes.results.dataset.listState,'error');
 const retry=h.c.catalog(true);assert.equal(h.calls[0].payload.offset,20);assert.equal(h.nodes.results.querySelectorAll('[data-list-notice]').length,0);h.calls.shift().resolve({...response([item(2)],null),total:2});await retry;
 assert.equal(h.nodes.results.children[0],card);assert.equal(h.nodes.results.children.length,2);assert.equal(h.nodes.results.dataset.listState,'ready');assert.equal(h.nodes.more.hidden,true);assert.equal(h.nodes.results.attributes['aria-busy'],'false');
});
test('outdated successes and failures cannot overwrite a newer query or tab',async()=>{
 const h=setup();h.nodes.search.value='이전';const old=h.c.loadTab('catalog'),oldRpc=h.calls.shift();h.nodes.search.value='최신';const latest=h.c.loadTab('catalog');h.calls.shift().resolve(response([item(2)]));await latest;
 assert.equal(oldRpc.current(),false);oldRpc.reject(Error('예전 연결 오류'));await old;assert.equal(h.nodes.results.children[0].dataset.toolId,2);assert.equal(h.nodes.results.dataset.listState,'ready');assert.deepEqual(h.feedback,[]);
 const obsolete=h.c.loadTab('catalog'),obsoleteRpc=h.calls.shift(),installed=h.c.loadTab('installed');h.calls.shift().resolve({items:[{name:'설치 기록',installationId:'record1'}]});await installed;
 obsoleteRpc.resolve(response([item(9)]));await obsolete;assert.equal(h.nodes.results.children[0].dataset.record,'record1');assert.equal(h.nodes['results-label'].textContent,'설치된 기능 1개');
});
test('changed connection invalidates an old list, including rejected queued request',async()=>{
 const h=setup(),old=h.c.loadTab('catalog'),oldRpc=h.calls.shift();h.c.state.connectionGeneration++;h.c.state.baseUrl='https://other.example';
 const current=h.c.loadTab('catalog');h.calls.shift().resolve(response([item(4)]));await current;assert.equal(oldRpc.current(),false);oldRpc.reject(Error('기존 KEY 오류'));await old;
 assert.equal(h.nodes.results.children[0].dataset.toolId,4);assert.equal(h.nodes.results.attributes['aria-busy'],'false');assert.deepEqual(h.feedback,[]);
});
test('query change before pagination uses a fresh first page; warnings stay in list region',async()=>{
 const h=setup(),first=h.c.loadTab('catalog');h.calls.shift().resolve({...response([item(1)],20),warning:'표본이 적어요.'});await first;assert.equal(h.nodes.results.querySelectorAll('[data-list-notice]').length,1);
 h.nodes.search.value='새 검색';h.c.state.generation++;const more=h.c.catalog(true);assert.equal(h.calls[0].payload.offset,0);assert.equal(h.calls[0].payload.q,'새 검색');h.calls.shift().resolve(response([item(3)]));await more;
 assert.equal(h.nodes.results.children.length,1);assert.equal(h.nodes.results.children[0].dataset.toolId,3);assert.equal(h.nodes.results.querySelectorAll('[data-list-notice]').length,0);assert.equal(h.nodes.feedback.textContent,'설치 파일 확인이 필요해요.');
});
