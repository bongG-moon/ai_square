// Workspace extension: retain the approved home, catalog, typography and motion.
const work={tab:'tools',scope:'mine',requestFilter:'대기',ideaFilter:'전체',notifications:[],unreadOnly:false,users:[]};
const dated=t=>new Date(t*1000).toLocaleString('ko-KR',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
const badge=s=>`<span class="ws-badge" data-status="${esc(s)}">${esc(s)}</span>`;
const blank=(i,title,body)=>`<div class="ws-empty">${icon(i)}<h3>${esc(title)}</h3><p>${esc(body)}</p></div>`;
const originalRender=render, originalModal=openModal, originalDetail=detail, originalManage=manage;
const workspace=document.createElement('section');workspace.id='sq-workspace';workspace.hidden=true;$('#sq-main').append(workspace);
const nav=$('.sq-header nav');nav.insertAdjacentHTML('beforeend',`${button('requests-board','기능 요청','','data-route="ideas"')}${button('manage','등록 관리','','data-route="manage"')}${button('admin-home','관리자','','data-route="admin" id="ws-admin-nav" hidden')}`);
$('.sq-header-actions [data-action="manage"]').remove();
$('.sq-header-actions').insertAdjacentHTML('afterbegin',`<button class="sq-quiet ws-bell" data-action="inbox" aria-label="내 알림" title="내 알림">${icon('bell')}<span id="ws-unread" hidden></span></button>`);
render=function(){
 const categories=server.categories||[];
 $('#sq-category').innerHTML=options(['모든 업무',...categories.filter(x=>x.enabled||x.name===state.category).map(x=>x.name)],state.category);
 originalRender();const special=['manage','admin','ideas'].includes(state.route);
 workspace.hidden=!special;$('.sq-toolbar').hidden=special;$('#sq-search-form').hidden=special;
 $('#ws-admin-nav').hidden=server.user.role!=='admin';
 const unread=server.unread||0;$('#ws-unread').hidden=!unread;$('#ws-unread').textContent=unread>99?'99+':unread;
 $('.ws-bell').setAttribute('aria-label',`내 알림, 읽지 않은 알림 ${unread}개`);
 if(special){
  const labels={manage:['내가 나눈 노하우.','동료의 피드백으로 더 나은 도구로.'],admin:['함께 쓰는 공간을 가꾸세요.','좋은 공유가 이어질 수 있도록.'],ideas:['작은 불편함도 좋은 시작.','함께 만들고 싶은 도구를 이야기하세요.']};
  setPageHeading(...labels[state.route],true);renderWorkspace();
 }
 enhanceSelects();
};
openModal=function(title,kicker,html){originalModal(title,kicker,html);decorateForms();enhanceSelects();};
function decorateForms(){
 const form=$('#sq-register-form')||$('#sq-edit-tool-form');if(!form)return;
 form.querySelector('[name=visibility]')?.closest('label')?.remove();$('#sq-audience')?.remove();
 const audience=form.querySelector('[name=audience]');audience?.closest('.sq-field')?.remove();
 const org=form.querySelector('[name=org]');if(org){const old=org.value;org.innerHTML=options(organizations.filter(o=>o.enabled||o.name===old).map(o=>o.name),old);}
 let cat=form.querySelector('[name=category]');
 if(!cat&&form.id==='sq-edit-tool-form'){const label=document.createElement('label');label.className='sq-field';label.innerHTML='<span>업무 분야</span><select name="category"></select>';form.querySelector('.sq-form-grid').append(label);cat=label.querySelector('select');cat.dataset.previous=getItem(runtime.detailId).category;}
 if(cat){const old=cat.dataset.previous||cat.value;cat.innerHTML=options((server.categories||[]).filter(c=>c.enabled||c.name===old).map(c=>c.name),old);}
 const approval=form.querySelector('[name=approval]');
 if(approval){
  const checked=approval.type==='checkbox'?approval.checked:approval.value==='true';
  const box=approval.closest('.sq-field');
  box.outerHTML=`<div class="sq-field wide ws-access-field"><span>조회 권한 설정</span><label class="ws-access-card"><span class="ws-access-icon">${icon('shield-check')}</span><span class="ws-access-copy"><strong>승인받은 사용자만 상세 조회</strong><small>켜면 등록자·관리자의 승인 후 상세 내용과 파일을 볼 수 있습니다.</small></span><input type="checkbox" role="switch" name="approval" aria-label="승인받은 사용자만 상세 조회" ${checked?'checked':''}></label><small>끄면 사내 사용자가 바로 조회합니다. 목록은 모두에게 보이며 등록자와 관리자는 항상 조회할 수 있습니다.</small></div>`;
 }
 const upload=form.querySelector('.sq-upload');if(upload)upload.outerHTML=uploadArea('artifact',runtime.draft.file?[runtime.draft.file]:[]);
 decoratePackageForm(form);

}

// Searchable, keyboard-accessible select surface. Native select remains the form source.
let picker=null,pickerSerial=0;
function closePicker(restore=false){if(!picker)return;const p=picker;picker=null;p.panel.remove();p.trigger.setAttribute('aria-expanded','false');if(restore&&p.trigger.isConnected)p.trigger.focus();}
function enhanceSelects(){
 $$('select').forEach(select=>{
  if(select.disabled||select.closest('[hidden]'))return;
  let trigger=select.nextElementSibling;
  if(!trigger?.classList.contains('ws-select')){trigger=document.createElement('button');trigger.type='button';trigger.className='ws-select';trigger.setAttribute('role','combobox');trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-expanded','false');select.after(trigger);select.classList.add('ws-native');select.tabIndex=-1;select.setAttribute('aria-hidden','true');trigger.addEventListener('click',e=>{e.preventDefault();openPicker(select,trigger);});trigger.addEventListener('keydown',e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();openPicker(select,trigger);}});}
  trigger.innerHTML=`<span>${esc(select.selectedOptions[0]?.textContent||'선택하세요')}</span>${icon('chevron-down')}`;
  const label=select.getAttribute('aria-label')||select.closest('label')?.querySelector('span')?.textContent||'항목 선택';trigger.setAttribute('aria-label',label+' · '+(select.selectedOptions[0]?.textContent||''));
 });mountIcons();
}
function openPicker(select,trigger){
 if(picker?.trigger===trigger){closePicker(true);return;}closePicker();
 const panel=document.createElement('div');panel.className='ws-select-panel';panel.setAttribute('popover','manual');const id='ws-options-'+(++pickerSerial);
 panel.innerHTML=`<div class="ws-select-search">${icon('search')}<input type="search" placeholder="검색…" aria-label="선택 항목 검색" role="combobox" aria-expanded="true" aria-controls="${id}" aria-autocomplete="list"></div><div role="listbox" id="${id}" class="ws-select-options"></div><div class="ws-select-hint">↑ ↓ 이동 · Enter 선택 · Esc 닫기</div>`;
 (select.closest('dialog')||root).append(panel);panel.showPopover?.();
 const rect=trigger.getBoundingClientRect();panel.style.width=Math.min(Math.max(rect.width,230),innerWidth-24)+'px';panel.style.left=Math.min(rect.left,innerWidth-parseFloat(panel.style.width)-12)+'px';panel.style.top=Math.max(12,Math.min(rect.bottom+8,innerHeight-340))+'px';
 const input=panel.querySelector('input'),list=panel.querySelector('[role=listbox]');let filtered=[],index=0;
 picker={panel,trigger};trigger.setAttribute('aria-expanded','true');trigger.setAttribute('aria-controls',id);
 function draw(){filtered=[...select.options].filter(o=>!o.disabled&&Core.normalizeSearch(o.text).includes(Core.normalizeSearch(input.value)));index=Math.min(index,filtered.length-1);list.innerHTML=filtered.map((o,i)=>`<button type="button" role="option" tabindex="-1" id="${id}-${i}" aria-selected="${o.selected}" class="${i===index?'is-focused':''}" data-option="${i}"><span>${esc(o.text)}</span>${o.selected?icon('check'):''}</button>`).join('')||'<p class="sq-note">일치하는 항목이 없습니다.</p>';input.setAttribute('aria-activedescendant',index>=0?`${id}-${index}`:'');mountIcons();}
 function choose(i){const o=filtered[i];if(!o)return;select.value=o.value;closePicker(true);select.dispatchEvent(new Event('change',{bubbles:true}));enhanceSelects();}
 list.addEventListener('click',e=>{const b=e.target.closest('[data-option]');if(b){e.preventDefault();choose(+b.dataset.option);}});
 input.addEventListener('input',()=>{index=0;draw();});input.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closePicker(true);}if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();index=(index+(e.key==='ArrowDown'?1:-1)+filtered.length)%Math.max(1,filtered.length);draw();list.querySelector('.is-focused')?.scrollIntoView({block:'nearest'});}if(e.key==='Enter'){e.preventDefault();choose(index);}if(e.key==='Tab')closePicker();});draw();input.focus();
}
document.addEventListener('pointerdown',e=>{if(picker&&!picker.panel.contains(e.target)&&!picker.trigger.contains(e.target))closePicker();});
window.addEventListener('resize',()=>closePicker());document.addEventListener('scroll',e=>{if(picker&&!picker.panel.contains(e.target))closePicker();},true);
$('#sq-dialog').addEventListener('close',()=>closePicker());

