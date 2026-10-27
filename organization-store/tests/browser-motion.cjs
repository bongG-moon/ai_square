// Real Chromium animation and interaction regression. All API replies are local
// synthetic fixtures; this test never reads a personal KEY, installs or publishes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(require('node:os').homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const root = path.resolve(__dirname, '../..');
const source = path.join(root, 'organization-store');
const output = path.resolve(process.env.MOTION_OUTPUT || path.join(root, 'outputs/store-motion-20261026'));
const origin = 'http://127.0.0.1:48739';
const html = fs.readFileSync(path.join(source, 'ui/index.html'), 'utf8').replace('<!--STORE_STYLE-->', '<style>' + fs.readFileSync(path.join(source, 'ui/store.css'), 'utf8') + '</style>');
const script = fs.readFileSync(path.join(source, 'ui/store.js'), 'utf8');
const font = fs.readFileSync(path.join(process.env.AX_WORKSPACE_SOURCE || path.join(root, 'build/workspace-local-repository'), 'local_app/web/fonts/NotoSansKR-Variable.woff'));
fs.mkdirSync(output, { recursive: true });
const report = { passed: false, environment: 'Real headless Edge, current extension sources, synthetic host; no live service, personal KEY or installation.', checks: [], screenshots: [], measurements: {}, errors: [] };

