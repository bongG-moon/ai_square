// Dependency-free unit tests of actual upload event handlers; no browser automation.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const callbacks={};let renders=0,errors=[];
const area={outerHTML:''};
const context={runtime:{draft:{file:null}},work:{ideaFiles:[]},
 root:{addEventListener:(name,fn,capture)=>{(callbacks[name]??=[]).push({fn,capture});}},
 $:()=>area,esc:s=>String(s).replace(/</g,'&lt;').replace(/"/g,'&quot;'),icon:()=>'<svg></svg>',
 captureDraft:()=>{},wizard:()=>renders++,mountIcons:()=>{},showError:e=>errors.push(e.message)};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../frontend/frontend_upload.js'),'utf8'),context);
const file={name:'report.zip',size:2048};
context.runtime.draft.workflow={steps:[{title:'Previous file workflow'}]};
context.selectFiles('artifact',[file]);assert.equal(context.runtime.draft.file,file);assert.equal(renders,1);assert.equal(context.runtime.draft.workflow,null);
assert.throws(()=>context.selectFiles('artifact',[{name:'bad.txt',size:12}]));assert.equal(context.runtime.draft.file,file);
const extension={name:'PNT-AI-Square.axextension',size:1024};
context.selectFiles('artifact',[extension]);assert.equal(context.runtime.draft.file,extension);
assert.match(context.uploadArea('artifact'),/accept="\.zip,\.axextension,/);
assert.doesNotMatch(context.uploadArea('attachments'),/axextension/);
assert.throws(()=>context.selectFiles('attachments',[extension]));
const dropArea={dataset:{upload:'artifact'},classList:{toggle(){}}};
callbacks.drop[0].fn({target:{closest:()=>dropArea},preventDefault(){},dataTransfer:{files:[{name:'replace.zip',size:30}]}});
assert.equal(context.runtime.draft.file.name,'replace.zip');context.runtime.draft.workflow={steps:[{title:'Stale'}]};
callbacks.click[0].fn({target:{closest:s=>s==='[data-file-remove]'?{dataset:{fileRemove:'artifact',index:'0'}}:null},preventDefault(){}});
assert.equal(context.runtime.draft.file,null);assert.equal(context.runtime.draft.workflow,null);
context.selectFiles('attachments',[{name:'example.csv',size:100},{name:'capture.png',size:90}]);
assert.equal(context.work.ideaFiles.length,2);assert.ok(area.outerHTML.includes('capture.png'));
callbacks.click[0].fn({target:{closest:s=>s==='[data-file-remove]'?{dataset:{fileRemove:'attachments',index:'0'}}:null},preventDefault(){}});
assert.equal(context.work.ideaFiles.length,1);assert.equal(context.work.ideaFiles[0].name,'capture.png');
assert.throws(()=>context.selectFiles('attachments',[{name:'large.pdf',size:21*1048576}]));
assert.equal(context.work.ideaFiles.length,1);
const injection=context.uploadArea('artifact',[{name:'<script>.zip',size:10}]);
assert.ok(!injection.includes('<script>'));assert.ok(injection.includes('type="button"'));
assert.ok(callbacks.change.some(x=>x.capture===true));
console.log('Upload UI checks passed: select, replace, drag/drop, cancel, attachment removal, limits, escaping.');
const app=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
vm.runInContext(app.slice(app.indexOf('const Core='),app.indexOf('const items='))+';globalThis.core=Core;',context);
assert.equal(context.core.pages(25,0,12).count,3);
assert.equal(context.core.pages(25,9,12).page,2);
assert.equal(context.core.pages(0,9,12).page,0);
assert.equal(context.core.filter([{name:'A',type:'MCP/Tool',platform:'Claude',org:'공통',category:'기술'}],{platform:'전체',org:'전체 조직',category:'모든 업무',type:'MCP/Tool',query:''}).length,1);
console.log('Catalog checks passed: 12-per-page boundaries and grouped type filter.');
