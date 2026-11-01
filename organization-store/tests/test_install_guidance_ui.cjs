const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../ui/store.js'),'utf8');
function setup(){
 const calls=[],buttons=[],connection={};
 const context={el:(tag,cls,text)=>({tag,cls,text,type:'',dataset:{},addEventListener(name,fn){this[name]=fn;},replaceChildren(...nodes){this.text=nodes.join('');},prepend(){},setAttribute(){},removeAttribute(){}}),state:{installation:null},$:id=>id==='connection-button'?connection:null,document:{querySelectorAll:()=>buttons,createTextNode:s=>s},installationActive:()=>false,prepare:id=>{calls.push(id);return Promise.resolve();},feedback(){}};
 vm.createContext(context);vm.runInContext(source.slice(source.indexOf('  function installGuidance('),source.indexOf('  function installationState(')),context);
 vm.runInContext(source.slice(source.indexOf('  function renderInstallation('),source.indexOf('  const motionPreference')),context);return {context,calls,buttons};
}
test('declared supported packages offer install and preserve supported notice',()=>{
 const {context,calls}=setup(),b=context.installationButton(4);
 assert.equal(b.text,'바로 설치하기');b.click();assert.deepEqual(calls,[4]);
 assert.equal(context.installGuidance({canInstall:true,installNotice:'설치 위치 확인'}),'설치 위치 확인');
});
test('uninspected ZIP asks to check structure, never claims it requires missing metadata',()=>{
 const {context,calls}=setup(),b=context.installationButton(5,true);
 assert.equal(b.text,'설치 가능 여부 확인');b.click();assert.deepEqual(calls,[5]);
 const notice=context.installGuidance({canInstall:false,canInspectInstall:true,installNotice:'등록자가 설치 정보를 등록해야 합니다.',inspectionNotice:'ZIP 구조를 먼저 확인합니다.'});
 assert.equal(notice,'ZIP 구조를 먼저 확인합니다.');
 assert.match(context.installGuidance({canInspectInstall:true}),/먼저 확인/);
});
test('unsupported files retain manual instructions and active installs cannot start again',()=>{
 const {context,calls}=setup();assert.equal(context.installGuidance({canInstall:false,canInspectInstall:false,installNotice:'직접 설치하세요.'}),'직접 설치하세요.');
 context.installationActive=()=>true;context.installationButton(5).click();assert.deepEqual(calls,[]);
});

test('inspection label survives actual installation state renders, including another active tool and return to idle',()=>{
 const {context,buttons}=setup(),inspect=context.installationButton(5,true),direct=context.installationButton(6);buttons.push(inspect,direct);
 context.renderInstallation();assert.equal(inspect.text,'설치 가능 여부 확인');assert.equal(direct.text,'바로 설치하기');
 context.state.installation={toolId:6,phase:'preparing'};context.installationActive=()=>true;context.renderInstallation();assert.equal(inspect.text,'설치 가능 여부 확인');assert.equal(inspect.disabled,true);assert.equal(direct.text,'설치 준비 중…');
 context.state.installation=null;context.installationActive=()=>false;context.renderInstallation();assert.equal(inspect.text,'설치 가능 여부 확인');assert.equal(inspect.disabled,false);assert.equal(direct.text,'바로 설치하기');
});
test('served detail connects state-dependent labels and removes obsolete future-only web guidance',()=>{
 assert.match(source,/installationButton\(item.id, !result.canInstall\)/);
 assert.match(source,/catalog-note',installGuidance\(result\)/);
 const webPath=['../../pt_ai_square/static/app.js','../../static/app.js'].map(p=>path.join(__dirname,p)).find(p=>fs.existsSync(p));
 const web=fs.readFileSync(webPath,'utf8');
 assert.doesNotMatch(web,/PC 자동 설치·업데이트는 후속 앱 연동 기능입니다/);
 assert.match(web,/AX Workspace 확장이나 AI SQUARE MCP에서 설치할 수 있습니다/);
});