manage=function(tab='tools'){work.tab=tab;const adminTab=['storage','activity','taxonomy','orgs','admins'].includes(tab);work.scope=adminTab?'all':'mine';if($('#sq-dialog').open)closeModal();navigate(adminTab?'admin':'manage');};
function managementItems(){return items.filter(x=>work.scope==='all'||x.ownerId===server.user.id);}
function renderWorkspace(){
 if(state.route==='ideas'){renderIdeas();return;}
 const isAdmin=state.route==='admin';work.scope=isAdmin?'all':'mine';
 const tabs=isAdmin?[['tools','전체 기능'],['requests','권한 관리'],['taxonomy','조직·업무'],['admins','관리자 설정'],['storage','저장 공간'],['activity','사용 이력']]:[['tools','내 등록 기능'],['requests','권한 관리'],['feedback','피드백']];
 if(!tabs.some(t=>t[0]===work.tab))work.tab='tools';
 const list=managementItems();const pending=requests.filter(r=>r.status==='대기'&&(isAdmin||r.ownerId===server.user.id)).length;
 let html=`<div class="ws-summary"><div><span>공유한 기능</span><strong>${list.filter(x=>!x.deleted).length}<small>개</small></strong></div><div><span>승인 대기</span><strong>${pending}<small>건</small></strong></div><div><span>새로운 피드백</span><strong>${list.reduce((n,x)=>n+x.comments.filter(c=>c.status==='접수').length,0)}<small>건</small></strong></div><div class="ws-summary-action">${button('register',icon('plus')+' 기능 등록','sq-primary')}</div></div><div class="ws-surface"><div class="sq-tabs ws-tabs">${tabs.map(([id,label])=>button('workspace-tab',label,'',`data-tab="${id}" aria-pressed="${work.tab===id}"`)).join('')}</div>`;
 if(work.tab==='tools')html+=`<div class="ws-panel-head"><div><h2>${isAdmin?'전체 등록 기능':'내가 공유한 기능'}</h2><p>등록 정보와 배포 버전, 조회 권한을 관리하세요.</p></div></div><div class="ws-list">${list.map(x=>`<article class="ws-row"><span class="sq-tool-icon" data-type="${esc(x.type)}">${icon(x.icon)}</span><div class="ws-row-main"><strong>${esc(x.name)}</strong><p>${esc(x.org)} · ${esc(x.type)} · v${x.active}${isAdmin?' · '+esc(x.owner):''}</p></div>${badge(x.deleted?'휴지통':x.approval?'승인 후 조회':'전체 공개')}<div class="sq-row-actions">${x.deleted?button('restore-tool','복원','sq-link',`data-id="${x.id}"`):`${button('edit-tool','수정','sq-link',`data-id="${x.id}"`)}${button('manage-versions','버전','sq-link',`data-id="${x.id}"`)}${button('grant-users','권한','sq-link',`data-id="${x.id}"`)}${button('delete-tool',icon('trash-2'),'sq-icon ws-danger',`data-id="${x.id}" aria-label="${esc(x.name)} 삭제"`)}`}</div></article>`).join('')||blank('package-open','아직 등록한 기능이 없습니다.','잘 만든 도구를 동료들과 공유해 보세요.')}</div>`;
 if(work.tab==='requests'){
  const all=requests.filter(r=>isAdmin||r.ownerId===server.user.id);const filtered=all.filter(r=>work.requestFilter==='대기'?r.status==='대기':work.requestFilter==='승인됨'?r.granted:!r.granted&&r.status!=='대기');
  html+=`<div class="ws-panel-head"><div><h2>조회 권한 관리</h2><p>신청자와 실제 권한 보유자를 구분해서 관리합니다.</p></div><div class="ws-segment">${['대기','승인됨','처리 이력'].map(s=>button('access-filter',s,'',`data-filter="${s}" aria-pressed="${s===work.requestFilter}"`)).join('')}</div></div><div class="ws-list">${filtered.map(r=>`<article class="ws-row"><span class="ws-avatar">${esc(r.who.slice(0,1))}</span><div class="ws-row-main"><strong>${esc(r.who)} <small>${esc(r.user)}</small></strong><p>${esc(r.name)} · ${esc(r.source)}</p><p class="ws-message">${esc(r.reason||'직접 권한을 부여한 사용자입니다.')}</p>${r.decision?`<p>${esc(r.decision)}</p>`:''}</div>${badge(r.granted?'승인됨':r.status==='승인'?'권한 회수':r.status)}<div class="sq-row-actions">${r.status==='대기'?button('access-decision','승인','sq-primary',`data-request="${r.id}" data-status="승인"`)+button('access-decision','반려','sq-secondary',`data-request="${r.id}" data-status="반려"`):r.granted?button('access-decision','권한 회수','sq-secondary',`data-request="${r.id}" data-status="회수"`):''}${button('access-history','이력','sq-link',`data-request="${r.id}"`)}</div></article>`).join('')||blank('shield-check','처리할 항목이 없습니다.','권한 신청과 승인 결과가 여기에 표시됩니다.')}</div>`;
 }
 if(work.tab==='feedback'){const feedback=list.flatMap(x=>x.comments.map(c=>({...c,toolName:x.name}))).sort((a,b)=>b.created-a.created);html+=`<div class="ws-panel-head"><div><h2>동료들의 피드백</h2><p>의견을 확인하고 답변과 처리 상태를 남겨주세요.</p></div></div>${feedback.map(c=>`<button class="ws-row ws-click" data-action="feedback-open" data-id="${c.tool}"><span class="ws-avatar">${icon('message-square')}</span><span class="ws-row-main"><strong>${esc(c.toolName)}</strong><span>${esc(c.author)} · ${esc(c.text)}</span></span>${badge(c.status)}${icon('chevron-right')}</button>`).join('')||blank('messages-square','아직 피드백이 없습니다.','사용자가 남긴 의견을 이곳에서 확인할 수 있습니다.')}`;}
 if(work.tab==='taxonomy')html+=taxonomyPanel();
 if(work.tab==='admins')html+=`<div class="ws-panel-head"><div><h2>함께 운영하는 관리자</h2><p>기본 관리자는 설정 파일에서, 추가 관리자는 이 화면에서 관리합니다.</p></div>${server.user.baseAdmin?button('add-admin',icon('user-plus')+' 관리자 추가','sq-primary'):''}</div>${(work.admins||[]).map(a=>`<div class="ws-row"><span class="ws-avatar">${esc(a.name.slice(0,1))}</span><div class="ws-row-main"><strong>${esc(a.name)}</strong><p>${esc(a.id)}</p></div>${badge(a.base?'기본 관리자':'추가 관리자')}${!a.base&&server.user.baseAdmin?button('remove-admin','해제','sq-secondary',`data-user="${esc(a.id)}"`):''}</div>`).join('')||blank('users','관리자 목록을 불러오는 중입니다.','잠시만 기다려 주세요.')}`;
 if(work.tab==='storage')html+=`<div class="ws-panel-head"><div><h2>배포 파일 저장 공간</h2><p>배포 파일과 기능 요청 첨부파일은 서버 디스크에 저장합니다. 요청·버전·권한·이력과 파일 정보는 MongoDB에 저장됩니다.</p></div>${button('storage-dialog','보관 정책·이전 버전 정리','sq-primary')}</div><div class="ws-storage">${((server.storage?.used||0)/1048576).toFixed(1)} <small>MB 사용 / ${((server.storage?.quota||0)/1073741824).toFixed(1)} GB</small></div>`;
 if(work.tab==='activity')html+=activityPanel();
 workspace.innerHTML=html+'</div>';mountIcons();enhanceSelects();
}
function taxonomyPanel(){return `<div class="ws-panel-head"><div><h2>조직과 업무 분류</h2><p>저장하면 검색 필터와 등록·수정 화면에 바로 반영됩니다.</p></div></div><div class="ws-taxonomy">${[['organization','조직',organizations],['category','업무',server.categories||[]]].map(([kind,label,rows])=>`<section><div class="ws-panel-head"><h3>${label}</h3>${button('taxonomy-edit',icon('plus')+' 추가','sq-link',`data-kind="${kind}"`)}</div>${rows.map(x=>`<div class="ws-row"><span class="ws-order">${x.order}</span><div class="ws-row-main"><strong>${esc(x.name)}</strong><p>${x.enabled?'선택 가능':'사용 중지 · 기존 기록 유지'}</p></div>${button('taxonomy-edit',icon('pencil'),'sq-icon',`data-kind="${kind}" data-id="${esc(x.id)}" aria-label="${esc(x.name)} 수정"`)}</div>`).join('')}</section>`).join('')}</div>`;}

