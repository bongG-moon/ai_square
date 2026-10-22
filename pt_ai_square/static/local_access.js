(() => {
  let csrf = '';
  // Relative API URLs also work when deployed under a reverse-proxy prefix.
  const api = 'api/local-tokens';
  const status = document.querySelector('#status');
  async function call(path, options = {}) {
    const r = await fetch(path, {...options, headers: {'Content-Type':'application/json', 'X-CSRF-Token':csrf}});
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || '처리하지 못했습니다.');
    return data;
  }
  async function refresh() {
    const data = await call(api); csrf = data.csrf;
    document.querySelector('#employee').textContent=`${data.employee.name} · 사번 ${data.employee.id} — 로그인한 본인 명의로 발급됩니다.`;
    document.querySelector('#usage').textContent=`내 API 이용 · 업로드 ${data.usage.uploads}건 · 다운로드 ${data.usage.downloads}건`;
    const list = document.querySelector('#tokens'); list.replaceChildren();
    for (const t of data.tokens) {
      const li = document.createElement('li'), text = document.createElement('span'), button = document.createElement('button');
      const name=document.createElement('strong'), detail=document.createElement('small');
      name.textContent=t.name;
      detail.textContent=`${t.scope==='publish'?'업로드 포함':'조회·다운로드'} · ${new Date(t.expires*1000).toLocaleDateString()}까지 · 업로드 ${t.uploads} / 다운로드 ${t.downloads}`;
      text.append(name, detail);
      button.textContent = t.status==='revoked'?'취소됨':t.status==='expired'?'만료됨':'사용 취소'; button.className = 'sq-secondary'; button.disabled=t.status!=='active';
      button.onclick = async () => {
        button.disabled = true;
        try { await call(`${api}/${t.id}`, {method:'DELETE'}); await refresh(); status.textContent='인증키 사용을 취소했습니다.'; }
        catch (e) {status.textContent=e.message; button.disabled=false;}
      };
      li.append(text, button); list.append(li);
    }
    const history=document.querySelector('#history'); history.replaceChildren();
    for(const event of data.history){
      const li=document.createElement('li');
      li.textContent=`${new Date(event.created*1000).toLocaleString()} · ${event.action==='upload'?'업로드':'다운로드'} · 도구 #${event.tool} · v${event.version}${event.action==='download'&&!event.counted?' · 반복/업데이트, 집계 제외':''}`;
      history.append(li);
    }
    if(!data.history.length){const li=document.createElement('li');li.textContent='아직 API 이용 이력이 없습니다.';history.append(li);}
  }
  document.querySelector('#refresh-usage').onclick=()=>refresh().catch(e=>status.textContent=e.message);
  document.querySelector('#token-form').onsubmit = async e => {
    e.preventDefault(); const button=e.target.querySelector('button'); button.disabled=true;
    try {
      const result = await call(api, {method:'POST', body:JSON.stringify({name:document.querySelector('#token-name').value, days:Number(document.querySelector('#token-days').value), scope:document.querySelector('#token-scope').value})});
      document.querySelector('#secret').value=result.token; document.querySelector('#issued').hidden=false;
      status.textContent='발급했습니다. 로컬 입력 시 화면에는 키가 표시되지 않습니다.'; await refresh();
    } catch(e) {status.textContent=e.message;} finally {button.disabled=false;}
  };
  document.querySelector('#copy-token').onclick = async () => {
    try {await navigator.clipboard.writeText(document.querySelector('#secret').value); status.textContent='복사했습니다.';}
    catch {status.textContent='복사가 차단되었습니다. 인증키 입력란을 선택해 복사하세요.'; document.querySelector('#secret').select();}
  };
  refresh().catch(e => status.textContent=e.message);
})();
