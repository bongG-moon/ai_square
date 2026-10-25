// Real Chromium with a synthetic host contract; no personal KEY or profile.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(require('node:os').homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const source = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(source, 'ui/index.html'), 'utf8').replace('<!--STORE_STYLE-->', '<style>' + fs.readFileSync(path.join(source, 'ui/store.css'), 'utf8') + '</style>');
const script = fs.readFileSync(path.join(source, 'ui/store.js'), 'utf8');
const output = path.resolve(source, '../outputs/store-install-targets-ui');
fs.mkdirSync(output, {recursive:true});
(async () => {
  const server = await chromium.launchServer({executablePath:path.join(process.env['ProgramFiles(x86)'] || 'C:/Program Files (x86)','Microsoft/Edge/Application/msedge.exe'),headless:true});
  const browser = await chromium.connect(server.wsEndpoint());
  try {
    const page = await browser.newPage({viewport:{width:1100,height:950}});page.setDefaultTimeout(6000);
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    async function fixture(options={}) {
      await page.goto('about:blank');await page.setContent(html);
      await page.evaluate(config=>{
        window.requests=[];
        const works=config.empty?[]:[{id:'work-a',title:'주간 실적 보고서',workspace:'C:/Work/weekly'},{id:'work-b',title:'품질 개선 보고서',workspace:'D:/Projects/quality'}];
        const item={id:1,name:'업무 보고서 작성',type:'Skill',platform:'Claude',access:config.gated?'pending':'approved',registrantName:'예시 등록자'};
        let plan,installed=false;
        window.addEventListener('message',event=>{
          const m=event.data;
          if(m.type==='ax-extension-ready')return window.postMessage({type:'ax-extension-init',channel:'fixture',hostFeatures:config.legacy?[]:['workspaces'],theme:config.dark?'dark':'light',context:{kind:'work',title:works[0]?.title,workspace:works[0]?.workspace}},'*');
          if(m.type!=='ax-extension-request')return;
          window.requests.push(m);
          let result={};
          if(m.action==='status')result={configured:true,baseUrl:'https://square.example.test'};
          if(m.action==='options')result={organizations:[]};
          if(m.action==='catalog')result={items:[item],total:1};
          if(m.action==='detail')result={item,canInstall:!config.manual&&!config.inspect,canInspectInstall:!!config.inspect,manifest:{downloadUrl:'/download/1',...(config.inspect?{}:{installProfile:{scopes:config.userOnly?['user']:['project','user']}})}};
          if(m.action==='host.listWorkspaces')result={items:works};
          if(m.action==='host.selectWorkspace'){
            const work=works.find(w=>w.id===m.payload.sessionId);
            result={cancelled:false,directoryToken:'work-token',path:work.workspace,title:work.title,sessionId:work.id};
          }
          if(m.action==='host.pickDirectory')result={cancelled:false,directoryToken:'folder-token',path:'E:/Selected'};
          if(m.action==='prepareInstall'){
            const destination=m.payload.scope==='user'?'C:/Users/demo/.claude/skills/report':m.payload.directoryToken==='work-token'?'D:/Projects/quality/.claude/skills/report':'E:/Selected/.claude/skills/report';
            plan={canInstall:true,planId:'approved-plan',approvalDigest:'approved-digest',destination,release:'1.0',...(config.inspect?{detectionNotice:'ZIP의 SKILL.md를 확인했습니다. 선택한 공간에 스킬을 설치합니다.'}:{})};
            result=config.unsupportedArchive?{canInstall:false,reason:'ZIP에서 설치할 스킬이나 연결 설정을 확인하지 못했습니다. 등록자의 설치 안내를 확인하세요.'}:plan;
          }
          if(m.action==='install'){installed=true;result={status:'installed',notice:'선택한 공간에 설치했어요.'};}
          if(m.action==='installations')result={items:installed?[{installationId:'fixture-install',name:item.name,status:'installed',target:plan.destination}]:[]};
          window.postMessage({type:'ax-extension-response',channel:m.channel,requestId:m.requestId,ok:true,result},'*');
        });
      },options);
      await page.addScriptTag({content:script});await page.getByRole('button',{name:'업무 보고서 작성',exact:true}).click();await page.getByRole('tab',{name:'설치·연결',exact:true}).click();
    }
    const count=action=>page.evaluate(a=>requests.filter(r=>r.action===a).length,action);
    await fixture();await page.getByRole('button',{name:'바로 설치하기',exact:true}).click();await page.locator('#confirm-dialog').waitFor({state:'visible'});
    assert.equal(await page.locator('#confirm-yes').isDisabled(),true);
    await page.getByRole('button',{name:'설치할 업무',exact:true}).click();
    await page.getByRole('option',{name:/품질 개선 보고서/}).click();
    assert.equal(await page.locator('input[value=work]').isChecked(),true);
    await page.screenshot({path:path.join(output,'01-task-target.png'),animations:'disabled'});
    await page.locator('#confirm-yes').click();await page.getByRole('dialog',{name:'이 내용으로 설치할까요?'}).waitFor();
    assert.match(await page.locator('#confirm-content').innerText(),/품질 개선 보고서/);
    assert.match(await page.locator('#confirm-content').innerText(),/D:\/Projects\/quality/);
    const selected=await page.evaluate(()=>requests.find(r=>r.action==='host.selectWorkspace').payload);
    assert.deepEqual(selected,{sessionId:'work-b'});
    const prepared=await page.evaluate(()=>requests.find(r=>r.action==='prepareInstall').payload);
    assert.deepEqual(prepared,{toolId:1,scope:'directory',directoryToken:'work-token'});
    await page.screenshot({path:path.join(output,'02-plan.png'),animations:'disabled'});
    assert.equal(await count('install'),0);await page.locator('#confirm-yes').click();
    await page.getByRole('button',{name:'상태 확인',exact:true}).waitFor();
    const installed=await page.evaluate(()=>requests.find(r=>r.action==='install').payload);
    assert.deepEqual(installed,{planId:'approved-plan',approvalDigest:'approved-digest',confirmed:true,directoryToken:'work-token'});
    assert.equal(await count('download'),0);assert.equal(await count('install'),1);

    await fixture();await page.getByRole('button',{name:'바로 설치하기',exact:true}).click();await page.locator('#confirm-dialog').waitFor({state:'visible'});await page.locator('#confirm-no').click();
    assert.equal(await count('prepareInstall'),0);assert.equal(await count('host.selectWorkspace'),0);
    await page.getByRole('button',{name:'바로 설치하기',exact:true}).click();await page.locator('#confirm-dialog').waitFor({state:'visible'});await page.locator('input[value=user]').check();await page.locator('#confirm-yes').click();
    await page.getByRole('dialog',{name:'이 내용으로 설치할까요?'}).waitFor();
    assert.match(await page.locator('#confirm-content').innerText(),/공통 \(내 계정\)/);
    assert.deepEqual(await page.evaluate(()=>requests.find(r=>r.action==='prepareInstall').payload),{toolId:1,scope:'user'});
    await page.locator('#confirm-no').click();assert.equal(await count('install'),0);

    await fixture({empty:true});await page.getByRole('button',{name:'바로 설치하기',exact:true}).click();await page.locator('#confirm-dialog').waitFor({state:'visible'});
    assert.equal(await page.locator('input[value=work]').isDisabled(),true);assert.match(await page.locator('#confirm-content').innerText(),/등록된 업무가 없습니다/);
    await page.getByText('목록에 없는 폴더에 설치',{exact:true}).click();await page.getByRole('button',{name:'폴더 선택',exact:true}).click();
    await page.locator('.selected-directory').filter({hasText:'E:/Selected'}).waitFor();assert.equal(await page.locator('input[value=directory]').isChecked(),true);await page.locator('#confirm-yes').click();
    await page.getByRole('dialog',{name:'이 내용으로 설치할까요?'}).waitFor();assert.match(await page.locator('#confirm-content').innerText(),/E:\/Selected/);
    await page.locator('#confirm-no').click();

    await fixture({legacy:true});await page.getByRole('button',{name:'바로 설치하기',exact:true}).click();await page.locator('#confirm-dialog').waitFor({state:'visible'});
    assert.equal(await count('host.listWorkspaces'),0);assert.match(await page.locator('#confirm-content').innerText(),/AX Workspace를 업데이트/);await page.locator('#confirm-no').click();
    await fixture({userOnly:true});await page.getByRole('button',{name:'바로 설치하기',exact:true}).click();await page.locator('#confirm-dialog').waitFor({state:'visible'});
    assert.equal(await count('host.listWorkspaces'),0);assert.equal(await page.locator('input[value=work]').isDisabled(),true);assert.equal(await page.locator('input[value=directory]').count(),0);
    await page.locator('#confirm-no').click();
    await fixture({manual:true});assert.equal(await page.getByRole('button',{name:'바로 설치하기',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'파일 다운로드',exact:true}).count(),1);
    await fixture({gated:true});assert.equal(await page.getByRole('button',{name:'바로 설치하기',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:'파일 다운로드',exact:true}).count(),0);

    await fixture({inspect:true});await page.getByRole('button',{name:'바로 설치하기',exact:true}).click();await page.locator('#confirm-dialog').waitFor({state:'visible'});
    await page.locator('input[value=user]').check();await page.locator('#confirm-yes').click();await page.getByRole('dialog',{name:'이 내용으로 설치할까요?'}).waitFor();
    assert.match(await page.locator('#confirm-content').innerText(),/ZIP의 SKILL.md를 확인/);await page.locator('#confirm-no').click();assert.equal(await count('install'),0);
    await fixture({inspect:true,unsupportedArchive:true});await page.getByRole('button',{name:'바로 설치하기',exact:true}).click();await page.locator('#confirm-dialog').waitFor({state:'visible'});
    await page.locator('input[value=user]').check();await page.locator('#confirm-yes').click();await page.locator('#detail-feedback').filter({hasText:'ZIP에서 설치할 스킬이나 연결 설정을 확인하지 못했습니다.'}).waitFor();assert.equal(await count('install'),0);

    await fixture({dark:true});await page.getByRole('button',{name:'바로 설치하기',exact:true}).click();await page.locator('#confirm-dialog').waitFor({state:'visible'});await page.getByRole('button',{name:'설치할 업무',exact:true}).click();
    await page.screenshot({path:path.join(output,'03-dark-task-list.png'),animations:'disabled'});
    await page.setViewportSize({width:420,height:850});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.screenshot({path:path.join(output,'04-narrow-task-list.png'),animations:'disabled'});
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({passed:true,checks:['task list and selected target','no download action for app install','explicit common scope','scope cancel no plan','plan cancel no install','no tasks folder fallback','old host update guidance','unsupported scope rejected','manual file and gated tool not autoexecuted','ZIP inspection plan and unsupported archive message','dark and narrow dropdown'],pageErrors:errors},null,2));
    console.log('PASS: task/common direct install, approval digest, cancel, empty/legacy/manual/gated cases, dark and narrow layouts.');
  }finally{
    if(process.platform==='win32')require('node:child_process').spawnSync('taskkill.exe',['/PID',String(server.process().pid),'/T','/F'],{windowsHide:true,timeout:10000,stdio:'ignore'});
    await Promise.race([server.close(),new Promise(resolve=>setTimeout(resolve,3000))]);
  }
})().then(()=>process.exit(0),error=>{console.error(error);process.exit(1);});
