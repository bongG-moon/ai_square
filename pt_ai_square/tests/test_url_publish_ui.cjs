// Exercise the shipped wizard validator; no endpoint is contacted.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
const source=fs.readFileSync(path.join(__dirname,'../static/app.js'),'utf8');
const context=vm.createContext({URL});
vm.runInContext(source.slice(source.indexOf('const Core='),source.indexOf('const items='))+';globalThis.core=Core;',context);
const core=context.core;
const draft=url=>({mode:'url',url,guide:'연결 설정에 주소를 입력하세요.'});

test('web wizard accepts internal HTTP MCP/API URLs with ports and paths without a file',()=>{
 for(const url of ['http://mcp.example.internal:8080/mcp','http://api.example.internal/v1/query?team=pt','http://intranet/mcp',
  'http://10.20.30.40:8080/api','http://[fd00::1]:8080/mcp','HTTP://MCP.EXAMPLE.INTERNAL:80/mcp','  http://intranet/api  ',
  'http://도구.example/mcp','https://mcp.example.internal/mcp']){
  const value=draft(url);assert.equal(core.validate(value,2),'',url);assert.equal(value.url,url);assert.equal(value.file,undefined);
 }
});

test('web wizard rejects unsafe schemes, credentials and malformed addresses',()=>{
 for(const url of ['', 'ftp://intranet/file','javascript:alert(1)','file:///C:/x','//intranet/mcp','http:intranet/mcp',
  'http:///intranet/mcp','http://user:secret@intranet/mcp','http://@intranet/mcp','http://intranet:',
  'http://intranet:0/mcp','http://intranet:65536/mcp','http://intranet:abc/mcp','http://bad host/mcp',
  'http://intranet/with space','http://intranet\\@other/mcp','http://intranet/\napi','\thttp://intranet/api','http://intranet/\u0085api','http://intranet/\ud800',
  'http://%65xample/mcp','http://[fd00::1','http://[fe80::1%25eth0]/mcp','http://-bad/mcp','http://bad..host/mcp',
  'http://127.1/api','http://999.1.1.1/api','http://01.2.3.4/api','http://host/'+ 'a'.repeat(2048)]){
  assert.notEqual(core.validate(draft(url),2),'',url);
 }
});

test('connection instructions remain required and file registration still requires its artifact',()=>{
 assert.match(core.validate({...draft('http://intranet/mcp'),guide:''},2),/연결하는 방법/);
 assert.match(core.validate({mode:'file',guide:'설치 안내'},2),/파일을 선택/);
 assert.equal(core.validate({mode:'file',guide:'설치 안내',file:{name:'package.zip'}},2),'');
});
