const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const requests=[],announcements=[];let renders=0,currentTool=null;
const context={runtime:{draft:null,releaseId:null},root:{addEventListener(){}},
 $:()=>({}),wizard:()=>renders++,captureDraft(){},esc:s=>String(s).replaceAll('<','&lt;'),icon:()=>'',
 getItem:()=>currentTool,announce:value=>announcements.push(value),navigator:{clipboard:{writeText:async()=>{}}},
 FormData:class{append(){}},requestAPI:()=>new Promise((resolve,reject)=>requests.push({resolve,reject}))};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/frontend_package.js'),'utf8'),context);
const result={recognized:true,metadata:{name:'선언 이름',desc:'설명',platform:'Claude',type:'Skill',environment:'Python',changes:'v1',guide:'안내',workTags:['분석']},package:{packageId:'sample-tool',type:'Skill',name:'선언 이름',platform:'Claude',entryPoint:'SKILL.md',requirements:['Python']}};
const fresh=()=>({file:{name:'test.zip'},mode:'file',name:'',desc:'',org:'장비팀',owner:'사번 사용자',approval:true});
(async()=>{
 let imported='';context.runtime.step=1;context.runtime.draft={};
 context.decoratePackageForm({id:'sq-register-form',insertAdjacentHTML:(_where,html)=>imported+=html});
 assert.match(imported,/accept="\.zip,\.axextension"/);
 assert.match(imported,/배포 파일에서 불러오기/);
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
 // The numeric tool ID and first recognized package ID are different concepts.
 // Manual releases and rollback must not erase the server's persistent identity.
 context.runtime.releaseId=21;
 currentTool={id:21,name:'기존 도구',active:3,versions:[{n:4,package:null},{n:1,package:{packageId:'sample-tool'}},{n:3,deleted:true,withdrawn:true,package:{packageId:'later-source-id'}}]};
 assert.equal(context.updatePackageIdentity().toolId,21);
 assert.equal(context.updatePackageIdentity().packageId,'sample-tool');
 currentTool.packageId='server-fixed-identity';assert.equal(context.updatePackageIdentity().packageId,'server-fixed-identity');delete currentTool.packageId;
 context.runtime.step=2;context.runtime.draft={mode:'file',file:null};imported='';
 context.decoratePackageForm({id:'sq-register-form',insertAdjacentHTML:(_where,html)=>imported+=html});
 assert.match(imported,/도구 ID/);assert.match(imported,/value="21"/);
 assert.match(imported,/플랫폼 packageId/);assert.match(imported,/value="sample-tool"/);
 assert.match(imported,/data-package-copy="tool"/);assert.match(imported,/data-package-copy="package"/);
 assert.match(imported,/식별자가 달라도 등록/);assert.match(imported,/기존 도구/);
 // A completely new file with the same identity can proceed without changing its bytes or declaration.
 d=context.runtime.draft=fresh();d.name='기존 도구';const chosen=d.file;
 const changed={...result,package:{...result.package,entryPoint:'new_folder/run.py'}};
 pending=context.inspectSelectedPackage(d.file);requests.shift().resolve(changed);await pending;
 assert.equal(context.packageBlockingError(d),'');assert.equal(d.file,chosen);assert.equal(d.name,'기존 도구');
 assert.match(context.packagePanel(d),/new_folder\/run.py/);
 // A recognized different identity is informational and preserves the selected target and bytes.
 const mismatch={...result,package:{...result.package,packageId:'different-tool'}};
 const untouched=JSON.stringify(mismatch);
 pending=context.inspectSelectedPackage(d.file);requests.shift().resolve(mismatch);await pending;
 assert.equal(context.packageBlockingError(d),'');
 assert.match(context.packagePanel(d),/sample-tool/);assert.match(context.packagePanel(d),/different-tool/);
 assert.match(context.packagePanel(d),/role="status"/);assert.doesNotMatch(context.packagePanel(d),/is-error|role="alert"/);
 assert.match(context.packagePanel(d),/기존 도구의 새 버전으로 연결/);
 assert.match(context.packagePanel(d),/data-package-apply/);assert.equal(context.runtime.releaseId,21);
 assert.equal(d.file,chosen);assert.equal(JSON.stringify(mismatch),untouched);
 // The mismatch check is scoped to a selected file and does not turn advisory errors into blockers.
 d.mode='url';assert.equal(context.packageBlockingError(d),'');d.mode='file';
 pending=context.inspectSelectedPackage(d.file);requests.shift().reject(Error('검사 통신 실패'));await pending;
 assert.equal(context.packageBlockingError(d),'');
 pending=context.inspectSelectedPackage(d.file);requests.shift().resolve({recognized:false,warning:'선언 없음'});await pending;
 assert.equal(context.packageBlockingError(d),'');
 currentTool={id:21,versions:[{n:1,package:null}]};
 pending=context.inspectSelectedPackage(d.file);requests.shift().resolve(result);await pending;
 assert.equal(context.packageBlockingError(d),'');assert.match(context.updatePackagePanel(),/처음 정상적으로 읽힌 배포 파일/);
 context.runtime.releaseId=null;assert.equal(context.updatePackagePanel(),'');
 // Match the site's KEY-copy fallback on HTTP: select the readonly value for manual copy.
 let copied='',focused=0,selected=0;
 const field={value:'sample-tool',focus:()=>focused++,select:()=>selected++};
 const copyButton={closest:()=>({querySelector:()=>field}),textContent:'복사'};
 context.navigator.clipboard.writeText=async value=>{copied=value;};
 await context.copyPackageIdentity(copyButton);assert.equal(copied,'sample-tool');assert.equal(copyButton.textContent,'복사 완료');
 context.navigator.clipboard=undefined;
 await context.copyPackageIdentity(copyButton);assert.equal(focused,1);assert.equal(selected,1);assert.match(announcements.at(-1),/Ctrl\+C/);
 console.log('Package UI checks passed: auto-fill, advisory inspection, stale requests, fixed first identity, different-ID update without mutation, copy and HTTP fallback.');
})().catch(e=>{console.error(e);process.exitCode=1;});
