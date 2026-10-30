const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
const base=path.join(__dirname,'..'),app=fs.readFileSync(path.join(base,'static/app.js'),'utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const declaration={recognized:true,metadata:{name:'새 이름',desc:'새 소개',platform:'Claude',type:'Skill',environment:'Python',changes:'개선',guide:'새 안내',workTags:['보고서'],workflow:{steps:[{title:'새 흐름'}]}},package:{packageId:'new-tool',name:'새 이름',type:'Skill',platform:'Claude',entryPoint:'SKILL.md',requirements:[]}};
function setup(){
 const listeners={},dialogListeners={},requests=[],prompts=[],modals=[];
 let renders=0;
 const form={id:'sq-register-form',dataset:{}},error={textContent:'',setAttribute(){}},dialog={open:true};
 const confirmation={open:false,addEventListener(type,fn){(dialogListeners[type]??=[]).push(fn);},close(){this.open=false;for(const fn of dialogListeners.close||[])fn();}};
 const draft={file:{name:'old.zip',size:1024},mode:'file',name:'기존 이름',desc:'직접 입력한 소개',owner:'등록자',org:'장비팀',platform:'Claude',type:'Skill',guide:'직접 입력한 안내',environment:'',changes:'',workflow:{steps:[{title:'기존 흐름'}]},workTags:[],approval:false};
 const context={runtime:{draft,releaseId:null,step:2},work:{ideaFiles:[]},root:{addEventListener(type,fn,capture){(listeners[type]??=[]).push({fn,capture});}},
  $:s=>s==='#sq-register-form'?form:s==='#sq-dialog'?dialog:s==='#sq-confirm'?confirmation:s==='#sq-register-error'?error:null,
  Core:{validate:()=>''},captureDraft(){},wizard(){renders++;},esc:String,icon:()=>'',mountIcons(){},getItem:()=>null,
  FormData:class{constructor(){this.parts=[];}append(...values){this.parts.push(values);}[Symbol.iterator](){return this.parts[Symbol.iterator]();}},crypto:webcrypto,
  requestAPI:(url,method,body)=>new Promise((resolve,reject)=>requests.push({url,method,body,resolve,reject})),
  refresh:async()=>{},openModal:(...args)=>modals.push(args),button:()=>'',showError:e=>{throw e;},
  ask(title,copy,callback){context.runtime.confirm=callback;confirmation.open=true;prompts.push({title,copy,callback});}};
 vm.createContext(context);
 for(const file of ['frontend_upload.js','frontend_package.js','frontend_publish.js'])vm.runInContext(fs.readFileSync(path.join(base,'frontend',file),'utf8'),context);
 // Execute the real served wizard submit listener, with the production package guard.
 const start=app.indexOf("root.addEventListener('submit',event=>{");
 const end=app.indexOf("\nroot.addEventListener('change',event=>{",start);
 vm.runInContext(app.slice(start,end),context);
 return {context,draft,error,form,requests,prompts,modals,confirmation,dialogListeners,get renders(){return renders;},
  submit:()=>listeners.submit[0].fn({target:form,preventDefault(){}}),
  cancel:()=>{for(const fn of dialogListeners.cancel||[])fn();confirmation.close();},
  accept:()=>{const callback=context.runtime.confirm;context.runtime.confirm=null;confirmation.close();callback();},
  select:()=>context.selectFiles('artifact',[{name:'replacement.zip',size:2048}])};
}
(async()=>{
 const h=setup();h.select();assert.equal(h.requests[0].url,'/api/packages/inspect');
 h.submit();assert.equal(h.context.runtime.step,2);assert.match(h.error.textContent,/검사가 끝난/);
 h.context.runtime.step=3;
 await assert.rejects(h.context.publish(),/검사가 끝난/);assert.equal(h.requests.length,1);assert.equal(h.context.runtime.publishBusy,undefined);
 h.requests.shift().resolve(declaration);await tick();assert.equal(h.prompts.length,1);
 // A programmatic publish cannot pass while the replacement question is unanswered.
 await assert.rejects(h.context.publish(),/확인창에서 선택/);assert.equal(h.requests.length,0);
 h.cancel();assert.equal(h.draft.packageInspection.awaitingConfirmation,false);
 h.context.runtime.step=2;h.submit();assert.equal(h.context.runtime.step,3);
 const saved=h.context.publish();assert.equal(h.requests[0].url,'/api/tools');
 const metadata=JSON.parse(h.requests[0].body.parts.find(([key])=>key==='metadata')[1]);
 assert.equal(metadata.name,'기존 이름');assert.equal(metadata.workflow.steps[0].title,'기존 흐름');
 assert.equal(h.requests[0].body.parts.find(([key])=>key==='artifact')[1].name,'replacement.zip');
 assert.throws(()=>h.select(),/게시 중에는/);
 h.context.applyPackageFields(h.draft,declaration);assert.equal(h.draft.name,'기존 이름');
 h.requests.shift().resolve({id:19,version:2});await saved;assert.equal(h.modals.length,1);assert.equal(h.context.runtime.draft,null);
 // Approval posts the accepted declaration. A completed failed inspection still allows manual posting.
 const approved=setup();approved.select();approved.requests.shift().resolve(declaration);await tick();approved.accept();
 assert.equal(approved.draft.packageInspection.awaitingConfirmation,false);approved.context.runtime.step=3;
 const approvedSave=approved.context.publish();assert.equal(JSON.parse(approved.requests[0].body.parts[0][1]).name,'새 이름');
 approved.requests.shift().resolve({id:20,version:1});await approvedSave;
 const failed=setup();failed.select();failed.requests.shift().reject(Error('검사 실패'));await tick();
 failed.submit();assert.equal(failed.context.runtime.step,3);const manualSave=failed.context.publish();
 assert.equal(failed.requests[0].url,'/api/tools');failed.requests.shift().resolve({id:21,version:1});await manualSave;
 // A URL submission can race an old file inspection; the late file result must not edit or reopen UI.
 const switched=setup();switched.select();const preview=switched.requests.shift();
 switched.draft.mode='url';switched.draft.url='http://example.internal/api';switched.context.runtime.step=3;
 const urlSave=switched.context.publish(),beforeRenders=switched.renders;preview.resolve(declaration);await tick();
 assert.equal(switched.draft.mode,'url');assert.equal(switched.draft.name,'기존 이름');assert.equal(switched.prompts.length,0);assert.equal(switched.renders,beforeRenders);
 switched.requests.shift().resolve({id:22,version:1});await urlSave;
 console.log('Package publish boundary passed: real submit/publish block active preview and pending decision, accept/cancel/error resume, in-flight POST cannot change draft.');
})().catch(error=>{console.error(error);process.exitCode=1;});
