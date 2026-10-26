(() => {
  let csrf = '', currentKeyId = null, issuedKeyId = null;
  const api = 'api/local-tokens';
  const $ = selector => document.querySelector(selector);
  const status = $('#status');
  const scopeName = scope => scope === 'publish' ? '조회·다운로드·신규 등록·내 도구 업데이트' : '조회·다운로드·좋아요';
  const date = value => new Date(value * 1000).toLocaleString('ko-KR', {year:'numeric', month:'long', day:'numeric', hour:'2-digit', minute:'2-digit'});
  const lifetime = key => key.status === 'invalid' ? '재발급 필요' : (key.expires === null ? '유효기간 제한 없음' : (typeof key.expires === 'number' && Number.isFinite(key.expires) && key.expires > 0 ? `${date(key.expires)}까지` : '재발급 필요'));
  const stateName = state => ({active:'사용 중', expired:'만료됨', revoked:'사용 취소됨', replaced:'교체됨', invalid:'재발급 필요'}[state] || '발급 전');
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
    $('#current-key-detail').textContent = key ? `본인 사번에 연결된 KEY · ${lifetime(key)}` : '유효기간 제한 없이, 로그인한 본인 명의로 발급합니다.';
    $('#key-state').textContent = stateName(key?.status);
    $('#key-state').dataset.state = key?.status || 'none';
    $('#key-issue').textContent = data.tokens.length ? 'KEY 재발급' : '연결 KEY 발급';
    $('#key-issue').disabled = false;
    $('#key-revoke').hidden = key?.status !== 'active';
    $('#key-rule').textContent = data.tokens.length ? '재발급하면 기존 KEY는 즉시 사용할 수 없습니다. 확장 프로그램의 KEY 입력란이나 MCP 연결을 요청한 AI 채팅에 새 KEY를 입력하세요. 기존 이용 이력은 유지됩니다.' : 'KEY 원문은 발급 직후 한 번만 표시됩니다. 확장 프로그램의 KEY 입력란이나 MCP 연결을 요청한 AI 채팅에 입력하세요.';
    if (key && typeof key.expires === 'number') $('#key-rule').textContent += ' 이전에 발급한 KEY의 유효기간은 유지되며, 재발급하면 기간 제한이 없어집니다.';
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
      const result=await call(api,{method:'POST',body:JSON.stringify({})});
      $('#secret').value=result.token;$('#issued').hidden=false;issuedKeyId=result.id;
      await refresh();
      status.textContent=issuedKeyId ? '발급했습니다. KEY를 복사해 확장 프로그램의 KEY 입력란이나 MCP 연결을 요청한 AI 채팅에 입력하세요.' : '다른 화면에서 KEY가 변경되었습니다. 최신 KEY를 다시 확인하세요.';
    }catch(e){status.textContent=e.message;}
    finally{button.disabled=false;}
  };
  function selectIssuedKey() {
    const input = $('#secret');
    input.focus(); input.select(); input.setSelectionRange(0, input.value.length);
  }
  $('#copy-token').onclick=async()=>{
    const input=$('#secret'),button=$('#copy-token'),value=input.value,id=issuedKeyId;
    if(!value||!id||$('#issued').hidden||button.disabled)return;
    button.disabled=true;
    status.textContent='KEY를 복사하고 있습니다.';
    try{
      let copied=false;
      // Remote HTTP origins do not expose the modern Clipboard API. Keep the
      // legacy copy in the click gesture when that API is unavailable.
      try{
        if(window.isSecureContext&&navigator.clipboard?.writeText){
          await navigator.clipboard.writeText(value);copied=true;
        }
      }catch{/* A denied Clipboard request still has the manual selection path. */}
      // A KEY may have been revoked/replaced while Clipboard permission was pending.
      if(issuedKeyId!==id||input.value!==value||$('#issued').hidden){
        if(status.textContent==='KEY를 복사하고 있습니다.')status.textContent='KEY가 변경되었습니다. 최신 KEY를 확인해 주세요.';
        return;
      }
      if(!copied){
        selectIssuedKey();
        try{copied=document.execCommand('copy')===true;}catch{copied=false;}
      }
      status.textContent=copied?'KEY를 복사했습니다.':'자동 복사가 되지 않았습니다. 선택된 KEY를 Ctrl+C 또는 ⌘C로 복사해 주세요.';
    }finally{button.disabled=false;}
  };
  refresh().catch(e=>status.textContent=e.message);
})();