(async () => {
  const server = await chromium.launchServer({ executablePath: path.join(process.env['ProgramFiles(x86)'] || 'C:/Program Files (x86)', 'Microsoft/Edge/Application/msedge.exe'), headless: true });
  const browser = await chromium.connect(server.wsEndpoint());
  try {
    let page = await browser.newPage({ viewport: { width: 1180, height: 900 } });
    page.setDefaultTimeout(8000);
    page.on('pageerror', error => report.errors.push(error.message));
    await page.route(origin + '/**', route => route.fulfill({ status: 200, contentType: route.request().url().endsWith('.woff') ? 'font/woff' : 'text/html', body: route.request().url().endsWith('.woff') ? font : html }));
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Performance.enable');
    async function fixture(config = {}) {
      await page.goto(origin + '/');
      await page.evaluate(config => {
        window.requests = []; window.heldRequests = []; window.fixtureConfig = { hold: {}, ...config }; window.motionTasks = [];
        new PerformanceObserver(list => window.motionTasks.push(...list.getEntries().map(entry => ({ start: entry.startTime, duration: entry.duration })))).observe({ type: 'longtask', buffered: false });
        const options = { organizations: [{ id: 'org', name: '업무 혁신팀' }], categories: [{ id: 'reports', name: '문서 작성' }] };
        const items = Array.from({ length: 6 }, (_, i) => ({ id: i + 1, name: ['주간 실적 보고서 작성', '사내 자료 검색', '설비 점검 도우미', '업무 시작 가이드', '문서 연결 MCP', '업무 템플릿 모음'][i], type: ['Skill', 'MCP/Tool', '플러그인/하네스'][i % 3], platform: 'Claude', org: '업무 혁신팀', registrantName: '예시 등록자', category: '문서 작성', access: 'approved', desc: '업무 자료를 확인하고 필요한 내용을 정리합니다. 결과를 검토한 뒤 팀과 공유할 수 있으며 실제 작업 전에 설치할 공간을 선택합니다.', guide: '업무 폴더를 선택하고 자료 정리를 요청하세요.', statistics: { views: 24, likes: 3, downloads: 9 }, active: 2, versions: [{ n: 2, note: '현재 배포' }, { n: 1, note: '첫 배포' }], comments: [] }));
        const records = items.slice(0, 3).map(item => ({ installationId: 'installed-' + item.id, toolId: item.id, name: item.name, type: item.type, kind: 'skill', release: 2, scope: 'user', target: 'C:/Users/Example/.claude/skills/tool-' + item.id, status: 'installed', rollbackAvailable: true }));
        const reply = (message, result) => window.postMessage({ type: 'ax-extension-response', channel: message.channel, requestId: message.requestId, ok: true, result }, '*');
        function respond(message) {
          let result = {};
          if (message.action === 'status') result = { configured: !config.disconnected, baseUrl: 'https://square.example.test', presetBaseUrl: 'https://square.example.test', existingConnectionAvailable: true };
          if (message.action === 'options') result = options;
          if (message.action === 'catalog') { const matches = items.filter(item => !message.payload.q || item.name.includes(message.payload.q)); result = { items: matches, total: matches.length }; }
          if (message.action === 'detail') result = { item: items.find(item => item.id === message.payload.toolId), canInstall: true, manifest: { release: 2, downloadUrl: '/download/example', installProfile: { scopes: ['user', 'project'] } } };
          if (message.action === 'installations') result = { items: records, recovery: { recovered: [], blocked: [] } };
          if (message.action === 'checkUpdates') result = { items: [], complete: true, summary: { total: 0, checked: 0 } };
          if (message.action === 'host.listWorkspaces') result = { items: [] };
          if (message.action === 'publishOptions') result = { canPublish: true, options, candidates: [] };
          reply(message, result);
        }
        window.releaseHost = action => { delete window.fixtureConfig.hold[action]; const held = window.heldRequests.filter(message => message.action === action); window.heldRequests = window.heldRequests.filter(message => message.action !== action); held.forEach(respond); };
        window.addEventListener('message', event => {
          const message = event.data;
          if (message.type === 'ax-extension-ready') return window.postMessage({ type: 'ax-extension-init', channel: 'motion-fixture', theme: config.dark ? 'dark' : 'light', hostFeatures: ['workspaces', 'publishFiles'], context: { kind: 'work', title: '검증용 업무', workspace: 'D:/Example' } }, '*');
          if (message.type !== 'ax-extension-request') return;
          window.requests.push(message);
          if (window.fixtureConfig.hold[message.action]) window.heldRequests.push(message); else respond(message);
        });
      }, config);
      await page.evaluate(() => document.fonts.ready);
      await page.addScriptTag({ content: script });
      await page.locator(config.disconnected ? '#connection-view' : '.catalog-card').first().waitFor();
    }
    const tab = name => page.locator('[data-tab="' + name + '"]');
    const count = action => page.evaluate(action => window.requests.filter(message => message.action === action).length, action);
    const settled = () => page.waitForFunction(() => document.getAnimations().every(animation => animation.effect.getTiming().iterations === Infinity || (animation.playState !== 'running' && animation.playState !== 'pending')));
    const noOverflow = async () => assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'No horizontal viewport overflow');
    async function screenshot(name) { await page.screenshot({ path: path.join(output, name), fullPage: true }); report.screenshots.push(name); }
    async function motion(selector) {
      return page.locator(selector).evaluate(node => ({ opacity: getComputedStyle(node).opacity, transform: getComputedStyle(node).transform, open: node.open, pointerEvents: getComputedStyle(node).pointerEvents, duration: getComputedStyle(node).transitionDuration, animations: node.getAnimations().map(animation => ({ duration: animation.effect.getTiming().duration, properties: Object.keys(animation.effect.getKeyframes()[0] || {}), state: animation.playState })) }));
    }
    async function layout(selector) { return page.locator(selector).evaluate(node => ({ direction: getComputedStyle(node).flexDirection, width: node.offsetWidth, height: node.offsetHeight, childOffsets: [...node.children].filter(child => !child.hidden).map(child => ({ x: child.offsetLeft, y: child.offsetTop, width: child.offsetWidth, height: child.offsetHeight })) })); }
    async function instantClick(selector) { await page.locator(selector).evaluate(node => { node.focus({ preventScroll: true }); node.click(); }); }
    async function openDetail() { await instantClick('.catalog-card:first-child .tool-title'); await page.locator('#detail-panel').waitFor(); }
    async function metrics() { await cdp.send('HeapProfiler.collectGarbage'); const dom = await cdp.send('Memory.getDOMCounters'); const metrics = (await cdp.send('Performance.getMetrics')).metrics; return { ...dom, heapBytes: metrics.find(row => row.name === 'JSHeapUsedSize').value, animations: await page.evaluate(() => document.getAnimations().length) }; }
    async function pausedFrame(name, fraction = .42) {
      const saved = await page.evaluate(fraction => { window.pausedMotion = document.getAnimations().filter(animation => typeof animation.effect.getTiming().duration === 'number' && animation.effect.getTiming().duration > 0 && animation.effect.getTiming().iterations !== Infinity); window.pausedMotion.forEach(animation => { animation.pause(); animation.currentTime = animation.effect.getTiming().duration * fraction; }); return window.pausedMotion.length; }, fraction);
      assert(saved > 0, 'Mid-transition screenshot must contain a live animation');
      await screenshot(name);
      await page.evaluate(() => { window.pausedMotion.forEach(animation => animation.play()); window.pausedMotion = []; });
      await settled();
    }

    await fixture();
    const entrance = { results: await motion('#results'), view: await motion('#catalog-view') };
    report.measurements.initialResults = entrance;
    assert([entrance.results, entrance.view].some(node => node.animations.some(animation => animation.duration === 300 && animation.properties.includes('opacity'))), 'Loaded catalog or its containing view has a 300ms fade');
    await pausedFrame('01-catalog-enter-mid.png');
    await screenshot('02-catalog-light.png');

    await instantClick('[data-tab="installed"]'); await page.locator('.install-record').first().waitFor();
    assert((await motion('#results')).animations.some(animation => animation.duration === 300));
    await settled();
    await instantClick('[data-tab="updates"]'); await page.locator('#results .empty').waitFor(); await settled();
    await instantClick('[data-tab="catalog"]'); await page.locator('.catalog-card').first().waitFor(); await settled();
    report.checks.push('Store catalog, installed and update views render with finite 300ms content fades');
    await page.getByRole('button', { name: '기능 유형', exact: true }).click();
    const filterMotion = await page.locator('.filter-menu:not([hidden])').evaluate(node => ({ duration: getComputedStyle(node).transitionDuration, animations: node.getAnimations().map(animation => animation.effect.getTiming().duration) }));
    assert(filterMotion.duration.split(',').every(value => value.trim() === '0.2s'));
    await page.getByRole('option', { name: 'Skill', exact: true }).click(); await settled();
    assert.equal(await page.locator('#type-filter').inputValue(), 'Skill');
    await page.getByRole('button', { name: '기능 유형', exact: true }).click();
    await page.getByRole('option', { name: '모든 유형', exact: true }).click(); await settled();
    await page.evaluate(() => window.fixtureConfig.hold.installations = true);
    await instantClick('[data-tab="installed"]'); await page.waitForFunction(() => window.heldRequests.some(message => message.action === 'installations'));
    await instantClick('[data-tab="updates"]'); await instantClick('[data-tab="catalog"]');
    await page.evaluate(() => window.releaseHost('installations'));
    await page.locator('.catalog-card').first().waitFor(); await settled();
    assert.equal(await tab('catalog').getAttribute('aria-current'), 'page');
    assert.equal(await page.locator('.install-record').count(), 0);
    report.checks.push('Dropdown has a 200ms fade without losing selection; delayed prior-tab replies cannot replace the newest catalog');

    await openDetail();
    const openMotion = await motion('#detail-dialog');
    assert(openMotion.duration.split(',').every(value => value.trim() === '0.3s'), 'Modal transitions remain 300ms');
    assert(openMotion.animations.some(animation => animation.properties.includes('opacity')), 'Modal fades in');
    await pausedFrame('03-detail-open-mid.png');
    await screenshot('04-detail-open-light.png');
    await instantClick('#detail-tab-connect');
    const panelMotion = await motion('#detail-panel');
    assert(panelMotion.animations.some(animation => animation.duration === 300 && animation.properties.includes('opacity')));
    await settled();
    // Confirmation is stacked over the detail dialog, preserving it beneath.
    await instantClick('#detail-panel [data-install-tool]'); await page.locator('#confirm-dialog[open]').waitFor(); await settled();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#confirm-dialog').evaluate(node => node.open), false);
    assert.equal(await page.locator('#detail-dialog').evaluate(node => node.open), true);
    assert.equal(await count('install'), 0);
    await settled();
    const detailLayout = await layout('#detail-dialog');
    const closeMotion = await page.locator('#detail-close').evaluate(node => { node.click(); const dialog = document.querySelector('#detail-dialog'); return { open: dialog.open, pointerEvents: getComputedStyle(dialog).pointerEvents, animations: dialog.getAnimations().map(animation => ({ duration: animation.effect.getTiming().duration, properties: Object.keys(animation.effect.getKeyframes()[0] || {}) })), focusOnCard: !!document.activeElement.closest('.catalog-card') }; });
    assert.equal(closeMotion.open, false, 'Native dialog close is immediate');
    assert.equal(closeMotion.pointerEvents, 'none', 'Fading-out modal never intercepts pointer input');
    assert.equal(closeMotion.focusOnCard, true, 'Native keyboard focus is restored immediately');
    assert(closeMotion.animations.some(animation => animation.duration === 300), 'Closing modal retains a finite visual fade');
    assert.deepEqual(await layout('#detail-dialog'), detailLayout, 'Closing detail preserves its column layout throughout the retained fade layer');
    report.measurements.detailOpen = openMotion; report.measurements.detailClose = closeMotion;
    await pausedFrame('05-detail-close-mid.png');
    report.checks.push('Detail open/close and detail tabs animate; nested install cancellation preserves parent detail, performs no install and restores focus');

    // Reopen during the first close frame; a delayed close must not hide the new dialog.
    await openDetail(); await settled();
    await page.evaluate(() => { document.querySelector('#detail-close').click(); document.querySelector('.catalog-card:first-child .tool-title').click(); });
    await page.locator('#detail-dialog[open] #detail-panel').waitFor(); await settled();
    assert.equal(await page.locator('#detail-dialog').evaluate(node => node.open), true);
    await page.keyboard.press('Escape'); await settled();
    assert.equal(await page.locator('#detail-dialog').evaluate(node => node.open), false);
    // Backdrop clicks are not allowed to accidentally activate a card beneath.
    await openDetail(); await settled(); const detailsBeforeBackdrop = await count('detail');
    await page.mouse.click(4, 4); await settled();
    assert.equal(await count('detail'), detailsBeforeBackdrop);
    if (await page.locator('#detail-dialog').evaluate(node => node.open)) await page.keyboard.press('Escape');
    await settled();
    report.checks.push('Rapid close/reopen keeps newest dialog open; Escape and backdrop do not activate underlying cards');

    await instantClick('#publish-open'); await page.waitForFunction(() => !document.querySelector('#publish-name').disabled); await settled();
    await page.locator('#publish-name').fill('작성 중인 도구 이름'); await page.locator('#publish-desc').fill('이 설명은 팝업을 닫고 다시 열어도 유지되어야 합니다.');
    const publishLayout = await layout('#publish-dialog');
    await instantClick('#publish-close');
    assert.deepEqual(await layout('#publish-dialog'), publishLayout, 'Closing publish preserves its form/footer layout throughout the fade');
    await pausedFrame('06a-publish-close-mid.png');
    await instantClick('#publish-open'); await settled();
    assert.equal(await page.locator('#publish-name').inputValue(), '작성 중인 도구 이름');
    assert.equal(await page.locator('#publish-desc').inputValue(), '이 설명은 팝업을 닫고 다시 열어도 유지되어야 합니다.');
    assert.equal(await count('preparePublish'), 0); assert.equal(await count('publish'), 0);
    await screenshot('06-publish-draft-light.png');
    await page.keyboard.press('Escape'); await settled();
    assert.equal(await page.locator('#publish-open').evaluate(node => node === document.activeElement), true);
    await instantClick('#connection-button'); await page.locator('#connection-view').waitFor();
    assert((await motion('#connection-view')).animations.some(animation => animation.duration === 300));
    await settled(); await instantClick('#connection-cancel'); await page.locator('.catalog-card').first().waitFor(); await settled();
    report.checks.push('Publish modal keeps typed draft on close/reopen; connection view returns without credential mutation');

    await page.evaluate(() => window.postMessage({ type: 'ax-extension-theme', channel: 'motion-fixture', theme: 'dark' }, '*'));
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark'); await noOverflow(); await screenshot('07-catalog-dark.png');
    await openDetail(); await settled(); await noOverflow(); await screenshot('08-detail-dark.png');
    await page.keyboard.press('Escape'); await settled();
    await page.setViewportSize({ width: 390, height: 844 }); await noOverflow(); await screenshot('09-catalog-narrow.png');
    await openDetail(); await settled(); await noOverflow(); await screenshot('10-detail-narrow.png'); await page.keyboard.press('Escape'); await settled();
    report.checks.push('Light/dark 1180px and narrow 390px layouts have no horizontal overflow');

    await page.setViewportSize({ width: 1180, height: 900 });
    // Warm the browser/font/JS caches, then compare equal DOM states after GC.
    async function cycle() {
      await openDetail(); await page.locator('#detail-panel').waitFor(); await instantClick('#detail-tab-versions'); await page.keyboard.press('Escape');
      await instantClick('#publish-open'); await page.locator('#publish-dialog[open]').waitFor(); await page.keyboard.press('Escape');
      await instantClick('[data-tab="installed"]'); await page.locator('.install-record').first().waitFor();
      await instantClick('[data-tab="catalog"]'); await page.locator('.catalog-card').first().waitFor();
    }
    for (let index = 0; index < 5; index++) await cycle(); await settled();
    const before = await metrics();
    for (let index = 0; index < 30; index++) await cycle(); await settled();
    const after = await metrics();
    report.measurements.repeatedTransitions = { cycles: 30, before, after, delta: { nodes: after.nodes - before.nodes, listeners: after.jsEventListeners - before.jsEventListeners, heapBytes: after.heapBytes - before.heapBytes } };
    assert.equal(after.animations, 0, 'No finished animations retained by the document');
    assert(after.nodes - before.nodes <= 8, 'Repeated navigation must not accumulate detached DOM');
    assert(after.jsEventListeners - before.jsEventListeners <= 2, 'Repeated navigation must not add persistent event listeners');
    assert(after.heapBytes - before.heapBytes < 1500000, 'Retained heap growth stays below 1.5MB across 30 cycles');
    report.checks.push('30 repeated navigation/modal cycles leave no active animations or accumulating DOM/listeners after GC');

    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    const timingMetrics = async () => Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.filter(row => ['TaskDuration', 'ScriptDuration', 'RecalcStyleDuration', 'LayoutDuration'].includes(row.name)).map(row => [row.name, row.value]));
    const cpuBefore = await timingMetrics();
    await page.evaluate(() => { window.motionTasks.length = 0; window.motionFrameTimes = []; window.motionLastFrame = 0; window.motionFrameHandle = requestAnimationFrame(function frame(now) { if (window.motionLastFrame) window.motionFrameTimes.push(now - window.motionLastFrame); window.motionLastFrame = now; window.motionFrameHandle = requestAnimationFrame(frame); }); });
    for (let index = 0; index < 8; index++) await cycle(); await settled();
    const cpu = await page.evaluate(() => { cancelAnimationFrame(window.motionFrameHandle); return { tasks: window.motionTasks, frames: window.motionFrameTimes }; });
    const sorted = cpu.frames.slice().sort((a, b) => a - b);
    const cpuAfter = await timingMetrics();
    report.measurements.cpu4x = { cycles: 8, frameCount: sorted.length, frameIntervalP95Ms: sorted[Math.floor(sorted.length * .95)], worstFrameIntervalMs: sorted.at(-1), longTaskCount: cpu.tasks.length, maxLongTaskMs: Math.max(0, ...cpu.tasks.map(task => task.duration)), workMs: Object.fromEntries(Object.entries(cpuAfter).map(([key,value])=>[key, +(1000*(value-cpuBefore[key])).toFixed(2)])) };
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const reducedBefore = await timingMetrics();
    await page.evaluate(() => { window.motionTasks.length = 0; window.motionFrameTimes = []; window.motionLastFrame = 0; window.motionFrameHandle = requestAnimationFrame(function frame(now) { if (window.motionLastFrame) window.motionFrameTimes.push(now - window.motionLastFrame); window.motionLastFrame = now; window.motionFrameHandle = requestAnimationFrame(frame); }); });
    for (let index = 0; index < 8; index++) await cycle(); await settled();
    const reducedCpu = await page.evaluate(() => { cancelAnimationFrame(window.motionFrameHandle); return { tasks: window.motionTasks, frames: window.motionFrameTimes }; });
    const reducedAfter = await timingMetrics();
    const reducedFrames = reducedCpu.frames.slice().sort((a,b)=>a-b);
    report.measurements.cpu4xReducedMotionBaseline = { cycles:8, frameCount:reducedFrames.length, frameIntervalP95Ms:reducedFrames[Math.floor(reducedFrames.length*.95)], worstFrameIntervalMs:reducedFrames.at(-1), longTaskCount:reducedCpu.tasks.length, maxLongTaskMs:Math.max(0,...reducedCpu.tasks.map(task=>task.duration)), workMs:Object.fromEntries(Object.entries(reducedAfter).map(([key,value])=>[key,+(1000*(value-reducedBefore[key])).toFixed(2)])) };
    await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 });
    report.checks.push('CPU 4x slowdown recorded during eight full navigation/dialog cycles, with no page errors or stuck controls');

    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await instantClick('[data-tab="installed"]'); await page.locator('.install-record').first().waitFor();
    assert((await motion('#results')).animations.length > 0);
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.waitForFunction(() => document.getAnimations().length === 0);
    assert.equal(await page.evaluate(() => document.getAnimations().length), 0);
    await instantClick('[data-tab="catalog"]'); await page.locator('.catalog-card').first().waitFor();
    await openDetail(); assert.equal(await page.evaluate(() => document.getAnimations().length), 0);
    await page.keyboard.press('Escape'); assert.equal(await page.evaluate(() => document.getAnimations().length), 0);
    await instantClick('#publish-open'); assert.equal(await page.evaluate(() => document.getAnimations().length), 0);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#publish-name').inputValue(), '작성 중인 도구 이름');
    report.checks.push('Reduced-motion disables entrance, pane and dialog transitions while preserving interaction/drafts');
    assert.deepEqual(report.errors, []);
    assert.equal(await count('install'), 0); assert.equal(await count('publish'), 0); assert.equal(await count('disconnect'), 0);
    // A short real rendered clip makes the motion reviewable without a mockup.
    const videoContext = await browser.newContext({ viewport: { width: 1180, height: 900 }, recordVideo: { dir: path.join(output, 'video'), size: { width: 1180, height: 900 } } });
    page = await videoContext.newPage(); page.setDefaultTimeout(8000);
    await page.route(origin + '/**', route => route.fulfill({ status: 200, contentType: route.request().url().endsWith('.woff') ? 'font/woff' : 'text/html', body: route.request().url().endsWith('.woff') ? font : html }));
    await fixture(); await settled();
    await instantClick('[data-tab="installed"]'); await page.locator('.install-record').first().waitFor(); await settled();
    await instantClick('[data-tab="catalog"]'); await page.locator('.catalog-card').first().waitFor(); await settled();
    await openDetail(); await settled();
    await instantClick('#detail-tab-connect'); await settled();
    await page.keyboard.press('Escape'); await settled();
    const video = page.video(); await videoContext.close();
    await video.saveAs(path.join(output, 'store-motion-preview.webm'));
    report.video = 'store-motion-preview.webm';
    report.checks.push('Dialog flex layout remains unchanged during closing frames; actual motion preview recorded');
    report.passed = true;
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ passed: true, checks: report.checks.length, measurements: report.measurements, output }, null, 2));
  } catch (error) {
    report.failure = String(error.stack || error); fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(report, null, 2)); throw error;
  } finally {
    if (process.platform === 'win32') require('node:child_process').spawnSync('taskkill.exe', ['/PID', String(server.process().pid), '/T', '/F'], { windowsHide: true, timeout: 10000, stdio: 'ignore' });
    await Promise.race([server.close(), new Promise(resolve => setTimeout(resolve, 3000))]);
  }
})().then(() => process.exit(0), error => { console.error(error); process.exit(1); });
