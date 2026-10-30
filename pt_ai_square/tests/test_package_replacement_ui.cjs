// Exercise the production picker/drop handlers and asynchronous inspection path together.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const handlers={},requests=[],prompts=[],errors=[];let renders=0,edits={};
const dialog={open:true},confirmation={open:false,close(){this.open=false;}};
const form={id:'sq-register-form',html:'',insertAdjacentHTML(_where,html){this.html+=html;},querySelector(){return {insertAdjacentHTML(){}};}};
const fresh=()=>({file:null,mode:'file',name:'',desc:'',org:'장비팀',owner:'등록자',category:'설비',approval:true});
const context={runtime:{draft:fresh(),step:1,releaseId:null},work:{ideaFiles:[]},
 root:{addEventListener(type,fn,capture){(handlers[type]??=[]).push({fn,capture});}},
 $:selector=>selector==='#sq-register-form'?form:selector==='#sq-dialog'?dialog:selector==='#sq-confirm'?confirmation:null,
 esc:s=>String(s).replaceAll('<','&lt;').replaceAll('"','&quot;'),icon:()=>'<svg></svg>',getItem:()=>null,
 captureDraft(){Object.assign(context.runtime.draft,edits);edits={};},wizard(){renders++;},mountIcons(){},showError:e=>errors.push(e.message),
 FormData:class{append(){}},requestAPI:()=>new Promise((resolve,reject)=>requests.push({resolve,reject})),
 ask(title,copy,callback,label,extra){context.runtime.confirm=callback;confirmation.open=true;prompts.push({title,copy,callback,label,extra});}};
