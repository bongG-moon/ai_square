// Run against the isolated test server created by the experience QA harness.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const os=require('node:os');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(os.homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const base=process.env.PTAI_EXPERIENCE_URL;
if(!base)throw Error('PTAI_EXPERIENCE_URL must point to an isolated fixture server.');
const output=process.env.PTAI_EXPERIENCE_OUTPUT||path.resolve('outputs/experience-qa');
fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1280,height:900}});
  await context.addCookies([{name:'test_employee',value:'owner',url:base}]);
  const page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/login');await page.locator('#sq-session').filter({hasText:'owner'}).waitFor();
  assert.equal(await page.locator('#sq-chart-title').textContent(),'등록된 도구');
  assert.equal(await page.locator('#sq-download-title').textContent(),'먼저 살펴볼 도구');
  // New registration survives close, Escape, page reload, and retains only an allowlist.
  await page.locator('[data-action=register]').first().click();
  await page.locator('#sq-register-form [name=name]').fill('초안 보존 테스트');
  await page.locator('#sq-register-form [name=desc]').fill('부서별 실적을 비교하는 설명');
  await page.locator('#sq-register-form [name=workTags]').fill('실적, 보고서');
  await page.locator('#sq-register-form [name=approval]').check();
  await page.locator('#sq-register-form button').filter({hasText:'다음'}).click();
  await page.locator('#sq-register-form [name=guide]').fill('보관할 설치 안내');
  await page.locator('[data-action=close-dialog]').click();
  await page.locator('[data-action=register]').first().click();
  assert.equal(await page.locator('#sq-register-form [name=guide]').inputValue(),'보관할 설치 안내');
  await page.keyboard.press('Escape');await page.reload();
  await page.locator('[data-action=register]').first().click();
  assert.equal(await page.locator('#sq-register-form [name=guide]').inputValue(),'보관할 설치 안내');
  await page.locator('[data-action=wizard-back]').click();
  assert.equal(await page.locator('#sq-register-form [name=name]').inputValue(),'초안 보존 테스트');
  assert.equal(await page.locator('#sq-register-form [name=approval]').isChecked(),true);
  const stored=await page.evaluate(()=>JSON.stringify(sessionStorage));
  assert(stored.includes('초안 보존 테스트'));assert(stored.includes('보관할 설치 안내'));
  await page.screenshot({path:path.join(output,'registration-draft-wide.png')});
  await page.setViewportSize({width:560,height:900});
  assert(await page.locator('#sq-dialog').evaluate(el=>el.scrollWidth<=el.clientWidth+1));
  await page.screenshot({path:path.join(output,'registration-draft-narrow.png')});
  await page.locator('[data-action=registration-discard]').click();await page.locator('#sq-confirm-go').click();
  assert.equal(await page.locator('#sq-register-form [name=name]').inputValue(),'');
  await page.keyboard.press('Escape');await page.reload();await page.locator('[data-action=register]').first().click();
  assert.equal(await page.locator('#sq-register-form [name=name]').inputValue(),'');
  await page.keyboard.press('Escape');await page.setViewportSize({width:1280,height:900});
  // Natural language searches share exactly the server endpoint used by the extension.
  const query='분기 실적을 부서별로 분석해서 보고서를 만들고 싶어요';
  await page.locator('#sq-query').fill(query);await page.locator('#sq-query').press('Enter');
  await page.waitForFunction(()=>document.querySelector('#sq-result-count').textContent.includes('검색 결과 27개'));
  assert.equal(await page.locator('#sq-catalog .sq-tool').count(),12);
  assert((await page.locator('#sq-catalog h3').first().textContent()).includes('보고서'));
  await page.locator('[data-action=catalog-next]').click();
  await page.waitForFunction(()=>document.querySelector('#sq-catalog-pages').textContent.includes('2 / 3'));
  assert.equal(await page.locator('#sq-catalog .sq-tool').count(),12);
  await page.locator('[data-action=catalog-next]').click();
  await page.waitForFunction(()=>document.querySelector('#sq-catalog-pages').textContent.includes('3 / 3'));
  assert.equal(await page.locator('#sq-catalog .sq-tool').count(),3);
  await page.waitForFunction(()=>[...document.querySelectorAll('#sq-catalog .sq-tool')].every(node=>Number(getComputedStyle(node).opacity)>.99));
  await page.screenshot({path:path.join(output,'catalog-search-wide.png')});
  await page.locator('#sq-catalog .sq-tool-main').first().click();await page.locator('#sq-dialog[open] .sq-detail-id').waitFor();await page.keyboard.press('Escape');
  // Failures stop loading; retry reuses the current query. Older replies cannot overwrite it.
  let fail=true;
  await page.route('**/api/catalog?**',async route=>{
   const q=new URL(route.request().url()).searchParams.get('q');
   if(q==='fail-search'&&fail){await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'시험 서버에 연결하지 못했어요.'})});return;}
   if(q==='slow-search'){await new Promise(r=>setTimeout(r,800));await route.fulfill({contentType:'application/json',body:JSON.stringify({items:[],total:0,nextOffset:null,evaluatedCount:0,complete:true,facets:{total:0,organizations:[]}})});return;}
   await route.continue();
  });
  await page.locator('#sq-query').fill('fail-search');await page.locator('#sq-query').press('Enter');
  await page.locator('[data-action=catalog-retry]').waitFor();
  assert.equal(await page.locator('#sq-catalog').getAttribute('aria-busy'),null);
  fail=false;await page.locator('[data-action=catalog-retry]').click();
  await page.waitForFunction(()=>document.querySelector('#sq-result-count').textContent.includes('검색 결과 0개'));
  await page.locator('#sq-query').fill('slow-search');await page.locator('#sq-query').press('Enter');
  await page.locator('#sq-query').fill('html-report');await page.locator('#sq-query').press('Enter');
  await page.waitForFunction(()=>document.querySelector('#sq-result-count').textContent.includes('“html-report” 검색 결과'));
  await page.waitForTimeout(900);
  assert((await page.locator('#sq-result-count').textContent()).includes('html-report'));
  await page.locator('#sq-query').fill('not-found-anywhere');await page.locator('#sq-query').press('Enter');
  await page.locator('#sq-catalog [data-action=clear-filters]').click();
  assert.equal(await page.locator('#sq-query').inputValue(),'');
  // A delayed publish cannot clear a draft edited after the confirmation screen was closed.
  const preparePublish=async name=>{
   await page.locator('[data-action=register]').first().click();
   await page.locator('#sq-register-form [name=name]').fill(name);
   await page.locator('#sq-register-form [name=desc]').fill('게시 초안 회귀 검증');
   await page.locator('#sq-register-form button').filter({hasText:'다음'}).click();
   await page.locator('#sq-register-form input[name=artifact]').setInputFiles({name:'SKILL.md',mimeType:'text/markdown',buffer:Buffer.from('# Test skill\nQA only')});
   await page.locator('#sq-register-form [name=guide]').fill('SKILL.md 내용을 확인하세요.');
   await page.locator('#sq-register-form button').filter({hasText:'다음'}).click();
  };
  await preparePublish('게시 요청 A');
  let finishPublish;
  await page.route('**/api/tools',async route=>{if(route.request().method()!=='POST')return route.continue();const response=await route.fetch();await new Promise(resolve=>{finishPublish=resolve;});await route.fulfill({response});});
  await page.locator('[data-action=publish]').click();
  await page.locator('[data-action=close-dialog]').click();await page.locator('[data-action=register]').first().click();
  await page.locator('[data-action=wizard-back]').click();await page.locator('[data-action=wizard-back]').click();
  await page.locator('#sq-register-form [name=name]').fill('다음 작성 B');
  while(!finishPublish)await page.waitForTimeout(20);finishPublish();
  await page.waitForTimeout(500);
  assert.equal(await page.locator('#sq-register-form [name=name]').inputValue(),'다음 작성 B');
  assert((await page.evaluate(()=>JSON.stringify(sessionStorage))).includes('다음 작성 B'));
  await page.unroute('**/api/tools');
  await page.locator('[data-action=registration-discard]').click();await page.locator('#sq-confirm-go').click();await page.keyboard.press('Escape');
  await preparePublish('정상 게시 C');await page.locator('[data-action=publish]').click();await page.locator('#sq-dialog-title').filter({hasText:'공유할 준비가 되었습니다.'}).waitFor();
  await page.locator('[data-action=close-dialog]').click();await page.locator('[data-action=register]').first().click();assert.equal(await page.locator('#sq-register-form [name=name]').inputValue(),'');await page.keyboard.press('Escape');
  // One account's draft never appears in another account.
  await page.locator('[data-action=register]').first().click();await page.locator('#sq-register-form [name=name]').fill('OWNER_PRIVATE_DRAFT');await page.keyboard.press('Escape');
  await page.evaluate(async()=>{const bootstrap=await(await fetch('/api/bootstrap')).json();await fetch('/api/logout',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':bootstrap.csrf},body:'{}'});});
  await context.addCookies([{name:'test_employee',value:'member',url:base}]);await page.goto(base+'/login');await page.locator('#sq-session').filter({hasText:'member'}).waitFor();
  await page.locator('[data-action=register]').first().click();assert.equal(await page.locator('#sq-register-form [name=name]').inputValue(),'');
  assert.deepEqual(errors,[]);
  console.log('Browser experience checks passed: draft close/Escape/reload/discard/account isolation, form restoration, search pagination/error/retry/race, narrow dialog.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