detail=async function(id,tab='intro'){
 const x=getItem(id);if(!x)throw Error('이 기능은 삭제되었거나 더 이상 사용할 수 없습니다.');runtime.detailId=x.id;const token=runtime.detailLoadToken=(runtime.detailLoadToken||0)+1;
 if(x.deleted){openModal('휴지통에 있는 기능입니다.',x.name,`<p class="sq-note">복원한 후 기능 상세를 열 수 있습니다.</p>${button('restore-tool','복원','sq-primary',`data-id="${x.id}"`)}`);return;}
 // Revalidate on every open; no stale dialog bypass after access revocation.
 try{const fresh=await requestAPI(`/api/tools/${x.id}`);if(token!==runtime.detailLoadToken)return;Object.assign(x,fresh,{likes:fresh.likes-(fresh.liked?1:0)});}
 catch(error){if(error.status!==403)throw error;await refresh();if(token===runtime.detailLoadToken)lockedDetail(getItem(id));return;}
 originalDetail(id,tab);
 deploymentLinks(x,tab);
 $('.sq-detail-top .sq-row-actions')?.insertAdjacentHTML('afterbegin',button('subscribe',icon(x.subscribed?'bell-ring':'bell')+(x.subscribed?'업데이트 알림 켜짐':'업데이트 알림 받기'),'sq-secondary',`data-id="${x.id}" aria-pressed="${x.subscribed}"`));
 if(tab==='comments'){
  const tabs=$('#sq-dialog-body .sq-tabs');while(tabs.nextElementSibling)tabs.nextElementSibling.remove();
  tabs.insertAdjacentHTML('afterend',`<div class="ws-feedback-list">${x.comments.map(c=>`<article class="ws-feedback"><div class="ws-feedback-head"><div><strong>${esc(c.author)}</strong><small>${dated(c.created)} · ${esc(c.kind)}</small></div>${badge(c.status)}</div><p>${esc(c.text)}</p>${c.replies.map(r=>`<div class="ws-reply"><strong>${esc(r.author)}</strong><small>${dated(r.created)} · ${esc(r.status||'답변')}</small><p>${esc(r.text||'처리 상태를 변경했습니다.')}</p></div>`).join('')}${x.canManage||c.user===server.user.id?button('feedback-reply','답변·상태 변경','sq-link',`data-id="${c.id}"`):''}</article>`).join('')||blank('message-circle','첫 번째 의견을 남겨주세요.','사용 경험이나 개선할 점을 나눠주세요.')}</div><form id="sq-comment-form" class="ws-compose"><label class="sq-field"><span>피드백 종류</span><select name="kind">${options(['개선 의견','사용 후기','오류 제보','아이디어 제안'],'개선 의견')}</select></label><label class="sq-field"><span>의견</span><textarea name="comment" required maxlength="4000" placeholder="사용해 보니 어떤 점이 좋았나요? 개선이 필요한 부분도 알려주세요."></textarea></label><div class="sq-actions"><button class="sq-primary">피드백 등록</button></div></form>`);
 }mountIcons();enhanceSelects();
};
function lockedDetail(x){runtime.detailId=x.id;openModal('조회 권한이 필요합니다.',x.name,`<div class="ws-lock"><span class="ws-lock-icon">${icon('lock-keyhole')}</span><h3>${x.access==='pending'?'신청을 검토하고 있습니다.':'승인 후 상세 내용을 볼 수 있어요.'}</h3><p>목록은 누구나 볼 수 있지만, 상세 내용과 배포 파일은<br>등록자 또는 관리자의 승인 후 이용할 수 있습니다.</p>${x.accessDecision?`<div class="sq-callout">${esc(x.accessDecision)}</div>`:''}<div class="sq-actions">${x.access==='pending'?badge('승인 대기'):button('request-access','조회 권한 신청','sq-primary')}</div><small>처리 결과는 내 알림에서 알려드릴게요.</small></div>`);}
function renderIdeas(){
 const rows=(work.ideas||[]).filter(i=>work.ideaFilter==='전체'||i.status===work.ideaFilter);
 workspace.innerHTML=`<div class="ws-board-head"><div class="ws-segment">${['전체','접수 대기','개발 중','구현 완료'].map(s=>button('idea-filter',s,'',`data-filter="${s}" aria-pressed="${s===work.ideaFilter}"`)).join('')}</div>${button('idea',icon('plus')+' 새 기능 요청','sq-primary')}</div><div class="ws-idea-grid">${rows.map(i=>`<button class="ws-idea-card" data-action="idea-open" data-id="${i.id}"><div class="ws-idea-top">${badge(i.status)}<span>${esc(i.category)}</span></div><h2>${esc(i.name)}</h2><p>${esc(i.body)}</p><div class="ws-idea-foot"><span>${i.assigneeName?'담당 '+esc(i.assigneeName):'함께 만들 동료를 기다려요'}</span>${icon('arrow-up-right')}</div></button>`).join('')||blank('lightbulb','작은 불편함에서 좋은 도구가 시작됩니다.','필요한 기능을 요청하고 동료들과 함께 만들어 보세요.')}</div>`;mountIcons();
}
async function loadIdeas(){work.ideas=(await requestAPI('/api/ideas')).ideas;}
async function ideaDetail(id){await loadIdeas();const i=work.ideas.find(x=>x.id===+id);if(!i)throw Error('요청을 찾을 수 없습니다.');work.idea=i;
 const owner=server.user.role==='admin'||i.assignee===server.user.id;
 openModal(i.name,'기능 요청',`<div class="ws-idea-top">${badge(i.status)}<span>${esc(i.category)} · ${esc(i.author)} · ${dated(i.created)}</span></div><p class="ws-request-body">${esc(i.body)}</p>${attachmentLinks(i.attachments||[])}<div class="ws-assignee">${icon('user-round')}<span>${i.assigneeName?'개발 담당 · '+esc(i.assigneeName):'아직 담당자가 없습니다.'}</span>${!i.assignee&&i.status==='접수 대기'?button('idea-claim','제가 구현할게요','sq-primary',`data-id="${i.id}"`):''}</div>${i.toolName?`<button class="ws-linked-tool" data-action="detail" data-id="${i.tool}">${icon('package')}<span>연결된 기능<strong>${esc(i.toolName)}</strong></span>${icon('arrow-up-right')}</button>`:''}<div class="ws-feedback-list">${(i.replies||[]).map(r=>`<div class="ws-reply"><strong>${esc(r.author)}</strong><small>${dated(r.created)}</small><p>${esc(r.text)}</p></div>`).join('')}</div><form data-work-form="idea-reply"><label class="sq-field"><span>답변</span><textarea name="text" maxlength="4000" placeholder="진행 상황이나 추가 의견을 남겨주세요."></textarea></label>${owner?`<div class="sq-form-grid"><label class="sq-field"><span>진행 상태</span><select name="status">${options([i.status,...({'접수 대기':['보류'],'담당자 지정':['개발 중','보류','접수 대기'],'개발 중':['구현 완료','보류','접수 대기'],'보류':['접수 대기','개발 중'],'구현 완료':['개발 중']}[i.status]||[])],i.status)}</select></label><label class="sq-field"><span>구현 완료 시 연결할 기능</span><select name="tool"><option value="">기능 선택</option>${items.filter(x=>!x.deleted&&x.access==='approved').map(x=>`<option value="${x.id}" ${i.tool===x.id?'selected':''}>${esc(x.name)}</option>`).join('')}</select></label></div>`:''}<div class="sq-actions"><button class="sq-primary">${owner?'답변·상태 저장':'답변 등록'}</button></div></form>`);
}

