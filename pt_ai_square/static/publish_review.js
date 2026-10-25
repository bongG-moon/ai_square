(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const id = document.querySelector('[data-draft-id]').dataset.draftId;
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  let draft, busy = false;
  const statusNames = {pending:'확인 대기', approved:'승인 완료', committing:'게시 처리 중', committed:'게시 완료', expired:'기간 만료'};
  function message(text, error = false) { $('review-status').textContent = text; $('review-status').dataset.error = String(error); }
  async function api(path, data) {
    const res = await fetch(path, {credentials:'same-origin', cache:'no-store', headers:{'Accept':'application/json', ...(data ? {'Content-Type':'application/json', 'X-CSRF-Token':csrf} : {})}, ...(data ? {method:'POST', body:JSON.stringify(data)} : {})});
    const value = await res.json();
    if (!res.ok) throw new Error(value.error || '초안을 불러오지 못했습니다. 다시 확인해 주세요.');
    return value;
  }
  function addField(label, value) { const dt = document.createElement('dt'), dd = document.createElement('dd'); dt.textContent = label; dd.textContent = String(value || '—'); $('review-fields').append(dt, dd); }
  function render(options) {
    const m = draft.metadata, a = draft.artifact;
    $('review-content').hidden = false;
    $('review-action').textContent = draft.toolId ? `도구 #${draft.toolId} · 새 버전 게시` : '새 도구 등록';
    $('review-name').textContent = m.name;
    $('review-description').textContent = m.desc;
    $('review-state').textContent = statusNames[draft.status] || draft.status;
    $('review-fields').replaceChildren();
    const lookup = (items, value) => (items || []).find(v => (v.id || v._id) === value)?.name || value;
    addField('구분 · 프로그램', `${m.type} · ${m.platform}`);
    if (draft.packageId) addField('플랫폼 packageId', draft.packageId);
    if (draft.sourcePackageId) addField('파일의 원본 packageId', draft.sourcePackageId);
    if (draft.packageIdentityChanged) addField('버전 연결', '선택한 도구의 최초 packageId를 유지해 새 버전으로 게시합니다. 원본 ZIP은 변경하지 않습니다.');
    addField('조직', lookup(options?.organizations, m.orgId));
    addField('업무', lookup(options?.categories, m.categoryId));
    addField('관련 업무', (m.workTags || []).join(' · '));
    addField('변경 내용', m.changes);
    addField('필요 환경', m.environment);
    addField('확인 기한', new Date(draft.expires * 1000).toLocaleString('ko-KR'));
    $('review-file-name').textContent = a.name || (a.url ? 'URL 연결' : '명령어 연결');
    $('review-file-size').textContent = a.name ? `${Number(a.bytes).toLocaleString('ko-KR')} bytes · ${a.packageRecognized ? '배포 정보 확인됨' : '직접 등록 파일'}` : (a.url || '아래 설치 안내를 확인하세요.');
    $('review-file-hash').textContent = a.sha256 ? `SHA-256 · ${a.sha256}` : '';
    $('review-file-warning').textContent = a.packageWarning || '';
    $('review-file-warning').hidden = !a.packageWarning;
    $('review-guide').textContent = m.guide || '';
    $('review-flow').replaceChildren();
    for (const step of m.workflow?.steps || []) { const li = document.createElement('li'); li.textContent = `${step.title || ''} — ${step.description || step.detail || ''}`; $('review-flow').append(li); }
    const install = m.installProfile || a.commands;
    $('review-install').hidden = !install || !Object.keys(install).length;
    $('review-install').textContent = JSON.stringify(install, null, 2);
    $('review-suggested').textContent = `초안에서 제안한 범위: ${m.approval ? '조회 승인 필요' : '전체 공개'}. 위에서 직접 선택해 주세요.`;
    $('review-form').hidden = draft.status !== 'pending';
    message(draft.status === 'approved' ? '승인했습니다. AI 대화로 돌아가 “게시를 이어서 진행해줘”라고 말씀하세요.' : draft.status === 'committed' ? '게시가 완료되었습니다. 플랫폼 목록에서 확인할 수 있습니다.' : draft.status === 'expired' ? '초안이 만료되었습니다. AI에게 새 초안을 요청해 주세요.' : draft.status === 'committing' ? '게시 처리 중입니다. AI 대화에서 결과를 확인해 주세요.' : '아래 내용을 확인한 뒤 공개 범위를 선택해 주세요.');
  }
  let options;
  $('review-form').addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !draft || !$('review-form').reportValidity()) return;
    busy = true; $('review-approve').disabled = true;
    try {
      const choice = new FormData($('review-form')).get('visibility');
      draft = await api(`/api/publish-drafts/${encodeURIComponent(id)}/approve`, {approval:choice === 'approval', reviewDigest:draft.reviewDigest});
      render(options);
    } catch(error) { message(error.message, true); }
    finally { busy = false; $('review-approve').disabled = false; }
  });
  (async () => { try {
    draft = await api(`/api/publish-drafts/${encodeURIComponent(id)}`);
    try { options = await api('/api/catalog/options'); } catch { options = {}; }
    render(options);
  } catch(error) { message(error.message, true); } })();
})();
