// Visual regression with synthetic parent responses; no personal KEY or live server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(require('node:os').homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const root = path.resolve(__dirname, '../..'), source = path.join(root, 'organization-store');
const output = path.join(root, 'outputs/store-design-review-20261025');
fs.mkdirSync(output, { recursive: true });
const html = fs.readFileSync(path.join(source, 'ui/index.html'), 'utf8').replace('<!--STORE_STYLE-->', '<style>' + fs.readFileSync(path.join(source, 'ui/store.css'), 'utf8') + '</style>');
const script = fs.readFileSync(path.join(source, 'ui/store.js'), 'utf8');
const app = path.resolve(process.env.AX_WORKSPACE_SOURCE || path.join(root, 'build/workspace-local-repository'));
const fontPath = path.join(app, 'local_app/web/fonts/NotoSansKR-Variable.woff');
if (!fs.existsSync(fontPath)) throw new Error('This browser layout test needs the AX Workspace font. Set AX_WORKSPACE_SOURCE to its compatible source checkout.');
const font = fs.readFileSync(fontPath);
(async () => {
  const server = await chromium.launchServer({ executablePath: path.join(process.env['ProgramFiles(x86)'] || 'C:/Program Files (x86)', 'Microsoft/Edge/Application/msedge.exe'), headless: true });
  const browser = await chromium.connect(server.wsEndpoint());
  try {
    const page = await browser.newPage({ viewport: { width: 1180, height: 900 } });
    page.setDefaultTimeout(5000);
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    const base = 'http://127.0.0.1:17362';
    await page.route(base + '/**', route => route.fulfill({ status: 200, contentType: route.request().url().endsWith('.woff') ? 'font/woff' : 'text/html', body: route.request().url().endsWith('.woff') ? font : html }));
    await page.goto(base + '/');
    await page.evaluate(() => {
      window.requests = [];
      window.addEventListener('message', event => {
        const m = event.data;
        if (m.type === 'ax-extension-ready') return window.postMessage({ type: 'ax-extension-init', channel: 'design-review', context: {} }, '*');
        if (m.type !== 'ax-extension-request') return;
        window.requests.push(m);
        if (m.action === 'connect') {
          window.failConnection = () => window.postMessage({ type: 'ax-extension-response', channel: m.channel, requestId: m.requestId, ok: false, error: 'KEY는 서버에서 확인했지만 Windows 보안 저장소에 연결 정보를 저장하지 못했어요. 사용자 폴더의 저장 권한을 확인해 주세요. 기존 연결은 그대로 유지됩니다.' }, '*');
          return;
        }
        window.postMessage({ type: 'ax-extension-response', channel: m.channel, requestId: m.requestId, ok: true, result: { configured: false, baseUrl: '', presetBaseUrl: 'http://square.example.test', existingConnectionAvailable: true } }, '*');
      });
    });
    await page.addScriptTag({ content: script });
    await page.locator('#connection-view').waitFor({ state: 'visible' });
    await page.evaluate(() => document.fonts.load('13px "Noto Sans KR"'));
    assert.equal(await page.evaluate(() => document.fonts.check('13px "Noto Sans KR"')), true);
    const layouts = [];
    for (const [width, theme, name] of [[1180, 'light', 'connection-light'], [1180, 'dark', 'connection-dark'], [780, 'light', 'connection-medium'], [390, 'dark', 'connection-narrow']]) {
      await page.setViewportSize({ width, height: 900 });
      await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme);
      const layout = await page.evaluate(() => ({ width: innerWidth, pageWidth: document.documentElement.scrollWidth, inputWidth: document.querySelector('#connection-key').getBoundingClientRect().width, buttonHeight: document.querySelector('#connect-submit').getBoundingClientRect().height }));
      assert.ok(layout.pageWidth <= width, JSON.stringify(layout));
      assert.ok(layout.buttonHeight >= 34);
      layouts.push({ theme, ...layout });
      await page.screenshot({ path: path.join(output, name + '.png'), fullPage: true, animations: 'disabled' });
    }
    await page.locator('#connection-key').fill('ptsq_' + 'a'.repeat(43));
    await page.locator('#allow-http').check();
    await page.locator('#connect-submit').click();
    await page.waitForFunction(() => !!window.failConnection);
    assert.equal(await page.locator('#connect-submit').getAttribute('aria-busy'), 'true');
    assert.match(await page.locator('#connect-submit').innerText(), /연결 확인 중/);
    await page.screenshot({ path: path.join(output, 'connection-pending-narrow.png'), fullPage: true, animations: 'disabled' });
    await page.evaluate(() => window.failConnection());
    await page.waitForFunction(() => !document.querySelector('#connect-submit').disabled);
    assert.equal(await page.locator('#connection-feedback').isVisible(), true);
    assert.match(await page.locator('#connection-feedback').innerText(), /기존 연결은 그대로 유지/);
    assert.equal(await page.locator('#feedback').isVisible(), false);
    const feedbackBounds = await page.locator('#connection-feedback').evaluate(node => ({ bottom: node.getBoundingClientRect().bottom, buttonTop: document.querySelector('#connect-submit').getBoundingClientRect().top }));
    assert.ok(feedbackBounds.bottom <= feedbackBounds.buttonTop);
    await page.screenshot({ path: path.join(output, 'connection-error-narrow.png'), fullPage: true, animations: 'disabled' });
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'connection-layout.json'), JSON.stringify({ passed: true, layouts, errors }, null, 2));
    console.log('PASS: connection layout light/dark at 1180/780/390, pending and failure states, Noto Sans KR, no page errors.');
  } finally {
    if (process.platform === 'win32') require('node:child_process').spawnSync('taskkill.exe', ['/PID', String(server.process().pid), '/T', '/F'], { windowsHide: true, timeout: 10000, stdio: 'ignore' });
    await Promise.race([server.close(), new Promise(resolve => setTimeout(resolve, 3000))]);
  }
})().then(() => process.exit(0), error => { console.error(error); process.exit(1); });
