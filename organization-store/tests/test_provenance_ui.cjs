const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../ui/store.js'),'utf8');
function setup(){
 const calls=[];
 const el=(tag,cls,text='')=>({tag,cls,text:String(text),children:[],dataset:{},attributes:{},isConnected:true,classList:{add(){}},append(...nodes){this.children.push(...nodes);},setAttribute(k,v){this.attributes[k]=v;},removeAttribute(k){delete this.attributes[k];},addEventListener(name,fn){this[name]=fn;},set textContent(value){this.text=String(value);},get textContent(){return this.text;}});
 const c={el,state:{baseUrl:'https://current.example',connectionGeneration:1,context:{workspace:'C:/업무',title:'보고서 업무'}},symbol:()=>el('span'),typeBadge:()=>el('span'),button:(text)=>el('button','',text),rpc:(action,payload,current)=>new Promise((resolve,reject)=>calls.push({action,payload,current,resolve,reject}))};vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('  function metadata('),source.indexOf('  function dated(')),c);
 vm.runInContext(source.slice(source.indexOf('  function recordName('),source.indexOf('  function section(')),c);return {c,calls};
}
function text(n){return [n.text,...n.children.map(text)].join(' ');}
function find(n,cls){return n.cls===cls?n:n.children.map(c=>find(c,cls)).find(Boolean);}
test('compact installed card keeps on-demand information and shows original receipt source/hash',async()=>{
 const {c,calls}=setup(),record={name:'보고서 만들기',installationId:'record-1',recordDigest:'d'.repeat(64),toolId:7,release:2,scope:'project',scopeDir:'C:/업무',target:'C:/업무/.claude/skills/report',origin:'https://original.example',sha256:'a'.repeat(64),status:'installed'};
 const before=JSON.stringify(record),card=c.recordCard(record,false),details=find(card,'record-details');
 for(const value of ['플랫폼 배포 v2','설치 정보',record.target,record.origin,record.sha256,'#7','현재 Claude 연결'])assert.ok(text(card).includes(value),value);
 assert.equal(find(card,'record-target').text,'보고서 업무');assert.equal(calls.length,0,'Listing must not read installed files');assert.equal(JSON.stringify(record),before);
 details.open=true;const toggle=details.toggle();assert.equal(calls[0].action,'installationInfo');assert.equal(calls[0].payload.recordDigest,record.recordDigest);calls.shift().resolve({skillName:'actual-skill-name',connectionVerified:false});await toggle;
 assert.match(text(details),/actual-skill-name/);await details.toggle();assert.equal(calls.length,0,'Cached bounded info is reused');
});
test('legacy records explain missing source/hash and do not invent commands or content evidence',()=>{
 const {c}=setup(),rendered=text(c.installedDetails({release:1,sha256:'invalid'}));
 assert.match(rendered,/플랫폼 주소가 없습니다/);assert.match(rendered,/파일 해시가 없습니다/);assert.doesNotMatch(rendered,/invalid|current\.example/);
 const html=fs.readFileSync(path.join(__dirname,'../ui/index.html'),'utf8');assert.match(html,/확장 프로그램 버전 0\.1\.0/);
});
test('late installation info from an old connection cannot add a stale skill name',async()=>{
 const {c,calls}=setup(),details=c.installedDetails({installationId:'one',recordDigest:'a'.repeat(64),release:1});details.open=true;
 const pending=details.toggle(),request=calls.shift();c.state.connectionGeneration++;assert.equal(request.current(),false);request.resolve({skillName:'old-server-skill'});await pending;assert.doesNotMatch(text(details),/old-server-skill/);
});
