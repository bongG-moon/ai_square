// Real Chromium form behavior with synthetic host RPC; never uses a personal KEY.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(require('node:os').homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const source = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(source, 'ui/index.html'), 'utf8')
  .replace('<!--STORE_STYLE-->', '<style>' + fs.readFileSync(path.join(source, 'ui/store.css'), 'utf8') + '</style>');
const script = fs.readFileSync(path.join(source, 'ui/store.js'), 'utf8');

(async () => {
  const server = await chromium.launchServer({ executablePath: path.join(process.env['ProgramFiles(x86)'] || 'C:/Program Files (x86)', 'Microsoft/Edge/Application/msedge.exe'), headless: true });
  const browser = await chromium.connect(server.wsEndpoint());
  try {
    const page = await browser.newPage();
    page.setDefaultTimeout(5000);
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    async function fixture(status) {
      await page.goto('about:blank'); await page.setContent(html);
      await page.evaluate(initial => {
        window.requests = [];
        let status = initial;
        window.addEventListener('message', event => {
          const m = event.data;
          if (m.type === 'ax-extension-ready') return window.postMessage({ type: 'ax-extension-init', channel: 'fixture', context: {} }, '*');
          if (m.type !== 'ax-extension-request') return;
          window.requests.push(m);
          let result = {};
          if (m.action === 'status') result = status;
          if (m.action === 'connect') { status = { ...status, configured: true, baseUrl: m.payload.url }; result = status; }
          if (m.action === 'options') result = { organizations: [] };
          if (m.action === 'catalog') result = { items: [], total: 0 };
          window.postMessage({ type: 'ax-extension-response', channel: m.channel, requestId: m.requestId, ok: true, result }, '*');
        });
      }, status);
      await page.addScriptTag({ content: script });
      await page.waitForFunction(() => window.requests.some(r => r.action === 'status'));
    }
    const key = 'ptsq_' + 'a'.repeat(43);
    await fixture({ configured: false, baseUrl: '', presetBaseUrl: 'https://square.example.test' });
    await page.locator('#connection-view').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#server-url').inputValue(), 'https://square.example.test');
    assert.equal(await page.locator('#server-url').getAttribute('readonly'), '');
    assert.equal(await page.locator('#http-warning').isVisible(), false);
    await page.locator('#connection-key').fill(key); await page.locator('#connect-submit').click();
    await page.locator('#catalog-view').waitFor({ state: 'visible' });
    const submitted = await page.evaluate(() => window.requests.find(r => r.action === 'connect').payload);
    assert.deepEqual(submitted, { url: 'https://square.example.test', key, allowHttp: false });
    assert.equal(await page.locator('#connection-key').inputValue(), '');

    await fixture({ configured: false, baseUrl: '', presetBaseUrl: 'http://internal.example.test' });
    await page.locator('#http-warning').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#allow-http').isChecked(), false);
    await page.locator('#connection-key').fill(key); await page.locator('#connect-submit').click();
    assert.equal(await page.evaluate(() => window.requests.filter(r => r.action === 'connect').length), 0);
    await page.locator('#allow-http').check(); await page.locator('#connect-submit').click();
    await page.locator('#catalog-view').waitFor({ state: 'visible' });

    await page.locator('#connection-button').click();
    await page.locator('#connection-key').fill(key); await page.locator('#allow-http').check();
    await page.locator('#change-server').click();
    assert.equal(await page.locator('#server-url').isEditable(), true);
    assert.equal(await page.locator('#connection-key').inputValue(), '');
    assert.equal(await page.locator('#allow-http').isChecked(), false);
    await page.locator('#connection-key').fill(key);
    await page.locator('#server-url').fill('https://other.example.test');
    assert.equal(await page.locator('#connection-key').inputValue(), '');
    assert.equal(await page.locator('#http-warning').isVisible(), false);
    await page.locator('#change-server').click();
    assert.equal(await page.locator('#server-url').inputValue(), 'http://internal.example.test');

    await fixture({ configured: true, baseUrl: 'https://saved.example.test', presetBaseUrl: 'https://downloaded.example.test' });
    await page.locator('#catalog-view').waitFor({ state: 'visible' });
    await page.locator('#connection-button').click();
    assert.equal(await page.locator('#server-url').inputValue(), 'https://saved.example.test');
    assert.match(await page.locator('#server-help').innerText(), /기존에 저장한 연결/);
    assert.equal(await page.evaluate(() => window.requests.filter(r => r.action === 'connect').length), 0);

    await fixture({ configured: false, baseUrl: '', presetBaseUrl: '', presetMessage: '주소를 직접 입력하세요.' });
    await page.locator('#connection-view').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#server-url').isEditable(), true);
    assert.equal(await page.locator('#change-server').isVisible(), false);
    assert.match(await page.locator('#server-help').innerText(), /직접 입력/);
    assert.deepEqual(errors, []);
    console.log('PASS: preset KEY-only form, HTTP consent, manual switch clears KEY, saved connection precedence, invalid-preset fallback.');
  } finally { await browser.close(); await server.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