async function inbox(loadMore=false){
 const url='/api/notifications?unread='+work.unreadOnly+(loadMore&&work.notificationCursor?'&before='+encodeURIComponent(work.notificationCursor):'');const r=await requestAPI(url);
 work.notifications=loadMore?[...work.notifications,...r.notifications]:r.notifications;work.notificationCursor=r.nextCursor;server.unread=r.unread;render();
 openModal('내 알림','나에게 필요한 소식',`<div class="ws-inbox-head"><div class="ws-segment">${button('inbox-filter','전체','','data-unread="false" aria-pressed="'+!work.unreadOnly+'"')}${button('inbox-filter','안읽음','','data-unread="true" aria-pressed="'+work.unreadOnly+'"')}</div>${button('read-all','모두 읽음','sq-link')}</div><div class="ws-inbox">${work.notifications.map(n=>`<button class="ws-notification ${n.read?'':'is-unread'}" data-action="notification-open" data-id="${esc(n.id)}"><span class="ws-notice-icon">${icon(({approval:'shield-check',feedback:'message-square',release:'package-check',idea:'lightbulb',admin:'settings'})[n.kind]||'bell')}</span><span><strong>${esc(n.title)}</strong><small>${dated(n.created)}</small></span><span class="ws-unread-dot" ${n.read?'hidden':''}></span></button>`).join('')||blank('bell','모두 확인했습니다.','답변, 권한 처리 결과, 새 버전 소식이 여기에 도착합니다.')}</div>${r.nextCursor?button('inbox-more','이전 알림 더 보기','sq-secondary'):''}`);
}

