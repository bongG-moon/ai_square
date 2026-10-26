// Real Edge renderer, synthetic host replies only. Never touches user installations or KEYs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(require('node:os').homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const root = path.resolve(__dirname, '../..'), source = path.join(root, 'organization-store');
const html = fs.readFileSync(path.join(source, 'ui/index.html'), 'utf8').replace('<!--STORE_STYLE-->', '<style>' + fs.readFileSync(path.join(source, 'ui/store.css'), 'utf8') + '</style>');
const script = fs.readFileSync(path.join(source, 'ui/store.js'), 'utf8');
const font = fs.readFileSync(path.join(root, 'build/workspace-local-repository/local_app/web/fonts/NotoSansKR-Variable.woff'));
const output = process.env.STORE_PROGRESS_OUTPUT || path.join(root, 'outputs/store-install-progress-20261026');
fs.mkdirSync(output, { recursive: true });

(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless: true });
  const errors = [], checks = [], screenshots = [], origins = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 950 } });
    page.setDefaultTimeout(7000);
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      const url = new URL(route.request().url()); origins.push(url.origin);
      if (url.origin !== 'http://127.0.0.1:48592') return route.abort();
      return route.fulfill({ status: 200, contentType: url.pathname.endsWith('.woff') ? 'font/woff' : 'text/html', body: url.pathname.endsWith('.woff') ? font : html });
    });
    async function fixture(config = {}) {
      await page.emulateMedia({ reducedMotion: 'no-preference' });
      await page.setViewportSize({ width: 1100, height: 950 });
      await page.goto('http://127.0.0.1:48592/');
      await page.evaluate(options => {
        window.requests = []; window.held = {}; window.armInstallTimeout = false;
        window.fixtureStatus = { configured: true, baseUrl: 'https://square.example.test', existingConnectionAvailable: true };
        window.fixtureRecords = null; window.fixtureRecovery = { blocked: [] };
        const originalTimeout = window.setTimeout.bind(window);
        if (options.timeout) window.setTimeout = (fn, ms, ...args) => originalTimeout(fn, ms === 130000 && window.armInstallTimeout ? 150 : ms, ...args);
        const item = { id: 1, name: '주간 업무 보고서', desc: '업무 자료를 정리하고 보고서를 작성합니다.', type: 'Skill', platform: 'Claude', access: 'approved', registrantName: '예시 등록자', guide: '처음 사용하기 전에 등록자가 제공한 설정 안내를 확인하세요.' };
        const plan = { canInstall: true, planId: 'approved-plan', approvalDigest: 'approved-digest', destination: 'C:/Users/demo/.claude/skills/weekly-report', release: '1.0' };
        let installed = false;
        const reply = (message, result, error) => {
          if (message.action === 'install' && !error) installed = true;
          window.postMessage({ type: 'ax-extension-response', channel: message.channel, requestId: message.requestId, ok: !error, result, ...(error ? { error } : {}) }, '*');
        };
        window.release = action => { const entry = window.held[action]; if (!entry) throw Error('No held ' + action); delete window.held[action]; reply(...entry); };
        window.addEventListener('message', event => {
          const message = event.data;
          if (message.type === 'ax-extension-ready') return window.postMessage({ type: 'ax-extension-init', channel: 'progress-fixture', hostFeatures: ['workspaces'], theme: 'light', context: { kind: 'work', title: '주간 보고', workspace: 'D:/Work/weekly' } }, '*');
          if (message.type !== 'ax-extension-request') return;
          window.requests.push(message);
          let result = {}, error;
          if (message.action === 'status') result = window.fixtureStatus;
          if (message.action === 'options') result = { organizations: [] };
          if (message.action === 'catalog') result = { items: [item], total: 1 };
          if (message.action === 'detail') result = { item, canInstall: true, manifest: { downloadUrl: '/download/1', installProfile: { scopes: ['user', 'project'] } } };
          if (message.action === 'host.listWorkspaces') result = { items: [{ id: 'work-a', title: '주간 보고', workspace: 'D:/Work/weekly' }] };
          if (message.action === 'prepareInstall') {
            result = options.unsupported ? { canInstall: false, reason: '이 ZIP은 자동 설치를 지원하지 않습니다.' } : plan;
            if (options.prepareError) error = '설치 자료를 확인하지 못했습니다.';
          }
          if (message.action === 'install') { result = { status: 'installed', notice: '파일 설치를 완료했어요.' }; if (options.installError) error = '폴더 접근 권한이 없어 설치하지 못했습니다.'; }
          if (message.action === 'installations') {
            result = { items: window.fixtureRecords || (installed ? [{ installationId: 'fixture-install', name: item.name, toolId: 1, type: 'Skill', release: '1.0', status: 'installed', target: plan.destination, completedPlanId: plan.planId }] : []), recovery: window.fixtureRecovery };
            if (options.listError) error = '설치는 완료됐지만 목록 조회가 실패했습니다.';
          }
          if ((message.action === 'prepareInstall' && options.holdPrepare) || (message.action === 'install' && options.holdInstall)) { window.held[message.action] = [message, result, error]; return; }
          reply(message, result, error);
        });
      }, config);
      await page.addScriptTag({ content: script });
      await page.getByRole('button', { name: '주간 업무 보고서', exact: true }).click();
      await page.getByRole('tab', { name: '설치·연결', exact: true }).click();
    }
    const phase = value => page.waitForFunction(phase => document.querySelector('#installation-status')?.dataset.phase === phase, value);
    const count = action => page.evaluate(action => window.requests.filter(item => item.action === action).length, action);
    async function connectionLocked() {
      assert.equal(await page.locator('#connection-button').isDisabled(), true);
      await page.evaluate(() => {
        for (const id of ['connection-button', 'reuse-connection', 'disconnect']) document.getElementById(id).dispatchEvent(new MouseEvent('click', { bubbles: true }));
      });
      assert.equal(await page.locator('#connection-view').isVisible(), false);
      assert.equal(await count('connect'), 0); assert.equal(await count('disconnect'), 0);
    }
    async function chooseScope() {
      await page.locator('[data-install-tool]').click();
      await page.getByRole('dialog', { name: '어디에서 사용할까요?' }).waitFor();
      await connectionLocked();
      await page.locator('input[value=user]').check(); await page.locator('#confirm-yes').click();
    }
    async function confirmInstall() {
      await page.getByRole('dialog', { name: '이 내용으로 설치할까요?' }).waitFor();
      assert.match(await page.locator('#confirm-content').innerText(), /KEY/);
      await page.locator('#confirm-yes').click();
    }
    async function shot(name) {
      await page.screenshot({ path: path.join(output, name), fullPage: true, animations: 'disabled' }); screenshots.push(name);
    }
    async function assertLayout() {
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), true);
      for (const id of ['detail-installation-status', 'installation-status']) {
        const node = page.locator('#' + id);
        if (await node.isVisible()) assert.equal(await node.evaluate(n => n.scrollWidth <= n.clientWidth + 1), true);
      }
    }

    await fixture({ holdPrepare: true, holdInstall: true });
    await chooseScope(); await phase('preparing');
    assert.equal(await count('install'), 0);
    assert.equal(await page.locator('[data-install-tool]').isDisabled(), true);
    assert.equal(await page.locator('[data-install-tool] .install-spinner[aria-hidden=true]').count(), 1);
    assert.equal(await page.locator('#detail-installation-status').isVisible(), true);
    assert.doesNotMatch(await page.locator('#detail-installation-status').innerText(), /\d+\s*%/);
    await shot('01-preparing-light.png');
    await page.evaluate(() => window.release('prepareInstall')); await phase('review');
    assert.equal(await count('install'), 0);
    await confirmInstall(); await phase('installing');
    await connectionLocked();
    await page.waitForFunction(() => window.requests.some(r => r.action === 'install'));
    assert.equal(await count('install'), 1);
    assert.match(await page.locator('[data-install-tool]').innerText(), /설치 중/);
    await page.getByRole('tab', { name: '소개', exact: true }).click();
    await page.getByRole('tab', { name: '설치·연결', exact: true }).click();
    assert.equal(await page.locator('[data-install-tool]').isDisabled(), true);
    await page.locator('[data-install-tool]').evaluate(node => { node.dispatchEvent(new MouseEvent('click', { bubbles: true })); node.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
    assert.equal(await count('install'), 1); assert.equal(await count('prepareInstall'), 1);
    await assertLayout(); await shot('02-installing-light.png');
    await page.evaluate(() => window.postMessage({ type: 'ax-extension-theme', channel: 'progress-fixture', theme: 'dark' }, '*'));
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    await shot('03-installing-dark.png');
    await page.setViewportSize({ width: 420, height: 850 }); await assertLayout(); await shot('04-installing-narrow.png');
    await page.emulateMedia({ reducedMotion: 'reduce' });
    assert.equal(await page.locator('[data-install-tool] .install-spinner').evaluate(node => getComputedStyle(node).animationName), 'none');
    await page.locator('#detail-close').click();
    assert.equal(await page.locator('#installation-status').isVisible(), true); await phase('installing');
    await shot('05-installing-persistent.png');
    await page.locator('[data-tab=installed]').click(); await phase('installing');
    await page.evaluate(() => window.release('install')); await phase('done');
    await page.getByRole('button', { name: '상태 확인', exact: true }).waitFor();
    assert.equal(await page.locator('[data-tab=installed]').getAttribute('aria-current'), 'page');
    assert.equal(await count('install'), 1);
    assert.deepEqual(await page.evaluate(() => window.requests.find(r => r.action === 'install').payload), { planId: 'approved-plan', approvalDigest: 'approved-digest', confirmed: true });
    assert.equal(await page.locator('#installation-status .install-spinner').count(), 0);
    assert.equal(await page.locator('#installation-status').getByRole('button', { name: '설정 안내 보기', exact: true }).count(), 1);
    await shot('06-complete.png');
    await page.locator('#installation-status').getByRole('button', { name: '설정 안내 보기', exact: true }).click();
    await page.getByRole('tab', { name: '설치·연결', exact: true }).waitFor();
    assert.equal(await page.getByRole('tab', { name: '설치·연결', exact: true }).getAttribute('aria-selected'), 'true');
    assert.match(await page.locator('#detail-panel').innerText(), /등록자가 제공한 설정 안내/);
    assert.equal(await count('install'), 1);
    checks.push('Deferred preparation and installation, no false percent/completion, duplicated activation/rerender cannot repeat install, closed-modal/tab progress persists, verified receipt completes, light/dark/narrow/reduced-motion');

    await fixture({ listError: true }); await chooseScope(); await confirmInstall(); await phase('done');
    await page.locator('#feedback').filter({ hasText: /목록/ }).waitFor();
    assert.equal(await page.locator('#installation-status').getAttribute('data-phase'), 'done');
    assert.equal(await count('install'), 1); checks.push('Installed-list refresh failure does not change successful installation into failure');

    await fixture({ installError: true }); await chooseScope(); await confirmInstall(); await phase('error');
    assert.match(await page.locator('#detail-installation-status').innerText(), /접근 권한/);
    assert.equal(await page.locator('[data-install-tool]').isDisabled(), false);
    assert.equal(await count('install'), 1); assert.equal(await count('installations'), 0);
    await shot('07-failed.png'); checks.push('Explicit install error remains failure and restores install control without auto-retry');

    await fixture({ timeout: true, holdInstall: true }); await chooseScope();
    await page.getByRole('dialog', { name: '이 내용으로 설치할까요?' }).waitFor();
    await page.evaluate(() => { window.armInstallTimeout = true; }); await page.locator('#confirm-yes').click();
    await phase('uncertain');
    await connectionLocked();
    assert.match(await page.locator('#detail-installation-status').innerText(), /설치된 기능/);
    assert.equal(await count('install'), 1);
    assert.equal(await page.locator('[data-install-tool]').isDisabled(), true);
    await shot('08-result-uncertain.png');
    await page.evaluate(() => window.release('install'));
    await phase('done');
    assert.equal(await count('install'), 1);
    checks.push('Timeout blocks repeat installation as result-uncertain, never auto-replays, authenticated late receipt resolves completion');

    await fixture({ timeout: true, holdInstall: true, installError: true }); await chooseScope();
    await page.getByRole('dialog', { name: '이 내용으로 설치할까요?' }).waitFor();
    await page.evaluate(() => { window.armInstallTimeout = true; }); await page.locator('#confirm-yes').click(); await phase('uncertain');
    await page.evaluate(() => window.release('install')); await phase('error');
    assert.equal(await page.locator('[data-install-tool]').isDisabled(), false);
    assert.match(await page.locator('#detail-installation-status').innerText(), /접근 권한/);
    assert.equal(await count('install'), 1);
    checks.push('Authenticated late error resolves uncertainty into failure and releases install control');

    // A persisted receipt must match this exact approved plan, not merely the tool/version.
    async function uncertainFixture() {
      await fixture({ timeout: true, holdInstall: true }); await chooseScope();
      await page.getByRole('dialog', { name: '이 내용으로 설치할까요?' }).waitFor();
      await page.evaluate(() => { window.armInstallTimeout = true; }); await page.locator('#confirm-yes').click(); await phase('uncertain');
    }
    const matchingReceipt = { installationId: 'fixture-install', name: '주간 업무 보고서', toolId: 1, type: 'Skill', release: '1.0', status: 'installed', target: 'C:/Users/demo/.claude/skills/weekly-report', completedPlanId: 'approved-plan' };
    await uncertainFixture();
    await page.evaluate(record => { window.fixtureRecords = [record]; }, matchingReceipt);
    await page.locator('#detail-installation-status').getByRole('button', { name: '설치된 기능 확인', exact: true }).click(); await phase('done');
    assert.match(await page.locator('#installation-status').innerText(), /저장된 설치 기록/);
    assert.equal(await count('install'), 1); assert.equal(await page.locator('#connection-button').isDisabled(), false);
    checks.push('Exact approved plan receipt restores confirmed completion after response loss, without installing again');

    await uncertainFixture();
    await page.evaluate(record => { window.fixtureRecords = [record]; }, { ...matchingReceipt, completedPlanId: 'old-plan' });
    await page.locator('#detail-installation-status').getByRole('button', { name: '설치된 기능 확인', exact: true }).click();
    await page.locator('#installation-status').getByRole('button', { name: '확인 마침', exact: true }).waitFor(); await phase('uncertain');
    for (const mismatch of [{ completedPlanId: undefined }, { toolId: 9 }, { target: 'D:/Unrelated/.claude/skills/weekly-report' }, { release: '0.9' }, { status: 'rolled-back' }]) {
      await page.evaluate(record => { window.fixtureRecords = [record]; }, { ...matchingReceipt, ...mismatch });
      const before = await count('installations'); await page.locator('#refresh').click();
      await page.waitForFunction(n => window.requests.filter(r => r.action === 'installations').length > n, before);
      await page.waitForFunction(() => !document.querySelector('#refresh').disabled);
      await phase('uncertain'); assert.equal(await page.locator('#connection-button').isDisabled(), true);
    }
    await page.evaluate(() => { window.fixtureRecovery = { blocked: [{ toolId: 1, target: 'C:/Users/demo/.claude/skills/weekly-report', message: '변경된 파일을 확인해야 합니다.' }] }; });
    await page.locator('#refresh').click(); await page.waitForFunction(() => !document.querySelector('#refresh').disabled);
    assert.equal(await page.locator('#installation-status').getByRole('button', { name: '확인 마침', exact: true }).count(), 0);
    assert.equal(await page.locator('#connection-button').isDisabled(), true); await phase('uncertain');
    await page.evaluate(() => { window.fixtureRecovery = { blocked: [] }; }); await page.locator('#refresh').click();
    await page.locator('#installation-status').getByRole('button', { name: '확인 마침', exact: true }).click();
    assert.equal(await page.locator('#installation-status').isVisible(), false);
    assert.equal(await page.locator('#connection-button').isDisabled(), false); assert.equal(await count('install'), 1);
    await page.evaluate(() => window.release('install'));
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(await page.locator('#installation-status').isVisible(), false);
    await page.locator('[data-tab=catalog]').click(); await page.getByRole('button', { name: '주간 업무 보고서', exact: true }).click(); await page.getByRole('tab', { name: '설치·연결', exact: true }).click();
    assert.equal(await page.locator('[data-install-tool]').isDisabled(), false); assert.equal(await count('install'), 1);
    checks.push('Old/mismatched receipt never completes new install; blocked recovery remains locked; explicit reviewed finish clears uncertainty and late callback without reinstalling');

    for (const status of [{ configured: true, baseUrl: 'https://another-square.example.test', existingConnectionAvailable: true }, { configured: false, baseUrl: '', existingConnectionAvailable: true }]) {
      await fixture(); await chooseScope(); await confirmInstall(); await phase('done');
      await page.locator('#connection-button').click();
      await page.evaluate(value => { window.fixtureStatus = value; }, status);
      await page.locator('#reuse-connection').click();
      await page.waitForFunction(() => !document.querySelector('#reuse-connection').disabled);
      assert.equal(await page.locator('#installation-status').isVisible(), false);
      assert.equal(await count('install'), 1);
      if (status.configured) assert.match(await page.locator('#connection-label').innerText(), /another-square/);
      else assert.equal(await page.locator('#connection-view').isVisible(), true);
    }
    checks.push('Operation origin is fixed while active; terminal banner is cleared when authenticated initialize changes origin or disconnects');

    await fixture(); await page.locator('[data-install-tool]').click();
    await page.getByRole('dialog', { name: '어디에서 사용할까요?' }).waitFor(); await page.locator('#confirm-no').click(); await phase('cancelled');
    assert.equal(await count('prepareInstall'), 0); assert.equal(await count('install'), 0);
    await chooseScope(); await page.getByRole('dialog', { name: '이 내용으로 설치할까요?' }).waitFor(); await page.locator('#confirm-no').click(); await phase('cancelled');
    assert.equal(await count('install'), 0); assert.equal(await page.locator('[data-install-tool]').isDisabled(), false);
    checks.push('Scope and installation approval cancellation do not execute installation');
    await fixture({ unsupported: true }); await chooseScope(); await phase('error'); assert.equal(await count('install'), 0);
    await fixture({ prepareError: true }); await chooseScope(); await phase('error'); assert.equal(await count('install'), 0);
    checks.push('Unsupported archive and preparation error cannot execute installation');

    assert.deepEqual(errors, []); assert.ok(origins.every(origin => origin === 'http://127.0.0.1:48592'));
    const report = { passed: true, browser: 'Edge headless', fixture: 'Real extension HTML/CSS/JS and deterministic synthetic postMessage host. No real installation, profile, credentials, platform, or external network.', checks, screenshots, pageErrors: errors };
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(report, null, 2) + '\n');
    console.log('PASS: install progress lifecycle, duplicate prevention, uncertainty, completion vs refresh failure, cancellation, layouts, reduced motion.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
