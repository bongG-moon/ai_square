const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
const context={URL};vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('const Core={'),source.indexOf('const items=[];'))+'\nglobalThis.core=Core;',context);
const base={platform:'Claude',org:'개발팀',type:'Skill',category:'공통 업무',name:'회의 정리',desc:'회의 기록',workTags:[]};
const items=[{...base,id:1,registrantName:'김 하늘',owner:'지원 담당'},
 {...base,id:2,registrantName:'Lee AX',owner:'김하늘',org:'운영팀'},
 {...base,id:3,registrantName:'김하늘',hidden:true}];
const search=(query,filters={})=>Array.from(context.core.filter(items,{platform:'전체',org:'전체 조직',type:'전체',category:'모든 업무',query,...filters}),item=>item.id);
assert.deepEqual(search(' 김하늘 '),[1,2]);
assert.deepEqual(search('lee ax'),[2]);
assert.deepEqual(search('지원 담당'),[1]);
assert.deepEqual(search('김하늘',{org:'개발팀'}),[1]);
assert.deepEqual(search('김하늘',{type:'MCP/Tool'}),[]);
assert.deepEqual(search('.*'),[]);
assert.deepEqual(search('회의'),[1,2]);
assert.deepEqual(search('missing'),[]);
console.log('Registrant search UI: 8 checks passed');
