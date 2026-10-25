// Real Chromium interactions with a synthetic host. Never opens a real website.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || path.join(require('node:os').homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const root = path.resolve(__dirname, '../..'), source = path.join(root, 'organization-store');
const output = process.env.STORE_NAVIGATION_OUTPUT || path.join(root, 'outputs/store-card-navigation-20261025');
fs.mkdirSync(output, {recursive:true});
const html = fs.readFileSync(path.join(source, 'ui/index.html'), 'utf8').replace('<!--STORE_STYLE-->', '<style>' + fs.readFileSync(path.join(source, 'ui/store.css'), 'utf8') + '</style>');
const script = fs.readFileSync(path.join(source, 'ui/store.js'), 'utf8');
(async () => {
  const server = await chromium.launchServer({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless:true});
  const browser = await chromium.connect(server.wsEndpoint());
  try {
    const page = await browser.newPage({viewport:{width:1280,height:900}});
    page.setDefaultTimeout(7000);
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    const font = fs.readFileSync(path.join(root, 'build/workspace-local-repository/local_app/web/fonts/NotoSansKR-Variable.woff'));
    await page.route('http://127.0.0.1:48591/**', route => route.fulfill({status:200, contentType:route.request().url().endsWith('.woff') ? 'font/woff' : 'text/html', body:route.request().url().endsWith('.woff') ? font : html}));
    async function fixture(config = {}) {
      await page.goto('http://127.0.0.1:48591/');
      await page.evaluate(config => {
        window.requests = [];
        const items = Array.from({length:6}, (_, i) => ({id:i+1, name:'업무 보고서 ' + (i+1), desc:'자료를 읽고 보고서를 작성합니다. 설명을 선택해서 복사할 수도 있습니다.', type:'Skill', registrantName:'예시 등록자', org:'업무 혁신팀', category:'보고서', statistics:{views:10,likes:2,downloads:4}, access:'approved'}));
        window.addEventListener('message', event => {
          const message = event.data;
          if (message.type === 'ax-extension-ready') return window.postMessage({type:'ax-extension-init',channel:'navigation-test',hostFeatures:['workspaces','publishFiles'],theme:config.dark ? 'dark':'light',context:{}}, '*');
          if (message.type !== 'ax-extension-request') return;
          window.requests.push(message);
          let result = {};
          if (message.action === 'status') result = {configured:config.configured !== false,baseUrl:config.configured === false ? '' : (config.baseUrl || 'https://square.example.test'),presetBaseUrl:config.preset || ''};
          if (message.action === 'options') result = {organizations:[]};
          if (message.action === 'catalog') {
            const q = (message.payload.q || '').toLowerCase();
            const found = items.filter(i => [i.name,i.desc,i.registrantName].join(' ').toLowerCase().includes(q));
            result = {items:found,total:found.length};
          }
          if (message.action === 'detail') result = {item:items.find(i => i.id === message.payload.toolId),canInstall:false};
          const error = message.action === 'host.openExternal' && config.homeError ? '이 주소는 앱에서 열 수 없습니다.' : null;
          window.postMessage({type:'ax-extension-response',channel:message.channel,requestId:message.requestId,ok:!error,result,error}, '*');
        });
      }, config);
      await page.addScriptTag({content:script});
      await page.locator(config.configured === false ? '#connection-view' : '.catalog-card').first().waitFor({state:'visible'});
    }
    const count = action => page.evaluate(action => requests.filter(r => r.action === action).length, action);
    async function opensOnce(click, focusTitle = true) {
      const previous = await count('detail');
      await click();
      await page.locator('#detail-title').filter({hasText:'업무 보고서 1'}).waitFor();
      assert.equal(await count('detail'), previous + 1);
      await page.locator('#detail-close').click();
      if (focusTitle) assert.equal(await page.locator('.catalog-card .tool-title').first().evaluate(n => n === document.activeElement), true);
    }
    await fixture();
    await page.locator('#platform-home').click();
    await page.waitForFunction(() => requests.some(r => r.action === 'host.openExternal'));
    assert.deepEqual(await page.evaluate(() => requests.filter(r => r.action === 'host.openExternal').map(r => r.payload)), [{url:'https://square.example.test/',homepage:true}]);
    const card = page.locator('.catalog-card').first();
    for (const selector of ['.tool-symbol svg', '.tool-desc', '.card-owner', '.tags', '.metrics']) await opensOnce(() => card.locator(selector).click());
    await opensOnce(() => card.click({position:{x:8,y:8}}));
    await opensOnce(() => card.locator('.tool-title').click());
    await opensOnce(() => card.locator('.card-bottom button').click(), false);
    for (const key of ['Enter', 'Space']) await opensOnce(async () => {await card.locator('.tool-title').focus();await page.keyboard.press(key);});
    // Selection is preserved instead of turning a copy gesture into navigation.
    const beforeSelection = await count('detail');
    await card.locator('.tool-desc').evaluate(n => {const range=document.createRange();range.selectNodeContents(n);getSelection().removeAllRanges();getSelection().addRange(range);n.dispatchEvent(new MouseEvent('click',{bubbles:true}));});
    assert.equal(await count('detail'), beforeSelection);
    assert.equal(await page.locator('#detail-dialog').evaluate(n => n.open), false);
    await page.evaluate(() => getSelection().removeAllRanges());
    await opensOnce(() => card.evaluate(n => {n.click();n.click();}));
    await page.locator('#search').fill('예시 등록자');
    await page.waitForFunction(() => requests.filter(r => r.action === 'catalog').at(-1)?.payload.q === '예시 등록자');
    assert.equal(await page.locator('.catalog-card').count(), 6);
    await page.locator('#search').fill('없는 등록자');
    await page.locator('.empty').waitFor();assert.equal(await page.locator('.catalog-card').count(),0);
    await page.locator('#search').clear();await page.locator('.catalog-card').first().waitFor();
    assert.equal(await page.locator('.catalog-card').count(),6);
    assert.match(await page.locator('#search').getAttribute('placeholder'),/등록자/);
    await page.screenshot({path:path.join(output,'catalog-light.png'),animations:'disabled'});
    await fixture({dark:true}); await page.setViewportSize({width:420,height:850});
    await opensOnce(() => page.locator('.catalog-card .tool-desc').first().click());
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
    await page.screenshot({path:path.join(output,'catalog-dark-narrow.png'),animations:'disabled'});
    await fixture({configured:false,preset:'https://preset.example.test'});await page.locator('#platform-home').click();
    await page.waitForFunction(() => requests.some(r => r.action === 'host.openExternal'));
    assert.deepEqual(await page.evaluate(() => requests.filter(r => r.action === 'host.openExternal').map(r => r.payload)),[{url:'https://preset.example.test/',homepage:true}]);
    await fixture({baseUrl:'http://localhost:8080'});await page.locator('#platform-home').click();
    await page.waitForFunction(() => requests.some(r => r.action === 'host.openExternal'));
    assert.deepEqual(await page.evaluate(() => requests.filter(r => r.action === 'host.openExternal').map(r => r.payload)),[{url:'http://localhost:8080/',homepage:true}]);
    await fixture({configured:false});await page.locator('#platform-home').click();
    assert.equal(await count('host.openExternal'),0);assert.match(await page.locator('#feedback').innerText(),/주소를 먼저 연결/);
    assert.equal(await page.locator('#server-url').evaluate(n => n === document.activeElement),true);
    await fixture({configured:false,preset:'https://user:password@wrong.example.test'});await page.locator('#platform-home').click();
    assert.equal(await count('host.openExternal'),0);assert.match(await page.locator('#feedback').innerText(),/기본 주소를 확인/);
    await fixture({homeError:true});await page.locator('#platform-home').click();
    await page.locator('#feedback.error').waitFor();assert.match(await page.locator('#feedback').innerText(),/이 주소는 앱에서 열 수 없습니다/);
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({passed:true,checks:['configured homepage via host','preset homepage before KEY entry','localhost homepage root with scoped host flag','missing and invalid homepage guarded','host navigation denial shown','card icon description owner tag metrics and whitespace','title and footer no double-open','native Enter and Space','focus restored','text selection preserved','rapid duplicate clicks guarded','registrant search transport and empty/clear states','dark narrow layout'],errors},null,2));
    console.log('PASS: homepage, full-card activation, keyboard/focus, selection, duplicate clicks, search UX, narrow theme.');
  } finally {
    await browser.close();
    await server.close();
  }
})().catch(error => {console.error(error);process.exitCode=1;});
