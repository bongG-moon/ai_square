(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = String(text); return n; };
  const button = (text, cls, fn, icon) => {
    const n = el('button', cls, text); n.type = 'button'; n.addEventListener('click', () => busy(n, fn));
    if (icon === 'web') {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('class', 'action-icon');
      svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('focusable', 'false');
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM3 12h18M12 3c5 5 5 13 0 18-5-5-5-13 0-18Z');
      svg.append(path); n.prepend(svg); n.classList.add('action-link');
    }
    return n;
  };
  const state = { channel: '', seq: 0, pending: new Map(), tail: Promise.resolve(), connected: false, baseUrl: '', presetBaseUrl: '', context: {}, hostFeatures: [], tab: 'catalog', offset: null, generation: 0, records: [], detail: null, detailGeneration: 0, detailTab: 'intro', detailOpener: null, installation: null };
  const installationActive = () => ['choosing','preparing','review','installing','uncertain','request-uncertain'].includes(state.installation?.phase);
  function installationButton(toolId) {
    const node = el('button', 'primary', '바로 설치하기'); node.type = 'button'; node.dataset.installTool = String(toolId);
    node.addEventListener('click', () => { if (!installationActive()) prepare(toolId).catch(error => feedback(error.message, true)); });
    return node;
  }
  function installationState(operation, phase, message) {
    if (state.installation !== operation) return;
    Object.assign(operation, {phase, message}); renderInstallation();
  }
  function forgetLateInstallation() {
    for (const [id,pending] of state.pending) if (pending.lateInstallation) { clearTimeout(pending.timer); state.pending.delete(id); }
  }
  function clearInstallation() {
    forgetLateInstallation();
    state.installation = null; renderInstallation();
  }
  function installationComplete(operation, installed) {
    operation.configured = installed.status === 'configured';
    const message=installed.notice || (operation.configured ? 'MCP 연결 설정을 저장했어요. 작업이 끝난 뒤 Claude를 다시 연결해 실제 동작을 확인하세요.' : '파일 설치가 끝났어요. 작업이 끝난 뒤 해당 업무의 Claude를 다시 연결해 주세요.');
    installationState(operation,'done',`${message}\nKEY·서버 주소 등 추가 설정은 등록자의 안내를 확인해 주세요. 실제 기능 실행·연결 시험은 아직 하지 않았습니다.`);
  }
  function reconcileInstallation(records) {
    const operation=state.installation;
    if (operation?.phase !== 'uncertain' || operation.origin !== state.baseUrl || !operation.plan) return;
    const path=value=>String(value || '').replace(/\\/g,'/').toLowerCase();
    const committed=(Array.isArray(records.items)?records.items:[]).find(record=>record.completedPlanId === operation.plan.planId &&
      String(record.toolId) === String(operation.toolId) && path(record.target) === path(operation.plan.destination) &&
      String(record.release) === String(operation.plan.release) && ['installed','configured'].includes(record.status));
    if (committed) { forgetLateInstallation(); installationComplete(operation,{status:committed.status,notice:'저장된 설치 기록에서 이번 설치의 완료를 확인했어요.'}); return; }
    // The authenticated list is read after installation/recovery under the
    // worker lock. Let the user finish reviewing an absent receipt explicitly;
    // neither an old receipt nor an absent one is evidence of this install succeeding.
    operation.reviewed = !(records.recovery?.blocked || []).length;
    installationState(operation,'uncertain',operation.reviewed ?
      '이번 설치의 완료 기록을 확인하지 못했어요. 아래 목록과 상태를 확인한 뒤 확인 마침을 눌러 주세요. 설치를 자동으로 다시 실행하지 않습니다.' :
      '중단된 설치를 먼저 확인해야 합니다. 아래 설치 기록의 안내에 따라 파일과 보관본을 확인해 주세요.');
  }
  function renderInstallation() {
    const operation = state.installation, active = installationActive();
    const pending = operation && ['choosing','preparing','installing'].includes(operation.phase);
    $('connection-button').disabled = active;
    const labels = {choosing:'설치 준비 중…',preparing:'설치 준비 중…',review:'설치 확인 중',installing:'설치 중…',uncertain:'설치 결과 확인 필요'};
    for (const node of document.querySelectorAll('[data-install-tool]')) {
      const same = operation && node.dataset.installTool === String(operation.toolId);
      node.disabled = active; node.replaceChildren(document.createTextNode(active && same ? labels[operation.phase] : '바로 설치하기'));
      node.removeAttribute('aria-busy');
      if (same && pending) { const spinner = el('span','install-spinner'); spinner.setAttribute('aria-hidden','true'); node.prepend(spinner); node.setAttribute('aria-busy','true'); }
    }
    const headings = {choosing:'설치 위치 선택',preparing:'설치 준비 중',review:'설치 내용 확인',installing:'설치 중',done:operation?.configured?'연결 설정 저장 완료':'파일 설치 완료',error:'설치하지 못했어요',uncertain:'설치 결과 확인 필요',cancelled:'설치를 취소했어요',requested:'설치 요청 전달 완료','request-uncertain':'설치 요청 결과 확인 필요'};
    for (const region of [$('installation-status'), $('detail-installation-status')].filter(Boolean)) {
      const show = operation && (region.id === 'installation-status' || String(region.dataset.toolId) === String(operation.toolId));
      region.hidden = !show; if (!show) { region.replaceChildren(); delete region.dataset.phase; continue; }
      region.dataset.phase = operation.phase;
      const mark = el('span',pending?'install-spinner':'install-state-mark',pending?'':operation.phase==='done'?'✓':operation.phase==='error'||operation.phase==='uncertain'?'!':'·'); mark.setAttribute('aria-hidden','true');
      const text = el('div','install-status-text');
      text.append(el('strong','',`${operation.name} · ${headings[operation.phase]}`),el('p','',operation.message));
      const actions = el('div','install-status-actions');
      if (['done','uncertain','error'].includes(operation.phase)) actions.append(button('설치된 기능 확인','text-button',()=>loadTab('installed')));
      if (operation.phase === 'uncertain' && operation.reviewed) actions.append(button('확인 마침','text-button',()=>clearInstallation()));
      if (operation.phase === 'done') actions.append(button('설정 안내 보기','text-button',async()=>{
        await detail(operation.toolId);
        if (String(state.detail?.item?.id) === String(operation.toolId)) { detailPanel('connect'); $('detail-tab-connect').focus(); }
      }));
      if(operation.phase==='request-uncertain')actions.append(button('요청 결과 확인','text-button',async()=>{
        const result=await rpc('host.requestInstall',operation.requestPayload);
        installationState(operation,'requested',`${result.title} 업무 대화에서 설치 진행과 추가 질문을 확인하세요.`);
      }));
      if(operation.phase==='requested')actions.append(button('확인','text-button',clearInstallation));
      region.replaceChildren(mark,text,actions);
    }
  }
  const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
  const panelAnimations = new WeakMap(), activePanelAnimations = new Set();
  function revealPanel(node) {
    if (!node) return;
    panelAnimations.get(node)?.cancel();
    if (!node.animate || motionPreference.matches || node.closest('[hidden]')) return;
    // A parent already entering covers content that arrives in the same frame.
    // Avoid multiplying opacity and motion on nested panels.
    for (let parent = node.parentElement; parent; parent = parent.parentElement) {
      if (activePanelAnimations.has(panelAnimations.get(parent))) return;
    }
    const animation = node.animate([{opacity:0,transform:'translateY(8px)'},{opacity:1,transform:'translateY(0)'}],
      {duration:300,easing:'cubic-bezier(.22,.61,.36,1)'});
    panelAnimations.set(node, animation); activePanelAnimations.add(animation);
    // Only live animations are retained. Superseding a view never delays input
    // or holds an old result in a detached DOM snapshot.
    const release = () => {
      activePanelAnimations.delete(animation);
      if (panelAnimations.get(node) === animation) panelAnimations.delete(node);
    };
    animation.finished.then(release, release);
  }
  const cancelPanelAnimations = () => { for (const animation of activePanelAnimations) animation.cancel(); activePanelAnimations.clear(); };
  motionPreference.addEventListener('change', () => { if (motionPreference.matches) cancelPanelAnimations(); });
  function feedback(message, error = false) {
    for (const id of ['feedback', ...($('detail-dialog').open ? ['detail-feedback'] : [])]) { $(id).textContent = message || ''; $(id).hidden = !message; $(id).classList.toggle('error', error); }
    if (error) document.querySelectorAll('.loading').forEach(n => { n.textContent = '불러오지 못했어요. 연결 설정을 확인하거나 다시 시도해 주세요.'; });
  }
  async function busy(node, fn) {
    if (node.disabled) return;
    const hadFocus = document.activeElement === node;
    node.disabled = true; node.setAttribute('aria-busy', 'true');
    try { return await fn(); }
    catch (e) { feedback(e.message || '처리하지 못했습니다. 다시 확인해 주세요.', true); }
    finally {
      node.disabled = false; node.removeAttribute('aria-busy');
      // A dialog cannot return native focus to its temporarily disabled opener.
      // Restore it after enabling, only if focus did not move to another control.
      const active = document.activeElement;
      if (hadFocus && node.isConnected && !document.querySelector('dialog[open]') &&
          (active === document.body || active?.closest('dialog:not([open])'))) node.focus({preventScroll:true});
    }
  }
  function rpc(action, payload = {}, stillNeeded = () => true, onLateResponse = null) {
    const send = () => new Promise((resolve, reject) => {
      if (!stillNeeded()) return resolve(null);
      if (!state.channel) return reject(new Error('앱과 연결을 확인해 주세요.'));
      const requestId = `store-${++state.seq}`;
      const timer = setTimeout(() => {
        // Keep at most the single uncertain installation's reply handler. A late
        // receipt can resolve the UI without submitting the installation again.
        if (onLateResponse) state.pending.set(requestId, {resolve:result=>onLateResponse(null,result),reject:error=>onLateResponse(error),timer:null,lateInstallation:true});
        else state.pending.delete(requestId);
        const error = new Error('처리 결과를 확인하지 못했습니다. 설치된 기능에서 상태를 확인해 주세요. 같은 설치를 자동으로 다시 실행하지 않습니다.');
        error.code = 'response_timeout'; reject(error);
      }, 130000);
      state.pending.set(requestId, { resolve, reject, timer });
      parent.postMessage({ type: 'ax-extension-request', channel: state.channel, requestId, action, payload }, '*');
    });
    const result = state.tail.then(send, send); state.tail = result.catch(() => {}); return result;
  }
  window.addEventListener('message', event => {
    if (event.source !== parent || !event.data || typeof event.data !== 'object') return;
    const message = event.data;
    if (message.type === 'ax-extension-init' && !state.channel && typeof message.channel === 'string') {
      state.channel = message.channel; state.context = message.context || {}; state.hostFeatures = Array.isArray(message.hostFeatures) ? message.hostFeatures : [];
      document.documentElement.dataset.theme = message.theme === 'dark' ? 'dark' : 'light';
      revealPanel(document.querySelector('.store-header'));
      $('workspace-context').textContent = state.context.workspace ? `현재 업무: ${state.context.title || state.context.workspace}` : '전체 공간(내 계정) 또는 선택한 폴더에 설치할 수 있어요.';
      initialize().catch(e => { connectionView(); feedback(e.message, true); }); return;
    }
    if (message.channel !== state.channel) return;
    if (message.type === 'ax-extension-theme') document.documentElement.dataset.theme = message.theme === 'dark' ? 'dark' : 'light';
    if (message.type !== 'ax-extension-response') return;
    const pending = state.pending.get(message.requestId); if (!pending) return;
    clearTimeout(pending.timer); state.pending.delete(message.requestId);
    if (message.ok) pending.resolve(message.result);
    else pending.reject(new Error(typeof message.error === 'string' ? message.error : message.error?.message || '요청을 완료하지 못했습니다.'));
  });
  window.addEventListener('pagehide', () => { cancelPanelAnimations(); for (const p of state.pending.values()) clearTimeout(p.timer); state.pending.clear(); });
  function show(view) { const changed=$(view).hidden; for (const id of ['connection-view', 'catalog-view']) $(id).hidden = id !== view; if(changed)revealPanel($(view)); }
  function connectionView() { if (installationActive()) return; ++state.generation; show('connection-view'); $('connection-cancel').hidden = !state.connected; $('disconnect').hidden = !state.connected; }
  function httpConsent() {
    let http = false;
    try { http = new URL($('server-url').value.trim()).protocol === 'http:'; } catch (_) { /* Invalid addresses are reported by the form. */ }
    $('http-warning').hidden = !http; $('allow-http').checked = false; $('allow-http').required = http;
  }
  let connectionPending = false;
  function connectionMessage(message, error = false) {
    const notice = $('connection-feedback');
    notice.textContent = message || ''; notice.hidden = !message; notice.classList.toggle('error', error);
  }
  async function connectionAction(node, action) {
    if (connectionPending || node.disabled || installationActive()) return;
    connectionPending = true;
    const label = node.textContent;
    feedback(''); connectionMessage('');
    if (node.id !== 'disconnect') node.textContent = '연결 확인 중…';
    // Direct KEY, reuse and disconnect share one connection. Keep the origin and action
    // stable until its reply arrives, rather than queueing conflicting connection changes.
    const controls = ['connect-submit', 'reuse-connection', 'disconnect', 'connection-cancel', 'change-server', 'server-url', 'connection-key', 'allow-http']
      .map(id => [$(id), $(id).disabled]);
    controls.forEach(([control]) => { control.disabled = true; });
    node.setAttribute('aria-busy', 'true'); $('connection-form').setAttribute('aria-busy', 'true');
    try { return await action(); }
    catch (e) { connectionMessage(e.message || '연결하지 못했어요. 주소와 KEY를 확인하고 다시 시도해 주세요.', true); }
    finally {
      controls.forEach(([control, disabled]) => { control.disabled = disabled; });
      node.textContent = label;
      node.removeAttribute('aria-busy'); $('connection-form').removeAttribute('aria-busy'); connectionPending = false;
    }
  }
  function connectionFields(result) {
    connectionMessage('');
    state.presetBaseUrl = result.presetBaseUrl || '';
    $('server-url').value = state.baseUrl || state.presetBaseUrl;
    // A successful reuse can select a different server than the typed KEY's origin.
    $('connection-key').value = '';
    $('server-url').readOnly = !!state.presetBaseUrl;
    $('change-server').hidden = !state.presetBaseUrl; $('change-server').textContent = '서버 주소 변경';
    $('server-help').textContent = result.presetMessage || (state.connected && state.presetBaseUrl && state.baseUrl !== state.presetBaseUrl
      ? '기존에 저장한 연결을 유지합니다. 다른 서버로 바꾸려면 주소를 변경하고 해당 서버의 KEY를 입력하세요.'
      : state.presetBaseUrl ? '다운로드한 플랫폼 주소가 준비됐어요. 개인 KEY만 입력해 연결하세요.' : '사용 중인 플랫폼의 기본 주소를 입력하세요.');
    $('connection-server-step').textContent = state.presetBaseUrl ? '연결할 플랫폼 확인' : '플랫폼 주소 입력';
    $('connection-title').textContent = state.presetBaseUrl ? '개인 KEY로 시작하세요.' : '플랫폼과 한 번 연결하세요.';
    httpConsent();
  }
  async function initialize() {
    publication.loaded=false; const result = await rpc('status'); state.connected = result.configured; state.baseUrl = result.baseUrl || '';
    if (state.installation && (state.installation.origin !== state.baseUrl || !state.connected)) clearInstallation();
    connectionFields(result); $('reuse-connection').hidden = !result.existingConnectionAvailable; $('reuse-help').hidden = !result.existingConnectionAvailable;
    $('connection-button').hidden = !state.connected; $('publish-open').hidden = !state.connected;
    if (!state.connected) return connectionView();
    $('connection-label').textContent = new URL(state.baseUrl).hostname;
    $('connection-button').title = '연결 설정 · ' + state.baseUrl;
    try { const options = await rpc('options'); $('org-filter').replaceChildren(new Option('모든 조직', '')); for (const org of options.organizations || []) $('org-filter').append(new Option(org.name, org.id)); $('org-filter').dispatchEvent(new Event('optionschanged')); } catch (e) { feedback(e.message, true); }
    return loadTab('catalog');
  }
  function normalUrl() { const url = new URL($('server-url').value.trim()); if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== '/') throw new Error('플랫폼의 기본 주소를 입력해 주세요.'); return url.href.replace(/\/$/, ''); }
  $('platform-home').addEventListener('click', () => busy($('platform-home'), async () => {
    const configured = state.baseUrl || state.presetBaseUrl;
    if (!configured) {
      connectionView(); feedback('플랫폼 주소를 먼저 연결해 주세요. 연결하면 여기서 홈페이지를 열 수 있어요.'); $('server-url').focus(); return;
    }
    const url = new URL(configured);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== '/')
      throw new Error('플랫폼의 기본 주소를 확인해 주세요. 연결 설정에서 주소를 다시 지정할 수 있어요.');
    await rpc('host.openExternal', {url: url.href, homepage: true});
  }));
  $('server-url').addEventListener('input', () => { httpConsent(); $('connection-key').value = ''; });
  $('change-server').addEventListener('click', () => {
    const editing = $('server-url').readOnly; $('server-url').readOnly = !editing;
    if (!editing) $('server-url').value = state.baseUrl || state.presetBaseUrl;
    $('change-server').textContent = editing ? '주소 변경 취소' : '서버 주소 변경';
    $('connection-key').value = ''; httpConsent();
    if (editing) $('server-url').focus();
  });
  function connect(event) { event.preventDefault(); if (connectionPending || !$('connection-form').reportValidity()) return; connectionAction($('connect-submit'), async () => {
    const key = $('connection-key').value.trim(); const url = normalUrl(); $('connection-key').value = '';
    const result = await rpc('connect', { url, key, allowHttp: $('allow-http').checked }); state.connected = result.configured;
    feedback('플랫폼에 연결했어요. 웹과 같은 계정으로 이용합니다.'); await initialize();
  }); }
  $('connect-submit').addEventListener('click', connect);
  $('connection-form').addEventListener('submit', event => event.preventDefault());
  $('connection-form').addEventListener('keydown', event => { if (event.key === 'Enter' && event.target.matches('input:not([type=checkbox])')) connect(event); });
  $('key-guide').addEventListener('click', () => busy($('key-guide'), async () => rpc('host.openExternal', { url: normalUrl() + '/local-access' })));
  $('reuse-connection').addEventListener('click', () => connectionAction($('reuse-connection'), async () => { await rpc('connect', { reuseExisting: true }); feedback('저장된 주소와 KEY로 플랫폼에 연결했어요. MCP를 새로 설치하거나 실행하지 않았습니다.'); await initialize(); }));
  $('connection-button').addEventListener('click', connectionView);
  $('connection-cancel').addEventListener('click', () => loadTab(state.tab).catch(e => feedback(e.message, true)));
  $('disconnect').addEventListener('click', () => connectionAction($('disconnect'), async () => {
    if (!await confirm('스토어 연결을 해제할까요?', [el('p', '', '이 스토어의 연결만 해제합니다. 기존 MCP 연결, 내려받은 파일과 설치한 기능은 유지됩니다.')], '연결 해제')) return;
    await rpc('disconnect'); state.connected = false; state.baseUrl = ''; $('connection-key').value = ''; await initialize(); feedback('스토어 연결을 해제했어요.');
  }));
  function confirm(title, nodes, label = '확인', ready = () => true) {
    return new Promise(resolve => {
      const dialog = $('confirm-dialog'); $('confirm-title').textContent = title; $('confirm-content').replaceChildren(...nodes); $('confirm-yes').textContent = label;
      const validate = () => { $('confirm-yes').disabled = !ready(); };
      const finish = value => { openFilter?.close(false); dialog.close(); $('confirm-yes').onclick = null; $('confirm-no').onclick = null; dialog.oncancel = null; dialog.onchange = null; $('confirm-yes').disabled = false; resolve(value); };
      $('confirm-yes').onclick = () => { if (ready()) finish(true); }; $('confirm-no').onclick = () => finish(false); dialog.oncancel = event => { event.preventDefault(); finish(false); }; dialog.onchange=validate; validate(); dialog.showModal(); $('confirm-no').focus();
    });
  }
  document.querySelectorAll('[data-tab]').forEach(n => n.addEventListener('click', () => busy(n, () => loadTab(n.dataset.tab))));
  let debounce;
  $('search').addEventListener('input', () => { clearTimeout(debounce); ++state.generation; debounce = setTimeout(() => loadTab('catalog').catch(e => feedback(e.message, true)), 300); });
  for (const id of ['type-filter', 'org-filter', 'sort']) $(id).addEventListener('change', () => loadTab('catalog').catch(e => feedback(e.message, true)));
  $('refresh').addEventListener('click', () => busy($('refresh'), () => loadTab(state.tab)));
  $('more').addEventListener('click', () => busy($('more'), () => catalog(true)));
  function empty(title, text) { const n = el('div', 'empty'); n.append(el('strong', '', title), el('p', '', text)); return n; }
  function recoveryCards(recovery) {
    const cards = [];
    if ((recovery?.recovered || []).length) {
      const completed = recovery.recovered.filter(r => r.outcome === 'completed').length;
      const restored = recovery.recovered.filter(r => r.outcome === 'restored').length;
      feedback(`중단된 설치를 확인했어요.${completed ? ` 완료된 설치 ${completed}건의 기록을 복원했습니다.` : ''}${restored ? ` 미완료 설치 ${restored}건은 이전 상태로 복구했습니다.` : ''} 설치 요청을 자동으로 다시 실행하지 않았습니다.`);
    }
    for (const issue of recovery?.blocked || []) {
      const n = el('article', 'tool-card recovery-card'); n.append(el('h2', 'tool-title', '중단된 설치 확인 필요'), el('p', 'muted', issue.message || '파일 또는 설정이 변경되어 자동으로 복구하지 않았습니다. 현재 내용과 보관본을 확인해 주세요.'), el('p', 'detail-result', `대상: ${issue.target || ''}${issue.backup ? '\n보관본: ' + issue.backup : ''}`));
      n.append(button('다시 상태 확인', 'text-button', () => loadTab(state.tab))); cards.push(n);
    }
    return cards;
  }
  async function loadTab(tab) {
    clearTimeout(debounce); closeDetail(false); state.tab = tab; show('catalog-view');
    document.querySelectorAll('[data-tab]').forEach(n => n.setAttribute('aria-current', n.dataset.tab === tab ? 'page' : 'false'));
    $('catalog-toolbar').hidden = tab !== 'catalog'; $('more').hidden = true;
    $('results').classList.toggle('record-list', tab !== 'catalog');
    $('results-label').textContent = tab === 'installed' ? '설치 기록을 확인하고 있어요.' : tab === 'updates' ? '설치한 기능의 새 버전을 확인하고 있어요.' : '기능을 불러오는 중입니다.';
    $('catalog-note').textContent = tab === 'installed' ? '이 플랫폼에서 설치한 기능과 설치 위치입니다. 파일 다운로드 기록은 포함하지 않습니다.' : tab === 'updates' ? '지금 설치할 수 있는 새 버전만 표시합니다. 업데이트는 설치 위치와 변경 내용을 확인한 뒤 진행합니다.' : '조회·좋아요·다운로드는 웹의 기록과 연결됩니다. 파일 다운로드와 실제 설치 상태는 구분해서 표시합니다.';
    if (tab === 'catalog') return catalog();
    const generation = ++state.generation; $('results').replaceChildren(el('p', 'loading', tab === 'updates' ? '설치된 기능의 업데이트를 확인하고 있어요…' : '설치 기록을 확인하고 있어요…'));
    if (tab === 'installed') {
      const records = await rpc('installations',{},()=>generation===state.generation); if (generation !== state.generation) return;
      reconcileInstallation(records);
      state.records = Array.isArray(records.items) ? records.items : [];
      const recovery = recoveryCards(records.recovery);
      $('results-label').textContent = `설치된 기능 ${state.records.length}개`;
      $('results').replaceChildren(...recovery, ...state.records.map(record => recordCard(record)));
      if (!state.records.length && !recovery.length) $('results').append(empty('아직 설치한 기능이 없어요.', '둘러보기에서 기능을 선택한 뒤 설치 위치를 확인하세요. 파일 다운로드는 설치 기록에 포함되지 않습니다.'));
      revealPanel($('results')); return;
    }
    const updates = await rpc('checkUpdates',{},()=>generation===state.generation); if (generation !== state.generation) return;
    const checked = Array.isArray(updates.items) ? updates.items : [];
    const blocked = Array.isArray(updates.recovery?.blocked) ? updates.recovery.blocked : [];
    const available = blocked.length ? [] : checked.filter(actualUpdate);
    const unknown = checked.filter(row => !available.includes(row) && row.result?.status !== 'current');
    const incomplete = updates.complete === false || unknown.length > 0 || blocked.length > 0;
    state.records = checked;
    $('results-label').textContent = `업데이트 가능한 기능 ${available.length}개`;
    $('results').replaceChildren(...available.map(row => recordCard(row, false, row.result)));
    if (!available.length) $('results').append(empty(incomplete ? '현재 확인된 업데이트가 없어요.' : !checked.length ? '확인할 설치 기록이 없어요.' : '모두 최신 버전이에요.', incomplete ? '일부 기능은 새 버전을 확인하지 못했거나 설치 상태 확인이 필요해요. 아래 확인 결과를 참고하세요.' : !checked.length ? '스토어에서 설치한 기능의 업데이트를 이곳에서 확인합니다.' : '설치한 기능을 그대로 사용하시면 됩니다. 새 버전이 등록되면 이곳에서 확인할 수 있어요.'));
    if (incomplete) {
      const summary=el('details','update-summary'), heading=el('summary','','일부 기능은 추가 확인이 필요해요.'), list=el('ul');
      for(const row of unknown){const result=row.result||{};const line=el('li');line.append(el('strong','',recordName(row)),el('span','',updateNotice(result)));list.append(line);}
      for(const issue of blocked){if(unknown.some(row=>String(row.toolId)===String(issue.toolId)))continue;const line=el('li');line.append(el('strong','','중단된 설치 확인'),el('span','',issue.message||'설치된 기능에서 파일과 보관본을 확인해 주세요.'));list.append(line);}
      const counts=updates.summary||{};
      const parts=[['current','최신'],['attention','상태 확인 필요'],['failed','조회 실패'],['pending','확인 대기']].filter(([key])=>Number.isInteger(counts[key])&&counts[key]>0).map(([key,label])=>`${label} ${counts[key]}개`);
      summary.append(heading,el('p','muted',parts.length?parts.join(' · '):'사용 권한과 설치 상태에 따라 새 버전 확인이 제한될 수 있어요.'),list,button('설치된 기능에서 확인', 'text-button', () => loadTab('installed')));$('results').append(summary);
    }
    revealPanel($('results'));
  }
  function actualUpdate(row) {
    const result=row.result||{}, current=result.installedRelease, next=result.activeRelease;
    // Older hosts omit the boolean. Their compatibility path still requires a
    // strictly newer release; paused, recovery and rollback states stay out.
    return result.status==='update_available' && Number.isSafeInteger(current) && current>0 && Number.isSafeInteger(next) && next>current && !result.updatePaused && (row.updateAvailable===true || row.updateAvailable===undefined);
  }
  function updateNotice(result) {
    if(result.updatePaused)return '새 버전의 배포가 일시 중지되어 있어요.';
    if(result.message)return result.message;
    return {rollback_available:'서버의 현재 배포가 설치된 버전보다 이전이에요. 자동으로 이전 버전으로 바꾸지 않습니다.',unknown_release:'현재 설치 버전의 배포 정보를 확인하지 못했어요.',pending:'이번 확인 범위를 넘어 확인 대기 중이에요. 새로고침으로 다시 확인해 주세요.',recovery_required:'중단된 설치 상태를 먼저 확인해 주세요.'}[result.status] || '배포 정보 또는 사용 권한을 다시 확인해 주세요.';
  }
  async function catalog(append = false) {
    const generation = ++state.generation; if (!append) $('results').replaceChildren(el('p', 'loading', '기능을 불러오는 중입니다…'));
    const result = await rpc('catalog', { q: $('search').value.trim(), type: $('type-filter').value, orgId: $('org-filter').value, sort: $('sort').value, offset: append ? state.offset : 0, limit: 20 }, () => generation === state.generation);
    if (generation !== state.generation) return;
    if (!append) $('results').replaceChildren();
    for (const item of result.items || []) $('results').append(toolCard(item));
    state.offset = result.nextOffset; $('more').hidden = result.nextOffset == null;
    $('results-label').textContent = `등록된 기능 ${result.total ?? (result.items || []).length}개`;
    if (!append && !(result.items || []).length) $('results').append(empty('조건에 맞는 기능이 없어요.', '검색어나 유형·조직 필터를 바꿔보세요.'));
    if (!append) revealPanel($('results'));
    if (result.warning) feedback(result.warning);
  }
  function symbol(type) {
    const n = el('span', 'tool-symbol'); n.dataset.type = type || ''; n.setAttribute('aria-hidden', 'true');
    const path = type === 'Skill' ? 'M12 3v18M12 5C8 2 4 3 3 4v15c3-1 6-1 9 2 3-3 6-3 9-2V4c-1-1-5-2-9 1Z' : /하네스|플러그인/.test(type || '') ? 'm12 3 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 16l9 5 9-5' : 'M9 3v4m6-4v4M7 7h10v4a5 5 0 0 1-10 0V7Zm5 9v5';
    n.innerHTML = `<svg viewBox="0 0 24 24"><path d="${path}"/></svg>`; return n;
  }
  function typeBadge(type) { const n = el('span', 'badge type-badge', type || '기능'); n.dataset.type = type || ''; return n; }
  function registrant(item) { return item.registrantName || '등록자 정보 없음'; }
  function number(item, kind) { const value = item.statistics?.[kind] ?? item[kind]; return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null; }
  function metrics(item) {
    const row = el('div', 'metrics');
    for (const [key, label, path] of [['views','조회','M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Zm13 0a3 3 0 1 0-6 0 3 3 0 0 0 6 0'],['likes','좋아요','M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z'],['downloads','다운로드','M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5']]) {
      const value = number(item,key), cell = el('span', 'metric'); cell.dataset.metric = key; cell.setAttribute('aria-label', value == null ? `${label} 미집계` : `${label} ${value.toLocaleString('ko-KR')}회`); cell.title = cell.getAttribute('aria-label');
      cell.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>`; cell.append(el('span', '', value == null ? '—' : value.toLocaleString('ko-KR'))); row.append(cell);
    }
    return row;
  }
  function updateCard(item) {
    for (const card of $('results').querySelectorAll('.tool-card[data-tool-id]')) if (card.dataset.toolId === String(item.id)) card.querySelector('.metrics')?.replaceWith(metrics(item));
  }
  function toolCard(item) {
    const card = el('article', 'tool-card catalog-card'); card.dataset.toolId = item.id;
    const top = el('div', 'card-top'); top.append(symbol(item.type), typeBadge(item.type));
    const title = button(item.name, 'tool-title', () => detail(item.id));
    title.setAttribute('aria-haspopup', 'dialog');
    title.setAttribute('aria-controls', 'detail-dialog');
    // Keep a native button for keyboard/screen-reader activation. Card surfaces
    // share that one action, while nested controls keep their own click behavior.
    card.addEventListener('click', event => {
      if (event.target.closest('button,a,input,select,textarea,label,summary,[role=button],[contenteditable=true]')) return;
      const selection = window.getSelection();
      if (selection && !selection.isCollapsed && (card.contains(selection.anchorNode) || card.contains(selection.focusNode))) return;
      if (title.disabled) return;
      title.focus({preventScroll:true}); title.click();
    });
    const tags = el('div', 'tags'); for (const tag of [item.org, item.category, ...(item.workTags || []).slice(0, 2)].filter(Boolean)) tags.append(el('span', '', tag));
    const owner = el('p', 'card-owner'); owner.append(el('span', 'owner-label', '등록자'), el('span', '', registrant(item))); owner.title = `등록자 · ${registrant(item)}`;
    const foot = el('div', 'card-bottom'); foot.append(metrics(item), button('자세히 보기', 'text-button', () => detail(item.id)));
    card.append(top, title, el('p', 'tool-desc', item.desc || '상세 화면에서 사용 방법을 확인하세요.'), tags, owner);
    if (item.access && item.access !== 'approved') card.append(el('span', 'badge access-badge', '사용 승인 필요'));
    card.append(foot); return card;
  }
  function recordName(record) { return record.name || record.toolName || record.title || record.packageName || '이름을 확인할 수 없는 기능'; }
  function recordType(record) { return record.type || record.toolType || (record.kind === 'skill' ? 'Skill' : record.kind === 'mcp' ? 'MCP/Tool' : ''); }
  function releaseLabel(value) { if(value===undefined || value===null || value==='')return '버전 미확인'; const text=String(value);return /^v/i.test(text)?text:'v'+text; }
  function recordCard(record, controls = true, update = null) {
    const statuses = {installed:'파일 설치 완료',configured:'연결 설정 완료', 'verified-file':'설치 파일 확인됨'};
    const n = el('article', 'install-record'); n.dataset.installationId=record.installationId||'';if(update)n.classList.add('update-record');
    const type=recordType(record), main=el('div','record-main'), heading=el('div','record-heading'), title=el('h2','record-title',recordName(record));title.title=recordName(record);
    heading.append(title,typeBadge(type));
    const metadata=el('div','record-meta'), versions=el('span','record-versions');versions.append(el('span','record-version',releaseLabel(record.release??update?.installedRelease)));
    if(update)versions.append(el('span','record-version-arrow','→'),el('strong','record-new-version',releaseLabel(update.activeRelease)));
    metadata.append(versions,el('span','record-scope',record.scope==='project'||record.scope==='directory'?'업무 폴더':'공통 · 내 계정'));
    if(!update) metadata.append(el('span','record-status',statuses[record.status]||'설치 기록'));
    main.append(heading,metadata);
    const target=record.target||record.scopeDir;if(target){const location=el('p','record-target',target);location.title=target;main.append(location);}
    const actions = el('div', 'record-actions'); if (record.toolId) actions.append(button(update?'업데이트 보기':'상세 보기', update?'secondary':'text-button', async () => {await detail(record.toolId);if(update&&String(state.detail?.item?.id)===String(record.toolId))detailPanel('connect');}));
    if (controls) {
      const verify = button('상태 확인', 'text-button', async () => { const result = await rpc('verify', { installationId: record.installationId }); const changed = result.filesIntact === false || result.configurationIntact === false; feedback(changed ? '설치 후 파일 또는 설정이 변경되었어요. 현재 내용을 확인한 뒤 복구·재설치를 결정해 주세요.' : result.notice || result.message || '설치 기록을 확인했습니다. Claude 연결 상태는 다음 연결에서 확인하세요.', changed); });
      verify.title = '설치 파일과 MCP 설정을 설치 당시 기록과 비교합니다. 실제 기능 실행이나 서버 연결 시험은 하지 않습니다.';
      verify.setAttribute('aria-description', verify.title); actions.append(verify);
      if (record.rollbackAvailable) {
        const rollback = button('이전 상태로 복구', 'text-button', async () => {
        if (!await confirm('이전 설치 상태로 복구할까요?', [el('p', '', '스토어가 설치한 파일과 설정만 복구합니다. 첫 설치였다면 해당 기능을 제거합니다. 사용자가 변경한 파일이 있으면 복구를 중단합니다.'), el('p', 'detail-result', record.target || record.scopeDir)], '복구하기')) return;
        const result = await rpc('rollback', { installationId: record.installationId, confirmed: true }); feedback(result.notice || '이전 설치 상태로 복구했어요.'); await loadTab('installed');
        });
        rollback.title = '이 PC의 해당 설치를 되돌립니다. 업데이트는 직전 버전으로 복구하고, 최초 설치는 제거합니다. 변경 범위를 먼저 확인합니다.';
        rollback.setAttribute('aria-description', rollback.title); actions.append(rollback);
      }
    }
    n.append(symbol(type),main,actions); return n;
  }
  function section(title, text) { const n = el('section', 'detail-section'); n.append(el('h3', '', title), el('p', 'guide-text', text || '등록된 안내가 없습니다.')); return n; }
  function closeDetail(focus = true) {
    ++state.detailGeneration; state.detail = null;
    if (!$('detail-dialog').open) return;
    $('detail-dialog').close();
    if (focus && state.detailOpener?.isConnected) state.detailOpener.focus({preventScroll:true});
    state.detailOpener = null;
  }
  $('detail-close').addEventListener('click', () => closeDetail());
  $('detail-dialog').addEventListener('cancel', event => { event.preventDefault(); closeDetail(); });
  function metadata(rows) {
    const list = el('dl','detail-metadata');
    for (const [name, value] of rows) if (value !== undefined && value !== null && value !== '') list.append(el('dt','',name),el('dd','',value));
    return list;
  }
  function dated(value) {
    if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return '';
    const date = new Date(value * 1000); return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit'});
  }
  function workflowView(workflow) {
    const steps = Array.isArray(workflow?.steps) ? workflow.steps.slice(0,8) : [];
    if (!steps.length) return null;
    const details=el('details','workflow'),heading=el('summary','workflow-heading');
    heading.append(el('strong','','이렇게 동작해요.'),el('span','muted',`${steps.length}단계`));
    const list=el('ol','workflow-steps'); list.setAttribute('aria-label','동작 순서');
    for (const step of steps) {const row=el('li'),copy=el('div');copy.append(el('strong','',step.title || '단계'));if(step.description)copy.append(el('p','',step.description));row.append(copy);list.append(row);}
    details.append(heading,list,el('p','workflow-note','등록자가 정리한 동작 순서입니다. 실제 실행 상태를 표시하지 않습니다.')); return details;
  }
  async function requestAiInstall(result) {
    if(installationActive())return;
    if(!state.hostFeatures.includes('installRequests'))throw Error('AI 설치 요청을 사용하려면 AX Workspace를 최신 버전으로 업데이트해 주세요.');
    const operation={toolId:result.item.id,name:result.item.name||'선택한 도구',origin:state.baseUrl};
    state.installation=operation;installationState(operation,'choosing','설치 범위와 요청을 처리할 업무를 선택하세요.');
    try {
      const listed=await rpc('host.listWorkspaces'), works=listed.items||[];
      if(!works.length)throw Error('먼저 업무를 만들고 폴더 접근을 확인해 주세요. 그 업무의 권한과 승인 모드로 설치를 요청합니다.');
      const box=el('div','scope-options'),scope=el('select'),select=el('select');
      scope.id='ai-install-scope';select.id='ai-install-work';
      scope.setAttribute('aria-label','설치 범위');scope.append(new Option('공통으로 사용 · 내 계정','user'),new Option('선택한 업무 폴더','work'));
      select.setAttribute('aria-label','요청을 처리할 업무 위치');
      for(const row of works)select.append(new Option(row.title||'이름 없는 업무',row.id));
      const current=works.find(row=>row.workspace===state.context.workspace);if(current)select.value=current.id;
      for(const [control,label] of [[scope,'설치 범위'],[select,'요청을 처리할 업무 위치']]){
        const field=el('div','scope-field'),caption=el('label','',label);caption.htmlFor=control.id;
        field.append(caption,control);box.append(field);
      }
      const scopeHint=el('p','muted scope-hint');
      const describeScope=()=>{scopeHint.textContent=scope.value==='user'?'내 계정의 모든 업무에서 쓸 수 있게 설치해요. 설치 과정은 선택한 업무에 기록돼요.':'선택한 업무 폴더에 설치해요. 설치 과정도 같은 업무에서 확인할 수 있어요.';};
      scope.onchange=describeScope;describeScope();box.append(scopeHint);
      filterSelect(scope);filterSelect(select);
      const navigates=state.hostFeatures.includes('installRequestNavigation');
      const help=el('div','install-request-help');
      help.append(el('p','muted','작업이 없으면 바로 시작하고, 작업 중이면 끝난 뒤 설치해요.'),el('p','muted','추가 설정은 업무 대화에서 안내해요. 중지된 업무는 먼저 이어 실행해 주세요.'));
      if(!await confirm('AI에게 설치를 요청할까요?',[box,help],navigates?'설치 요청하고 업무로 이동':'설치 요청 보내기')){
        installationState(operation,'cancelled','설치 요청을 보내지 않았습니다.');return;
      }
      installationState(operation,'preparing','설치 자료를 내려받고 업무에 요청을 전달하고 있어요.');
      operation.requestPayload={requestId:crypto.randomUUID(),scope:scope.value,sessionId:select.value,action:'prepareInstallRequest',payload:{toolId:result.item.id},confirmed:true};
      const response=await rpc('host.requestInstall',operation.requestPayload);
      installationState(operation,'requested',`${response.title} 업무 대화에서 설치 진행과 추가 질문을 확인하세요.${response.paused?' 해당 업무의 이어 할 일 안내를 확인한 뒤 이어 실행해 주세요.':''}`);
      feedback('설치 요청을 전달했어요. 설치 완료 여부와 추가 질문은 선택한 업무 대화에서 확인하세요.');
    } catch(error) {
      installationState(operation,error.code==='response_timeout'?'request-uncertain':'error',error.message);throw error;
    }
  }
  async function downloadDetail(result) {
    const downloaded = await rpc('download', {toolId:result.item.id});
    result.downloadedFile = downloaded.file;
    feedback('파일을 내려받았어요. 다운로드만으로 설치되지는 않습니다.');
    if (state.detail === result && state.detailTab === 'connect') detailPanel('connect');
  }
  function detailPanel(tab, animate = true) {
    const result = state.detail; if (!result) return;
    const item = result.item, panel = $('detail-panel'); state.detailTab = tab;
    document.querySelectorAll('[data-detail-tab]').forEach(n => {const selected = n.dataset.detailTab === tab; n.setAttribute('aria-selected',String(selected)); n.tabIndex=selected?0:-1;});
    panel.setAttribute('aria-labelledby','detail-tab-'+tab); panel.replaceChildren();
    if (animate) revealPanel(panel);
    const active = result.manifest?.release ?? item.active;
    const versions = (item.versions || []).filter(v => !v.deleted);
    const currentVersion = versions.find(v => String(v.n) === String(active));
    if (tab === 'intro') {
      const hero = el('section','detail-hero'); hero.append(el('h3','',item.name),el('p','',item.desc || '등록된 설명이 없습니다.'));
      const cols = el('div','detail-columns'); cols.append(metadata([['사용 프로그램',item.platform],['공유 유형',item.type],['등록 조직',item.org],['등록자',registrant(item)],['담당자',item.owner]]),metadata([['현재 배포',active != null ? `v${active}` : undefined],['배포일',dated(currentVersion?.created)],['공개 범위',item.visibility],['사용 권한',item.approval ? (item.access==='approved'?'사용 승인됨':item.access==='pending'?'사용 승인 대기':'담당자 승인 필요') : '사내 사용자'],['지원 수준',item.support]]));
      panel.append(hero,cols);
      const flow=workflowView(item.workflow || result.manifest?.workflow);if(flow)panel.append(flow);
      if(currentVersion?.note || item.changes)panel.append(section('현재 배포의 변경 내용',currentVersion?.note || item.changes));
      if (item.workTags?.length) { const tags=el('div','tags'); item.workTags.forEach(t=>tags.append(el('span','',t))); const related=el('section','detail-section'); related.append(el('h3','','관련 업무'),tags); panel.append(related); }
      return;
    }
    if (tab === 'connect') {
      const gated = item.access && item.access !== 'approved';
      panel.append(el('h3','','사용할 공간을 정하고 시작하세요.'));
      if (gated) panel.append(section('사용 권한 확인',item.access==='pending'?'사용 신청을 검토 중입니다. 웹에서 신청 상태를 확인해 주세요.':'이 기능은 사용 승인이 필요합니다. 웹에서 담당자에게 사용 권한을 신청해 주세요.'));
      if (item.environment || item.platform) panel.append(section('실행 환경',item.environment || item.platform));
      const actions=el('div','detail-actions');
      if (!gated && (result.canInstall || result.canInspectInstall)) actions.append(installationButton(item.id));
      if (!gated && !result.canInstall && result.manifest?.downloadUrl) actions.append(button('AI에게 설치 요청',result.canInspectInstall?'secondary':'primary',()=>requestAiInstall(result),'install'));
      if (!gated && result.manifest?.downloadUrl) actions.append(button('파일 다운로드','secondary',()=>downloadDetail(result)));
      if (result.webUrl) actions.append(button(gated?'웹에서 사용 권한 확인':'웹에서 보기','text-button',()=>rpc('host.openExternal',{url:result.webUrl}),'web'));
      const progress = el('section','installation-status'); progress.id='detail-installation-status'; progress.dataset.toolId=String(item.id); progress.setAttribute('aria-live','polite'); progress.setAttribute('aria-label','설치 진행 상태'); progress.hidden=true;
      panel.append(actions,progress,el('p','catalog-note',result.installNotice || '파일 다운로드와 실제 설치는 별개입니다. 설치 전 사용할 공간과 변경 경로를 확인하세요.'));
      renderInstallation();
      if (item.guide) panel.append(section('등록자가 제공한 안내',item.guide));
      if (item.url) panel.append(section('연결 주소',item.url));
      if (currentVersion?.commands) for (const [scope,label] of [['user','전체 공간(내 계정)'],['project','특정 폴더']]) if (currentVersion.commands[scope]) panel.append(section(`${label} 설치 안내`,currentVersion.commands[scope]));
      if (result.downloadedFile) panel.append(section('내려받은 파일',result.downloadedFile));
      if (item.updatePaused) panel.append(el('p','detail-callout','현재 배포는 이전 버전으로 복구한 상태입니다. 배포 이력을 확인한 뒤 사용할 버전을 결정하세요.'));
      return;
    }
    if (tab === 'versions') {
      panel.append(el('h3','','배포 이력'));
      if (!versions.length) panel.append(el('p','muted detail-callout','확인할 수 있는 배포 이력이 없습니다.'));
      for (const version of versions) {
        const row=el('article','version-row'), heading=el('div','version-heading'); heading.append(el('strong','',`v${version.n}`));
        if (String(version.n) === String(active)) heading.append(el('span','badge accent','현재 배포'));
        else if (version.withdrawn) heading.append(el('span','badge','배포 중단'));
        else if (String(version.n) === String(item.fallback)) heading.append(el('span','badge','복구용 보관'));
        row.append(heading,el('p','version-note',version.note || '등록된 변경 내용이 없습니다.'));
        const published=dated(version.created) || (typeof version.age==='number'&&version.age>=0?`${version.age}일 전`:'');
        const info=[published,version.filename,version.size!=null?`${version.size} MB`:''].filter(Boolean).join(' · '); if(info)row.append(el('p','muted',info));
        if (version.sha256) {const hash=el('details','version-hash');hash.append(el('summary','','파일 검증 정보'),el('code','',`SHA-256: ${version.sha256}`));row.append(hash);}
        panel.append(row);
      }
      if (result.webUrl) panel.append(button('웹에서 배포 이력 보기','text-button',()=>rpc('host.openExternal',{url:result.webUrl}),'web'));
      return;
    }
    panel.append(el('h3','','함께 개선하는 기능'));
    for (const comment of item.comments || []) {
      const row=el('article','comment-row'),head=el('div','comment-heading');head.append(el('strong','',comment.author || '사용자'),el('span','badge',comment.kind || '의견'));if(comment.status)head.append(el('span','badge',comment.status));if(dated(comment.created))head.append(el('small','muted',dated(comment.created)));
      row.append(head,el('p','guide-text',comment.text || ''));
      for(const reply of comment.replies || []) {const replyRow=el('div','comment-reply'),replyHead=el('div','comment-heading');replyHead.append(el('strong','',reply.author || '사용자'),el('small','muted',[dated(reply.created),reply.status || '답변'].filter(Boolean).join(' · ')));replyRow.append(replyHead,el('p','',reply.text || '처리 상태를 변경했습니다.'));row.append(replyRow);}
      panel.append(row);
    }
    if (!item.comments?.length) panel.append(el('p','muted detail-callout','아직 등록된 의견이 없습니다.'));
    if (result.webUrl) panel.append(button('웹에서 의견 남기기','text-button',()=>rpc('host.openExternal',{url:result.webUrl}),'web'));
  }
  async function detail(toolId) {
    const generation=++state.detailGeneration, dialog=$('detail-dialog');
    if (!dialog.open) state.detailOpener=document.activeElement;
    state.detail=null; $('detail-title').textContent='기능 상세'; $('detail-kicker').textContent='P&T AI Square'; $('detail-feedback').hidden=true; $('detail-view').replaceChildren(el('p','loading','상세 정보를 확인하고 있어요…'));
    if (!dialog.open) dialog.showModal(); $('detail-close').focus({preventScroll:true});
    const result=await rpc('detail',{toolId,recordView:true},()=>generation===state.detailGeneration);
    if (generation!==state.detailGeneration || !dialog.open) return;
    state.detail=result; const item=result.item, root=$('detail-view');
    $('detail-title').textContent=item.name; $('detail-kicker').replaceChildren(typeBadge(item.type),el('span','',item.platform || ''));
    const top=el('div','detail-top'), identity=el('div','detail-identity'), identityText=el('div');
    identityText.append(el('strong','',item.org || '등록 조직 미지정'),el('p','',`등록자 · ${registrant(item)}`),metrics(item)); identity.append(symbol(item.type),identityText);
    const actions=el('div','detail-top-actions');
    const like=button(`${item.liked?'♥':'♡'} 좋아요 ${number(item,'likes') ?? ''}`.trim(),'secondary',async()=>{
      const response=await rpc('like',{toolId,liked:!item.liked}); item.liked=response.liked; item.likes=response.count; if(item.statistics)item.statistics.likes=response.count;
      like.textContent=`${response.liked?'♥':'♡'} 좋아요 ${response.count}`;like.setAttribute('aria-pressed',String(response.liked));identityText.querySelector('.metrics')?.replaceWith(metrics(item));updateCard(item);feedback('웹과 같은 좋아요 기록에 반영했어요.');
    }); like.setAttribute('aria-pressed',String(!!item.liked));
    actions.append(like,button('사용 시작','primary',()=>{detailPanel('connect');$('detail-tab-connect').focus();}));top.append(identity,actions);
    const tabs=el('div','detail-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','기능 상세 탭');
    for(const [id,title] of [['intro','소개'],['connect','설치·연결'],['versions','버전'],['comments','의견']]){const tab=el('button','',title);tab.type='button';tab.addEventListener('click',()=>detailPanel(id));tab.id='detail-tab-'+id;tab.dataset.detailTab=id;tab.setAttribute('role','tab');tab.setAttribute('aria-controls','detail-panel');tabs.append(tab);}
    tabs.addEventListener('keydown',event=>{const keys=['ArrowLeft','ArrowRight','Home','End'];if(!keys.includes(event.key))return;event.preventDefault();const items=[...tabs.children],index=items.indexOf(document.activeElement),next=event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowRight'?1:-1)+items.length)%items.length;detailPanel(items[next].dataset.detailTab);items[next].focus();});
    const panel=el('section','detail-panel');panel.id='detail-panel';panel.setAttribute('role','tabpanel');panel.tabIndex=0;
    root.replaceChildren(top,tabs,panel);root.scrollTop=0;detailPanel('intro', false);revealPanel(root);updateCard(item);
  }
  async function prepare(toolId) {
    if (installationActive()) return;
    const detailSnapshot = state.detail;
    const operation = {toolId,name:detailSnapshot?.item?.name || '선택한 기능',origin:state.baseUrl};
    state.installation = operation;
    feedback(''); installationState(operation,'choosing','설치할 공간을 선택해 주세요. 아직 파일을 변경하지 않았습니다.');
    try {
    const choices = el('div', 'scope-choices');
    const scopes = detailSnapshot?.manifest?.installProfile?.scopes || ['project','user'];
    let directory = null, works = [], workError = '';
    if (scopes.includes('project') && state.hostFeatures.includes('workspaces')) {
      try {
        const result = await rpc('host.listWorkspaces');
        works = Array.isArray(result.items) ? result.items : [];
      } catch (error) { workError = error.message || '업무 목록을 불러오지 못했어요. 다시 시도하거나 폴더를 직접 선택하세요.'; }
    }
    function scopeOption(value, title, description, supported) {
      const option = el('div','scope-option'), label = el('label','scope-choice'), input = el('input');
      input.type='radio'; input.name='install-scope'; input.value=value; input.disabled=!supported;
      const text=el('span'); text.append(el('strong','',title),el('small','muted',description));label.append(input,text);option.append(label);return {option,input};
    }
    const common=scopeOption('user','공통으로 사용 (내 계정)',scopes.includes('user') ? '내 Windows 계정의 모든 업무에서 사용합니다. 다른 사용자 계정에는 설치하지 않습니다.' : '이 기능은 공통 설치를 지원하지 않습니다.',scopes.includes('user'));
    choices.append(common.option);
    const canChooseWork=scopes.includes('project')&&works.length>0;
    const workDescription=!scopes.includes('project') ? '이 기능은 업무별 설치를 지원하지 않습니다.' : !state.hostFeatures.includes('workspaces') ? '업무 목록에서 선택하려면 AX Workspace를 업데이트해 주세요. 아래에서 폴더를 직접 선택할 수도 있어요.' : workError || (works.length ? '선택한 업무의 폴더에 설치합니다. 현재 대화와 작성 중인 내용은 유지됩니다.' : '등록된 업무가 없습니다. 새 업무를 만들거나 아래에서 폴더를 직접 선택하세요.');
    const work=scopeOption('work','업무를 선택해 사용',workDescription,canChooseWork);
    let workSelect;
    if (canChooseWork) {
      workSelect=el('select');workSelect.id='install-workspace';workSelect.setAttribute('aria-label','설치할 업무');
      for(const item of works){const option=new Option(item.title || '이름 없는 업무',item.id);option.dataset.description=item.workspace;workSelect.append(option);}
      const current=works.find(item=>item.workspace===state.context.workspace);if(current)workSelect.value=current.id;
      const selectedPath=el('p','selected-directory');
      const updateWork=()=>{const selected=works.find(item=>item.id===workSelect.value);selectedPath.textContent=selected?.workspace||'';selectedPath.title=selected?.workspace||'';};
      workSelect.addEventListener('change',()=>{work.input.checked=true;updateWork();choices.dispatchEvent(new Event('change',{bubbles:true}));});
      work.option.append(workSelect,selectedPath);filterSelect(workSelect);updateWork();
    }
    choices.append(work.option);
    if(scopes.includes('project')){
      const more=el('details','scope-more'),summary=el('summary','','목록에 없는 폴더에 설치');
      const other=scopeOption('directory','다른 폴더 선택','선택한 폴더에만 적용합니다. 앱의 업무 목록이나 현재 폴더를 바꾸지 않습니다.',true);
      const path=el('p','selected-directory','아직 선택한 폴더가 없습니다.');
      const pick=button('폴더 선택','secondary directory-pick',async()=>{
        const selected=await rpc('host.pickDirectory');if(selected.cancelled)return;
        directory=selected;other.input.checked=true;path.textContent=selected.path;path.title=selected.path;choices.dispatchEvent(new Event('change',{bubbles:true}));
      });
      other.option.append(pick,path);more.append(summary,other.option);choices.append(more);
    }
    const ready=()=>{const value=choices.querySelector('input:checked')?.value;return value==='user'||value==='work'&&!!workSelect?.value||value==='directory'&&!!directory?.directoryToken;};
    if (!await confirm('어디에서 사용할까요?', [choices, el('p', 'muted', '설치할 공간을 선택하세요. 다음 화면에서 실제 파일·설정 변경 경로를 확인합니다.')], '설치 내용 확인', ready)) {
      installationState(operation,'cancelled','파일과 설정은 변경하지 않았습니다.'); return;
    }
    installationState(operation,'preparing','설치할 파일을 내려받고 변경 위치를 확인하고 있어요.');
    const choice=choices.querySelector('input:checked')?.value;
    let targetLabel='공통 (내 계정)';
    if(choice==='work'){
      directory=await rpc('host.selectWorkspace',{sessionId:workSelect.value});
      if(directory.cancelled || !directory.directoryToken)throw Error('설치할 업무를 다시 선택해 주세요.');
      targetLabel=directory.title || works.find(item=>item.id===workSelect.value)?.title || '선택한 업무';
    }else if(choice==='directory'){targetLabel='선택한 폴더';}
    const scope=choice==='user'?'user':'directory';
    const directoryFields=scope==='directory'?{directoryToken:directory.directoryToken}:{};
    const plan = await rpc('prepareInstall', { toolId, scope, ...directoryFields }); if (!plan.canInstall) {
      const message=plan.reason || plan.notice || '자동 설치를 지원하지 않는 항목입니다. 등록자의 설치 안내를 확인해 주세요.';
      installationState(operation,'error',message); feedback(message,true); return;
    }
    operation.plan = {planId:plan.planId,destination:plan.destination,release:plan.release};
    installationState(operation,'review','설치 위치와 변경 내용을 확인한 뒤 설치하기를 눌러 주세요.');
    const details = el('dl', 'plan-summary'); for (const [name, value] of [['설치 대상', targetLabel], ['설치 위치', plan.destination || plan.scopeDir], ['설치 버전', plan.release || plan.releaseId || '플랫폼의 현재 배포 버전']]) { details.append(el('dt', '', name), el('dd', '', value)); }
    if (plan.configurationFile) details.append(el('dt', '', '변경할 설정'), el('dd', '', plan.configurationFile));
    if (Array.isArray(plan.command)) details.append(el('dt', '', '다음 Claude 연결에서 실행할 명령'), el('dd', '', plan.command.join(' ')));
    const notes=[details];if(plan.detectionNotice)notes.push(el('p','detail-callout',plan.detectionNotice));
    notes.push(el('p', 'muted', '파일과 설정을 설치합니다. 진행 중인 대화는 유지하며, Claude 연결은 자동으로 재시작하지 않습니다.'));
    notes.push(el('p','muted','KEY·서버 주소 등 추가 설정이 필요한 기능은 등록자의 안내에 따라 설정해 주세요. 이 설치는 설정 입력창이나 설치 스크립트를 실행하지 않습니다.'));
    if (!await confirm('이 내용으로 설치할까요?', notes, '설치하기')) { installationState(operation,'cancelled','파일과 설정은 변경하지 않았습니다.'); return; }
    installationState(operation,'installing','선택한 공간에 파일과 설정을 저장하고 있어요. 완료 결과를 기다려 주세요.');
    const completed = async (error, installed) => {
      if (state.installation !== operation) return;
      if (error) { installationState(operation,'error',error.message || '설치 결과를 확인하지 못했어요. 설치된 기능에서 상태를 확인해 주세요.'); return; }
      if (!['installed','configured'].includes(installed?.status)) {
        installationState(operation,'uncertain','완료 여부를 확인하지 못했어요. 설치된 기능에서 상태를 확인해 주세요. 같은 설치를 자동으로 다시 실행하지 않습니다.'); return;
      }
      installationComplete(operation,installed);
      // A list refresh is independent of a confirmed installation receipt.
      // Its failure must never relabel a completed installation as failed.
      try { await loadTab('installed'); }
      catch (refreshError) { feedback(`설치는 완료됐지만 목록을 불러오지 못했어요. 새로고침으로 다시 확인해 주세요.\n${refreshError.message || ''}`,true); }
    };
    const installed = await rpc('install', { planId: plan.planId, approvalDigest: plan.approvalDigest, confirmed: true, ...directoryFields },()=>true,
      (error,result)=>{ completed(error,result).catch(failure=>feedback(failure.message,true)); });
    await completed(null,installed);
    } catch (error) {
      const uncertain = operation.phase === 'installing' && error.code === 'response_timeout';
      installationState(operation,uncertain?'uncertain':'error',error.message || '설치를 진행하지 못했어요. 다시 확인해 주세요.');
    }
  }
  // One local select component; no OS-native dropdown, remote library or polling.
  let openFilter = null;
  function filterSelect(select) {
    select.hidden = true;
    const wrap = el('div', 'filter-select'), trigger = el('button', 'filter-trigger'); trigger.type = 'button';
    trigger.setAttribute('aria-label', select.getAttribute('aria-label')); trigger.setAttribute('aria-haspopup','listbox'); trigger.setAttribute('aria-expanded','false');
    const menu = el('div','filter-menu'); menu.id=select.id+'-menu'; menu.setAttribute('role','listbox'); menu.setAttribute('aria-label',select.getAttribute('aria-label')); menu.hidden=true; trigger.setAttribute('aria-controls',menu.id);
    const update = () => { trigger.textContent = select.selectedOptions[0]?.textContent || ''; trigger.disabled = select.disabled; };
    const close = focus => { menu.hidden=true; trigger.setAttribute('aria-expanded','false'); if(openFilter?.wrap===wrap) openFilter=null; if(focus) trigger.focus(); };
    const focusOption = option => {
      if(!option)return;option.focus({preventScroll:true});
      if(option.offsetTop<menu.scrollTop)menu.scrollTop=option.offsetTop;
      else if(option.offsetTop+option.offsetHeight>menu.scrollTop+menu.clientHeight)menu.scrollTop=option.offsetTop+option.offsetHeight-menu.clientHeight;
    };
    const open = () => {
      openFilter?.close(false); menu.replaceChildren();
      for(const option of select.options) {
        const item=el('button','filter-option',option.textContent); item.type='button'; item.disabled=option.disabled; item.setAttribute('role','option'); item.setAttribute('aria-selected',String(option.selected)); item.tabIndex=-1;
        if(option.dataset.description) {item.classList.add('filter-option-description');item.append(el('small','',option.dataset.description));}
        item.onclick=()=>{select.value=option.value; update(); close(true); select.dispatchEvent(new Event('change',{bubbles:true}));}; menu.append(item);
      }
      menu.hidden=false;
      // Fit the list inside the nearest scrolling dialog/page. This keeps the
      // last option reachable without putting the menu behind a sticky footer.
      let top=8,bottom=innerHeight-8;
      for(let parent=wrap.parentElement;parent&&parent!==document.body;parent=parent.parentElement){
        const style=getComputedStyle(parent);
        if(/auto|scroll|hidden|clip/.test(style.overflowY)){
          const rect=parent.getBoundingClientRect();top=Math.max(top,rect.top+4);bottom=Math.min(bottom,rect.bottom-4);
        }
      }
      const rect=trigger.getBoundingClientRect(),below=Math.max(0,bottom-rect.bottom-7),above=Math.max(0,rect.top-top-7);
      const desired=Math.min(250,menu.scrollHeight),flip=below<desired&&above>below;
      menu.style.top=flip?'auto':'calc(100% + 6px)';menu.style.bottom=flip?'calc(100% + 6px)':'auto';
      menu.style.setProperty('--menu-offset',flip?'4px':'-4px');
      menu.style.maxHeight=Math.max(40,Math.min(250,flip?above:below))+'px';
      trigger.setAttribute('aria-expanded','true'); openFilter={wrap,close}; focusOption(menu.querySelector('[aria-selected=true]')||menu.firstElementChild);
    };
    trigger.onclick=()=>menu.hidden?open():close(true);
    trigger.onkeydown=event=>{if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();open();}};
    menu.onkeydown=event=>{
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);return;}
      if(event.key==='Tab'){close(false);return;}
      const options=[...menu.querySelectorAll('button:not(:disabled)')]; const index=options.indexOf(document.activeElement);
      const moves={ArrowDown:(index+1)%options.length,ArrowUp:(index-1+options.length)%options.length,Home:0,End:options.length-1};
      if(event.key in moves){event.preventDefault();focusOption(options[moves[event.key]]);}
    };
    select.addEventListener('change',update); select.addEventListener('optionschanged',update); update(); wrap.append(trigger,menu); select.after(wrap);
  }
  // Registration confirms the exact immutable draft from the explicit app submit.
  // Owner, KEY scope, digest, revision and duplicate checks stay on the server.
  const publication = { loaded: false, allowed: false, busy: false, file: null, draft: null, requestId: null, extra: {}, existingExtra: {}, fileExtra: {}, fileFields: {}, existingFields: {}, manualFields: new Set(), fileSourceSelected: false, opener: null, origin: '' };
  const publishFields = {name:'publish-name',desc:'publish-desc',platform:'publish-platform',type:'publish-type',guide:'publish-guide',orgId:'publish-org',categoryId:'publish-category',changes:'publish-changes',url:'publish-url',commandProject:'publish-command-project',commandUser:'publish-command-user'};
  const publishFileFields = ['name','desc','platform','type','guide','changes'];
  const publishExtraFields = ['packageId','workTags','environment','workflow','installProfile'];
  const publishSelects = ['publish-target','publish-existing','publish-mode','publish-platform','publish-type','publish-org','publish-category'];
  const publishActionIds = ['publish-pick-file','publish-file-reapply','publish-prepare','publish-status','publish-review-open','publish-commit','publish-edit','publish-target-find'];
  function publishMessage(text, error = false) { $('publish-message').textContent=text; $('publish-message').classList.toggle('error',error); }
  function publishChanged() { publication.requestId=null; publication.draft=null; }
  function publishControls() {
    const draft=publication.draft, committed=draft?.status==='committed';
    const visiblePanel=draft ? $('publish-review') : $('publish-form');
    const changed=visiblePanel.hidden;
    $('publish-form').hidden=!!draft; $('publish-form').inert=publication.busy||!publication.allowed;
    $('publish-review').hidden=!draft; $('publish-prepare').hidden=!!draft; $('publish-commit').hidden=!draft||committed;
    for(const id of publishActionIds) $(id).disabled=publication.busy||!publication.allowed;
    $('publish-commit').disabled=publication.busy||!publication.allowed||!['pending','approved','committing'].includes(draft?.status);
    $('publish-pick-file').disabled=publication.busy||!publication.allowed||!state.hostFeatures.includes('publishFiles');
    $('publish-status').hidden=committed; $('publish-review-open').hidden=true;
    $('publish-edit').textContent=committed?'다른 도구 등록':'내용 수정';
    $('publish-dialog').setAttribute('aria-busy',String(publication.busy));
    if (changed && $('publish-dialog').open) revealPanel(visiblePanel);
  }
  async function publishAction(fn) {
    if(publication.busy)return;
    publication.busy=true;publishControls();
    try{await fn();}catch(error){publishMessage(error.message||'등록 상태를 확인하지 못했어요. 같은 내용으로 다시 확인해 주세요.',true);}
    finally{publication.busy=false;publishControls();}
  }
  function publishOptions(select, rows, placeholder) {
    const value=select.value;select.replaceChildren(new Option(placeholder,''));
    for(const item of rows||[])select.append(new Option(item.name||item.title||String(item.id),String(item.id)));
    if([...select.options].some(option=>option.value===value))select.value=value;
    select.dispatchEvent(new Event('optionschanged'));
  }
  function publishMode() {
    const mode=$('publish-mode').value;
    $('publish-file-panel').hidden=mode!=='file';$('publish-url-field').hidden=mode!=='url';$('publish-command-fields').hidden=mode!=='command';
    $('publish-existing-field').hidden=$('publish-target').value!=='update';$('publish-install-info').hidden=mode!=='file'||!publication.extra.installProfile;
    $('publish-file-reapply').hidden=mode!=='file'||!publication.file||!publication.fileExtra.packageId;
    if(mode==='file'&&!state.hostFeatures.includes('publishFiles')) $('publish-file-help').textContent='파일을 선택하려면 AX Workspace를 최신 버전으로 업데이트해 주세요.';
  }
  function publishInstallInfo() {
    const profile=publication.extra.installProfile;
    $('publish-install-info').hidden=!profile;
    if(!profile)return;
    const scopes=(profile.scopes||[]).map(value=>({user:'공통',project:'업무 폴더'})[value]||value).join(' · ');
    $('publish-install-summary').textContent=[profile.kind,profile.host,scopes,profile.entrypoint].filter(Boolean).join(' / ');
    $('publish-keep-install').checked=true;
  }
  function setPublishField(key, value) {
    const field=$(publishFields[key]);
    // A package may name another supported host, but cannot invent a server
    // organization/category or change the user's publication approval choice.
    if(field.tagName==='SELECT'&&value&&![...field.options].some(option=>option.value===value)) {
      if(key!=='platform')return;
      field.append(new Option(value,value));
    }
    field.value=value;
    if(field.tagName==='SELECT')field.dispatchEvent(new Event('optionschanged'));
  }
  function publishExtra(metadata) {
    return Object.fromEntries(publishExtraFields.filter(key=>Object.prototype.hasOwnProperty.call(metadata||{},key)).map(key=>[key,metadata[key]]));
  }
  function updatePublishExtra() {
    // An existing tool's installation declaration belongs to its old artifact.
    // Once a replacement is picked, only that file's verified declaration applies.
    publication.extra={...(publication.fileSourceSelected?publication.fileExtra:publication.existingExtra)};
    publishInstallInfo();publishMode();
  }
  function fillFileMetadata(metadata={}) {
    const next=Object.fromEntries(publishFileFields.filter(key=>typeof metadata[key]==='string').map(key=>[key,metadata[key]]));
    let filled=0;
    for(const key of new Set([...Object.keys(publication.fileFields),...Object.keys(next)])) {
      const identity=(key==='platform'||key==='type')&&Object.prototype.hasOwnProperty.call(next,key);
      if(publication.manualFields.has(key)&&!identity)continue;
      if(identity)publication.manualFields.delete(key);
      setPublishField(key,next[key]??publication.existingFields[key]??'');
      if(next[key])filled++;
    }
    publication.fileFields=next;
    publication.fileExtra=publishExtra(metadata);updatePublishExtra();
    return filled;
  }
  function fillPublishMetadata(metadata) {
    if(!metadata||typeof metadata!=='object')return;
    // Choosing a different existing tool is an explicit replacement of defaults.
    const selectedFileFields=publication.fileFields;
    publication.manualFields.clear();publication.fileFields={};publication.existingFields={};
    publication.existingExtra=publishExtra(metadata);
    for(const [key,id] of Object.entries(publishFields)) {
      const value=typeof metadata[key]==='string'?metadata[key]:'';
      publication.existingFields[key]=value;setPublishField(key,value);
    }
    if(typeOfBoolean(metadata.approval))document.querySelector(`input[name="publish-visibility"][value="${metadata.approval?'approval':'public'}"]`).checked=true;
    if(['file','url','command'].includes(metadata.mode)){$('publish-mode').value=metadata.mode;$('publish-mode').dispatchEvent(new Event('optionschanged'));}
    if(publication.file)fillFileMetadata({...publication.fileExtra,...selectedFileFields});
    else updatePublishExtra();
    publishMode();
  }
  function typeOfBoolean(value){return typeof value==='boolean';}
  function resetPublish() {
    $('publish-form').reset();publication.file=null;publication.draft=null;publication.requestId=null;publication.extra={};publication.existingExtra={};publication.fileExtra={};
    publication.fileFields={};publication.existingFields={};publication.manualFields.clear();publication.fileSourceSelected=false;
    $('publish-file-name').textContent='배포할 파일을 선택하세요';$('publish-file-help').textContent='ZIP · MD · AXEXTENSION · EXE · MSI · PS1 / 최대 64MB';
    for(const id of publishSelects)$(id).dispatchEvent(new Event('optionschanged'));
    publishInstallInfo();publishMode();
  }
  async function refreshMyTools() {
    $('publish-target-search').value='';
    const result=await rpc('publishOptions');
    publishOptions($('publish-existing'),result.candidates,'기존 도구 선택');
    publication.allowed=result.canPublish===true;
  }
  $('publish-open').addEventListener('click',()=>{
    publication.opener=document.activeElement;
    if(publication.origin!==state.baseUrl){resetPublish();publication.loaded=false;publication.origin=state.baseUrl;}
    $('publish-dialog').showModal();$('publish-close').focus();
    if(publication.loaded){publishControls();publishAction(refreshMyTools);return;}
    publishAction(async()=>{
      publishMessage('등록 권한과 분류를 확인하고 있어요…');
      const result=await rpc('publishOptions');publication.allowed=result.canPublish===true;publication.loaded=true;
      publishOptions($('publish-org'),result.options?.organizations,'조직 선택');publishOptions($('publish-category'),result.options?.categories,'업무 분류 선택');
      publishOptions($('publish-existing'),result.candidates,'기존 도구 선택');
      $('publish-access').hidden=publication.allowed;
      $('publish-access').replaceChildren();
      if(!publication.allowed){
        $('publish-access').append(el('p','',result.notice||'도구 등록에는 업로드 권한이 포함된 연결 KEY가 필요합니다.'),button('웹에서 연결 KEY 확인','text-button',()=>rpc('host.openExternal',{url:state.baseUrl+'/local-access'})));
        publishMessage('연결 설정에서 업로드 권한이 포함된 KEY로 연결한 뒤 다시 열어 주세요.');publication.loaded=false;
      }else publishMessage('창을 닫아도 이 화면에서 작성 중인 내용은 유지됩니다.');
      publishMode();
    });
  });
  function closePublish(){openFilter?.close(false);$('publish-dialog').close();publication.opener?.focus();}
  $('publish-close').addEventListener('click',closePublish);
  $('publish-dialog').addEventListener('cancel',event=>{event.preventDefault();closePublish();});
  $('publish-form').addEventListener('submit',event=>event.preventDefault());
  function publishFormChanged(event) {
    publishChanged();
    const key=Object.keys(publishFields).find(key=>publishFields[key]===event.target.id);
    if(key)publication.manualFields.add(key);
  }
  $('publish-form').addEventListener('input',publishFormChanged);
  $('publish-form').addEventListener('change',publishFormChanged);
  $('publish-target').addEventListener('change',()=>{publishMode();if($('publish-target').value==='update')publishAction(refreshMyTools);if($('publish-target').value==='new'){publication.existingExtra={};publication.existingFields={};updatePublishExtra();$('publish-existing').value='';$('publish-existing').dispatchEvent(new Event('optionschanged'));}});
  $('publish-mode').addEventListener('change',publishMode);
  $('publish-target-find').addEventListener('click',()=>publishAction(async()=>{
    const result=await rpc('publishOptions',{q:$('publish-target-search').value.trim()});
    publishOptions($('publish-existing'),result.candidates,'기존 도구 선택');publishChanged();
    publishMessage(result.candidates?.length?'검색한 도구 중 새 버전을 등록할 대상을 선택하세요.':'해당하는 내 도구가 없어요. 검색어를 바꿔 보세요.');
  }));
  $('publish-existing').addEventListener('change',()=>publishAction(async()=>{
    if(!$('publish-existing').value)return;
    const result=await rpc('publishOptions',{toolId:Number($('publish-existing').value)});
    fillPublishMetadata(result.existing?.metadata);
    if(publication.file)$('publish-mode').value='file';$('publish-mode').dispatchEvent(new Event('optionschanged'));publishMode();
    publishMessage('기존 도구의 설정을 불러왔어요. 새 자료·변경 내용과 공개 범위를 확인하세요.');
  }));
  async function selectPublishFile(file) {
    publishMessage(file?'파일을 앱으로 전송하고 있어요…':'등록할 파일을 선택해 주세요.');
    const selected=file?await rpc('host.uploadFile',{file}):await rpc('host.pickFile');if(selected.cancelled)return;
    // A new picker choice revokes the old capability. Preserve all written
    // metadata, but never keep a now-unusable file selection after inspection fails.
    publication.file=null;publication.fileSourceSelected=true;publication.fileExtra={};updatePublishExtra();publishChanged();
    $('publish-file-name').textContent='선택한 파일을 확인하고 있어요…';
    let inspected;
    try{inspected=await rpc('inspectPublishSource',{fileToken:selected.fileToken});}
    catch(error){$('publish-file-name').textContent='배포할 파일을 다시 선택하세요';$('publish-file-help').textContent='작성한 설명은 유지됩니다. 파일을 다시 확인해 주세요.';throw error;}
    publication.file=selected;publishChanged();
    $('publish-file-name').textContent=inspected.source?.name||selected.name;
    const bytes=inspected.source?.bytes??selected.size;
    const size=Number.isFinite(bytes)?(bytes<1024?`${bytes} B`:bytes<1024*1024?`${(bytes/1024).toFixed(1)} KB`:`${(bytes/1024/1024).toFixed(2)} MB`):'';
    $('publish-file-help').textContent=size?`${size} · 파일 내용은 등록 준비 시 업로드합니다.`:'파일 내용은 등록 준비 시 업로드합니다.';
    const filled=fillFileMetadata(inspected.metadata||{});$('publish-mode').value='file';$('publish-mode').dispatchEvent(new Event('optionschanged'));publishMode();
    if(inspected.options){publishOptions($('publish-org'),inspected.options.organizations,'조직 선택');publishOptions($('publish-category'),inspected.options.categories,'업무 분류 선택');}
    // ZIP matches are suggestions only; never replace all tools owned by this user.
    if(inspected.candidates?.length&&!$('publish-existing').value&&$('publish-target').value==='update')publishMessage('ZIP과 연결된 기존 도구가 있어요. 전체 목록에서 등록 대상을 선택해 주세요.');
    const packaged=!!inspected.metadata?.packageId;
    const notice=packaged?(filled?'ZIP에서 이름·설명·사용 안내 등을 자동으로 불러왔어요. 직접 작성한 설명은 유지하고 프로그램·유형은 ZIP에 맞췄습니다. 내용과 분류·공개 범위를 확인해 주세요.':'ZIP의 배포 정보를 확인했어요. 직접 작성한 설명은 유지했습니다. 내용과 분류·공개 범위를 확인해 주세요.'):'자동으로 채울 배포 정보가 없는 파일이에요. 이름·설명·사용 안내와 분류를 직접 입력해 주세요.';
    publishMessage(inspected.packageWarning||notice,!!inspected.packageWarning);
  }
  $('publish-pick-file').addEventListener('click',()=>{
    if(state.hostFeatures.includes('publishUpload'))$('publish-file-input').click();
    else publishAction(()=>selectPublishFile());
  });
  $('publish-file-input').addEventListener('change',event=>{
    const file=event.target.files?.[0];event.target.value='';if(file)publishAction(()=>selectPublishFile(file));
  });
  const publishDrop=$('publish-file-panel');
  for(const type of ['dragenter','dragover'])publishDrop.addEventListener(type,event=>{
    if(![...(event.dataTransfer?.types||[])].includes('Files'))return;
    event.preventDefault();if(!publication.busy&&state.hostFeatures.includes('publishUpload'))publishDrop.classList.add('drag-over');
  });
  publishDrop.addEventListener('dragleave',event=>{if(!publishDrop.contains(event.relatedTarget))publishDrop.classList.remove('drag-over');});
  publishDrop.addEventListener('drop',event=>{
    event.preventDefault();publishDrop.classList.remove('drag-over');
    if(publication.busy)return;
    if(!state.hostFeatures.includes('publishUpload'))return publishMessage('끌어놓기로 등록하려면 AX Workspace를 최신 버전으로 업데이트해 주세요.',true);
    if(event.dataTransfer.files.length!==1)return publishMessage('배포 파일 한 개를 놓아 주세요.',true);
    const file=event.dataTransfer.files[0];publishAction(()=>selectPublishFile(file));
  });
  $('publish-file-reapply').addEventListener('click',()=>{
    if(publication.busy||!publication.file||!publication.fileExtra.packageId)return;
    for(const key of publishFileFields)publication.manualFields.delete(key);
    fillFileMetadata({...publication.fileExtra,...publication.fileFields});publishChanged();
    publishMessage('ZIP의 이름·설명·사용 안내를 다시 적용했어요. 조직·분류·공개 범위는 그대로 유지됩니다.');
  });
  function publishPayload() {
    const target=$('publish-target').value, mode=$('publish-mode').value;
    if(!target)throw Error('새 도구인지, 기존 도구의 새 버전인지 선택해 주세요.');
    if(target==='update'&&!$('publish-existing').value)throw Error('새 버전을 등록할 기존 도구를 선택해 주세요.');
    if(mode==='file'&&!publication.file)throw Error('배포할 파일을 선택해 주세요.');
    const metadata={...(mode==='file'?publication.extra:publication.existingExtra),mode};
    for(const [key,id] of Object.entries(publishFields))metadata[key]=$(id).value.trim();
    if(mode==='file'&&publication.fileExtra.packageId)for(const [key,label] of [['platform','사용 프로그램'],['type','기능 유형']]){
      if(publication.fileFields[key]&&metadata[key]!==publication.fileFields[key])throw Error(`${label}은(는) 선택한 ZIP의 값(${publication.fileFields[key]})과 일치해야 해요.`);
    }
    for(const [key,label] of [['name','도구 이름'],['desc','설명'],['platform','사용 프로그램'],['type','기능 유형'],['guide','설치·사용 안내'],['orgId','조직'],['categoryId','업무 분류']])if(!metadata[key])throw Error(`${label}을(를) 입력하거나 선택해 주세요.`);
    const visibility=document.querySelector('input[name="publish-visibility"]:checked');if(!visibility)throw Error('상세 내용과 파일의 공개 범위를 선택해 주세요.');
    metadata.approval=visibility.value==='approval';
    if(publication.extra.installProfile&&!$('publish-keep-install').checked)delete metadata.installProfile;
    if(mode==='url'){
      let url;try{url=new URL(metadata.url);}catch{throw Error('연결할 웹 주소를 확인해 주세요.');}
      if(!['http:','https:'].includes(url.protocol)||url.username||url.password)throw Error('아이디·비밀번호가 포함되지 않은 HTTP 또는 HTTPS 주소를 입력하세요.');
    }
    if(mode==='command'&&!metadata.commandProject&&!metadata.commandUser)throw Error('지원하는 설치 명령어를 한 개 이상 입력해 주세요.');
    if(mode!=='file'){delete metadata.installProfile;delete metadata.packageId;}
    if(mode!=='url')delete metadata.url;
    if(mode!=='command'){delete metadata.commandProject;delete metadata.commandUser;}
    if(!publication.requestId)publication.requestId=crypto.randomUUID();
    return {requestId:publication.requestId,target,metadata,...(target==='update'?{toolId:Number($('publish-existing').value)}:{}),...(mode==='file'?{fileToken:publication.file.fileToken}:{})};
  }
  function reviewUrl(draft) {
    const url=new URL(draft.reviewUrl||'',state.baseUrl);
    if(url.origin!==new URL(state.baseUrl).origin||!/^\/publish-review\/[a-f0-9-]{16,64}$/.test(url.pathname)||url.search||url.hash)throw Error('웹 확인 주소를 검증하지 못했어요. 등록 상태를 다시 확인해 주세요.');
    return url.href;
  }
  function showPublishDraft(draft) {
    publication.draft=draft;const status=draft.status,committed=status==='committed';
    const labels={pending:'등록 준비 완료',approved:'등록 준비 완료',committing:'등록 결과 확인 필요',committed:'등록 완료',expired:'확인 기한 만료'};
    $('publish-review-label').textContent=labels[status]||'등록 상태 확인 필요';
    $('publish-review-title').textContent=committed?'플랫폼에 등록했어요.':status==='approved'?'등록할 내용을 확인했어요.':status==='expired'?'새 등록 내용을 준비해 주세요.':'등록 내용이 준비됐어요.';
    $('publish-review-text').textContent=committed?'웹과 앱에서 같은 도구를 확인할 수 있어요.':status==='approved'?'등록하기를 눌러 게시하세요.':status==='expired'?'내용 수정을 누른 뒤 다시 확인하면 새 검토 링크를 만들 수 있어요.':'선택한 대상과 공개 범위로 등록합니다. 결과 확인이 필요하면 등록 결과 확인을 눌러 주세요.';
    const metadata=draft.metadata||{},summary=$('publish-summary');summary.replaceChildren();
    for(const [label,value]of[['도구 이름',metadata.name||$('publish-name').value],['등록 대상',draft.toolId?`기존 도구 #${draft.toolId} · 새 버전`:'새 도구'],['배포 자료',draft.artifact?.name||metadata.url||(metadata.mode==='command'?'설치 명령어 안내':publication.file?.name)],['공개 범위',metadata.approval===true?'조회 승인 필요':metadata.approval===false?'전체 사용자':undefined],['등록 결과',committed&&draft.result?`도구 #${draft.result.id} · 버전 ${draft.result.version}`:undefined]])if(value)summary.append(el('dt','',label),el('dd','',value));
    publishControls();$('publish-review').scrollIntoView({block:'start'});
  }
  $('publish-prepare').addEventListener('click',()=>publishAction(async()=>{
    const payload=publishPayload();publishMessage('등록 자료와 내용을 준비하고 있어요…');
    const result=await rpc('preparePublish',payload);
    if(result.ready===false)throw Error('필수 내용을 확인해 주세요: '+(result.missing||[]).join(', '));
    if(!result.id)throw Error('등록 초안 번호를 확인하지 못했어요. 같은 내용으로 다시 확인해 주세요.');
    showPublishDraft(result);await commitPublication();
  }));
  $('publish-status').addEventListener('click',()=>publishAction(async()=>{
    const result=await rpc('publishStatus',{draftId:publication.draft.id});showPublishDraft({...publication.draft,...result});
    publishMessage(result.status==='committed'?'등록 완료 상태를 확인했어요.':result.status==='expired'?'등록 기한이 지났어요. 내용을 다시 준비해 주세요.':'등록이 완료되지 않았어요. 내용을 확인한 뒤 등록하기를 눌러 주세요.');
  }));
  async function commitPublication() {
    const draft=publication.draft;
    if(!['pending','approved','committing'].includes(draft?.status))return;
    if(!/^[a-f0-9]{64}$/.test(draft.reviewDigest||''))throw Error('플랫폼을 앱 등록이 지원되는 버전으로 업데이트해 주세요. 작성한 내용은 유지됩니다.');
    publishMessage('선택한 내용과 공개 범위로 등록하고 있어요…');
    const result=await rpc('publish',{draftId:draft.id,reviewDigest:draft.reviewDigest,confirmed:true});
    if(result.published!==true||result.status!=='committed'){showPublishDraft({...draft,...result});throw Error(result.notice||'등록 결과를 확인해 주세요.');}
    showPublishDraft({...draft,status:'committed',result});
    publishMessage('등록했어요. 웹과 앱에서 같은 도구를 확인할 수 있습니다.');
    await refreshMyTools();
  }
  $('publish-commit').addEventListener('click',()=>publishAction(commitPublication));
  $('publish-edit').addEventListener('click',()=>{
    if(publication.busy)return;
    if(publication.draft?.status==='committed')resetPublish();else publishChanged();
    publishControls();publishMessage('내용을 수정한 뒤 등록하기를 누르면 선택한 설정으로 등록합니다.');$('publish-target').nextElementSibling?.querySelector('button')?.focus();
  });
  for(const id of ['type-filter','org-filter','sort',...publishSelects]) filterSelect($(id));
  document.addEventListener('pointerdown',event=>{if(openFilter&&!openFilter.wrap.contains(event.target))openFilter.close(false);});
  for(const type of ['wheel','touchmove'])document.addEventListener(type,event=>{if(openFilter&&!openFilter.wrap.contains(event.target))openFilter.close(false);},{capture:true,passive:true});
  window.addEventListener('resize',()=>openFilter?.close(false));
  parent.postMessage({ type: 'ax-extension-ready' }, '*');
})();
