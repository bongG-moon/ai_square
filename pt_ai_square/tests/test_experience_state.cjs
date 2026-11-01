// Preserve the published experience contracts while exercising the split controllers.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{test}=require('node:test');
const read=name=>fs.readFileSync(path.join(__dirname,'../frontend',name),'utf8');
function drafts(){
 const stored=new Map(),runtime={releaseId:null,step:2},freshDraft=()=>({name:'',desc:'',workTags:'',approval:false,mode:'file',url:'',guide:'',file:null});
 const context={runtime,server:{user:{id:'owner'}},sessionStorage:{getItem:k=>stored.get(k)??null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},Date,
  freshDraft,getItem:()=>null,captureDraft(){},register(){},wizard(){},navigate(){},openModal(){},closeModal(){},$:()=>({addEventListener(){},insertAdjacentHTML(){}}),root:{addEventListener(){}},window:{addEventListener(){}},actions:{},button:()=>'',esc:String,announce(){}};
 vm.createContext(context);vm.runInContext(read('frontend_registration_draft.js'),context);context.register();
 Object.assign(runtime.draft,{name:'Example',desc:'Draft',workTags:'test',approval:true,mode:'url',url:'https://example.test/',guide:'사용 안내',apiKey:'SECRET_KEY',file:{name:'example.zip',bytes:'SECRET_BYTES'},packageInspection:{raw:'SECRET_INSPECTION'}});
 return {context,runtime,stored,freshDraft};
}
test('form metadata survives reload but KEY, file bytes and inspection responses are never saved',()=>{
 const h=drafts();h.context.saveRegistrationDraft();const value=[...h.stored.values()][0];assert(!value.includes('SECRET'));
 const saved=JSON.parse(value).data;assert.equal(saved.approval,true);assert.equal(saved.mode,'url');assert.equal(saved.guide,'사용 안내');assert.equal(saved.url,'https://example.test/');assert.equal(saved.file,undefined);
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
test('clearing all form values back to the empty baseline removes the old draft',()=>{
 const h=drafts();h.context.saveRegistrationDraft();h.runtime.draft=h.freshDraft();h.context.saveRegistrationDraft();assert.equal(h.stored.size,0);
});
test('late completion clears its captured account and target only',()=>{
 const h=drafts();h.context.saveRegistrationDraft();const revision=h.context.registrationDraftRevision();h.context.server.user.id='other';h.context.register();h.runtime.draft.name='Other draft';h.context.saveRegistrationDraft();
 h.context.clearRegistrationDraft('owner',null,revision);assert.equal(h.stored.size,1);assert([...h.stored.keys()][0].includes('other'));
});
function search(){
 const nodes=new Map(),items=[{id:1,name:'Tool',likes:0}],calls=[];
 const node=s=>{if(!nodes.has(s))nodes.set(s,{setAttribute(){},removeAttribute(){},classList:{add(){}},innerHTML:'',textContent:'',insertAdjacentHTML(){}});return nodes.get(s);};
 const context={runtime:{},state:{route:'browse',query:'test',type:'전체',org:'전체 조직',category:'모든 업무',sort:'discovery',page:0,liked:new Set()},server:{user:{id:'owner'}},items,organizations:[],toolTypes:[],
  $:node,$$:()=>[],getItem:id=>items.find(row=>row.id===id),card:JSON.stringify,num:String,esc:String,icon:()=>'',button:()=>'',mountIcons(){},revealElements(){},navigate(){},renderCatalog(){},renderFilterTabs(){},scheduleOrgFilter(){},detail(){},refresh:async()=>{},actions:{like(){}},URLSearchParams,
  requestAPI:()=>new Promise(resolve=>calls.push(resolve))};
 vm.createContext(context);vm.runInContext(read('frontend_catalog.js'),context);return {context,items,calls,nodes};
}
const result=(id=1,liked=true)=>({items:[{id,name:'Found',liked,statistics:{likes:1,downloads:0}}],total:1,nextOffset:null,complete:true,evaluatedCount:1,facets:{total:1,organizations:[]}});
test('catalog response updates a like changed by another client',async()=>{
 const h=search(),pending=h.context.renderCatalog();h.calls.shift()(result());await pending;assert(h.context.state.liked.has(1));assert.equal(h.items[0].likes,0);
});
test('an in-flight like is not overwritten by an older search',async()=>{
 const h=search(),pending=h.context.renderCatalog();h.context.actions.like();h.context.state.liked.add(1);h.calls.shift()(result(1,false));await pending;assert(h.context.state.liked.has(1));
});
test('search-only public summaries never become bootstrap items, including after page changes',async()=>{
 const h=search();let pending=h.context.renderCatalog();h.calls.shift()(result(2));await pending;assert.equal(h.items.length,1);
 h.context.state.query='next';pending=h.context.renderCatalog();h.calls.shift()(result(3));await pending;assert.equal(h.items.length,1);
 h.context.state.query='';h.context.renderCatalog();assert.deepEqual(h.items.map(row=>row.id),[1]);
});
test('successful bootstrap refresh invalidates the same-query cache',async()=>{
 const h=search(),pending=h.context.renderCatalog();h.calls.shift()(result());await pending;await h.context.refresh();h.context.renderCatalog();assert.equal(h.calls.length,1);
});
