const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{test}=require('node:test');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_experience.js'),'utf8');
function drafts(){
 const stored=new Map(),runtime={draftOwner:'owner',releaseId:null,step:2,draft:{name:'Example',desc:'Draft',workTags:'test',approval:true,mode:'url',url:'PRIVATE_URL',guide:'PRIVATE_GUIDE',file:{name:'PRIVATE_FILE'}}};
 const context={runtime,server:{user:{id:'owner'}},sessionStorage:{getItem:k=>stored.get(k)??null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},Date,
  captureDraft(){},register(){},wizard(){},openModal(){},closeModal(){},$:()=>({addEventListener(){}}),root:{addEventListener(){}},window:{addEventListener(){}},actions:{},setTimeout,clearTimeout};
 vm.createContext(context);vm.runInContext(source.slice(0,source.indexOf('// Use the same authenticated')),context);return {context,runtime,stored};
}
test('only descriptive metadata and typed approval/mode are saved',()=>{
 const h=drafts();h.context.saveRegistrationDraft();const value=[...h.stored.values()][0];
 assert(!value.includes('PRIVATE'));const saved=JSON.parse(value).new.data;assert.equal(saved.approval,true);assert.equal(saved.mode,'url');
});
test('closing an unchanged draft preserves revision so publish can clear it',()=>{
 const h=drafts();h.context.saveRegistrationDraft();const revision=h.context.registrationDraftRevision();h.context.saveRegistrationDraft();
 assert.equal(h.context.registrationDraftRevision(),revision);h.context.clearRegistrationDraft('owner',null,revision);assert.equal(h.stored.size,0);
});
test('new changes and file replacements survive a late older publish',()=>{
 const h=drafts();h.context.saveRegistrationDraft();const revision=h.context.registrationDraftRevision();h.runtime.draft.file={name:'new-file'};h.context.saveRegistrationDraft();
 assert(h.context.registrationDraftRevision()>revision);h.context.clearRegistrationDraft('owner',null,revision);assert.equal(h.stored.size,1);
 h.runtime.draft.name='Later';h.context.saveRegistrationDraft();h.context.clearRegistrationDraft('owner',null,revision);assert([...h.stored.values()][0].includes('Later'));
});
test('emptying all descriptive fields removes the old draft',()=>{
 const h=drafts();h.context.saveRegistrationDraft();Object.assign(h.runtime.draft,{name:'',desc:'',workTags:''});h.context.saveRegistrationDraft();assert.equal(h.stored.size,0);
});
test('late completion clears its captured account and target only',()=>{
 const h=drafts();h.context.saveRegistrationDraft();const revision=h.context.registrationDraftRevision();h.context.server.user.id='other';h.runtime.draftOwner='other';h.context.saveRegistrationDraft();
 h.context.clearRegistrationDraft('owner',null,revision);assert.equal(h.stored.size,1);assert([...h.stored.keys()][0].endsWith('other'));
});
function search(){
 const nodes=new Map(),items=[{id:1,name:'Tool',likes:0}],calls=[];
 const context={runtime:{},state:{route:'browse',query:'test',type:'전체',org:'전체 조직',category:'모든 업무',sort:'discovery',page:0,liked:new Set()},server:{user:{id:'owner'}},items,organizations:[],
  $:s=>{if(!nodes.has(s))nodes.set(s,{setAttribute(){},innerHTML:'',textContent:'',insertAdjacentHTML(){}});return nodes.get(s);},$$:()=>[],
  getItem:id=>items.find(row=>row.id===id),card:JSON.stringify,num:String,esc:String,icon:()=>'',button:()=>'',mountIcons(){},revealElements(){},navigate(){},renderCatalog(){},refresh:async()=>{},actions:{like(){}},URLSearchParams,
  requestAPI:()=>new Promise(resolve=>calls.push(resolve))};
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf('let catalogSearch=null;'),source.indexOf('// Zero activity')),context);
 return {context,items,calls,nodes};
}
const result=(id=1,liked=true)=>({items:[{id,name:'Found',liked,statistics:{likes:1,downloads:0}}],total:1,nextOffset:null,complete:true,evaluatedCount:1});
const tick=()=>new Promise(setImmediate);
test('catalog response updates a like changed by another client',async()=>{
 const h=search();h.context.loadCatalogSearch();h.calls.shift()(result());await tick();assert(h.context.state.liked.has(1));assert.equal(h.items[0].likes,0);
});
test('an in-flight like is not overwritten by an older search',async()=>{
 const h=search();h.context.loadCatalogSearch();h.context.actions.like();h.context.state.liked.add(1);h.calls.shift()(result(1,false));await tick();assert(h.context.state.liked.has(1));
});
test('search-only public summaries are bounded to current page and removed on clear',async()=>{
 const h=search();h.context.loadCatalogSearch();h.calls.shift()(result(2));await tick();assert.equal(h.items.length,2);
 h.context.state.query='next';h.context.loadCatalogSearch();assert.equal(h.items.length,1);h.calls.shift()(result(3));await tick();assert.equal(h.items.length,2);
 h.context.state.query='';h.context.renderCatalog();assert.deepEqual(h.items.map(row=>row.id),[1]);
});
test('bootstrap refresh invalidates the same-query cache',async()=>{
 const h=search();h.context.loadCatalogSearch();h.calls.shift()(result());await tick();await h.context.refresh();h.context.loadCatalogSearch();assert.equal(h.calls.length,1);
});
