(() => {
  let csrf = '', currentKeyId = null, issuedKeyId = null, loaded = false;
  const api = 'api/local-tokens';
  const $ = selector => document.querySelector(selector);
  const status = $('#status');
  const scopeName = scope => scope === 'publish' ? '업로드 포함' : '조회·다운로드';
  const date = value => new Date(value * 1000).toLocaleString('ko-KR', {year:'numeric', month:'long', day:'numeric', hour:'2-digit', minute:'2-digit'});
  const stateName = state => ({active:'사용 중', expired:'만료됨', revoked:'사용 취소됨', replaced:'교체됨'}[state] || '발급 전');
  async function call(path, options = {}) {
    const response = await fetch(path, {...options, headers:{'Content-Type':'application/json', 'X-CSRF-Token':csrf}, cache:'no-store'});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '처리하지 못했습니다.');
    return data;
  }
  function clearIssued() {
    $('#secret').value=''; $('#issued').hidden=true; issuedKeyId=null;
  }
  async function refresh() {
    const data = await call(api); csrf = data.csrf;
    currentKeyId = data.currentKeyId;
    const key = data.connectionKey;
    $('#employee').textContent = `${data.employee.name} · 사번 ${data.employee.id}`;
    $('#current-key-detail').textContent = key ? `${key.name} · ${scopeName(key.scope)} · ${date(key.expires)}까지` : '로그인한 본인 명의로 하나의 KEY를 발급합니다.';
    $('#key-state').textContent = stateName(key?.status);
    $('#key-state').dataset.state = key?.status || 'none';
    $('#key-issue').textContent = data.tokens.length ? 'KEY 재발급' : '연결 KEY 발급';
    $('#key-issue').disabled = false;
    $('#key-revoke').hidden = key?.status !== 'active';
    $('#key-rule').textContent = data.tokens.length ? '재발급하면 기존 KEY는 즉시 사용할 수 없습니다. 연결한 프로그램에도 새 KEY를 입력하세요. 기존 이용 이력은 유지됩니다.' : '본인 사번에만 연결됩니다. 업로드 포함 권한도 도구 삭제·권한 변경은 허용하지 않습니다.';
    if (!loaded && key) {
      $('#token-name').value=key.name; $('#token-scope').value=key.scope;
    }
    loaded = true;
    if (issuedKeyId && (issuedKeyId !== currentKeyId || key?.status !== 'active')) clearIssued();
    $('#usage').textContent = `내 API 이용 · 업로드 ${data.usage.uploads}건 · 다운로드 ${data.usage.downloads}건`;
    const historical=data.tokens.filter(t=>t.id!==currentKeyId), list=$('#tokens'); list.replaceChildren();
    $('#key-history-count').textContent = `(${historical.length})`;
    for (const t of historical) {
      const li=document.createElement('li'), text=document.createElement('span'), name=document.createElement('strong'), detail=document.createElement('small'), badge=document.createElement('span');
      name.textContent=t.name; detail.textContent=`${scopeName(t.scope)} · ${date(t.created)} 발급 · 업로드 ${t.uploads} / 다운로드 ${t.downloads}`;
      badge.textContent=stateName(t.status); badge.className='local-history-state';
      text.append(name,detail); li.append(text,badge); list.append(li);
    }
    if (!historical.length) {const li=document.createElement('li'); li.textContent='이전 KEY 이력이 없습니다.'; list.append(li);}
    const history=$('#history'); history.replaceChildren();
    for (const event of data.history) {
      const li=document.createElement('li');
      li.textContent=`${date(event.created)} · ${event.action==='upload'?'업로드':'다운로드'} · 도구 #${event.tool} · v${event.version}${event.action==='download'&&!event.counted?' · 반복/업데이트, 집계 제외':''}`;
      history.append(li);
    }
    if (!data.history.length) {const li=document.createElement('li');li.textContent='아직 API 이용 이력이 없습니다.';history.append(li);}
  }
  $('#refresh-usage').onclick=()=>refresh().catch(e=>status.textContent=e.message);
  $('#key-revoke').onclick=async()=>{
    const id=currentKeyId; if(!id)return;
    const button=$('#key-revoke');button.disabled=true;
    try {await call(`${api}/${encodeURIComponent(id)}`,{method:'DELETE'});clearIssued();await refresh();status.textContent='KEY 사용을 취소했습니다. 기존 연결에서 이 KEY를 사용할 수 없습니다.';}
    catch(e){status.textContent=e.message;}
    finally{button.disabled=false;}
  };
  $('#token-form').onsubmit=async e=>{
    e.preventDefault();const button=$('#key-issue');if(button.disabled)return;button.disabled=true;
    clearIssued(); status.textContent='연결 KEY를 발급하고 있습니다.';
    try {
      const result=await call(api,{method:'POST',body:JSON.stringify({name:$('#token-name').value,days:Number($('#token-days').value),scope:$('#token-scope').value})});
      $('#secret').value=result.token;$('#issued').hidden=false;issuedKeyId=result.id;
      await refresh();
      status.textContent=issuedKeyId ? '발급했습니다. KEY를 복사해 연결할 프로그램에 입력하세요.' : '다른 화면에서 KEY가 변경되었습니다. 최신 KEY를 다시 확인하세요.';
    }catch(e){status.textContent=e.message;}
    finally{button.disabled=false;}
  };
  $('#copy-token').onclick=async()=>{
    if(!$('#secret').value)return;
    try{await navigator.clipboard.writeText($('#secret').value);status.textContent='KEY를 복사했습니다.';}
    catch{status.textContent='KEY 입력란을 선택해 직접 복사하세요.';$('#secret').select();}
  };
  refresh().catch(e=>status.textContent=e.message);
})();
