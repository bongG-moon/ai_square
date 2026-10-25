// Verify actual font decoding inside the production opaque-origin iframe.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || path.join(require('node:os').homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const out = path.resolve(process.env.STORE_BROWSER_OUTPUT || 'outputs/store-publish-design-20261025');
const runtime = JSON.parse(fs.readFileSync(path.join(out,'runtime.json'),'utf8'));
(async()=>{
  const browser = await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  try {
    const page = await browser.newPage(), errors = [];
    page.on('console', m=>{if(m.type()==='error') errors.push(m.text());});
    await page.goto(runtime.url);
    await page.locator('.workspace-extension-menu').click();
    const frame = await (await page.locator('.workspace-extension-frame').elementHandle()).contentFrame();
    await frame.locator('#store').waitFor();
    const result = await frame.evaluate(async()=>{
      const f = new FontFace('Verified Host Noto','url(/fonts/NotoSansKR-Variable.woff)',{weight:'100 900'});
      await f.load(); document.fonts.add(f);
      const entry = performance.getEntriesByName(new URL('/fonts/NotoSansKR-Variable.woff',location.href).href)[0];
      return {fontStatus:f.status,decoded:true,hostFontPath:'/fonts/NotoSansKR-Variable.woff',bodyBytes:entry?.decodedBodySize,
        secureContext:isSecureContext,requestIdSupported:typeof crypto.randomUUID==='function'};
    });
    assert.equal(result.fontStatus,'loaded'); assert.equal(result.requestIdSupported,true); assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(out,'host-font-result.json'), JSON.stringify({...result,errors},null,2));
    console.log(JSON.stringify(result));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
