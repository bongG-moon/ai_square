const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{test}=require('node:test'),{webcrypto}=require('node:crypto');
const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_publish.js'),'utf8');
function setup(){
 const cleared=[],opened=[];let resolve;
 const draft={name:'A',desc:'A draft',mode:'url',url:'https://example.test/',owner:'Owner',guide:'Guide',file:null};
 const runtime={draft,releaseId:1,draftOwner:'owner',detailLoadToken:3,step:3};
 const context={runtime,server:{user:{id:'owner'}},Core:{validate:()=>''},packageBlockingError:()=>'',crypto:webcrypto,FormData:class{append(){}},
  registrationDraftRevision:()=>71,clearRegistrationDraft:(...args)=>cleared.push(args),
  requestAPI:()=>new Promise(ok=>resolve=ok),refresh:async()=>{},$:()=>null,
  openModal:(...args)=>opened.push(args),esc:String,getItem:()=>null,button:()=>'',icon:()=>''};
 vm.createContext(context);vm.runInContext(source,context);return {context,draft,runtime,cleared,opened,resolve:result=>resolve(result)};
}
test('late A publish keeps newly opened B draft and clears only A saved revision',async()=>{
 const h=setup(),pending=h.context.publish();
 const b={...h.draft,name:'B',desc:'B draft'};h.runtime.draft=b;h.runtime.releaseId=2;h.runtime.detailLoadToken++;
 h.resolve({id:1,version:2});await pending;
 assert.equal(h.runtime.draft,b);assert.deepEqual(h.cleared,[['owner',1,71]]);assert.equal(h.opened.length,0);
});
test('editing the same draft during a pending publish is not discarded',async()=>{
 const h=setup(),pending=h.context.publish();h.draft.desc='later edit';h.resolve({id:1,version:2});await pending;
 assert.equal(h.runtime.draft.desc,'later edit');assert.equal(h.opened.length,0);
});
test('new input before the debounce writes the model is preserved',async()=>{
 const h=setup(),pending=h.context.publish();h.runtime.draftChangeSequence=1;
 h.resolve({id:1,version:2});await pending;
 assert.equal(h.runtime.draft,h.draft);assert.equal(h.opened.length,0);
});
test('closing the dialog does not reopen it after publishing',async()=>{
 const h=setup(),pending=h.context.publish();h.runtime.detailLoadToken++;h.resolve({id:1,version:2});await pending;
 assert.equal(h.runtime.draft,null);assert.equal(h.opened.length,0);
});
test('current successful publish clears its draft and displays the receipt',async()=>{
 const h=setup(),pending=h.context.publish();h.resolve({id:1,version:2});await pending;
 assert.equal(h.runtime.draft,null);assert.equal(h.opened.length,1);
});