vm.createContext(context);
for(const file of ['frontend_upload.js','frontend_package.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend',file),'utf8'),context);
const declaration=name=>({recognized:true,metadata:{name,desc:name+' 설명',platform:'Claude',type:'Skill',environment:'Python',changes:'개선',guide:name+' 설치',workTags:['보고서'],workflow:{steps:[{title:name}]}},package:{packageId:name,name,type:'Skill',platform:'Claude',entryPoint:'SKILL.md',requirements:[]}});
const file=name=>({name:name+'.zip',size:1024});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const resolve=async result=>{requests.shift().resolve(result);await tick();};
const dropArea={dataset:{upload:'artifact'},classList:{toggle(name,active){this.active=active;}},contains:()=>true};
const drop=files=>{const event={target:{closest:()=>dropArea},preventDefault(){this.prevented=true;},dataTransfer:{files}};handlers.drop[0].fn(event);assert.equal(event.prevented,true);return event;};
const decline=()=>{context.runtime.confirm=null;confirmation.close();};
const accept=()=>{const fn=context.runtime.confirm;context.runtime.confirm=null;confirmation.close();fn();};
(async()=>{
 // Step 1 exposes a real shared drop target and a keyboard-usable file button.
 context.decoratePackageForm(form);assert.match(form.html,/data-upload="artifact"/);assert.match(form.html,/type="button"[^>]*data-file-pick="artifact"/);
 const drag={target:{closest:()=>dropArea},preventDefault(){},dataTransfer:{}};handlers.dragover[0].fn(drag);assert.equal(drag.dataTransfer.dropEffect,'copy');assert.equal(dropArea.classList.active,true);
 handlers.dragleave[0].fn({...drag,relatedTarget:{}});assert.equal(dropArea.classList.active,true);
 // Drag/drop uses the same validation and automatic fill as the picker.
 const first=file('첫 파일');drop([first]);await resolve(declaration('첫 제목'));let d=context.runtime.draft;
 assert.equal(d.file,first);assert.equal(d.name,'첫 제목');assert.equal(prompts.length,0);
 assert.equal(d.workflow.steps[0].title,'첫 제목');
 assert.equal(d.owner,'등록자');assert.equal(d.org,'장비팀');assert.equal(d.approval,true);
 form.html='';context.decoratePackageForm(form);assert.match(form.html,/첫 파일\.zip/);assert.match(form.html,/data-file-remove="artifact"/);
 // Replacing a ZIP preserves edits until an explicit confirmation, including edits during inspection.
 const second=file('두 번째 파일');edits={name:'직접 고친 제목',guide:'직접 적은 안내'};drop([second]);
 edits={desc:'검사 중 입력한 소개'};await resolve(declaration('두 번째 제목'));
 assert.equal(d.name,'직접 고친 제목');assert.equal(d.desc,'검사 중 입력한 소개');assert.equal(d.guide,'직접 적은 안내');
 assert.equal(d.workflow.steps[0].title,'첫 제목');
 assert.equal(prompts.length,1);assert.equal(prompts[0].title,'신규 파일 내용을 적용하시겠습니까?');
 assert.match(prompts[0].extra,/두 번째 파일/);assert.match(prompts[0].extra,/두 번째 제목/);
 accept();assert.equal(d.name,'두 번째 제목');assert.equal(d.desc,'두 번째 제목 설명');assert.equal(d.guide,'두 번째 제목 설치');
 assert.equal(d.workflow.steps[0].title,'두 번째 제목');
 assert.equal(d.org,'장비팀');assert.equal(d.category,'설비');assert.equal(d.approval,true);assert.equal(context.runtime.step,1);
 // Declining keeps the new file but leaves user-facing metadata untouched, with manual apply available.
 const third=file('세 번째 파일');drop([third]);await resolve(declaration('세 번째 제목'));decline();
 assert.equal(d.file,third);assert.equal(d.name,'두 번째 제목');assert.equal(d.packageInspection.applied,undefined);
 assert.equal(d.workflow.steps[0].title,'두 번째 제목');
 assert.match(context.packagePanel(d),/data-package-apply/);
 context.applyPackageFields(d,d.packageInspection.result);assert.equal(d.name,'세 번째 제목');
 // Removing the old attachment preserves all entered/imported metadata. A new
 // ZIP must still ask, even if the prior title and introduction were cleared.
 handlers.click[0].fn({target:{closest:s=>s==='[data-file-remove]'?{dataset:{fileRemove:'artifact'}}:null},preventDefault(){}});
 assert.equal(d.file,null);assert.equal(d.name,'세 번째 제목');assert.equal(d.workflow.steps[0].title,'세 번째 제목');
 d.name='';d.desc='';drop([file('삭제 후 다시 선택')]);await resolve(declaration('새로 고른 제목'));
 assert.equal(d.name,'');assert.equal(prompts.at(-1).title,'신규 파일 내용을 적용하시겠습니까?');
 decline();assert.equal(d.name,'');assert.equal(d.workflow.steps[0].title,'세 번째 제목');
 d.name='세 번째 제목';d.desc='세 번째 제목 설명';const currentFile=d.file;
 // Unsupported files/multiple files never replace the current file or create a confirmation.
 const beforeErrors=errors.length,beforePrompts=prompts.length;
 drop([{name:'invalid.txt',size:10}]);drop([file('A'),file('B')]);
 assert.equal(errors.length,beforeErrors+2);assert.equal(d.file,currentFile);assert.equal(prompts.length,beforePrompts);
 // Unrecognized or unreadable packages do not ask to apply absent metadata.
 drop([file('일반')]);await resolve({recognized:false,notice:'일반 파일'});assert.equal(prompts.length,beforePrompts);assert.equal(d.name,'세 번째 제목');
 drop([file('검사 실패')]);requests.shift().reject(Error('연결 오류'));await tick();assert.equal(prompts.length,beforePrompts);assert.equal(d.packageInspection.state,'error');
 // Retry preserves replacement intent, then asks when declaration inspection succeeds.
 const retry=context.inspectSelectedPackage(d.file);await resolve(declaration('재검사 제목'));await retry;assert.equal(prompts.length,beforePrompts+1);decline();
 // Late responses cannot overwrite a more recently chosen package or show its confirmation.
 drop([file('느린 파일')]);const old=requests.shift();drop([file('최신 파일')]);
 await resolve(declaration('최신 제목'));const currentCheck=d.packageInspection,currentPrompt=prompts.at(-1);
 old.resolve(declaration('오래된 제목'));await tick();assert.equal(d.packageInspection,currentCheck);assert.equal(prompts.at(-1),currentPrompt);assert.equal(d.name,'세 번째 제목');
 // A no-longer-current confirmation cannot apply to a newly selected file.
 drop([file('다음 파일')]);assert.equal(confirmation.open,false);currentPrompt.callback();assert.equal(d.name,'세 번째 제목');
 await resolve(declaration('<script>새 제목'));assert.match(prompts.at(-1).extra,/&lt;script>/);assert.doesNotMatch(prompts.at(-1).extra,/<script>/);decline();
 // Closing the wizard during inspection must not reopen it or show another popup.
 drop([file('닫은 창')]);dialog.open=false;const closedRenders=renders,closedPrompts=prompts.length;
 await resolve(declaration('닫은 제목'));assert.equal(renders,closedRenders);assert.equal(prompts.length,closedPrompts);
 dialog.open=true;
 // A changed mode or new draft also makes old previews/confirmation callbacks harmless.
 drop([file('다른 방식')]);d.mode='url';await resolve(declaration('URL을 덮으면 안 됨'));assert.equal(d.mode,'url');assert.equal(prompts.length,closedPrompts);
 d.mode='file';drop([file('초안 교체')]);const switchedRenders=renders;context.runtime.draft=fresh();await resolve(declaration('이전 초안'));
 assert.equal(context.runtime.draft.name,'');assert.equal(renders,switchedRenders);
 // The picker routes through the same capture handler as dragging into step 1.
 const picked=file('파일 선택');let stopped=false;
 handlers.change.find(h=>h.capture).fn({target:{type:'file',name:'artifact',files:[picked],closest:()=>dropArea},stopImmediatePropagation(){stopped=true;}});
 assert.equal(stopped,true);await resolve(declaration('선택 제목'));assert.equal(context.runtime.draft.name,'선택 제목');
 console.log('Package replacement UI passed: step 1 drop/picker, auto-fill, confirmation accept/decline, invalid files, retries, stale/closed/mode-changed drafts.');
})().catch(error=>{console.error(error);process.exitCode=1;});