Object.assign(actions,{
 'manage':()=>manage(),
 'admin-home':async()=>{work.tab='tools';closeModal();navigate('admin');},
 'workspace-tab':async b=>{work.tab=b.dataset.tab;if(work.tab==='admins')work.admins=(await requestAPI('/api/admins')).admins;if(work.tab==='activity'){const r=await requestAPI('/api/activity');server.activityEvents=r.events;server.activityCursor=r.nextCursor;}renderWorkspace();},
 'admin-tab':b=>{work.tab=b.dataset.tab==='orgs'?'taxonomy':b.dataset.tab;closeModal();navigate(work.scope==='all'?'admin':'manage');},
 'storage-dialog':()=>originalManage('storage'),
 'access-filter':b=>{work.requestFilter=b.dataset.filter;renderWorkspace();},
 'requests-board':async()=>{await loadIdeas();closeModal();navigate('ideas');},
 'idea-filter':b=>{work.ideaFilter=b.dataset.filter;renderIdeas();},
 'idea-open':b=>ideaDetail(b.dataset.id),
 'idea':()=>{work.ideaFiles=[];openModal('어떤 기능이 필요하세요?','새 기능 요청',`<form data-work-form="idea"><div class="sq-form-grid"><label class="sq-field wide"><span>요청 제목</span><input name="name" required maxlength="100" placeholder="예: 여러 장비의 점검 이력을 한 번에 비교하고 싶어요."></label><label class="sq-field wide"><span>현재 불편한 점과 원하는 결과</span><textarea name="desc" required maxlength="4000" placeholder="지금은 어떻게 일하고 있나요? 어떤 결과가 나오면 도움이 될까요?"></textarea></label><label class="sq-field"><span>관련 업무</span><select name="category">${options((server.categories||[]).filter(c=>c.enabled).map(c=>c.name),'공통 업무')}</select></label></div>${uploadArea('attachments',work.ideaFiles)}<div class="sq-actions"><button class="sq-primary">요청 등록</button></div></form>`);},
 'idea-claim':b=>ask('이 요청의 개발을 맡으시겠어요?','내 이름이 개발 담당자로 표시되고 요청자에게 알림이 전달됩니다.',async()=>{await requestAPI(`/api/ideas/${b.dataset.id}`,'PATCH',{claim:true,expectedRevision:work.idea.revision});await ideaDetail(b.dataset.id);},'제가 구현할게요'),
 'feedback-open':b=>detail(b.dataset.id,'comments'),
 'feedback-reply':b=>{const x=getItem(runtime.detailId),c=x.comments.find(c=>c.id===+b.dataset.id);work.feedback=c;openModal('피드백에 답변하기',x.name,`<div class="sq-callout"><strong>${esc(c.author)}</strong><br>${esc(c.text)}</div><form data-work-form="feedback"><label class="sq-field"><span>답변</span><textarea name="text" maxlength="4000" placeholder="검토 결과나 진행 상황을 알려주세요."></textarea></label>${x.canManage?`<label class="sq-field"><span>처리 상태</span><select name="status">${options(['접수','검토 중','반영 중','반영 완료','보류'],c.status)}</select></label>`:''}<div class="sq-actions"><button class="sq-primary">답변 저장</button></div></form>`);},
 'subscribe':async b=>{const x=getItem(b.dataset.id);await requestAPI(`/api/tools/${x.id}/subscription`,'PUT',{enabled:!x.subscribed});await detail(x.id,runtime.detailTab);},
 'delete-tool':b=>{const x=getItem(b.dataset.id);ask('이 기능을 휴지통으로 이동할까요?',x.name+' · 목록과 다운로드가 중단됩니다. 등록자·관리자가 복원할 수 있습니다.',async()=>{await requestAPI(`/api/tools/${x.id}`,'DELETE',{expectedRevision:x.revision});await refresh();},'휴지통으로 이동');},
 'restore-tool':async b=>{const x=getItem(b.dataset.id);await requestAPI(`/api/tools/${x.id}/restore`,'POST',{expectedRevision:x.revision});closeModal();await refresh();},
 'taxonomy-edit':b=>{const kind=b.dataset.kind,x=[...organizations,...server.categories].find(x=>x.id===b.dataset.id);work.taxonomy={kind,id:x?.id};openModal(x?'분류 수정':'분류 추가',kind==='organization'?'조직 설정':'업무 설정',`<form data-work-form="taxonomy"><div class="sq-form-grid"><label class="sq-field wide"><span>이름</span><input name="name" value="${esc(x?.name||'')}" required maxlength="80"></label><label class="sq-field"><span>표시 순서</span><input name="order" type="number" min="0" max="999" value="${x?.order??10}" required></label><label class="sq-field"><span>사용 여부</span><select name="enabled"><option value="true" ${x?.enabled!==false?'selected':''}>사용</option><option value="false" ${x?.enabled===false?'selected':''}>사용 중지</option></select></label><label class="sq-field wide"><span>안내 담당자 (선택)</span><input name="owner" maxlength="100" value="${esc(x?.owner||'')}"></label></div><div class="sq-callout">이름을 바꿔도 기존 기능과의 연결은 유지됩니다. 사용 중지한 항목은 새로 선택할 수 없습니다.</div><div class="sq-actions"><button class="sq-primary">저장</button></div></form>`);},
 'access-decision':b=>{work.access={id:b.dataset.request,status:b.dataset.status};openModal('조회 권한 '+b.dataset.status,'신청 처리',`<form data-work-form="access"><label class="sq-field"><span>처리 사유 ${b.dataset.status==='승인'?'(선택)':''}</span><textarea name="reason" maxlength="2000" ${b.dataset.status==='승인'?'':'required'} placeholder="신청자에게 안내할 내용을 적어주세요."></textarea></label><div class="sq-actions"><button class="sq-primary">${b.dataset.status}</button></div></form>`);},
 'access-history':b=>{const r=requests.find(r=>r.id===b.dataset.request);openModal('권한 처리 이력',r.name,`<div class="ws-timeline">${r.history.map(h=>`<article><strong>${esc(h.status)}</strong><small>${esc(h.actor)} · ${dated(h.at)}</small><p>${esc(h.reason||'')}</p></article>`).join('')}</div>`);},
 'grant-users':b=>{work.grantTool=+b.dataset.id;userPicker('grant');},
 'add-admin':()=>userPicker('admin'),
 'user-search':async()=>{const q=$('#ws-user-search').value;work.users=(await requestAPI('/api/users?q='+encodeURIComponent(q))).users;renderUserChoices();},
 'choose-user':async b=>{const uid=b.dataset.user;if(work.userMode==='grant')await requestAPI(`/api/tools/${work.grantTool}/grants`,'POST',{user:uid});else await requestAPI('/api/admins/'+encodeURIComponent(uid),'PUT',{active:true});closeModal();await refresh();if(work.userMode==='admin'){work.admins=(await requestAPI('/api/admins')).admins;renderWorkspace();}announce('권한을 부여했습니다.');},
 'remove-admin':b=>ask('추가 관리자 권한을 해제할까요?',b.dataset.user+' 계정은 일반 사용자로 이용할 수 있습니다.',async()=>{await requestAPI('/api/admins/'+encodeURIComponent(b.dataset.user),'PUT',{active:false});work.admins=(await requestAPI('/api/admins')).admins;await refresh();},'해제'),
 'inbox':()=>inbox(),
 'inbox-more':()=>inbox(true),
 'inbox-filter':b=>{work.unreadOnly=b.dataset.unread==='true';return inbox();},
 'read-all':async()=>{await requestAPI('/api/notifications/read','PUT',{all:true});await inbox();},
 'notification-open':async b=>{const n=work.notifications.find(n=>n.id===b.dataset.id);await requestAPI('/api/notifications/read','PUT',{id:n.id});await refresh();if(n.target.type==='idea')return ideaDetail(n.target.id);if(n.target.type==='access'){work.tab='requests';closeModal();navigate(server.user.role==='admin'?'admin':'manage');return;}if(n.target.type==='admin'){closeModal();navigate(server.user.role==='admin'?'admin':'home');return;}return detail(n.target.id,n.target.type==='feedback'?'comments':'intro');}
});
function userPicker(mode){work.userMode=mode;work.users=[];openModal(mode==='grant'?'조회 사용자 추가':'추가 관리자 지정',mode==='grant'?getItem(work.grantTool).name:'기본 관리자 전용',`<p class="sq-note">이 사이트에 로그인한 적이 있는 계정을 이름 또는 사번으로 검색하세요.</p><form data-work-form="user-search" class="ws-user-search"><input id="ws-user-search" type="search" placeholder="이름 또는 사번" aria-label="사용자 검색"><button class="sq-primary">검색</button></form><div id="ws-user-results"></div>`);}
function renderUserChoices(){$('#ws-user-results').innerHTML=work.users.map(u=>`<div class="ws-row"><span class="ws-avatar">${esc(u.name.slice(0,1))}</span><div class="ws-row-main"><strong>${esc(u.name)}</strong><p>${esc(u.id)}</p></div>${button('choose-user',work.userMode==='admin'?'관리자 지정':'조회 승인','sq-secondary',`data-user="${esc(u.id)}"`)}</div>`).join('')||blank('search','일치하는 사용자가 없습니다.','먼저 사이트에 로그인한 계정인지 확인해 주세요.');mountIcons();}
root.addEventListener('submit',event=>{
 const form=event.target;if(!form.dataset.workForm)return;event.preventDefault();event.stopImmediatePropagation();if(form.dataset.busy)return;
 form.dataset.busy='true';const data=Object.fromEntries(new FormData(form));form.querySelectorAll('button').forEach(b=>b.disabled=true);
 (async()=>{
  switch(form.dataset.workForm){
   case 'idea':{const body=new FormData();delete data.attachments;body.append('metadata',JSON.stringify(data));for(const file of work.ideaFiles||[])body.append('attachments',file);const r=await requestAPI('/api/ideas','POST',body);await loadIdeas();navigate('ideas');await ideaDetail(r.id);break;}
   case 'idea-reply':{const i=work.idea;await requestAPI(`/api/ideas/${i.id}`,'PATCH',{...data,tool:data.tool?+data.tool:null,expectedRevision:i.revision});await ideaDetail(i.id);await loadIdeas();if(state.route==='ideas')renderIdeas();break;}
   case 'feedback':{const c=work.feedback;await requestAPI(`/api/feedback/${c.id}/reply`,'POST',data);await refresh();await detail(c.tool,'comments');break;}
   case 'taxonomy':await requestAPI('/api/taxonomy','POST',{...data,...work.taxonomy,order:+data.order,enabled:data.enabled==='true'});closeModal();await refresh();break;
   case 'access':await requestAPI(`/api/requests/${encodeURIComponent(work.access.id)}/decision`,'POST',{status:work.access.status,reason:data.reason});closeModal();await refresh();break;
   case 'user-search':await actions['user-search']();break;
  }
 })().catch(showError).finally(()=>{delete form.dataset.busy;form.querySelectorAll('button').forEach(b=>b.disabled=false);});
},true);
// Keep errors visible in the active dialog, not behind its backdrop.
const originalError=showError;
showError=function(error){if($('#sq-dialog').open){let e=$('#ws-dialog-error');if(!e){e=document.createElement('p');e.id='ws-dialog-error';e.className='sq-error';e.setAttribute('role','alert');$('#sq-dialog-body').prepend(e);}e.textContent=error.message;e.scrollIntoView({block:'nearest'});announce(error.message);}else originalError(error);};
setInterval(()=>{if(document.hidden||runtime.requestBusy)return;requestAPI('/api/notifications?unread=true').then(r=>{server.unread=r.unread;$('#ws-unread').hidden=!r.unread;$('#ws-unread').textContent=r.unread>99?'99+':r.unread;}).catch(()=>{});},30000);
