const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const requests=[];let renders=0;
const context={runtime:{draft:null,releaseId:null},root:{addEventListener(){}},
 $:()=>({}),wizard:()=>renders++,captureDraft(){},esc:s=>String(s).replaceAll('<','&lt;'),icon:()=>'',
 FormData:class{append(){}},requestAPI:()=>new Promise((resolve,reject)=>requests.push({resolve,reject}))};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/frontend_package.js'),'utf8'),context);
const result={recognized:true,metadata:{name:'선언 이름',desc:'설명',platform:'Claude',type:'Skill',environment:'Python',changes:'v1',guide:'안내',workTags:['분석']},package:{type:'Skill',name:'선언 이름',platform:'Claude',entryPoint:'SKILL.md',requirements:['Python']}};
const fresh=()=>({file:{name:'test.zip'},mode:'file',name:'',desc:'',org:'장비팀',owner:'사번 사용자',approval:true});
(async()=>{
 let d=context.runtime.draft=fresh();
 let pending=context.inspectSelectedPackage(d.file);
 assert.equal(context.packageBlockingError(d),'');
 requests.shift().resolve(result);await pending;
 assert.equal(d.name,'선언 이름');assert.equal(d.guide,'안내');assert.equal(d.approval,true);assert.equal(d.org,'장비팀');assert.equal(d.owner,'사번 사용자');
 assert.equal(context.packageBlockingError(d),'');
 assert.ok(context.packagePanel(d).includes('필수 파일 확인'));
 d=context.runtime.draft=fresh();d.name='직접 작성';
 pending=context.inspectSelectedPackage(d.file);requests.shift().resolve(result);await pending;
 assert.equal(d.name,'직접 작성');context.applyPackageFields(d,result);assert.equal(d.name,'선언 이름');
 // An older request must not overwrite the currently selected package.
 d=context.runtime.draft=fresh();pending=context.inspectSelectedPackage(d.file);
 d.file={name:'second.zip'};const second=context.inspectSelectedPackage(d.file);
 requests.shift().resolve(result);await pending;assert.equal(d.name,'');
 requests.shift().resolve({recognized:false,metadata:{},notice:'일반 파일'});await second;
 assert.equal(d.packageInspection.result.recognized,false);
 assert.ok(context.packagePanel(d).includes('일반 파일 등록'));
 // Inspection failure is advisory; closing/starting a new draft ignores late results.
 d=context.runtime.draft=fresh();pending=context.inspectSelectedPackage(d.file);
 requests.shift().reject(Error('필수 파일 누락'));await pending;
 assert.equal(context.packageBlockingError(d),'');
 assert.ok(context.packagePanel(d).includes('직접 작성하면 그대로 게시'));
 assert.ok(context.packagePanel(d).includes('다시 검사'));
 d=context.runtime.draft=fresh();pending=context.inspectSelectedPackage(d.file);
 context.runtime.draft=fresh();const before=renders;requests.shift().resolve(result);await pending;
 assert.equal(renders,before);assert.equal(context.runtime.draft.name,'');
 console.log('Package UI checks passed: auto-fill, manual-edit preservation, authority fields, stale requests, validation failure and draft replacement.');
})().catch(e=>{console.error(e);process.exitCode=1;});
