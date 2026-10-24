
(()=>{
'use strict';
const root=document.getElementById('square-app'),$=s=>root.querySelector(s),$$=s=>[...root.querySelectorAll(s)];
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon=name=>`<i data-lucide="${name}" aria-hidden="true"></i>`,num=value=>Number(value).toLocaleString('ko-KR');
const motion=matchMedia('(prefers-reduced-motion: reduce)');
const Core={
 normalizeSearch:value=>String(value??'').normalize('NFKC').toLowerCase().replace(/\s+/g,''),
 normalizeTags:value=>{const seen=new Set();return (Array.isArray(value)?value:String(value??'').split(/[,，\n]/)).map(t=>String(t).trim().replace(/\s+/g,' ')).filter(t=>{const key=Core.normalizeSearch(t);if(!key||seen.has(key))return false;seen.add(key);return true;});},
 tagError:value=>{const tags=Core.normalizeTags(value);return tags.length>8?'관련 업무는 최대 8개까지 입력해 주세요.':tags.some(t=>t.length>30)?'관련 업무 하나는 30자 이내로 입력해 주세요.':'';},
 filter:(items,f)=>items.filter(x=>!x.hidden&&(f.platform==='전체'||x.platform===f.platform)&&(f.org==='전체 조직'||x.org===f.org)&&(f.type==='전체'||x.type===f.type)&&(f.category==='모든 업무'||x.category===f.category)&&(!f.query||[x.name,x.desc,x.org,x.type,x.category,...(x.workTags||[])].some(value=>Core.normalizeSearch(value).includes(Core.normalizeSearch(f.query))))),
 sort:(items,order)=>[...items].sort((a,b)=>order==='downloads'?b.downloads-a.downloads:order==='recent'?b.created-a.created:order==='name'?a.name.localeCompare(b.name,'ko'):a.editorial-b.editorial),
 pages:(length,page,size)=>({page:Math.max(0,Math.min(page,Math.max(0,Math.ceil(length/size)-1))),count:Math.max(1,Math.ceil(length/size))}),
 canDelete:(item,v)=>!v.deleted&&v.n!==item.active&&v.n!==item.fallback&&!v.refs,
 retention:(item,keep,days)=>{const retained=[...item.versions].filter(v=>!v.deleted).sort((a,b)=>b.n-a.n).slice(0,keep).map(v=>v.n);return item.versions.filter(v=>!retained.includes(v.n)&&v.age>days&&Core.canDelete(item,v));},
 rollback:(item,target)=>{const v=item.versions.find(v=>v.n===target&&!v.deleted&&!v.withdrawn);if(!v||target===item.active)throw Error('복구할 수 없는 버전입니다.');const previous=item.active;item.versions.find(v=>v.n===previous).withdrawn=true;item.active=target;item.fallback=target;item.revision++;item.updatePaused=true;return previous;},
 validate:(draft,step)=>{if(step===1){if(Core.tagError(draft.workTags))return Core.tagError(draft.workTags);if(!draft.name.trim())return '도구 이름을 입력해 주세요.';if(!draft.desc.trim())return '어떤 업무를 돕는지 한 줄로 적어 주세요.';if(!draft.owner.trim())return '담당자를 입력해 주세요.';if(draft.visibility==='선택 조직'&&!draft.audience.length)return '공개할 조직을 하나 이상 선택해 주세요.';}if(step===2){if(!draft.guide.trim())return '설치하거나 연결하는 방법을 적어 주세요.';if(draft.mode==='url'){try{const u=new URL(draft.url);if(u.protocol!=='https:')return 'https://로 시작하는 연결 주소를 입력해 주세요.';}catch{return '올바른 연결 주소를 입력해 주세요.';}}else if(draft.mode==='command'){if(!draft.commandProject?.trim()&&!draft.commandUser?.trim())return '지원하는 설치 범위의 명령어를 하나 이상 적어 주세요.';if([draft.commandProject,draft.commandUser].some(s=>(s||'').length>8000))return '명령어는 범위별 8,000자 이내로 입력하세요.';}else if(!draft.file)return '공유할 파일을 선택해 주세요.';else if(!/\.(zip|exe|msi|ps1|md)$/i.test(draft.file.name))return 'ZIP, EXE, MSI, PS1, MD 중 하나를 선택해 주세요. 여러 코드 파일은 ZIP으로 묶어 주세요.';}return '';}
};
const items=[];
const state={route:'home',homeType:'전체',platform:'전체',org:'전체 조직',type:'전체',category:'모든 업무',query:'',sort:'discovery',page:0,rankPage:0,rankMode:'recent',auto:!motion.matches,liked:new Set(),snapshot:0};
const runtime={timer:null,progress:null,hover:false,focus:false,inView:false,busy:false,token:0,detailId:null,detailTab:'intro',adminTab:'tools',returnFocus:null,confirm:null,draft:null,step:1,releaseId:null,newId:null};
const organizations=[],requests=[];
const policy={keep:3,days:90},audit=[];
const mountIcons=()=>globalThis.lucide?.createIcons({attrs:{width:18,height:18}});
const announce=text=>{$('#sq-status').textContent=text;if($('#sq-dialog').open)$('#sq-modal-status').textContent=text;};
const persist=()=>{};
const getItem=id=>items.find(x=>x.id===Number(id));
const button=(action,label,cls='sq-secondary',extra='')=>`<button class="${cls} cursor-interaction" data-action="${action}" ${extra}>${label}</button>`;
const options=(values,selected)=>values.map(v=>`<option${v===selected?' selected':''}>${esc(v)}</option>`).join('');
function filtered(home=false){return Core.filter(items,{...state,platform:'전체',org:home?'전체 조직':state.org,type:home?state.homeType:state.type,category:home?'모든 업무':state.category,query:home?'':state.query});}
function rankMetrics(x){return state.rankMode==='recent'?{score:x.rankScore||0,likes:x.recentLikes||0,downloads:x.recentDownloads||0}:{score:x.totalRankScore||0,likes:x.likes+(state.liked.has(x.id)?1:0),downloads:x.downloads};}
function rankItems(){return filtered(true).sort((a,b)=>{const am=rankMetrics(a),bm=rankMetrics(b);return bm.score-am.score||bm.downloads-am.downloads||bm.likes-am.likes||b.created-a.created||a.id-b.id;}).slice(0,10);}
function tagChips(tags,limit=8,query=''){const all=Core.normalizeTags(tags),q=Core.normalizeSearch(query);return all.length?`<span class="sq-work-tags" aria-label="관련 업무">${all.slice(0,limit).map(t=>`<span class="sq-work-tag${q&&Core.normalizeSearch(t).includes(q)?' is-match':''}">${esc(t)}</span>`).join('')}${all.length>limit?`<span class="sq-work-tag">+${all.length-limit}</span>`:''}</span>`:'';}
function workTagField(value){return `<label class="sq-field wide"><span>관련 업무 태그</span><input name="workTags" value="${esc(value)}" maxlength="300" placeholder="예: 주간 보고, 실적 정리, 보고서 작성"><small>동료가 검색할 업무명을 쉼표로 구분하세요. 최대 8개, 각 30자까지. 예: 불량 분석, 수율 검토</small></label>`;}
function card(item,shelf=false){return `<article class="sq-tool" data-tone="${({MCP:'blue',Skill:'violet',Tool:'mint',플러그인:'peach',하네스:'rose'})[item.type]||'blue'}"><button class="sq-tool-main cursor-interaction" data-action="detail" data-id="${item.id}" aria-label="${esc(item.name)} 상세 보기"><div class="sq-tool-top"><span class="sq-tool-icon" data-type="${esc(item.type)}">${icon(item.icon)}</span><span class="sq-tool-kind">${esc(item.platform)} · <span class="sq-type-label" data-type="${esc(item.type)}">${esc(item.type)}</span></span></div><h3>${esc(item.name)}</h3><p class="sq-tool-summary">${esc(item.desc||"등록된 설명이 없습니다.")}</p>${shelf?'':tagChips([...(item.workTags||[])].sort((a,b)=>Number(!!state.query&&Core.normalizeSearch(b).includes(Core.normalizeSearch(state.query)))-Number(!!state.query&&Core.normalizeSearch(a).includes(Core.normalizeSearch(state.query)))),3,state.query)}</button><div class="sq-tool-footer"><span>${esc(item.org)}</span><div class="sq-tool-metrics"><button class="sq-count sq-like cursor-interaction" data-action="like" data-id="${item.id}" aria-label="${esc(item.name)} 좋아요" aria-pressed="${state.liked.has(item.id)}">${icon('heart')}<span>${num(item.likes+(state.liked.has(item.id)?1:0))}</span></button><span class="sq-count" aria-label="다운로드 ${num(item.downloads)}건">${icon('arrow-down-to-line')}${num(item.downloads)}</span></div></div></article>`;}
const toolTypes=['전체','MCP/Tool','Skill','플러그인/하네스'];
const typeLabel=type=>({'MCP/Tool':'MCP/TOOL',Skill:'SKILL'})[type]||type;
function renderFilterTabs(){
 const tabs=$('#sq-filter-tabs'),home=state.route==='home';
 tabs.setAttribute('aria-label',home?'도구 유형':'등록 조직');
 tabs.classList.toggle('sq-organization-tabs',!home);
 if(home){tabs.innerHTML=toolTypes.map(type=>`<button class="cursor-interaction" data-home-type="${type}" aria-pressed="${type===state.homeType}">${typeLabel(type)}</button>`).join('');return;}
 // Organization counts reflect all current filters except the organization itself.
 const available=Core.filter(items,{...state,platform:'전체',org:'전체 조직'});
 const names=[...new Set([...organizations.filter(o=>o.enabled!==false||items.some(x=>x.org===o.name)).map(o=>o.name),...items.filter(x=>!x.hidden).map(x=>x.org)])];
 tabs.innerHTML=['전체 조직',...names].map(org=>{const count=org==='전체 조직'?available.length:available.filter(x=>x.org===org).length;return `<button class="cursor-interaction" data-org="${esc(org)}" aria-pressed="${org===state.org}">${esc(org==='전체 조직'?'전체':org)} <span class="sq-filter-count">(${num(count)})</span></button>`;}).join('');
}
function setPageHeading(lead,continuation,home=false){
 const title=$('#sq-page-title');title.textContent=lead;
 const suffix=document.createElement('span');suffix.className='sq-heading-continuation'+(home?'':' sq-heading-secondary');suffix.textContent=' '+continuation;title.append(suffix);
 $('#sq-page-description').hidden=true;
}
function revealElements(){
 if(motion.matches)return;
 const elements=$$('.sq-heading,.sq-toolbar,.sq-chart,.sq-home-shelves .sq-section-head,.sq-tool').filter(el=>!el.dataset.revealed&&!el.closest('[hidden]'));
 if(!globalThis.IntersectionObserver)return;
 if(!runtime.revealObserver)runtime.revealObserver=new IntersectionObserver(entries=>{for(const entry of entries){if(!entry.isIntersecting)continue;entry.target.classList.add('sq-visible');runtime.revealObserver.unobserve(entry.target);}},{threshold:.06});
 elements.forEach((el,i)=>{el.dataset.revealed='true';el.style.setProperty('--enter-delay',Math.min(i%6*65,260)+'ms');el.classList.add('sq-reveal');el.addEventListener('animationend',()=>{el.classList.remove('sq-reveal','sq-visible');},{once:true});runtime.revealObserver.observe(el);});
}
function render(){
 runtime.token++;runtime.busy=false;stopAuto();
 $('#sq-home').hidden=state.route!=='home';$('#sq-browse').hidden=state.route!=='browse';$$('[data-route]').forEach(b=>{if(b.dataset.route===state.route)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
 if(state.route==='home')setPageHeading('좋은 도구가 모이는 곳.','동료의 노하우를, 당신의 업무로.',true);
 else setPageHeading('우리의 경험을 둘러보세요.','지금 필요한 도구를 찾는 시간.',true);
 $('#sq-query').value=state.query;renderFilterTabs();
 const homeItems=filtered(true);$('#sq-popular').innerHTML=Core.sort(homeItems,'downloads').slice(0,3).map(x=>card(x,true)).join('')||empty('선택한 유형의 도구가 아직 없습니다.');$('#sq-recent').innerHTML=Core.sort(homeItems,'recent').slice(0,3).map(x=>card(x,true)).join('')||empty('새로 공유된 도구가 없습니다.');
 renderRanks();renderCatalog();mountIcons();revealElements();schedule();
}
function empty(title){return `<div class="sq-empty"><h3>${esc(title)}</h3><p>도구 유형이나 조직 선택을 바꿔보세요.</p>${button('clear-filters','전체 도구 보기')}</div>`;}
function renderCatalog(){renderFilterTabs();const list=Core.sort(filtered(),state.sort),paging=Core.pages(list.length,state.page,12);state.page=paging.page;$('#sq-types').innerHTML=toolTypes.map(type=>`<button class="cursor-interaction" data-type="${type}" aria-pressed="${type===state.type}">${typeLabel(type)}</button>`).join('');$('#sq-category').value=state.category;$('#sq-sort').value=state.sort;$('#sq-result-count').textContent=state.query?`“${state.query}” 검색 결과 ${list.length}개`:`${list.length}개의 도구 · 순위 번호 없이 둘러보기`;$('#sq-catalog').innerHTML=list.slice(state.page*12,state.page*12+12).map(x=>card(x)).join('')||empty('검색 결과가 없습니다.');$('#sq-catalog-pages').innerHTML=paging.count>1?`${button('catalog-prev',icon('chevron-left'),'sq-icon',state.page===0?'disabled aria-label="이전 페이지"':'aria-label="이전 페이지"')}<span>${state.page+1} / ${paging.count}</span>${button('catalog-next',icon('chevron-right'),'sq-icon',state.page===paging.count-1?'disabled aria-label="다음 페이지"':'aria-label="다음 페이지"')}`:'';revealElements();}
function rankRowHTML(x,rank){const metric=rankMetrics(x);return `<div class="sq-rank-row" data-rank="${rank}"><span class="sq-rank-number">${rank}</span><button class="sq-rank-name cursor-interaction" data-action="detail" data-id="${x.id}"><strong>${esc(x.name)}</strong><small>${esc(x.platform)}<span class="sq-type-label" data-type="${esc(x.type)}">${esc(x.type)}</span></small></button><button class="sq-count sq-like cursor-interaction" data-action="like" data-id="${x.id}" aria-label="${esc(x.name)} 좋아요" aria-pressed="${state.liked.has(x.id)}">${icon('heart')}<span>${num(metric.likes)}</span></button><span class="sq-count" aria-label="다운로드 ${num(metric.downloads)}건">${icon('arrow-down-to-line')}${num(metric.downloads)}</span></div>`;}
function renderRanks(){$('#sq-rank-list').removeAttribute('aria-busy');const list=rankItems();if(state.rankPage*5>=list.length)state.rankPage=0;const group=list.slice(state.rankPage*5,state.rankPage*5+5);$('#sq-rank-range').textContent=state.rankMode==='recent'?'실시간 순위':'누적 순위';$('#sq-rank-period').textContent=state.rankMode==='recent'?'최근 7일':'전체 기간';$$('[data-action=rank-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===state.rankMode)));$('#sq-rank-list').innerHTML=group.map((x,i)=>rankRowHTML(x,state.rankPage*5+i+1)).join('')||'<div class="sq-empty">조건에 맞는 순위가 없습니다.</div>';$$('[data-action=rank-page]').forEach(b=>{b.setAttribute('aria-pressed',String(+b.dataset.page===state.rankPage));b.disabled=+b.dataset.page*5>=list.length;});$('#sq-chart-time').textContent=new Date(server.rankAsOf*1000).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',timeZone:'Asia/Seoul'});}
function stopAuto(){clearTimeout(runtime.timer);runtime.timer=null;runtime.progress?.cancel();runtime.progress=null;}
function canAuto(){return state.route==='home'&&runtime.inView&&!runtime.busy&&!document.hidden&&!$('#sq-dialog').open&&rankItems().length>5;}
function schedule(delay=5000){
 stopAuto();const count=rankItems().length;$('#sq-rank-all').hidden=count>5;

 if(!canAuto())return;
 const meter=$(`[data-action=rank-page][data-page="${state.rankPage}"] span`);
 if(!motion.matches&&meter?.animate)runtime.progress=meter.animate([{transform:'scaleX(0)'},{transform:'scaleX(1)'}],{duration:delay,fill:'forwards'});
 runtime.timer=setTimeout(()=>{if(canAuto())changeRank(1-state.rankPage);else schedule();},delay);
}

async function changeRank(page){
 const ranked=rankItems();
 if(runtime.busy||page===state.rankPage||page*5>=ranked.length)return;
 stopAuto();runtime.busy=true;
 const started=performance.now(),token=++runtime.token,list=$('#sq-rank-list'),direction=page>state.rankPage?1:-1;
 try{
  if(motion.matches||!list.animate){state.rankPage=page;renderRanks();mountIcons();return;}
  const next=ranked.slice(page*5,page*5+5),old=[...list.children];
  const emptyRow=()=>{const el=document.createElement('div');el.className='sq-rank-row';el.setAttribute('aria-hidden','true');return el;};
  list.setAttribute('aria-busy','true');
  await Promise.all(Array.from({length:Math.max(old.length,next.length)},async(_,i)=>{
   const front=old[i]||emptyRow();if(!front.isConnected)list.append(front);
   front.classList.add('sq-rank-flipping');front.inert=true;
   const turnOut=front.animate([
    {transform:'perspective(850px) rotateX(0deg)',filter:'brightness(1)'},
    {transform:`perspective(850px) rotateX(${-direction*90}deg)`,filter:'brightness(.96)'}
   ],{duration:260,delay:i*90,fill:'forwards',easing:'cubic-bezier(.55,0,1,.45)'});
   await turnOut.finished.catch(()=>{});
   if(token!==runtime.token||!front.isConnected){turnOut.cancel();return;}
   let back=emptyRow();
   if(next[i]){const template=document.createElement('template');template.innerHTML=rankRowHTML(next[i],page*5+i+1);back=template.content.firstElementChild;}
   back.classList.add('sq-rank-flipping');back.inert=true;
   front.replaceWith(back);turnOut.cancel();mountIcons();
   const turnIn=back.animate([
    {transform:`perspective(850px) rotateX(${direction*90}deg)`,filter:'brightness(.96)'},
    {transform:'perspective(850px) rotateX(0deg)',filter:'brightness(1)'}
   ],{duration:360,fill:'both',easing:'cubic-bezier(.16,1,.3,1)'});
   await turnIn.finished.catch(()=>{});turnIn.cancel();
   back.classList.remove('sq-rank-flipping');back.inert=false;
  }));
  if(token!==runtime.token)return;
  state.rankPage=page;renderRanks();mountIcons();
 }finally{if(token===runtime.token){list.removeAttribute('aria-busy');runtime.busy=false;schedule(Math.max(0,5000-(performance.now()-started)));}}
}
function navigate(route,sort){runtime.token++;runtime.busy=false;state.route=route;state.page=0;if(sort)state.sort=sort;render();persist();}
function openModal(title,kicker,html){if(!$('#sq-dialog').open)runtime.returnFocus=document.activeElement;$('#sq-dialog-title').textContent=title;$('#sq-dialog-kicker').textContent=kicker;$('#sq-dialog-body').innerHTML=html;$('#sq-modal-status').textContent='';if(!$('#sq-dialog').open)$('#sq-dialog').showModal();$('#sq-dialog-body').scrollTop=0;mountIcons();schedule();}
function closeModal(){if($('#sq-confirm').open)$('#sq-confirm').close();$('#sq-dialog').close();runtime.returnFocus?.isConnected&&runtime.returnFocus.focus({preventScroll:true});schedule();}
function ask(title,copy,action,label='확인',extra=''){runtime.confirm=action;$('#sq-confirm-title').textContent=title;$('#sq-confirm-copy').textContent=copy;$('#sq-confirm-extra').innerHTML=extra;$('#sq-confirm-go').textContent=label;$('#sq-confirm').showModal();mountIcons();}
function detail(id,tab='intro'){
 const x=getItem(id);runtime.detailId=x.id;runtime.detailTab=tab;
 const tabs=[['intro','소개'],['connect','설치·연결'],['versions','버전'],['comments','의견']].map(([value,label])=>button('detail-tab',label,'',`data-tab="${value}" aria-pressed="${tab===value}"`)).join('');
 let content='';
 if(tab==='intro')content=`<div class="sq-detail-hero"><h3>${esc(x.name)}.<br>업무의 다음 단계를 더 쉽게.</h3><p>${esc(x.desc)}</p></div><div class="sq-two-col"><dl class="sq-meta"><dt>사용 프로그램</dt><dd>${esc(x.platform)}</dd><dt>공유 유형</dt><dd>${esc(x.type)}</dd><dt>등록 조직</dt><dd>${esc(x.org)}</dd><dt>담당자</dt><dd>${esc(x.owner)}</dd></dl><dl class="sq-meta"><dt>현재 배포</dt><dd>v${x.active} · ${x.updatePaused?'자동 업데이트 보류':'배포 정보 API 제공'}</dd><dt>공개 범위</dt><dd>${esc(x.visibility)}</dd><dt>사용 권한</dt><dd>${x.approval?'담당자 승인 필요':'사내 사용자'}</dd><dt>지원 수준</dt><dd>${esc(x.support)}</dd></dl></div><div class="sq-callout"><strong>사용 예시</strong><br>“${x.category==='제조'?'이번 주 품질 결과에서 달라진 내용을 정리해줘.':x.type==='MCP/Tool'?'관련 문서와 근거를 찾아줘.':'이 자료를 우리 팀 양식에 맞춰 정리해줘.'}”처럼 요청해 보세요. 도구마다 필요한 환경은 설치·연결 탭에서 확인합니다.</div>`;
 if(tab==='intro')content+=`<section class="sq-related-work"><h3>관련 업무</h3>${tagChips(x.workTags)||'<p class="sq-note">등록된 관련 업무가 없습니다.</p>'}</section>`;
 if(tab==='connect'){
  const gated=x.approval&&x.access!=='approved';
  content=`<div class="sq-admin-head"><h3>사용을 시작해 볼까요?</h3><span class="sq-badge">${esc(x.support)}</span></div>`;
  if(gated)content+=`<div class="sq-callout"><strong>${x.access==='pending'?'사용 신청을 검토하고 있습니다.':'먼저 사용 권한을 신청해 주세요.'}</strong><br>승인 담당: ${esc(x.org)} · ${esc(x.owner)}<br>도구 사용 승인을 받아도 원본 데이터 권한은 별도로 확인합니다.</div>${x.access==='pending'?'<span class="sq-note">승인 대기 중입니다.</span>':button('request-access','사용 권한 신청','sq-primary')}`;
  else {content+=`<div class="sq-callout"><strong>사용 환경</strong><br>${esc(x.environment||x.platform)}</div>`;
  if(x.mode==='server')content+=`<div class="sq-callout"><strong>등록된 연결 주소</strong><br><a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.url)}</a></div><p class="sq-note">${x.platform==='ChatGPT'?'회사 ChatGPT 관리자에게 원격 연결 메뉴와 인증 방식의 지원 여부를 확인한 후 아래 안내를 따라 설정하세요.':'등록자가 제공한 안내에 따라 대상 프로그램에서 연결하세요.'} 웹이 연결 성공을 자동 확인하지는 않습니다.</p>`;
  else if(x.mode==='command')content+=commandScopePanel(x,x.versions.find(v=>v.n===x.active));
  else content+=`${button('download-file','파일 다운로드','sq-primary')}<div class="sq-callout">${x.platform==='ChatGPT'?'회사 계정에서 허용된 파일 첨부·지침 활용 방법을 확인하세요. Python 코드와 실행 파일은 ChatGPT에 첨부한다고 자동 설치되지 않습니다.':'파일을 받은 뒤 아래 설치 안내를 따라주세요.'} PC 자동 설치·업데이트는 후속 앱 연동 기능입니다.</div>`;
  }
  if(x.guide)content+=`<div class="sq-callout"><strong>등록자가 제공한 안내</strong><br>${esc(x.guide).replace(/\n/g,'<br>')}</div>`;
  if(x.updatePaused)content+='<div class="sq-callout">현재 배포는 이전 버전으로 복구한 상태입니다. 자동 업데이트 재개 전 점검이 필요합니다.</div>';
 }
 if(tab==='versions')content=`<div class="sq-admin-head"><h3>배포 이력</h3><span class="sq-badge">현재 v${x.active}</span></div><div class="sq-version-list">${x.versions.filter(v=>!v.deleted).map(v=>`<div class="sq-version"><div><strong>v${v.n}</strong> ${v.n===x.active?'<span class="sq-badge blue">현재 배포</span>':v.withdrawn?'<span class="sq-badge">배포 중단</span>':v.n===x.fallback?'<span class="sq-badge">복구용 보관</span>':''}<p>${esc(v.note)} · ${v.size} MB</p></div>${v.withdrawn?'<span class="sq-note">다운로드 중단</span>':button('version-download','이 버전 받기','sq-link',`data-version="${v.n}"`)}</div>`).join('')}</div><div class="sq-callout">사용자는 배포 가능한 이전 버전을 선택할 수 있습니다. 버전 복구·배포 중단·삭제는 등록자 또는 운영자 관리 화면에서 진행합니다.</div>${x.canManage?button('manage-versions','버전 관리 화면 보기'):''}`;
 if(tab==='comments')content=`<h3>함께 개선하는 도구</h3><div>${x.comments.map(c=>`<article class="sq-comment"><strong>${esc(c.author)}</strong><small>${esc(c.kind)}</small><p>${esc(c.text)}</p></article>`).join('')}</div><form id="sq-comment-form" class="sq-comment-form"><label class="sq-field"><span>의견 종류</span><select name="kind"><option>개선 의견</option><option>사용 후기</option><option>오류 제보</option><option>아이디어 제안</option></select></label><label class="sq-field"><span>내용</span><textarea name="comment" required placeholder="어떤 업무에서 어떻게 쓰셨나요?"></textarea></label><button class="sq-primary cursor-interaction">의견 등록</button></form>`;
 openModal(x.name,`${x.type} · ${x.platform}`,`<div class="sq-detail-top"><div class="sq-detail-id"><span class="sq-tool-icon" data-type="${esc(x.type)}">${icon(x.icon)}</span><div><strong>${esc(x.org)} · ${esc(x.owner)}</strong><p>다운로드 ${num(x.downloads)} · 좋아요 ${num(x.likes+(state.liked.has(x.id)?1:0))}</p></div></div><div class="sq-row-actions">${button('like',icon('heart')+`<span data-like-label>${state.liked.has(x.id)?'좋아요 취소':'좋아요'}</span><span data-like-count>${num(x.likes+(state.liked.has(x.id)?1:0))}</span>`,'sq-secondary sq-detail-like',`type="button" data-id="${x.id}" aria-pressed="${state.liked.has(x.id)}"`)}${button('detail-tab',x.approval&&x.access!=='approved'?'사용 권한 확인':'사용 시작','sq-primary','data-tab="connect"')}</div></div><div class="sq-tabs" aria-label="도구 상세 탭">${tabs}</div>${content}`);
}
function requestAccess(){const x=getItem(runtime.detailId);openModal('사용 권한 신청',x.name,`<div class="sq-callout">신청 도구: <strong>${esc(x.name)}</strong><br>승인 담당: ${esc(x.org)} · ${esc(x.owner)}</div><form id="sq-access-form"><label class="sq-field"><span>사용 목적</span><textarea name="reason" required placeholder="예: 장비 이력 검토를 위해 관련 매뉴얼을 검색하려고 합니다."></textarea></label><div class="sq-callout">도구 사용 권한과 데이터 접근 권한은 다릅니다. 실제 데이터 범위는 원본 시스템에서 확인합니다.</div><div class="sq-actions">${button('detail','돌아가기','sq-secondary',`data-id="${x.id}"`)}<button class="sq-primary cursor-interaction">신청하기</button></div></form>`);}
function freshDraft(x){return {name:x?.name||'',desc:x?.desc||'',workTags:(x?.workTags||[]).join(', '),platform:x?.platform||'Claude',type:x?.type||'Skill',org:x?.org||server.user.org,category:x?.category||'공통 업무',owner:x?.owner||server.user.name,visibility:x?.visibility||'전체 공개',audience:[...(x?.audience||[])],approval:x?.approval||false,mode:x?.mode==='command'?'command':x?.mode==='server'?'url':'file',commandProject:x?.versions?.find(v=>v.n===x.active)?.commands?.project||'',commandUser:x?.versions?.find(v=>v.n===x.active)?.commands?.user||'',url:x?.url||'',expectedRevision:x?.revision,file:null,guide:x?.guide||'',changes:'',sample:false,environment:x?.environment||'Windows · Claude Code'};}
function register(id){runtime.releaseId=id?Number(id):null;runtime.draft=freshDraft(id?getItem(id):null);runtime.step=1;wizard();}
function captureDraft(){const form=$('#sq-register-form');if(!form)return;const d=runtime.draft;for(const [key,value]of new FormData(form).entries()){if(key!=='artifact'&&key!=='audience'&&key!=='approval')d[key]=String(value);}if(runtime.step===1){d.approval=form.elements.approval.checked;d.audience=[...form.querySelectorAll('[name=audience]:checked')].map(e=>e.value);}}
function wizard(){
 const d=runtime.draft,step=runtime.step,x=runtime.releaseId?getItem(runtime.releaseId):null,nextVersion=x?Math.max(...x.versions.map(v=>v.n))+1:1;
 const steps=`<div class="sq-wizard-steps">${['기본 정보','파일·연결','확인·게시'].map((label,i)=>`<span class="${step===i+1?'active':''}"><b>${i+1}</b>${label}</span>`).join('')}</div>`;
 let content='';
 if(step===1)content=`<div class="sq-form-grid"><label class="sq-field wide"><span>도구 이름 *</span><input name="name" value="${esc(d.name)}" maxlength="50" placeholder="예: 주간 보고서 작성" required></label><label class="sq-field wide"><span>한 줄 소개 *</span><textarea name="desc" maxlength="200" placeholder="어떤 업무를 어떻게 도와주는지 적어주세요." required>${esc(d.desc)}</textarea></label>${workTagField(d.workTags)}<label class="sq-field"><span>사용 프로그램</span><select name="platform">${options(['Claude','ChatGPT','기타'],d.platform)}</select></label><label class="sq-field"><span>공유 유형</span><select name="type">${options(['MCP/Tool','Skill','플러그인/하네스'],d.type)}</select></label><label class="sq-field"><span>등록 조직</span><select name="org">${options(organizations.filter(o=>server.user.role==='admin'||o.name==='공통'||o.name===server.user.org).map(o=>o.name),d.org)}</select></label><label class="sq-field"><span>업무 분야</span><select name="category">${options(['공통 업무','제조','장비','기술'],d.category)}</select></label><label class="sq-field"><span>담당자 *</span><input name="owner" value="${esc(d.owner)}" required></label><label class="sq-field"><span>목록 공개 범위</span><select name="visibility">${options(['전체 공개','선택 조직'],d.visibility)}</select></label><div class="sq-field wide" id="sq-audience" ${d.visibility==='선택 조직'?'':'hidden'}><span>열람할 수 있는 조직</span><div class="sq-choice-row">${organizations.map(o=>`<label><input type="checkbox" name="audience" value="${esc(o.name)}" ${d.audience.includes(o.name)?'checked':''}>${esc(o.name)}</label>`).join('')}</div></div><div class="sq-field wide"><span>사용 승인</span><label class="sq-choice-row"><input type="checkbox" name="approval" ${d.approval?'checked':''}>사용 전 담당자의 승인이 필요합니다.</label><small>목록을 볼 수 있는 사람과 실제 사용할 수 있는 사람을 따로 정합니다.</small></div></div><div class="sq-callout">Skill에는 지침 문서뿐 아니라 Python 코드와 참고 자료도 포함할 수 있습니다. 함께 쓰는 파일은 ZIP으로 묶어주세요.</div>`;
 if(step===2)content=`<div class="sq-choice-row"><label><input type="radio" name="mode" value="file" ${d.mode==='file'?'checked':''}>파일 등록</label><label><input type="radio" name="mode" value="url" ${d.mode==='url'?'checked':''}>URL 연결</label><label><input type="radio" name="mode" value="command" ${d.mode==='command'?'checked':''}>명령어 안내</label></div>${d.mode==='file'?`<div class="sq-upload">${icon('upload-cloud')}<h3>${d.file?esc(d.file.name):'공유할 파일을 선택하세요.'}</h3><p>ZIP · EXE · MSI · PS1 · MD / 게시할 때 서버로 전송합니다.</p><input type="file" name="artifact" accept=".zip,.exe,.msi,.ps1,.md" aria-label="공유 파일 선택"></div>`:d.mode==='command'?commandFields(d):`<label class="sq-field" style="margin-top:20px"><span>연결 주소 *</span><input name="url" type="url" value="${esc(d.url)}" placeholder="https://mcp.example.internal/team"></label><div class="sq-callout">서버 연결형 MCP나 웹 서비스 주소를 등록합니다. 웹이 임의로 EXE로 변환하지 않습니다.</div>`}<div class="sq-form-grid"><label class="sq-field"><span>사용 환경</span><input name="environment" value="${esc(d.environment)}" placeholder="예: Windows · Claude Code"></label><label class="sq-field"><span>자동 배포 번호</span><input value="v${nextVersion} · 게시할 때 자동 생성" readonly></label><label class="sq-field wide"><span>설치·연결 방법 *</span><small>받은 파일이나 URL로 실제 사용을 시작하는 순서입니다. EXE도 실행할 파일과 설치 후 확인 방법을 적어주세요.</small><textarea name="guide" required placeholder="예: EXE 실행 후 Claude를 다시 시작하세요. / ZIP을 풀어 Skills 폴더에 넣으세요. / MCP URL을 연결 설정에 추가하세요.">${esc(d.guide)}</textarea></label><label class="sq-field wide"><span>이번에 바뀐 내용</span><textarea name="changes" placeholder="예: 보고서 양식 선택 기능을 추가했습니다.">${esc(d.changes)}</textarea></label></div>${d.platform==='ChatGPT'?'<div class="sq-callout">ChatGPT 항목은 파일 활용인지 원격 연결인지 구분합니다. 사내 계정에서 확인되지 않은 연결은 ‘조건 확인 필요’로 표시합니다.</div>':''}`;
 if(step===3)content=`<div class="sq-detail-hero"><span class="sq-badge blue">배포 미리보기 · v${nextVersion}</span><h3 style="margin-top:12px">${esc(d.name)}</h3><p>${esc(d.desc)}</p></div><dl class="sq-meta"><dt>프로그램 / 유형</dt><dd>${esc(d.platform)} / ${esc(d.type)}</dd><dt>조직 / 담당자</dt><dd>${esc(d.org)} / ${esc(d.owner)}</dd><dt>공개 / 사용</dt><dd>${esc(d.visibility)}${d.visibility==='선택 조직'?' · '+esc(d.audience.join(', ')):''} / ${d.approval?'승인 후 사용':'바로 안내'}</dd><dt>관련 업무</dt><dd>${tagChips(Core.normalizeTags(d.workTags))||'미입력'}</dd><dt>등록 대상</dt><dd>${esc(d.mode==='command'?'설치 범위 선택 후 명령어 복사':d.mode==='url'?d.url:d.file?.name)}</dd><dt>지원 수준</dt><dd>${d.platform==='ChatGPT'?(d.mode==='url'?'연결 조건 확인 필요':'파일 활용 안내'):d.mode==='url'?'서버 연결 안내':/\.(exe|msi|ps1)$/i.test(d.file?.name||'')?'수동 설치 · 자동 업데이트 미검증':'패키지 설치 안내'}</dd></dl><div class="sq-callout"><strong>${d.mode==='file'?'게시하면 서버에서 기본 파일 검사를 진행합니다.':'게시하면 입력한 연결·설치 정보를 버전별로 저장합니다.'}</strong><br>${d.mode==='command'?'명령어는 서버에서 실행하지 않으며, 사용자가 설치 범위를 선택해 복사합니다.':d.mode==='url'?'입력한 HTTPS 주소와 안내를 저장합니다.':'올린 파일 형식 그대로 저장하고 v1, v2처럼 배포 번호를 발급합니다. EXE 설치 파일을 배포하려면 완성된 EXE를 선택하세요. ZIP은 ZIP으로 배포됩니다. 기본 파일 검사에는 악성코드 검사와 실행 검증이 포함되지 않습니다.'}</div>`;
 openModal(x?'새 버전 등록':'도구 등록',x?`${x.name} · 버전은 자동으로 관리합니다.`:'잘 만든 도구를 동료들과 나눠보세요.',`${steps}<form id="sq-register-form" novalidate>${content}<p id="sq-register-error" class="sq-error" role="alert"></p><div class="sq-actions">${step>1?button('wizard-back','이전'):button('creator-guide','작성 가이드','sq-link')}${step<3?'<button class="sq-primary cursor-interaction">다음</button>':button('publish','게시','sq-primary')}</div></form>`);
}
async function publish(){
 if(runtime.publishBusy)return;
 const d=runtime.draft;if(!d)return;
 const error=packageBlockingError(d)||Core.validate(d,1)||Core.validate(d,2);if(runtime.step!==3||error){if(error)throw Error(error);return;}
 runtime.publishBusy=true;
 try{
 const metadata=JSON.stringify({...d,file:undefined,sample:undefined,packageInspection:undefined}),target=runtime.releaseId||null,file=d.mode==='file'?d.file:null;
 // Match the API's publish identity fields; preview state and revision checks are not content.
 const identity=Object.fromEntries(['name','desc','owner','platform','type','guide','environment','changes','org','orgId','category','categoryId'].map(key=>[key,String(d[key]??'').trim()]));
 identity.approval=!!d.approval;identity.workflow=d.workflow||null;identity.installProfile=d.installProfile||null;
 identity.workTags=[...new Set((Array.isArray(d.workTags)?d.workTags:String(d.workTags||'').split(/[,，\n]/)).map(tag=>tag.trim().replace(/\s+/g,' ')).filter(Boolean))];
 identity.mode=d.mode;identity.url=d.mode==='url'?String(d.url||'').trim():'';
 identity.commands=d.mode==='command'?{project:String(d.commandProject||'').trim(),user:String(d.commandUser||'').trim()}:{};
 const canonical=value=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])])):value;
 const signature=JSON.stringify(canonical(identity));
 let attempt=runtime.publishAttempt;
 if(!attempt||attempt.signature!==signature||attempt.target!==target||attempt.file!==file){
  const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const hex=[...bytes].map(b=>b.toString(16).padStart(2,'0')).join('');
  attempt=runtime.publishAttempt={signature,target,file,id:`${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`};
 }
 const progress=typeof $==='function'?$('#sq-register-error'):null;
 const validResult=value=>Number.isInteger(value?.id)&&value.id>0&&Number.isInteger(value?.version)&&value.version>0&&(!target||value.id===target);
 const recover=async()=>{
  if(progress){progress.textContent='연결이 끊겨 서버의 게시 결과를 확인하고 있습니다…';progress.setAttribute('role','status');progress.setAttribute('aria-live','polite');}
  // Check only: the first POST may still be committing. Never repeat an upload automatically.
  for(let check=0;check<3;check++){
   if(check)await new Promise(resolve=>setTimeout(resolve,check*750));
   let receipt;
   try{receipt=await requestAPI(`/api/publish-requests/${attempt.id}`,'GET',undefined,{timeoutMs:4000,redirectOnAuth:false});}
   catch(error){if(error.uncertain&&check<2)continue;throw error;}
   if(receipt.status==='confirmed'&&validResult(receipt))return receipt;
   if(receipt.status!=='unconfirmed')throw Error('게시 결과를 확인하지 못했습니다.');
  }
  return null;
 };
 const unresolved=cause=>{
  const message=cause?.status===401?'로그인이 만료되어 게시 결과를 확인하지 못했습니다. 다시 로그인한 뒤 등록 관리에서 확인해 주세요.':`게시 완료 여부를 아직 확인하지 못했습니다. 입력한 내용과 파일은 유지했습니다. 잠시 후 다시 게시를 누르면 같은 요청 번호로 확인합니다. [요청 번호: ${attempt.id}]`;
  const error=Error(message);error.uncertain=true;return error;
 };
 let result;
 if(attempt.uncertain){try{result=await recover();}catch(error){throw unresolved(error);}}
 if(!result){
  const form=new FormData();form.append('metadata',JSON.stringify({...JSON.parse(metadata),clientRequestId:attempt.id}));if(file)form.append('artifact',file);
  try{result=await requestAPI(target?`/api/tools/${target}/versions`:'/api/tools','POST',form);if(!validResult(result)){const error=Error('게시 응답 형식을 확인하지 못했습니다.');error.uncertain=true;throw error;}}
  catch(error){
   if(!error.uncertain)throw error;
   attempt.uncertain=true;
   try{result=await recover();}catch(recoveryError){throw unresolved(recoveryError);}
   if(!result)throw unresolved(error);
  }
 }
 runtime.newId=result.id;runtime.draft=null;runtime.publishAttempt=null;
 let refreshNotice='';try{await refresh();}catch{refreshNotice='게시가 완료되었습니다. 목록을 갱신하지 못했으므로 새로고침 후 확인해 주세요.';}
 openModal('공유할 준비가 되었습니다.','게시 완료',`<div class="sq-success"><span class="sq-feature-icon">${icon('check')}</span><h3>${esc(getItem(result.id)?.name||d.name)}</h3><p>v${result.version}을 서버에 저장했습니다.<br>설치·연결 안내와 공개 범위를 확인해 주세요.</p>${refreshNotice?`<p role="status">${refreshNotice}</p>`:''}${result.pending?'<p role="status">게시가 완료되었습니다. 이력·알림은 다음 조회 시 동기화됩니다.</p>':''}${result.packageWarning?`<div class="ws-package"><strong>파일은 게시되었습니다. 배포 정보는 읽지 못했습니다.</strong><p>${esc(result.packageWarning)}</p><p>직접 입력한 등록 정보로 제공됩니다.</p></div>`:''}${result.deploymentUrl?`<div class="ws-package"><strong>도구 ID ${result.id} · 배포 v${result.version}</strong><p>배포 정보에 원본 파일·버전 확인 주소를 연결했습니다.</p><a class="sq-link" href="${esc(result.deploymentUrl)}" download>배포 정보 JSON 받기</a></div>`:''}<div class="sq-actions" style="justify-content:center">${button('published-detail','상세 화면 보기','sq-primary')}${button('manage','등록 도구 관리')}</div></div>`);
 }finally{runtime.publishBusy=false;}
}
function versionManager(id){const x=getItem(id);runtime.detailId=x.id;const rows=x.versions.filter(v=>!v.deleted).map(v=>`<div class="sq-version"><div><strong>v${v.n}</strong> ${v.n===x.active?'<span class="sq-badge blue">현재 배포</span>':v.withdrawn?'<span class="sq-badge">배포 중단</span>':v.n===x.fallback?'<span class="sq-badge">복구용 보호</span>':''}<p>${esc(v.note)} · ${v.age}일 전 · ${v.size} MB</p></div><div class="sq-row-actions">${button('rollback','이 버전으로 복구','',`data-version="${v.n}" ${v.n===x.active||v.withdrawn?'disabled':''}`)}${button('delete-version','삭제','',`data-version="${v.n}" ${Core.canDelete(x,v)?'':'disabled'}`)}</div></div>`).join('');openModal('버전과 배포 관리',x.name,`<div class="sq-admin-head"><div><h3>현재 배포 v${x.active}</h3><p class="sq-note">배포 지시 번호 ${x.revision} · ${x.updatePaused?'업데이트 보류':'업데이트 정보 제공'}</p></div>${button('new-release','새 버전 등록','sq-primary',`data-id="${x.id}"`)}</div>${x.updatePaused?'<div class="sq-callout"><strong>이전 버전으로 복구했습니다.</strong> 문제가 있던 버전은 배포가 중단되었습니다. 사용자 PC 반영 여부는 연동 앱에서 별도로 확인해야 합니다.</div>':''}<div class="sq-version-list">${rows}</div><div class="sq-callout">현재 배포와 복구용 버전은 삭제할 수 없습니다. PC별 설치 현황은 아직 수집하지 않습니다. 파일을 지워도 배포 이력과 변경 기록은 남깁니다.</div><div class="sq-actions">${button('manage','관리 목록으로')}</div>`);}
function manage(tab='tools'){
 runtime.adminTab=tab;const tabs=[['tools','등록 도구'],['requests','권한 신청'],...(server.user.role==='admin'?[['orgs','조직 설정'],['storage','저장 공간'],['ideas','아이디어'],['activity','사용 이력']]:[])].map(([value,label])=>button('admin-tab',label,'',`data-tab="${value}" aria-pressed="${tab===value}"`)).join('');let content='';
 if(tab==='tools')content=`<div class="sq-admin-head"><div><h3>등록한 도구와 배포 상태</h3><p class="sq-note">수정 권한이 있는 도구만 표시됩니다.</p></div>${button('register','도구 등록','sq-primary')}</div><div class="sq-admin-list">${items.filter(x=>x.canManage).map(x=>`<div class="sq-admin-row"><div><strong>${esc(x.name)}</strong><p>${esc(x.org)} · ${esc(x.owner)} · v${x.active} · ${x.hidden?'목록에서 숨김':x.updatePaused?'복구 후 점검 중':'공개 중'}</p></div><div class="sq-row-actions">${button('edit-tool','정보 수정','',`data-id="${x.id}"`)}${button('manage-versions','버전 관리','',`data-id="${x.id}"`)}${button('toggle-hidden',x.hidden?'다시 공개':'공개 중단','',`data-id="${x.id}"`)}</div></div>`).join('')}</div>`;
 if(tab==='requests')content=`<div class="sq-admin-head"><h3>사용 권한 신청</h3><span class="sq-note">도구 담당자 승인 화면</span></div><div class="sq-admin-list">${requests.map(r=>`<div class="sq-admin-row"><div><strong>${esc(r.name)}</strong> <span class="sq-badge">${r.status}</span><p>${esc(r.who)}<br>${esc(r.reason)}</p></div>${r.status==='대기'?`<div class="sq-row-actions">${button('approve','승인','',`data-request="${r.id}"`)}${button('reject','반려','',`data-request="${r.id}"`)}</div>`:''}</div>`).join('')||'<p class="sq-note">접수된 신청이 없습니다.</p>'}</div><div class="sq-callout">승인은 도구 사용 범위에만 반영합니다. 데이터베이스나 문서 시스템의 권한을 자동으로 부여하지 않습니다.</div>`;
 if(tab==='orgs')content=`<div class="sq-admin-head"><div><h3>조직과 승인 담당자</h3><p class="sq-note">검색 필터와 도구 등록 시 선택하는 조직입니다.</p></div>${button('add-org','조직 추가','sq-primary')}</div><div class="sq-admin-list">${organizations.map((o,i)=>`<div class="sq-admin-row"><div><strong>${esc(o.name)}</strong><p>담당자 ${esc(o.owner)} · 등록 도구 ${items.filter(x=>x.org===o.name).length}개</p></div>${button('edit-org','수정','sq-link',`data-org-index="${i}"`)}</div>`).join('')}</div><div class="sq-callout">‘공통’은 여러 조직이 함께 쓰는 도구를 등록할 때 선택합니다. 사용자의 소속과 권한은 로그인 계정으로 확인합니다. 조직 담당자 이름은 안내용이며, 실제 승인은 도구 등록자 또는 운영자가 처리합니다.</div>`;
 if(tab==='storage'){const used=(server.storage?.used||0)/1048576,candidates=items.flatMap(x=>Core.retention(x,policy.keep,policy.days).map(v=>({item:x,v}))),size=candidates.reduce((n,c)=>n+c.v.size,0);content=`<div class="sq-storage-head"><div><h3>서버 저장 공간</h3><p class="sq-note">Flask 서버의 배포 파일 사용량 · DB와 로그 제외</p></div><div class="sq-storage-size">${(used/1024).toFixed(2)} <small>/ ${((server.storage?.quota||0)/1073741824).toFixed(1)} GB</small></div></div><div class="sq-storage-meter" role="meter" aria-label="서버 저장 공간 사용량" aria-valuemin="0" aria-valuemax="${(server.storage?.quota||1)/1048576}" aria-valuenow="${used}"><span style="width:${Math.min(100,used/((server.storage?.quota||1)/1048576)*100)}%"></span></div><p class="sq-note">현재 배포와 복구용 버전은 정리 대상에서 제외됩니다.</p><form id="sq-policy-form" style="margin-top:24px"><div class="sq-form-grid"><label class="sq-field"><span>도구별 최소 보관 버전</span><select name="keep">${[2,3,5].map(n=>`<option value="${n}" ${n===policy.keep?'selected':''}>최근 ${n}개</option>`).join('')}</select></label><label class="sq-field"><span>정리 대상으로 표시할 시점</span><select name="days">${[30,90,180].map(n=>`<option value="${n}" ${n===policy.days?'selected':''}>${n}일 지난 파일</option>`).join('')}</select></label></div><div class="sq-actions"><button class="sq-secondary cursor-interaction">보관 기준 적용</button></div></form><div class="sq-callout"><strong>${candidates.length}개 파일 · ${size} MB 정리 가능</strong><br>보관 기준을 적용해도 즉시 지우지 않습니다. 아래에서 대상 목록을 확인한 뒤 삭제합니다.</div>${button('cleanup-preview','정리 대상 확인','sq-primary','')}${audit.length?`<div class="sq-callout"><strong>최근 작업</strong><br>${audit.slice(0,4).map(esc).join('<br>')}</div>`:''}`;}
 if(tab==='ideas')content=server.ideas.map(i=>`<article class="sq-comment"><strong>${esc(i.name)}</strong><small>${esc(i.author)} · ${esc(i.category)}</small><p>${esc(i.body)}</p></article>`).join('')||'<p class="sq-note">접수된 아이디어가 없습니다.</p>';
 if(tab==='activity')content=activityPanel();
 openModal('운영 관리','관리자·등록자 화면',`<div class="sq-tabs" aria-label="관리 메뉴">${tabs}</div>${content}`);
}
function editTool(id){const x=getItem(id);runtime.detailId=x.id;openModal('등록 정보 수정',x.name,`<form id="sq-edit-tool-form"><div class="sq-form-grid"><label class="sq-field wide"><span>도구 이름</span><input name="name" value="${esc(x.name)}" required maxlength="50"></label><label class="sq-field wide"><span>설명</span><textarea name="desc" required>${esc(x.desc)}</textarea></label>${workTagField((x.workTags||[]).join(', '))}<label class="sq-field"><span>등록 조직</span><select name="org">${options(organizations.filter(o=>server.user.role==='admin'||o.name==='공통'||o.name===server.user.org).map(o=>o.name),x.org)}</select></label><label class="sq-field"><span>담당자</span><input name="owner" value="${esc(x.owner)}" required></label><label class="sq-field"><span>공개 범위</span><select name="visibility">${options(['전체 공개','선택 조직'],x.visibility)}</select></label><label class="sq-field"><span>사용 승인</span><select name="approval"><option value="false" ${!x.approval?'selected':''}>승인 없이 사용 안내</option><option value="true" ${x.approval?'selected':''}>담당자 승인 필요</option></select></label><div class="sq-field wide"><span>선택 조직 공개 대상</span><div class="sq-choice-row">${organizations.map(o=>`<label><input type="checkbox" name="audience" value="${esc(o.name)}" ${(x.audience||[x.org]).includes(o.name)?'checked':''}>${esc(o.name)}</label>`).join('')}</div><small>공개 범위가 ‘선택 조직’일 때 적용됩니다.</small></div></div><p class="sq-error" id="sq-edit-error" role="alert"></p><div class="sq-actions">${button('manage','취소')}<button class="sq-primary cursor-interaction">변경 저장</button></div></form>`);}
function editOrg(index){runtime.orgIndex=index;const o=organizations[index];openModal(o?'조직 설정 수정':'조직 추가','조직 이름과 승인 담당자',`<form id="sq-org-form"><div class="sq-form-grid"><label class="sq-field"><span>조직 이름</span><input name="name" value="${esc(o?.name||'')}" required maxlength="30" ${o?.name==='공통'?'readonly':''}></label><label class="sq-field"><span>승인 담당자</span><input name="owner" value="${esc(o?.owner||'')}" required></label></div><p class="sq-error" id="sq-org-error" role="alert"></p><div class="sq-actions">${button('admin-tab','취소','sq-secondary','data-tab="orgs"')}<button class="sq-primary cursor-interaction">저장</button></div></form>`);}
function cleanupPreview(){const candidates=items.flatMap(x=>Core.retention(x,policy.keep,policy.days).map(v=>({item:x,v})));runtime.cleanup=candidates;openModal('이전 버전 정리','삭제하기 전 대상 확인',`<div class="sq-callout"><strong>${candidates.length}개 파일 · ${candidates.reduce((n,c)=>n+c.v.size,0)} MB</strong><br>현재 배포·복구용 파일을 제외한 목록입니다. 삭제 후에는 해당 파일을 내려받거나 복구할 수 없습니다.</div><div class="sq-version-list">${candidates.map(c=>`<div class="sq-version"><div><strong>${esc(c.item.name)} · v${c.v.n}</strong><p>${c.v.age}일 전 · ${c.v.size} MB</p></div><span class="sq-badge">정리 가능</span></div>`).join('')}</div><div class="sq-actions">${button('admin-tab','돌아가기','sq-secondary','data-tab="storage"')}${button('cleanup-confirm','이 파일들 삭제','sq-primary',candidates.length?'':'disabled')}</div>`);}
function creatorGuide(){openModal('공유를 준비하는 가장 쉬운 방법','등록 가이드',`<ol class="sq-steps-list"><li><strong>누가, 어떤 프로그램에서 쓸지 정하세요.</strong><p>Claude · ChatGPT · 기타 중 하나를 선택하고 사용 환경을 적습니다. 관련 업무에는 ‘불량 분석, 수율 검토’처럼 동료가 검색할 말을 쉼표로 구분해 입력하세요.</p></li><li><strong>지침과 코드를 한 묶음으로 준비하세요.</strong><p>단일 Skill은 MD 그대로, 보조 코드가 있으면 ZIP으로 준비하세요. MCP는 URL이나 터미널 명령어로도 등록할 수 있습니다.</p></li><li><strong>파일에 맞는 배포 방식을 선택하세요.</strong><p>ZIP은 패키지, EXE·MSI는 기존 설치 프로그램, PS1은 설치 스크립트로 받습니다. 자동 설치를 지원하려면 실행·버전 확인·제거 규칙을 추가로 검증합니다.</p></li><li><strong>동료가 따라 할 설치 방법을 적으세요.</strong><p>필요한 계정, 실행할 파일, 설치 위치와 간단한 확인 예시를 적습니다. 버전 번호는 웹에서 발급합니다.</p></li></ol><div class="sq-callout"><strong>제작 도우미에 줄 요청 예시</strong><br>“이 도구를 사내 공유용으로 정리해줘. 지침, 실행 코드, 필요한 라이브러리, 설치·제거 방법, 사용 예시를 포함하고 내 개인 경로나 비밀키는 제외해줘.”</div><div class="sq-actions">${runtime.draft?button('resume-draft','작성 중인 등록으로 돌아가기','sq-primary'):button('register','도구 등록 시작','sq-primary')}</div>`);}
function downloadResource(kind){const asset=window.PT_GUIDE_ASSETS?.[kind];if(!asset){announce('다운로드 자료는 브라우저용 전체화면 HTML에 포함되어 있습니다. 해당 파일에서 다시 눌러주세요.');return;}const bytes=Uint8Array.from(atob(asset.base64),c=>c.charCodeAt(0));const url=URL.createObjectURL(new Blob([bytes],{type:asset.mime}));const a=document.createElement('a');a.href=url;a.download=asset.name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);announce(`${asset.name} 다운로드를 시작했습니다. 브라우저의 다운로드 목록에서 확인하세요.`);}
function resourceGuide(){openModal('공유 준비를 더 쉽게.','P&T AI SQUARE · 등록자 도우미',`<div class="sq-detail-hero"><h3>AI와 함께 파일을 정리하고,<br>가이드를 보며 등록하세요.</h3><p>파일 배포 Skill은 코드와 설치 안내에 ai-square.json 배포 정보를 더합니다. 웹이 이 정보를 읽고 필수 파일을 검사합니다.</p></div><div class="sq-two-col"><section><span class="sq-badge blue">AI로 준비하기</span><h3 style="margin:12px 0">파일 배포 Skill</h3><p class="sq-note">SKILL.md · 배포 정보 양식 · ZIP/MD 준비 스크립트 · 설치 범위 선택 템플릿을 제공합니다. 기존 코드와 지침을 함께 정리할 때 사용하세요.</p><div class="sq-actions" style="justify-content:flex-start">${button('download-skill',icon('download')+' Skill ZIP 다운로드','sq-primary')}</div></section><section><span class="sq-badge">직접 따라 하기</span><h3 style="margin:12px 0">등록 가이드</h3><p class="sq-note">파일 형식 선택부터 기본 정보, 사용 권한, 새 버전 등록까지 버튼과 실제 예시로 설명합니다. 브라우저에서 바로 읽는 HTML입니다.</p><div class="sq-actions" style="justify-content:flex-start">${button('download-guide',icon('download')+' 가이드 다운로드','sq-secondary')}</div></section></div><ol class="sq-steps-list"><li><strong>Skill ZIP을 받고 압축을 풉니다.</strong><p>Skill을 지원하는 도구에 폴더를 추가하거나 SKILL.md 내용을 작업 지침으로 제공하세요.</p></li><li><strong>공유할 프로젝트에서 준비를 요청합니다.</strong><p>“이 프로젝트를 P&T AI SQUARE에 등록할 수 있도록 파일, 설치·제거 안내, 등록 설명을 준비해줘.”</p></li><li><strong>결과를 확인한 뒤 도구 등록을 누릅니다.</strong><p>ZIP은 배포 정보를 불러오고, MD·URL·명령어는 직접 입력합니다. 읽기 실패도 수동 등록이 가능합니다. 설치 범위를 구분하고 조직·담당자·권한을 선택하세요.</p></li></ol><div class="sq-callout">Skill은 설치 프로그램이 아닌 AI 작업 지침입니다. 실제 게시·PC 설치·권한 변경은 자동으로 실행하지 않습니다. 배포 자료는 초안이며, 사용 중인 프로그램의 호환성과 사내 규칙을 확인해야 합니다.</div><div class="sq-actions">${runtime.draft?button('resume-draft','작성 중인 등록으로 돌아가기','sq-primary'):button('register','도구 등록 시작','sq-primary')}</div>`);}
const actions={
 home:()=>{state.query='';navigate('home');},
 browse:()=>{state.query='';state.type='전체';state.category='모든 업무';navigate('browse','discovery');},
 'browse-downloads':()=>{state.query='';state.type='전체';state.category='모든 업무';navigate('browse','downloads');},
 'browse-recent':()=>{state.query='';state.type='전체';state.category='모든 업무';navigate('browse','recent');},
 'clear-filters':()=>{Object.assign(state,{query:'',platform:'전체',homeType:'전체',org:'전체 조직',type:'전체',category:'모든 업무',page:0});render();persist();},
 'catalog-prev':()=>{state.page--;renderCatalog();mountIcons();},
 'catalog-next':()=>{state.page++;renderCatalog();mountIcons();},
 detail:b=>detail(b.dataset.id||runtime.detailId),
 'detail-tab':b=>detail(runtime.detailId,b.dataset.tab),
 like:b=>{
  const id=+b.dataset.id,x=getItem(id);state.liked.has(id)?state.liked.delete(id):state.liked.add(id);
  const liked=state.liked.has(id);
  $$(`[data-action="like"][data-id="${id}"]`).forEach(control=>{control.setAttribute('aria-pressed',String(liked));const count=control.querySelector('[data-like-count]')||(control.classList.contains('sq-like')?control.querySelector('span'):null);if(count)count.textContent=num(x.likes+(liked?1:0));const label=control.querySelector('[data-like-label]');if(label)label.textContent=liked?'좋아요 취소':'좋아요';});
  if($('#sq-dialog').open&&runtime.detailId===id){const summary=$('.sq-detail-id p');if(summary)summary.textContent=`다운로드 ${num(x.downloads)} · 좋아요 ${num(x.likes+(liked?1:0))}`;}
  const heart=b.querySelector('svg');if(liked&&!motion.matches&&heart?.animate)heart.animate([{transform:'scale(1)'},{transform:'scale(1.3)',offset:.4},{transform:'scale(1)'}],{duration:330,easing:'cubic-bezier(.2,.7,.2,1)'});
  announce(liked?'좋아요를 추가했습니다.':'좋아요를 취소했습니다.');persist();
 },
 'rank-page':b=>changeRank(+b.dataset.page),
 'rank-mode':b=>{if(b.dataset.mode===state.rankMode)return;state.rankMode=b.dataset.mode;state.rankPage=0;render();},
 autoplay:()=>{state.auto=!state.auto;schedule();},
 'rank-info':()=>openModal('좋아요 2점, 다운로드 1점.','인기 TOP 10 집계 기준',`<div class="sq-detail-hero"><h3>최근의 관심과 꾸준한 인기를<br>나누어 살펴보세요.</h3><p><strong>실시간</strong>은 집계 시각부터 최근 7일, <strong>누적</strong>은 전체 기간을 기준으로 합니다. 두 순위 모두 좋아요 × 2 + 다운로드 × 1로 계산합니다.</p></div><div class="sq-callout">좋아요는 한 사람·한 도구당 한 번 반영하며, 취소하면 점수가 빠집니다. 다시 눌러도 최초 좋아요 날짜가 유지되어 최근 점수를 반복해서 올릴 수 없습니다.<br><br>다운로드는 같은 사용자·도구의 전체 기간 최초 수신만 1점입니다. 반복 수신과 업데이트는 추가 점수가 없으며, 실시간 순위는 최초 수신일이 최근 7일인 경우만 반영합니다. URL 클릭은 다운로드 점수에 포함하지 않습니다.<br><br>동점이면 해당 기간의 다운로드 수 → 좋아요 수 → 최근 도구 등록일 순입니다. 순위 행에 표시되는 좋아요·다운로드 수도 선택한 기간 기준입니다.</div><p class="sq-note">접속·새로고침·좋아요·다운로드 후 재집계합니다. 5초마다 1–5위와 6–10위를 뒤집어 보여주며, 페이지 전환 자체는 재집계가 아닙니다. 다운로드 수는 서버 응답 기준이며 설치 완료 수가 아닙니다.</p>${button('rank-refresh','집계 새로고침','sq-primary')}`),
 'rank-refresh':()=>{state.snapshot++;render();closeModal();announce('다음 가상 집계를 반영했습니다. 화면 페이지 전환과 순위 재집계는 별개입니다.');},
 'close-dialog':closeModal,
 'cancel-confirm':()=>{$('#sq-confirm').close();runtime.confirm=null;},
 confirm:()=>{const callback=runtime.confirm;runtime.confirm=null;$('#sq-confirm').close();return callback?.();},
 register:()=>register(),
 'new-release':b=>register(b.dataset.id||runtime.detailId),
 'resume-draft':wizard,
 'wizard-back':()=>{captureDraft();runtime.step=Math.max(1,runtime.step-1);wizard();},
 publish,
 'published-detail':()=>detail(runtime.newId),
 'creator-guide':()=>{captureDraft();resourceGuide();},
 'distribution-skill':()=>{captureDraft();resourceGuide();},
 'download-skill':()=>downloadResource('skill'),
 'download-guide':()=>downloadResource('guide'),
 'request-access':requestAccess,
 'version-download':b=>{const x=getItem(runtime.detailId),v=x.versions.find(v=>v.n===+b.dataset.version);if(!v||v.deleted||v.withdrawn)return;if(x.approval&&x.access!=='approved'){requestAccess();return;}announce(`${x.name} v${v.n} 다운로드를 선택했습니다. 이 시안에서는 파일을 받지 않습니다.`);},
 'connection-check':()=>announce('연결 확인 결과 예시: 계정 인증 및 테스트 요청을 확인했습니다. 실제 서비스에는 연결하지 않았습니다.'),
 manage:()=>manage(),
 'admin-tab':b=>manage(b.dataset.tab),
 'manage-versions':b=>versionManager(b.dataset.id||runtime.detailId),
 'edit-tool':b=>editTool(b.dataset.id),
 'toggle-hidden':b=>{const x=getItem(b.dataset.id);ask(x.hidden?'도구를 다시 공개할까요?':'도구 공개를 중단할까요?',`${x.name}\n${x.hidden?'검색과 홈 목록에 다시 표시됩니다.':'목록에서 숨기지만 배포 파일과 기록은 유지합니다. 이미 설치한 PC에서 자동으로 제거하지 않습니다.'}`,()=>{x.hidden=!x.hidden;audit.unshift(`${x.name} ${x.hidden?'공개 중단':'공개 재개'}`);render();manage();},x.hidden?'다시 공개':'공개 중단');},
 rollback:b=>{const x=getItem(runtime.detailId),n=+b.dataset.version;ask(`v${n}으로 되돌릴까요?`,`${x.name}\n현재 v${x.active} 대신 v${n}을 배포합니다. 문제가 있던 현재 버전은 배포를 중단하고 자동 업데이트를 보류합니다.\n이미 설치된 PC는 연동 앱의 복구 지원 여부에 따라 별도로 처리합니다.`,()=>{const old=Core.rollback(x,n);audit.unshift(`${x.name} v${old} → v${n} 복구`);render();versionManager(x.id);},'이 버전으로 복구');},
 'delete-version':b=>{const x=getItem(runtime.detailId),v=x.versions.find(v=>v.n===+b.dataset.version);if(!v||!Core.canDelete(x,v))return;ask(`v${v.n} 파일을 삭제할까요?`,`${x.name} · ${v.size} MB\n파일을 삭제하면 이 버전으로 복구하거나 내려받을 수 없습니다. 변경 이력은 유지합니다.`,()=>{if(!Core.canDelete(x,v))return;v.deleted=true;audit.unshift(`${x.name} v${v.n} 파일 삭제`);versionManager(x.id);},'파일 삭제');},
 approve:b=>{const r=requests.find(r=>r.id===+b.dataset.request);ask('사용 신청을 승인할까요?',`${r.who}\n${r.name}\n도구 사용 권한만 승인하며 원본 데이터 권한은 변경하지 않습니다.`,()=>{r.status='승인';getItem(r.itemId).access='approved';manage('requests');},'승인');},
 reject:b=>{const r=requests.find(r=>r.id===+b.dataset.request);openModal('사용 신청 반려',r.name,`<form id="sq-reject-form" data-request="${r.id}"><label class="sq-field"><span>반려 사유</span><textarea name="reason" required placeholder="신청자가 보완할 내용을 적어주세요."></textarea></label><div class="sq-actions">${button('admin-tab','취소','sq-secondary','data-tab="requests"')}<button class="sq-primary cursor-interaction">사유를 남기고 반려</button></div></form>`);},
 'add-org':()=>editOrg(-1),
 'edit-org':b=>editOrg(+b.dataset.orgIndex),
 'cleanup-preview':cleanupPreview,
 'cleanup-confirm':()=>ask('이전 버전 파일을 정리할까요?',`${runtime.cleanup.length}개 파일을 삭제합니다. 배포 이력은 유지하지만 삭제한 파일은 복구할 수 없습니다.\n현재 배포와 복구용 파일은 보존합니다.`,()=>{let count=0;for(const c of runtime.cleanup)if(Core.retention(c.item,policy.keep,policy.days).includes(c.v)){c.v.deleted=true;count++;}audit.unshift(`보관 기준에 따라 ${count}개 이전 파일 정리`);manage('storage');},'선택 파일 삭제'),
 idea:()=>openModal('이런 도구가 있으면 좋겠어요.','개발 아이디어 제안',`<form id="sq-idea-form"><div class="sq-form-grid"><label class="sq-field wide"><span>아이디어 제목</span><input name="name" required placeholder="예: 여러 장비의 점검 이력을 한 번에 비교하고 싶어요."></label><label class="sq-field wide"><span>현재 불편한 점과 원하는 결과</span><textarea name="desc" required></textarea></label><label class="sq-field"><span>관련 업무</span><select name="category">${options(['공통 업무','제조','장비','기술'],'공통 업무')}</select></label></div><div class="sq-actions"><button class="sq-primary cursor-interaction">제안 등록</button></div></form>`)
};
const server={csrf:'',user:{},rankAsOf:0,storage:null,ideas:[]};
function showError(error,target){
 const message=error?.message||'처리 중 오류가 발생했습니다.',body=$('#sq-dialog')?.open?$('#sq-dialog-body'):null;
 if(!target?.isConnected)target=body?.querySelector('#sq-register-error,#sq-edit-error,#sq-org-error')||(!body?$('#ws-capacity-message'):null);
 if(!target&&body){target=$('#ws-dialog-error');if(!target){target=document.createElement('p');target.id='ws-dialog-error';target.className='sq-error';body.prepend(target);}}
 if(!target){target=$('#sq-server-error');if(!target){target=document.createElement('p');target.id='sq-server-error';target.className='sq-server-error';$('.sq-shell').prepend(target);}}
 // The alert is also the accessible announcement; announce() would add a second blue message.
 $$('#sq-server-error,#ws-dialog-error,#sq-register-error,#sq-edit-error,#sq-org-error,#ws-capacity-message,#sq-status,#sq-modal-status').forEach(node=>{if(node!==target){node.textContent='';if(node.id==='sq-server-error')node.hidden=true;}});
 target.hidden=false;target.setAttribute('role','alert');target.setAttribute('aria-live','assertive');target.textContent=message;
 if(body)target.scrollIntoView?.({block:'nearest'});
}
async function requestAPI(url,method='GET',body,options={}){
 runtime.requestBusy=(runtime.requestBusy||0)+1;
 const controller=options.timeoutMs?new AbortController():null;
 const timer=controller?setTimeout(()=>controller.abort(),options.timeoutMs):null;
 try{const headers={'X-CSRF-Token':server.csrf};if(body&&!(body instanceof FormData))headers['Content-Type']='application/json';
 let response;
 try{response=await fetch(url,{method,credentials:'same-origin',headers,body:body instanceof FormData?body:body?JSON.stringify(body):undefined,...(controller?{signal:controller.signal}:{})});}
 catch(cause){if(!['TypeError','AbortError'].includes(cause?.name))throw cause;const error=Error('서버 응답을 받지 못했습니다. 연결 상태를 확인해 주세요.');error.code='NETWORK_ERROR';error.uncertain=true;throw error;}
 let result;
 try{result=await response.json();}
 catch{const error=Error(response.status===413?'파일 크기가 서버의 업로드 한도를 초과했습니다.':'서버 응답을 확인하지 못했습니다. 저장 결과를 확인해 주세요.');error.status=response.status;error.code='INVALID_RESPONSE';error.uncertain=response.ok||response.status>=500;throw error;}
 if(!response.ok){if(response.status===401&&options.redirectOnAuth!==false)location.assign(result?.login||'/login');const error=Error(result?.error||'요청을 처리하지 못했습니다.');error.status=response.status;error.uncertain=response.status>=500;throw error;}
 if(!result||typeof result!=='object'||Array.isArray(result)){const error=Error('서버 응답 형식을 확인하지 못했습니다.');error.code='INVALID_RESPONSE';error.uncertain=true;throw error;}
 return result;
 }finally{if(timer!==null)clearTimeout(timer);runtime.requestBusy--;}
}
async function refresh(){
 const token=runtime.refreshToken=(runtime.refreshToken||0)+1;let data;
 try{data=await requestAPI('/api/bootstrap');}catch(error){if(token!==runtime.refreshToken)return false;throw error;}
 // Every caller shares this generation; a slower earlier request cannot overwrite newer data.
 if(token!==runtime.refreshToken)return false;
 Object.assign(server,data);items.splice(0,items.length,...data.items.map(x=>({...x,likes:x.likes-(x.liked?1:0)})));state.liked=new Set(data.items.filter(x=>x.liked).map(x=>x.id));
 if($('#sq-server-error'))$('#sq-server-error').hidden=true;
 organizations.splice(0,organizations.length,...data.organizations);requests.splice(0,requests.length,...data.requests);Object.assign(policy,data.policy);audit.splice(0,audit.length,...data.audit);
 $('#sq-session').textContent=data.user.name+' · '+data.user.org;$('.sq-demo').textContent=data.dataMode==='dummy'?'샘플 데이터 · 조회 전용':data.authMode==='mock'?'SSO 미사용':'SSO 사용';
 $('[data-action=logout]').hidden=data.authMode==='mock';render();return true;
}
async function mutate(url,method,body,after){
 await requestAPI(url,method,body);
 try{await refresh();return await after?.();}
 catch(error){throw Error(`변경 내용은 저장되었습니다. 화면을 갱신하지 못했습니다. ${error.message}`);}
}
async function downloadVersion(id,n){
 if(server.dataMode==='dummy')throw Error('샘플 데이터는 조회 전용입니다. 실제 데이터 모드에서 다운로드해 주세요.');
 const x=getItem(id);if(x.approval&&x.access!=='approved'){requestAccess();return;}
 const v=x.versions.find(v=>v.n===n);if(v?.deleted||v?.withdrawn)throw Error('배포가 중단된 버전입니다.');if(v?.commands&&Object.values(v.commands).some(Boolean)){openModal(`v${n} 명령어 설치`,x.name,commandScopePanel(x,v));return;}if(!v?.filename){if(v?.url)openModal(`v${n} 연결 안내`,x.name,`<div class="sq-callout"><a href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">${esc(v.url)}</a></div><p class="sq-note">이 버전에 저장된 연결 주소입니다. 원격 서버 프로그램의 버전을 되돌리는 기능은 아닙니다.</p>`);else detail(id,'connect');return;}
 // HEAD checks access without counting an event; browser streams the GET to disk.
 const check=await fetch(`/download/${id}/${n}`,{method:'HEAD'});if(!check.ok)throw Error('파일을 받을 수 없습니다. 권한 또는 배포 상태를 확인해 주세요.');
 const a=document.createElement('a');a.href=`/download/${id}/${n}`;a.download=v.filename;document.body.append(a);a.click();a.remove();setTimeout(()=>refresh().catch(showError),1500);
}
function setLikeBusy(id,busy){$$(`[data-action="like"][data-id="${id}"]`).forEach(control=>{control.disabled=busy;if(busy)control.setAttribute('aria-busy','true');else control.removeAttribute('aria-busy');});}
function applyLikeResult(id,liked,count){
 const x=getItem(id);if(x)x.likes=count-(liked?1:0);liked?state.liked.add(id):state.liked.delete(id);
 $$(`[data-action="like"][data-id="${id}"]`).forEach(control=>{control.setAttribute('aria-pressed',String(liked));const counter=control.querySelector('[data-like-count]')||(control.classList.contains('sq-like')?control.querySelector('span'):null);if(counter)counter.textContent=num(count);const label=control.querySelector('[data-like-label]');if(label)label.textContent=liked?'좋아요 취소':'좋아요';});
 if(x&&$('#sq-dialog').open&&runtime.detailId===id){const summary=$('.sq-detail-id p');if(summary)summary.textContent=`다운로드 ${num(x.downloads)} · 좋아요 ${num(count)}`;}
}
// Catalog/rank rendering or opening a detail can create another control during the request.
new MutationObserver(()=>{runtime.likeRequests?.forEach((_,id)=>setLikeBusy(id,true));}).observe(root,{childList:true,subtree:true});
actions.like=b=>{
 const id=+b.dataset.id,pending=runtime.likeRequests||(runtime.likeRequests=new Map());
 if(pending.has(id))return pending.get(id).promise;
 const operation={},previousLiked=state.liked.has(id),liked=!previousLiked;
 const previousBase=Number(getItem(id)?.likes);
 const previousCount=Math.max(previousLiked?1:0,(Number.isFinite(previousBase)?Math.floor(previousBase):0)+(previousLiked?1:0));
 pending.set(id,operation);setLikeBusy(id,true);
 operation.promise=(async()=>{
 const result=await requestAPI(`/api/tools/${id}/like`,'PUT',{liked}),savedLiked=result.liked??liked;
 // A confirmed state write can succeed even when the separate count query is unavailable.
 const savedCount=Math.max(savedLiked?1:0,Number.isFinite(result.count)?Math.floor(result.count):previousCount+(savedLiked?1:0)-(previousLiked?1:0));
 applyLikeResult(id,savedLiked,savedCount);
 const heart=b.querySelector('svg');if(savedLiked&&!motion.matches&&heart?.animate)heart.animate([{transform:'scale(1)'},{transform:'scale(1.3)'},{transform:'scale(1)'}],{duration:330});
 // Keep concurrent cards independent, but do not apply older bootstrap responses last.
 runtime.likeRefresh=(runtime.likeRefresh||Promise.resolve()).catch(()=>{}).then(()=>refresh());
 try{await runtime.likeRefresh;}catch(error){applyLikeResult(id,savedLiked,savedCount);showError({message:`좋아요 ${savedLiked?'추가':'취소'}는 저장되었습니다. 목록·순위를 새로고침하지 못했습니다. ${error.message}`});return;}
 const historyPending=result.historyPending??(result.countsPending==null&&result.pending);
 announce(historyPending&&result.countsPending?'좋아요는 저장되었습니다. 이력·집계는 다음 조회 시 다시 확인합니다.':historyPending?'좋아요는 저장되었습니다. 이력은 다음 조회 시 동기화됩니다.':result.countsPending?'좋아요는 저장되었습니다. 집계는 목록 조회 시 다시 확인합니다.':savedLiked?'좋아요를 추가하고 순위를 갱신했습니다.':'좋아요를 취소하고 순위를 갱신했습니다.');
 })().finally(()=>{pending.delete(id);setLikeBusy(id,false);});
 return operation.promise;
};
actions['published-detail']=async()=>{
 const id=runtime.newId,token=invalidateDetailLoad();
 const viewError=error=>Error(`게시한 도구는 저장되어 있습니다. 상세 화면을 불러오지 못했습니다. ${error.message}`);
 // Only guard the bootstrap recovery; detail() starts and owns its own load token.
 try{if(!getItem(id))await refresh();}
 catch(error){if(token!==runtime.detailLoadToken)return false;throw viewError(error);}
 if(token!==runtime.detailLoadToken)return false;
 try{
  if(!getItem(id))throw Error('목록에서 게시한 도구를 찾지 못했습니다.');
  return await detail(id);
 }catch(error){throw viewError(error);}
};
actions['rank-refresh']=async()=>{await refresh();closeModal();announce('서버 집계 기준으로 갱신했습니다.');};
actions['download-file']=()=>downloadVersion(runtime.detailId,getItem(runtime.detailId).active);
actions['version-download']=b=>downloadVersion(runtime.detailId,+b.dataset.version);
actions['connection-check']=()=>detail(runtime.detailId,'connect');
actions['toggle-hidden']=b=>{const x=getItem(b.dataset.id);ask(x.hidden?'다시 공개할까요?':'공개를 중단할까요?',x.name+' · 설치된 PC의 파일은 변경하지 않습니다.',()=>mutate(`/api/tools/${x.id}`,'PATCH',{hidden:!x.hidden,expectedRevision:x.revision},()=>manage()));};
actions.rollback=b=>{const x=getItem(runtime.detailId),n=+b.dataset.version;ask(`v${n}으로 복구할까요?`,`${x.name}의 현재 배포를 중단하고 선택한 버전을 배포합니다. PC 자동 복구는 아직 지원하지 않습니다.`,()=>mutate(`/api/tools/${x.id}/rollback`,'POST',{version:n,expectedRevision:x.revision},()=>versionManager(x.id)),'이 버전으로 복구');};
actions['delete-version']=b=>{const x=getItem(runtime.detailId),n=+b.dataset.version;ask(`v${n} 파일을 삭제할까요?`,'파일 삭제는 되돌릴 수 없습니다. 배포 이력은 보존합니다.',()=>mutate(`/api/tools/${x.id}/versions/${n}`,'DELETE',null,()=>versionManager(x.id)),'파일 삭제');};
actions.approve=b=>ask('사용 신청을 승인할까요?','도구 사용만 승인합니다. 원본 데이터 권한은 별도입니다.',()=>mutate(`/api/requests/${b.dataset.request}/decision`,'POST',{status:'승인',reason:''},()=>manage('requests')),'승인');
actions['cleanup-preview']=async()=>{const data=await requestAPI('/api/storage/candidates');runtime.cleanupServer=data.candidates;openModal('이전 버전 정리','삭제 전 대상 확인',`<div class="sq-callout">현재 배포·복구용 버전은 보호됩니다. 아래 파일은 삭제 후 복구할 수 없습니다.</div><div class="sq-version-list">${data.candidates.map(c=>`<div class="sq-version"><strong>${esc(getItem(c.tool).name)} · v${c.version}</strong><span>${(c.bytes/1048576).toFixed(2)} MB</span></div>`).join('')||'<p>새 정리 대상이 없습니다. 삭제 대기 파일이 있으면 아래 버튼으로 재시도할 수 있습니다.</p>'}</div><div class="sq-actions">${button('admin-tab','돌아가기','sq-secondary','data-tab="storage"')}${button('cleanup-confirm','선택 파일 삭제','sq-primary',data.candidates.length||server.storage?.pending?'':'disabled')}</div>`);};
actions['cleanup-confirm']=()=>ask('선택한 이전 파일을 삭제할까요?',`${runtime.cleanupServer.length}개 파일을 정리합니다.`,async()=>{const r=await requestAPI('/api/storage/cleanup','POST',{candidates:runtime.cleanupServer});await refresh();manage('storage');announce(r.pending?'일부 파일은 사용 중이어서 삭제 대기 중입니다. 다시 정리하면 재시도합니다.':'파일 정리를 완료했습니다.');},'삭제');
actions['admin-tab']=async b=>{if(b.dataset.tab==='ideas')server.ideas=(await requestAPI('/api/ideas')).ideas;if(b.dataset.tab==='activity'){const r=await requestAPI('/api/activity');server.activityEvents=r.events;server.activityCursor=r.nextCursor;}manage(b.dataset.tab);};
actions['download-skill']=()=>location.assign('/static/guides/PT_AI_SQUARE_파일배포_Skill.zip');
actions['download-guide']=()=>{const a=document.createElement('a');a.href='/static/guides/PT_AI_SQUARE_등록가이드.html';a.download='PT_AI_SQUARE_등록가이드.html';a.click();};
actions.fullscreen=async()=>{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();};
actions.logout=()=>ask('로그아웃할까요?',server.authMode==='sso'?'웹 세션을 종료합니다. 회사 SSO 세션이 남아 있으면 다시 접속할 때 자동 인증됩니다.':'현재 웹 로그인 세션을 종료합니다.',async()=>{await requestAPI('/api/logout','POST',{});location.assign('/login');},'로그아웃');
function activityPanel(){
 const labels={like:'좋아요',unlike:'좋아요 취소',download:'다운로드'};
 return `<div class="sq-callout">MongoDB에 저장된 실제 이력입니다. 반복 다운로드도 기록하며, 순위에는 사용자·도구별 전체 기간 최초 한 번만 반영하며 업데이트는 제외합니다. 이전 자료는 남아 있던 집계 정보만 이전했습니다.</div><div class="sq-activity-list">${(server.activityEvents||[]).map(e=>`<article class="sq-activity-row"><div><strong>${esc(labels[e.kind]||e.kind)}</strong><small>${new Date(e.created*1000).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})}</small></div><p>${esc(e.toolName)}${e.version?` · v${e.version}`:''}</p><small>${esc(e.userName)}${e.imported?' · 기존 집계 이전':''}${e.kind==='download'&&!e.counted?' · 반복/업데이트, 집계 제외':''}</small></article>`).join('')||'<p class="sq-note">아직 저장된 이력이 없습니다.</p>'}</div>${server.activityCursor?button('activity-more','이전 이력 더 보기','sq-secondary'):''}`;
}
actions['activity-more']=async()=>{const r=await requestAPI('/api/activity?before='+encodeURIComponent(server.activityCursor));server.activityEvents.push(...r.events);server.activityCursor=r.nextCursor;manage('activity');};

root.addEventListener('click',event=>{const b=event.target.closest('button');if(!b||!root.contains(b)||b.disabled)return;if(b.hasAttribute('data-home-type')){state.homeType=b.dataset.homeType;state.rankPage=0;render();return;}if(b.hasAttribute('data-org')){state.org=b.dataset.org;state.page=0;renderCatalog();mountIcons();return;}if(b.hasAttribute('data-type')){state.type=b.dataset.type;state.page=0;renderCatalog();mountIcons();return;}const handler=actions[b.dataset.action];if(handler){event.preventDefault();b.disabled=true;Promise.resolve().then(()=>handler(b)).catch(showError).finally(()=>{if(b.isConnected)b.disabled=false;});}});
root.addEventListener('submit',event=>{
 event.preventDefault();const form=event.target;if(form.dataset.busy)return;const values=new FormData(form),data=Object.fromEntries(values);
 if(form.id==='sq-search-form'){clearTimeout(runtime.searchTimer);state.query=$('#sq-query').value.trim();if(state.route==='home'){state.type='전체';state.category='모든 업무';state.org='전체 조직';}navigate('browse','discovery');return;}
 if(form.id==='sq-register-form'){captureDraft();const error=packageBlockingError(runtime.draft)||Core.validate(runtime.draft,runtime.step);if(error){$('#sq-register-error').textContent=error;return;}if(runtime.step===3)return;runtime.step++;wizard();return;}
 form.dataset.busy='true';form.querySelectorAll('button').forEach(b=>b.disabled=true);
 (async()=>{
  const id=runtime.detailId;
  if(form.id==='sq-comment-form'){await requestAPI(`/api/tools/${id}/comments`,'POST',{kind:data.kind,text:data.comment});await refresh();detail(id,'comments');}
  if(form.id==='sq-access-form'){await requestAPI(`/api/tools/${id}/requests`,'POST',{reason:data.reason});await refresh();detail(id,'connect');}
  if(form.id==='sq-policy-form'){await requestAPI('/api/storage/policy','PUT',{keep:+data.keep,days:+data.days});await refresh();manage('storage');}
  if(form.id==='sq-edit-tool-form'){await requestAPI(`/api/tools/${id}`,'PATCH',{...data,approval:form.elements.approval.checked,audience:values.getAll('audience'),expectedRevision:getItem(id).revision});await refresh();manage();}
  if(form.id==='sq-org-form'){await requestAPI('/api/organizations','POST',{...data,previous:organizations[runtime.orgIndex]?.name});await refresh();manage('orgs');}
  if(form.id==='sq-reject-form'){await requestAPI(`/api/requests/${form.dataset.request}/decision`,'POST',{status:'반려',reason:data.reason});await refresh();manage('requests');}
  if(form.id==='sq-idea-form'){await requestAPI('/api/ideas','POST',data);openModal('아이디어를 남겼습니다.','제안 등록 완료',`<div class="sq-success"><h3>${esc(data.name)}</h3><p>운영 관리의 아이디어 목록에 저장했습니다.</p>${button('close-dialog','확인','sq-primary')}</div>`);}
 })().catch(showError).finally(()=>{delete form.dataset.busy;form.querySelectorAll('button').forEach(b=>b.disabled=false);});
});

root.addEventListener('change',event=>{
 const el=event.target;if(el.id==='sq-sort'){state.sort=el.value;state.page=0;renderCatalog();mountIcons();}if(el.id==='sq-category'){state.category=el.value;state.page=0;renderCatalog();mountIcons();}
 if(el.closest('#sq-register-form')){if(el.name==='artifact'){captureDraft();const f=el.files?.[0];runtime.draft.file=f||null;runtime.draft.sample=false;wizard();}else if(el.name==='mode'){captureDraft();wizard();}else if(el.name==='visibility')$('#sq-audience').hidden=el.value!=='선택 조직';}
});
$('#sq-query').addEventListener('input',()=>{clearTimeout(runtime.searchTimer);runtime.searchTimer=setTimeout(()=>{if($('#sq-dialog').open)return;state.query=$('#sq-query').value.trim();if(!state.query&&state.route==='home')return;if(state.route==='home'){state.type='전체';state.category='모든 업무';state.org='전체 조직';}navigate('browse','discovery');},450);});
$('#sq-dialog').addEventListener('close',()=>{runtime.returnFocus?.isConnected&&runtime.returnFocus.focus({preventScroll:true});schedule();});$('#sq-confirm').addEventListener('cancel',()=>runtime.confirm=null);document.addEventListener('visibilitychange',()=>{schedule();if(!document.hidden&&!$('#sq-dialog').open&&!runtime.requestBusy)refresh().catch(showError);});motion.addEventListener('change',()=>{if(motion.matches){$$('.sq-reveal').forEach(el=>el.classList.remove('sq-reveal','sq-visible'));runtime.revealObserver?.disconnect();}state.auto=!motion.matches;runtime.token++;runtime.busy=false;renderRanks();schedule();});
if(globalThis.IntersectionObserver)new IntersectionObserver(entries=>{const visible=entries[0].isIntersecting;if(runtime.inView!==visible){runtime.inView=visible;schedule();}},{threshold:.05}).observe($('.sq-rank-window'));else runtime.inView=true;
// BEGIN WORKSPACE EXTENSION
// Workspace extension: retain the approved home, catalog, typography and motion.
const work={tab:'tools',scope:'mine',requestFilter:'대기',ideaFilter:'전체',notifications:[],unreadOnly:false,users:[]};
const dated=t=>new Date(t*1000).toLocaleString('ko-KR',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
const badge=s=>`<span class="ws-badge" data-status="${esc(s)}">${esc(s)}</span>`;
const blank=(i,title,body)=>`<div class="ws-empty">${icon(i)}<h3>${esc(title)}</h3><p>${esc(body)}</p></div>`;
async function afterWorkspaceSave(callback,form){
 // Call only after a confirmed write. A failed read must not invite a second save.
 if(form)form.dataset.saved='true';
 try{return await callback();}
 catch(error){const notice=Error(`변경사항은 서버에 저장되었습니다. 목록·상세 화면을 갱신하지 못했습니다. 새로고침 후 확인해 주세요. ${error.message||''}`);notice.saved=true;throw notice;}
}
const originalRender=render, originalModal=openModal, originalDetail=detail, originalManage=manage;
const originalCloseModal=closeModal,originalNavigate=navigate;
const workspace=document.createElement('section');workspace.id='sq-workspace';workspace.hidden=true;$('#sq-main').append(workspace);
const nav=$('.sq-header nav');nav.insertAdjacentHTML('beforeend',`${button('ax-workspace','AX Workspace','','data-route="ax"')}${button('requests-board','기능 요청','','data-route="ideas"')}${button('manage','등록 관리','','data-route="manage"')}${button('admin-home','관리자','','data-route="admin" id="ws-admin-nav" hidden')}`);
$('.sq-header-actions [data-action="manage"]').remove();
$('.sq-header-actions').insertAdjacentHTML('afterbegin',`<button class="sq-quiet ws-bell" data-action="inbox" aria-label="내 알림" title="내 알림">${icon('bell')}<span id="ws-unread" hidden></span></button>`);
render=function(){
 const categories=server.categories||[];
 $('#sq-category').innerHTML=options(['모든 업무',...categories.filter(x=>x.enabled||x.name===state.category).map(x=>x.name)],state.category);
 originalRender();const special=['manage','admin','ideas','ax'].includes(state.route);
 workspace.hidden=!special;$('.sq-toolbar').hidden=special;$('#sq-search-form').hidden=special;
 $('#ws-admin-nav').hidden=server.user.role!=='admin';
 const unread=server.unread||0;$('#ws-unread').hidden=!unread;$('#ws-unread').textContent=unread>99?'99+':unread;
 $('.ws-bell').setAttribute('aria-label',`내 알림, 읽지 않은 알림 ${unread}개`);
 if(special){
  const labels={manage:['내가 나눈 노하우.','동료의 피드백으로 더 나은 도구로.'],admin:['함께 쓰는 공간을 가꾸세요.','좋은 공유가 이어질 수 있도록.'],ideas:['작은 불편함도 좋은 시작.','함께 만들고 싶은 도구를 이야기하세요.'],ax:['AX Workspace.','업무를 연결하는 시작.']};
  setPageHeading(...labels[state.route],true);renderWorkspace();
 }
 enhanceSelects();
};
// A late detail response must not replace a newer dialog or reopen one the user dismissed.
function invalidateDetailLoad(){return runtime.detailLoadToken=(runtime.detailLoadToken||0)+1;}
openModal=function(title,kicker,html){invalidateDetailLoad();originalModal(title,kicker,html);decorateForms();enhanceSelects();};
closeModal=function(){invalidateDetailLoad();return originalCloseModal();};
navigate=function(route,sort){invalidateDetailLoad();return originalNavigate(route,sort);};
// This action captured the original function before the workspace extension loaded.
actions['close-dialog']=closeModal;
// Escape's cancel event is synchronous. A queued close event could otherwise cancel
// a newly requested detail after a deliberate close-and-open sequence.
$('#sq-dialog').addEventListener('cancel',invalidateDetailLoad);
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
async function loadDeletionJobs(){work.deletionJobs=(await requestAPI('/api/deletions')).jobs;}
function deletionJobsPanel(){
 const jobs=(work.deletionJobs||[]).filter(j=>j.kind==='idea'||!items.some(x=>x.id===j.entityId&&x.purgePending));
 return jobs.length?`<div class="ws-panel-head"><div><h2>마무리가 필요한 삭제</h2><p>파일이나 데이터 정리를 완료하지 못한 항목입니다. 다시 시도하면 남은 부분부터 처리합니다.</p></div></div><div class="ws-list">${jobs.map(j=>`<div class="ws-row"><span class="ws-avatar">${icon('refresh-cw')}</span><div class="ws-row-main"><strong>${j.kind==='idea'?'기능 요청':'등록 기능'} #${j.entityId}</strong><p>${dated(j.created)} · 삭제 처리 중</p></div>${button('retry-deletion','삭제 다시 시도','sq-secondary ws-danger',`data-job="${esc(j.id)}"`)}</div>`).join('')}</div>`:'';
}
function renderWorkspace(){
 if(state.route==='ideas'){renderIdeas();return;}
 if(state.route==='ax'){renderAxWorkspace();return;}
 const isAdmin=state.route==='admin';work.scope=isAdmin?'all':'mine';
 const tabs=isAdmin?[['tools','전체 기능'],['trash','휴지통'],['requests','권한 관리'],['taxonomy','조직·업무'],['admins','관리자 설정'],['storage','저장 공간'],['activity','사용 이력']]:[['tools','내 등록 기능'],['trash','휴지통'],['requests','권한 관리'],['feedback','피드백']];
 if(!tabs.some(t=>t[0]===work.tab))work.tab='tools';
 const list=managementItems();const pending=requests.filter(r=>r.status==='대기'&&(isAdmin||r.ownerId===server.user.id)).length;
 let html=`<div class="ws-summary"><div><span>공유한 기능</span><strong>${list.filter(x=>!x.deleted).length}<small>개</small></strong></div><div><span>승인 대기</span><strong>${pending}<small>건</small></strong></div><div><span>새로운 피드백</span><strong>${list.reduce((n,x)=>n+x.comments.filter(c=>c.status==='접수').length,0)}<small>건</small></strong></div><div class="ws-summary-action">${button('register',icon('plus')+' 기능 등록','sq-primary')}</div></div><div class="ws-surface"><div class="sq-tabs ws-tabs">${tabs.map(([id,label])=>button('workspace-tab',label,'',`data-tab="${id}" aria-pressed="${work.tab===id}"`)).join('')}</div>`;
 if(work.tab==='tools'||work.tab==='trash'){
  const trash=work.tab==='trash',rows=list.filter(x=>!!x.deleted===trash);
  html+=`<div class="ws-panel-head"><div><h2>${trash?'휴지통':isAdmin?'전체 등록 기능':'내가 공유한 기능'}</h2><p>${trash?'복원하면 다시 사용할 수 있습니다. 영구 삭제는 관리자만 가능하며 배포 파일과 관련 기록이 제거됩니다.':'등록 정보와 배포 버전, 조회 권한을 관리하세요.'}</p></div>${trash?badge(rows.length+'개'):''}</div><div class="ws-list">${rows.map(x=>`<article class="ws-row"><span class="sq-tool-icon" data-type="${esc(x.type)}">${icon(trash?'trash-2':x.icon)}</span><div class="ws-row-main"><strong>${esc(x.name)}</strong><p>${esc(x.org)} · ${esc(x.type)} · v${x.active}${isAdmin?' · '+esc(x.owner):''}</p>${x.purgePending?'<p class="ws-message">영구 삭제 처리 중입니다. 완료되지 않았다면 다시 시도해 주세요.</p>':''}</div>${badge(x.purgePending?'삭제 처리 중':trash?'휴지통':x.approval?'승인 후 조회':'전체 공개')}<div class="sq-row-actions">${trash?`${x.purgePending?'':button('restore-tool','복원','sq-link',`data-id="${x.id}"`)}${isAdmin?button('purge-tool',x.purgePending?'삭제 다시 시도':'영구 삭제','sq-secondary ws-danger',`data-id="${x.id}"`):''}`:`${button('edit-tool','수정','sq-link',`data-id="${x.id}"`)}${button('manage-versions','버전','sq-link',`data-id="${x.id}"`)}${button('grant-users','권한','sq-link',`data-id="${x.id}"`)}${button('delete-tool',icon('trash-2'),'sq-icon ws-danger',`data-id="${x.id}" aria-label="${esc(x.name)} 삭제"`)}`}</div></article>`).join('')||blank(trash?'trash-2':'package-open',trash?'휴지통이 비어 있습니다.':'아직 등록한 기능이 없습니다.',trash?'휴지통으로 이동한 기능을 여기서 복원하거나 정리할 수 있습니다.':'잘 만든 도구를 동료들과 공유해 보세요.')}</div>`;
 }

 if(work.tab==='trash'&&isAdmin)html+=deletionJobsPanel();
 if(work.tab==='requests'){
  const all=requests.filter(r=>isAdmin||r.ownerId===server.user.id);const filtered=all.filter(r=>work.requestFilter==='대기'?r.status==='대기':work.requestFilter==='승인됨'?r.granted:!r.granted&&r.status!=='대기');
  html+=`<div class="ws-panel-head"><div><h2>조회 권한 관리</h2><p>신청자와 실제 권한 보유자를 구분해서 관리합니다.</p></div><div class="ws-segment">${['대기','승인됨','처리 이력'].map(s=>button('access-filter',s,'',`data-filter="${s}" aria-pressed="${s===work.requestFilter}"`)).join('')}</div></div><div class="ws-list">${filtered.map(r=>`<article class="ws-row"><span class="ws-avatar">${esc(r.who.slice(0,1))}</span><div class="ws-row-main"><strong>${esc(r.who)} <small>${esc(r.user)}</small></strong><p>${esc(r.name)} · ${esc(r.source)}</p><p class="ws-message">${esc(r.reason||'직접 권한을 부여한 사용자입니다.')}</p>${r.decision?`<p>${esc(r.decision)}</p>`:''}</div>${badge(r.granted?'승인됨':r.status==='승인'?'권한 회수':r.status)}<div class="sq-row-actions">${r.status==='대기'?button('access-decision','승인','sq-primary',`data-request="${r.id}" data-status="승인"`)+button('access-decision','반려','sq-secondary',`data-request="${r.id}" data-status="반려"`):r.granted?button('access-decision','권한 회수','sq-secondary',`data-request="${r.id}" data-status="회수"`):''}${button('access-history','이력','sq-link',`data-request="${r.id}"`)}</div></article>`).join('')||blank('shield-check','처리할 항목이 없습니다.','권한 신청과 승인 결과가 여기에 표시됩니다.')}</div>`;
 }
 if(work.tab==='feedback'){const feedback=list.flatMap(x=>x.comments.map(c=>({...c,toolName:x.name}))).sort((a,b)=>b.created-a.created);html+=`<div class="ws-panel-head"><div><h2>동료들의 피드백</h2><p>의견을 확인하고 답변과 처리 상태를 남겨주세요.</p></div></div>${feedback.map(c=>`<button class="ws-row ws-click" data-action="feedback-open" data-id="${c.tool}"><span class="ws-avatar">${icon('message-square')}</span><span class="ws-row-main"><strong>${esc(c.toolName)}</strong><span>${esc(c.author)} · ${esc(c.text)}</span></span>${badge(c.status)}${icon('chevron-right')}</button>`).join('')||blank('messages-square','아직 피드백이 없습니다.','사용자가 남긴 의견을 이곳에서 확인할 수 있습니다.')}`;}
 if(work.tab==='taxonomy')html+=taxonomyPanel();
 if(work.tab==='admins')html+=`<div class="ws-panel-head"><div><h2>함께 운영하는 관리자</h2><p>기본 관리자는 설정 파일에서, 추가 관리자는 이 화면에서 관리합니다.</p></div>${server.user.baseAdmin?button('add-admin',icon('user-plus')+' 관리자 추가','sq-primary'):''}</div>${(work.admins||[]).map(a=>`<div class="ws-row"><span class="ws-avatar">${esc(a.name.slice(0,1))}</span><div class="ws-row-main"><strong>${esc(a.name)}</strong><p>${esc(a.id)}</p></div>${badge(a.base?'기본 관리자':'추가 관리자')}${!a.base&&server.user.baseAdmin?button('remove-admin','해제','sq-secondary',`data-user="${esc(a.id)}"`):''}</div>`).join('')||blank('users','관리자 목록을 불러오는 중입니다.','잠시만 기다려 주세요.')}`;
 if(work.tab==='storage')html+=storageCapacityPanel();
 if(work.tab==='activity')html+=activityPanel();
 workspace.innerHTML=html+'</div>';mountIcons();enhanceSelects();
}
function taxonomyPanel(){return `<div class="ws-panel-head"><div><h2>조직과 업무 분류</h2><p>저장하면 검색 필터와 등록·수정 화면에 바로 반영됩니다.</p></div></div><div class="ws-taxonomy">${[['organization','조직',organizations],['category','업무',server.categories||[]]].map(([kind,label,rows])=>`<section><div class="ws-panel-head"><h3>${label}</h3>${button('taxonomy-edit',icon('plus')+' 추가','sq-link',`data-kind="${kind}"`)}</div>${rows.map(x=>`<div class="ws-row"><span class="ws-order">${x.order}</span><div class="ws-row-main"><strong>${esc(x.name)}</strong><p>${x.enabled?'선택 가능':'사용 중지 · 기존 기록 유지'}</p></div>${button('taxonomy-edit',icon('pencil'),'sq-icon',`data-kind="${kind}" data-id="${esc(x.id)}" aria-label="${esc(x.name)} 수정"`)}</div>`).join('')}</section>`).join('')}</div>`;}

detail=async function(id,tab='intro'){
 const x=getItem(id);if(!x)throw Error('이 기능은 삭제되었거나 더 이상 사용할 수 없습니다.');runtime.detailId=x.id;const token=invalidateDetailLoad();
 if(x.deleted){openModal('휴지통에 있는 기능입니다.',x.name,`<p class="sq-note">복원한 후 기능 상세를 열 수 있습니다.</p>${button('restore-tool','복원','sq-primary',`data-id="${x.id}"`)}`);return false;}
 // Revalidate on every open; no stale dialog bypass after access revocation.
 try{const fresh=await requestAPI(`/api/tools/${x.id}`);if(token!==runtime.detailLoadToken)return false;Object.assign(x,fresh,{likes:fresh.likes-(fresh.liked?1:0)});}
 catch(error){
  if(token!==runtime.detailLoadToken)return false;
  if(error.status!==403)throw error;
  try{await refresh();}catch(refreshError){if(token!==runtime.detailLoadToken)return false;throw refreshError;}
  if(token!==runtime.detailLoadToken)return false;
  const current=getItem(id);if(current)lockedDetail(current);return false;
 }
 originalDetail(id,tab);
 deploymentLinks(x,tab);
 $('.sq-detail-top .sq-row-actions')?.insertAdjacentHTML('afterbegin',button('subscribe',icon(x.subscribed?'bell-ring':'bell')+(x.subscribed?'업데이트 알림 켜짐':'업데이트 알림 받기'),'sq-secondary',`data-id="${x.id}" aria-pressed="${x.subscribed}"`));
 if(tab==='comments'){
  const tabs=$('#sq-dialog-body .sq-tabs');while(tabs.nextElementSibling)tabs.nextElementSibling.remove();
  tabs.insertAdjacentHTML('afterend',`<div class="ws-feedback-list">${x.comments.map(c=>`<article class="ws-feedback"><div class="ws-feedback-head"><div><strong>${esc(c.author)}</strong><small>${dated(c.created)} · ${esc(c.kind)}</small></div>${badge(c.status)}</div><p>${esc(c.text)}</p>${c.replies.map(r=>`<div class="ws-reply"><strong>${esc(r.author)}</strong><small>${dated(r.created)} · ${esc(r.status||'답변')}</small><p>${esc(r.text||'처리 상태를 변경했습니다.')}</p></div>`).join('')}${x.canManage||c.user===server.user.id?button('feedback-reply','답변·상태 변경','sq-link',`data-id="${c.id}"`):''}</article>`).join('')||blank('message-circle','첫 번째 의견을 남겨주세요.','사용 경험이나 개선할 점을 나눠주세요.')}</div><form id="sq-comment-form" class="ws-compose"><label class="sq-field"><span>피드백 종류</span><select name="kind">${options(['개선 의견','사용 후기','오류 제보','아이디어 제안'],'개선 의견')}</select></label><label class="sq-field"><span>의견</span><textarea name="comment" required maxlength="4000" placeholder="사용해 보니 어떤 점이 좋았나요? 개선이 필요한 부분도 알려주세요."></textarea></label><div class="sq-actions"><button class="sq-primary">피드백 등록</button></div></form>`);
 }mountIcons();enhanceSelects();return true;
};
function lockedDetail(x){runtime.detailId=x.id;openModal('조회 권한이 필요합니다.',x.name,`<div class="ws-lock"><span class="ws-lock-icon">${icon('lock-keyhole')}</span><h3>${x.access==='pending'?'신청을 검토하고 있습니다.':'승인 후 상세 내용을 볼 수 있어요.'}</h3><p>목록은 누구나 볼 수 있지만, 상세 내용과 배포 파일은<br>등록자 또는 관리자의 승인 후 이용할 수 있습니다.</p>${x.accessDecision?`<div class="sq-callout">${esc(x.accessDecision)}</div>`:''}<div class="sq-actions">${x.access==='pending'?badge('승인 대기'):button('request-access','조회 권한 신청','sq-primary')}</div><small>처리 결과는 내 알림에서 알려드릴게요.</small></div>`);}
function renderIdeas(){
 const rows=(work.ideas||[]).filter(i=>work.ideaFilter==='전체'||i.status===work.ideaFilter);
 workspace.innerHTML=`<div class="ws-board-head"><div class="ws-segment">${['전체','접수 대기','개발 중','구현 완료'].map(s=>button('idea-filter',s,'',`data-filter="${s}" aria-pressed="${s===work.ideaFilter}"`)).join('')}</div>${button('idea',icon('plus')+' 새 기능 요청','sq-primary')}</div><div class="ws-idea-grid">${rows.map(i=>`<button class="ws-idea-card" data-action="idea-open" data-id="${i.id}"><div class="ws-idea-top">${badge(i.status)}<span>${esc(i.category)}</span></div><h2>${esc(i.name)}</h2><p>${esc(i.body)}</p><div class="ws-idea-foot"><span>${i.assigneeName?'담당 '+esc(i.assigneeName):'함께 만들 동료를 기다려요'}</span>${icon('arrow-up-right')}</div></button>`).join('')||blank('lightbulb','작은 불편함에서 좋은 도구가 시작됩니다.','필요한 기능을 요청하고 동료들과 함께 만들어 보세요.')}</div>`;mountIcons();
}
async function loadIdeas(){work.ideas=(await requestAPI('/api/ideas')).ideas;}
async function ideaDetail(id){
 const token=invalidateDetailLoad();
 try{await loadIdeas();}catch(error){if(token!==runtime.detailLoadToken)return false;throw error;}
 if(token!==runtime.detailLoadToken)return false;
 const i=work.ideas.find(x=>x.id===+id);if(!i)throw Error('요청을 찾을 수 없습니다.');work.idea=i;
 if(i.deletionPending){openModal(i.name,'기능 요청 · 삭제 처리 중',`<div class="sq-callout"><strong>삭제 작업을 마무리하고 있습니다.</strong><p>이 요청은 수정할 수 없습니다. 삭제를 다시 시도하면 남은 파일과 데이터 정리를 이어갑니다.</p></div><div class="sq-actions">${server.user.role==='admin'?button('idea-delete','삭제 다시 시도','sq-secondary ws-danger',`data-id="${i.id}"`):''}</div>`);return;}
 const owner=server.user.role==='admin'||i.assignee===server.user.id;
 openModal(i.name,'기능 요청',`<div class="ws-idea-top">${badge(i.deletionPending?'삭제 처리 중':i.status)}<span>${esc(i.category)} · ${esc(i.author)} · ${dated(i.created)}</span></div><p class="ws-request-body">${esc(i.body)}</p>${attachmentLinks(i.attachments||[])}<div class="ws-assignee">${icon('user-round')}<span>${i.assigneeName?'개발 담당 · '+esc(i.assigneeName):'아직 담당자가 없습니다.'}</span>${!i.assignee&&i.status==='접수 대기'?button('idea-claim','제가 구현할게요','sq-primary',`data-id="${i.id}"`):''}</div>${i.toolName?`<button class="ws-linked-tool" data-action="detail" data-id="${i.tool}">${icon('package')}<span>연결된 기능<strong>${esc(i.toolName)}</strong></span>${icon('arrow-up-right')}</button>`:''}<div class="ws-feedback-list">${(i.replies||[]).map(r=>`<div class="ws-reply"><strong>${esc(r.author)}</strong><small>${dated(r.created)}</small><p>${esc(r.text)}</p></div>`).join('')}</div>${server.user.role==='admin'?`<div class="ws-idea-admin">${button('idea-delete',icon('trash-2')+(i.deletionPending?'삭제 다시 시도':'요청 삭제'),'sq-link ws-danger',`data-id="${i.id}"`)}<span>요청 내용·답변·첨부파일을 삭제합니다.</span></div>`:''}<form data-work-form="idea-reply"><label class="sq-field"><span>답변</span><textarea name="text" maxlength="4000" placeholder="진행 상황이나 추가 의견을 남겨주세요."></textarea></label>${owner?`<div class="sq-form-grid"><label class="sq-field"><span>진행 상태</span><select name="status">${options(server.user.role==='admin'?['접수 대기','담당자 지정','개발 중','구현 완료','보류']:[i.status,...({'접수 대기':['보류'],'담당자 지정':['개발 중','보류','접수 대기'],'개발 중':['구현 완료','보류','접수 대기'],'보류':['접수 대기','개발 중'],'구현 완료':['개발 중']}[i.status]||[])],i.status)}</select></label><label class="sq-field"><span>구현 완료 시 연결할 기능</span><select name="tool"><option value="">기능 선택</option>${items.filter(x=>!x.deleted&&x.access==='approved').map(x=>`<option value="${x.id}" ${i.tool===x.id?'selected':''}>${esc(x.name)}</option>`).join('')}</select></label></div>`:''}<div class="sq-actions"><button class="sq-primary">${owner?'답변·상태 저장':'답변 등록'}</button></div></form>`);
}

async function inbox(loadMore=false){
 const url='/api/notifications?unread='+work.unreadOnly+(loadMore&&work.notificationCursor?'&before='+encodeURIComponent(work.notificationCursor):'');const r=await requestAPI(url);
 work.notifications=loadMore?[...work.notifications,...r.notifications]:r.notifications;work.notificationCursor=r.nextCursor;server.unread=r.unread;render();
 openModal('내 알림','나에게 필요한 소식',`<div class="ws-inbox-head"><div class="ws-segment">${button('inbox-filter','전체','','data-unread="false" aria-pressed="'+!work.unreadOnly+'"')}${button('inbox-filter','안읽음','','data-unread="true" aria-pressed="'+work.unreadOnly+'"')}</div>${button('read-all','모두 읽음','sq-link')}</div><div class="ws-inbox">${work.notifications.map(n=>`<button class="ws-notification ${n.read?'':'is-unread'}" data-action="notification-open" data-id="${esc(n.id)}"><span class="ws-notice-icon">${icon(({approval:'shield-check',feedback:'message-square',release:'package-check',idea:'lightbulb',admin:'settings'})[n.kind]||'bell')}</span><span><strong>${esc(n.title)}</strong><small>${dated(n.created)}</small></span><span class="ws-unread-dot" ${n.read?'hidden':''}></span></button>`).join('')||blank('bell','모두 확인했습니다.','답변, 권한 처리 결과, 새 버전 소식이 여기에 도착합니다.')}</div>${r.nextCursor?button('inbox-more','이전 알림 더 보기','sq-secondary'):''}`);
}

Object.assign(actions,{
 'manage':()=>manage(),
 'admin-home':async()=>{work.tab='tools';closeModal();navigate('admin');},
 'workspace-tab':async b=>{work.tab=b.dataset.tab;if(work.tab==='storage')await fetchStorageCapacity();if(work.tab==='trash'&&server.user.role==='admin')await loadDeletionJobs();if(work.tab==='admins')work.admins=(await requestAPI('/api/admins')).admins;if(work.tab==='activity'){const r=await requestAPI('/api/activity');server.activityEvents=r.events;server.activityCursor=r.nextCursor;}renderWorkspace();},
 'admin-tab':b=>{work.tab=b.dataset.tab==='orgs'?'taxonomy':b.dataset.tab;closeModal();navigate(work.scope==='all'?'admin':'manage');},
 'storage-dialog':()=>originalManage('storage'),
 'access-filter':b=>{work.requestFilter=b.dataset.filter;renderWorkspace();},
 'requests-board':async()=>{await loadIdeas();closeModal();navigate('ideas');},
 'idea-filter':b=>{work.ideaFilter=b.dataset.filter;renderIdeas();},
 'idea-open':b=>ideaDetail(b.dataset.id),
 'idea':()=>{work.ideaFiles=[];openModal('어떤 기능이 필요하세요?','새 기능 요청',`<form data-work-form="idea"><div class="sq-form-grid"><label class="sq-field wide"><span>요청 제목</span><input name="name" required maxlength="100" placeholder="예: 여러 장비의 점검 이력을 한 번에 비교하고 싶어요."></label><label class="sq-field wide"><span>현재 불편한 점과 원하는 결과</span><textarea name="desc" required maxlength="4000" placeholder="지금은 어떻게 일하고 있나요? 어떤 결과가 나오면 도움이 될까요?"></textarea></label><label class="sq-field"><span>관련 업무</span><select name="category">${options((server.categories||[]).filter(c=>c.enabled).map(c=>c.name),'공통 업무')}</select></label></div>${uploadArea('attachments',work.ideaFiles)}<div class="sq-actions"><button class="sq-primary">요청 등록</button></div></form>`);},
 'idea-claim':b=>ask('이 요청의 개발을 맡으시겠어요?','내 이름이 개발 담당자로 표시되고 요청자에게 알림이 전달됩니다.',async()=>{await requestAPI(`/api/ideas/${b.dataset.id}`,'PATCH',{claim:true,expectedRevision:work.idea.revision});await afterWorkspaceSave(()=>ideaDetail(b.dataset.id));},'제가 구현할게요'),
 'feedback-open':b=>detail(b.dataset.id,'comments'),
 'feedback-reply':b=>{const x=getItem(runtime.detailId),c=x.comments.find(c=>c.id===+b.dataset.id);work.feedback=c;openModal('피드백에 답변하기',x.name,`<div class="sq-callout"><strong>${esc(c.author)}</strong><br>${esc(c.text)}</div><form data-work-form="feedback"><label class="sq-field"><span>답변</span><textarea name="text" maxlength="4000" placeholder="검토 결과나 진행 상황을 알려주세요."></textarea></label>${x.canManage?`<label class="sq-field"><span>처리 상태</span><select name="status">${options(['접수','검토 중','반영 중','반영 완료','보류'],c.status)}</select></label>`:''}<div class="sq-actions"><button class="sq-primary">답변 저장</button></div></form>`);},
 'subscribe':async b=>{const x=getItem(b.dataset.id);await requestAPI(`/api/tools/${x.id}/subscription`,'PUT',{enabled:!x.subscribed});await afterWorkspaceSave(()=>detail(x.id,runtime.detailTab));},
 'delete-tool':b=>{const x=getItem(b.dataset.id);ask('이 기능을 휴지통으로 이동할까요?',x.name+' · 목록과 다운로드가 중단됩니다. 등록자·관리자가 복원할 수 있습니다.',async()=>{await requestAPI(`/api/tools/${x.id}`,'DELETE',{expectedRevision:x.revision});await afterWorkspaceSave(()=>refresh());},'휴지통으로 이동');},
 'restore-tool':async b=>{const x=getItem(b.dataset.id);await requestAPI(`/api/tools/${x.id}/restore`,'POST',{expectedRevision:x.revision});closeModal();await afterWorkspaceSave(()=>refresh());},
 'retry-deletion':b=>{const job=(work.deletionJobs||[]).find(j=>j.id===b.dataset.job);if(server.user.role!=='admin'||!job)return;ask('남은 삭제 작업을 마무리할까요?','이미 시작한 영구 삭제를 이어서 처리합니다. 복원할 수 없습니다.',async()=>{const result=await requestAPI(job.kind==='idea'?`/api/ideas/${job.entityId}`:`/api/tools/${job.entityId}/purge`,job.kind==='idea'?'DELETE':'POST',{expectedRevision:job.revision});await afterWorkspaceSave(async()=>{await refresh();await loadDeletionJobs();if(state.route==='admin')renderWorkspace();});announce(result.pending&&!result.deleted?'아직 정리하지 못한 항목이 있습니다. 잠시 후 다시 시도해 주세요.':'삭제를 완료했습니다.');},'삭제 마무리');},
 'purge-tool':b=>{const x=getItem(b.dataset.id);if(server.user.role!=='admin'||!x?.deleted)return;ask('이 기능을 영구 삭제할까요?',x.name+' · 모든 배포 버전과 파일, 좋아요·다운로드 이력, 권한·피드백이 삭제됩니다. 삭제 후 복원할 수 없습니다.',async()=>{const result=await requestAPI(`/api/tools/${x.id}/purge`,'POST',{expectedRevision:x.revision});closeModal();await afterWorkspaceSave(async()=>{await refresh();await loadDeletionJobs();if(state.route==='admin')renderWorkspace();});announce(result.pending&&!result.deleted?'삭제가 시작되었습니다. 휴지통에서 남은 작업을 다시 시도할 수 있습니다.':'기능을 영구 삭제했습니다.');},'영구 삭제');},
 'idea-delete':b=>{const i=work.idea;if(server.user.role!=='admin'||!i)return;ask('이 기능 요청을 삭제할까요?',i.name+' · 요청 내용, 답변, 첨부파일이 삭제되며 복원할 수 없습니다.',async()=>{const result=await requestAPI(`/api/ideas/${i.id}`,'DELETE',{expectedRevision:i.revision});closeModal();await afterWorkspaceSave(async()=>{await loadIdeas();navigate('ideas');});announce(result.pending&&!result.deleted?'삭제가 시작되었습니다. 요청 상세 또는 관리자 → 휴지통에서 남은 작업을 다시 시도할 수 있습니다.':'기능 요청을 삭제했습니다.');},'요청 삭제');},
 'taxonomy-edit':b=>{const kind=b.dataset.kind,x=[...organizations,...server.categories].find(x=>x.id===b.dataset.id);work.taxonomy={kind,id:x?.id};openModal(x?'분류 수정':'분류 추가',kind==='organization'?'조직 설정':'업무 설정',`<form data-work-form="taxonomy"><div class="sq-form-grid"><label class="sq-field wide"><span>이름</span><input name="name" value="${esc(x?.name||'')}" required maxlength="80"></label><label class="sq-field"><span>표시 순서</span><input name="order" type="number" min="0" max="999" value="${x?.order??10}" required></label><label class="sq-field"><span>사용 여부</span><select name="enabled"><option value="true" ${x?.enabled!==false?'selected':''}>사용</option><option value="false" ${x?.enabled===false?'selected':''}>사용 중지</option></select></label><label class="sq-field wide"><span>안내 담당자 (선택)</span><input name="owner" maxlength="100" value="${esc(x?.owner||'')}"></label></div><div class="sq-callout">이름을 바꿔도 기존 기능과의 연결은 유지됩니다. 사용 중지한 항목은 새로 선택할 수 없습니다.</div><div class="sq-actions"><button class="sq-primary">저장</button></div></form>`);},
 'access-decision':b=>{work.access={id:b.dataset.request,status:b.dataset.status};openModal('조회 권한 '+b.dataset.status,'신청 처리',`<form data-work-form="access"><label class="sq-field"><span>처리 사유 ${b.dataset.status==='승인'?'(선택)':''}</span><textarea name="reason" maxlength="2000" ${b.dataset.status==='승인'?'':'required'} placeholder="신청자에게 안내할 내용을 적어주세요."></textarea></label><div class="sq-actions"><button class="sq-primary">${b.dataset.status}</button></div></form>`);},
 'access-history':b=>{const r=requests.find(r=>r.id===b.dataset.request);openModal('권한 처리 이력',r.name,`<div class="ws-timeline">${r.history.map(h=>`<article><strong>${esc(h.status)}</strong><small>${esc(h.actor)} · ${dated(h.at)}</small><p>${esc(h.reason||'')}</p></article>`).join('')}</div>`);},
 'grant-users':b=>{work.grantTool=+b.dataset.id;userPicker('grant');},
 'add-admin':()=>userPicker('admin'),
 'user-search':async()=>{const q=$('#ws-user-search').value;work.users=(await requestAPI('/api/users?q='+encodeURIComponent(q))).users;renderUserChoices();},
 'choose-user':async b=>{const uid=b.dataset.user,mode=work.userMode;if(mode==='grant')await requestAPI(`/api/tools/${work.grantTool}/grants`,'POST',{user:uid});else await requestAPI('/api/admins/'+encodeURIComponent(uid),'PUT',{active:true});closeModal();await afterWorkspaceSave(async()=>{await refresh();if(mode==='admin'){work.admins=(await requestAPI('/api/admins')).admins;renderWorkspace();}});announce('권한을 부여했습니다.');},
 'remove-admin':b=>ask('추가 관리자 권한을 해제할까요?',b.dataset.user+' 계정은 일반 사용자로 이용할 수 있습니다.',async()=>{await requestAPI('/api/admins/'+encodeURIComponent(b.dataset.user),'PUT',{active:false});await afterWorkspaceSave(async()=>{work.admins=(await requestAPI('/api/admins')).admins;await refresh();});},'해제'),
 'inbox':()=>inbox(),
 'inbox-more':()=>inbox(true),
 'inbox-filter':b=>{work.unreadOnly=b.dataset.unread==='true';return inbox();},
 'read-all':async()=>{await requestAPI('/api/notifications/read','PUT',{all:true});await afterWorkspaceSave(()=>inbox());},
 'notification-open':async b=>{const n=work.notifications.find(n=>n.id===b.dataset.id);await requestAPI('/api/notifications/read','PUT',{id:n.id});return afterWorkspaceSave(async()=>{await refresh();if(n.target.type==='idea')return ideaDetail(n.target.id);if(n.target.type==='access'){work.tab='requests';closeModal();navigate(server.user.role==='admin'?'admin':'manage');return;}if(n.target.type==='admin'){closeModal();navigate(server.user.role==='admin'?'admin':'home');return;}return detail(n.target.id,n.target.type==='feedback'?'comments':'intro');});}
});
function userPicker(mode){work.userMode=mode;work.users=[];openModal(mode==='grant'?'조회 사용자 추가':'추가 관리자 지정',mode==='grant'?getItem(work.grantTool).name:'기본 관리자 전용',`<p class="sq-note">이 사이트에 로그인한 적이 있는 계정을 이름 또는 사번으로 검색하세요.</p><form data-work-form="user-search" class="ws-user-search"><input id="ws-user-search" type="search" placeholder="이름 또는 사번" aria-label="사용자 검색"><button class="sq-primary">검색</button></form><div id="ws-user-results"></div>`);}
function renderUserChoices(){$('#ws-user-results').innerHTML=work.users.map(u=>`<div class="ws-row"><span class="ws-avatar">${esc(u.name.slice(0,1))}</span><div class="ws-row-main"><strong>${esc(u.name)}</strong><p>${esc(u.id)}</p></div>${button('choose-user',work.userMode==='admin'?'관리자 지정':'조회 승인','sq-secondary',`data-user="${esc(u.id)}"`)}</div>`).join('')||blank('search','일치하는 사용자가 없습니다.','먼저 사이트에 로그인한 계정인지 확인해 주세요.');mountIcons();}
root.addEventListener('submit',event=>{
 const form=event.target;if(!form.dataset.workForm)return;event.preventDefault();event.stopImmediatePropagation();if(form.dataset.busy||form.dataset.saved)return;
 form.dataset.busy='true';const data=Object.fromEntries(new FormData(form));form.querySelectorAll('button').forEach(b=>b.disabled=true);
 (async()=>{
  switch(form.dataset.workForm){
   case 'idea':{
    const files=work.ideaFiles,token=runtime.detailLoadToken,previousNotice=work.ideaSaveNotice,body=new FormData();delete data.attachments;body.append('metadata',JSON.stringify(data));for(const file of files||[])body.append('attachments',file);
    await requestAPI('/api/ideas','POST',body);
    await afterWorkspaceSave(async()=>{
     // Creation is complete. Replying/claiming is a separate action on a list item.
     if(work.ideaFiles===files)work.ideaFiles=[];
     if(token!==runtime.detailLoadToken)return;
     work.ideaFilter='전체';delete work.idea;closeModal();navigate('ideas');
     const listToken=runtime.detailLoadToken;
     try{await loadIdeas();}catch(error){if(listToken!==runtime.detailLoadToken)return;throw error;}
     if(listToken!==runtime.detailLoadToken||state.route!=='ideas')return;
     // Clear only the previous request's unchanged page notice, not a newer error.
     if(previousNotice&&work.ideaSaveNotice===previousNotice){
      if(previousNotice.node.isConnected&&previousNotice.node.textContent===previousNotice.message){previousNotice.node.textContent='';previousNotice.node.hidden=true;}
      delete work.ideaSaveNotice;
     }
     renderIdeas();announce('기능 요청을 등록했습니다.');
    },form);break;
   }
   case 'idea-reply':{const i=work.idea;await requestAPI(`/api/ideas/${i.id}`,'PATCH',{...data,tool:data.tool?+data.tool:null,expectedRevision:i.revision});await afterWorkspaceSave(async()=>{await ideaDetail(i.id);await loadIdeas();if(state.route==='ideas')renderIdeas();},form);break;}
   case 'feedback':{const c=work.feedback;await requestAPI(`/api/feedback/${c.id}/reply`,'POST',data);await afterWorkspaceSave(async()=>{await refresh();await detail(c.tool,'comments');},form);break;}
   case 'taxonomy':await requestAPI('/api/taxonomy','POST',{...data,...work.taxonomy,order:+data.order,enabled:data.enabled==='true'});closeModal();await afterWorkspaceSave(()=>refresh(),form);break;
   case 'access':await requestAPI(`/api/requests/${encodeURIComponent(work.access.id)}/decision`,'POST',{status:work.access.status,reason:data.reason});closeModal();await afterWorkspaceSave(()=>refresh(),form);break;
   case 'user-search':await actions['user-search']();break;
  }
 })().catch(error=>{
  showError(error);
  if(form.dataset.workForm==='idea'&&error.saved){const node=$('#sq-server-error');if(node&&!node.hidden&&node.textContent===error.message)work.ideaSaveNotice={node,message:error.message};}
 }).finally(()=>{delete form.dataset.busy;form.querySelectorAll('button').forEach(b=>b.disabled=!!form.dataset.saved);});
},true);
// showError keeps one accessible error in the active form/dialog or page banner.
setInterval(()=>{if(document.hidden||runtime.requestBusy)return;requestAPI('/api/notifications?unread=true').then(r=>{server.unread=r.unread;$('#ws-unread').hidden=!r.unread;$('#ws-unread').textContent=r.unread>99?'99+':r.unread;}).catch(()=>{});},30000);

function fileSize(n){return n<1048576?`${(n/1024).toFixed(1)} KB`:`${(n/1048576).toFixed(1)} MB`;}
function uploadArea(kind,files=[]){
 const multi=kind==='attachments';
 return `<section class="ws-upload-area" data-upload="${kind}"><div class="ws-drop-zone"><span class="ws-upload-icon">${icon(multi?'paperclip':'cloud-upload')}</span><h3>${multi?'요청을 설명할 자료를 첨부하세요':'공유할 파일을 여기에 놓으세요'}</h3><p>${multi?'이미지·PDF·문서·ZIP · 최대 5개, 파일당 20MB':'ZIP · EXE · MSI · PS1 · MD · 최대 128MB · 원본 형식으로 배포'}</p><button type="button" class="sq-secondary" data-file-pick="${kind}">${icon('plus')} 파일 선택</button><input class="sq-sr" type="file" name="${kind}" aria-label="${multi?'요청 첨부파일':'공유 파일'} 선택" ${multi?'multiple':''} accept="${multi?'.png,.jpg,.jpeg,.webp,.pdf,.txt,.csv,.xlsx,.docx,.zip':'.zip,.exe,.msi,.ps1,.md'}"></div><div class="ws-selected-files" aria-live="polite">${files.map((f,i)=>`<div class="ws-selected-file">${icon('file')}<span><strong>${esc(f.name)}</strong><small>${fileSize(f.size)} · 게시할 때 업로드</small></span><button type="button" class="sq-icon" data-file-remove="${kind}" data-index="${i}" aria-label="${esc(f.name)} 선택 취소">${icon('x')}</button></div>`).join('')}</div></section>`;
}
function attachmentLinks(files){return files.length?`<section class="ws-attachments"><h3>첨부 자료 <span>${files.length}</span></h3>${files.map(f=>`<a class="ws-selected-file" href="${esc(f.url)}" download>${icon('file')}<span><strong>${esc(f.name)}</strong><small>${fileSize(f.size)}</small></span>${icon('download')}</a>`).join('')}</section>`:'';}
function selectFiles(kind,files){
 if(!files.length)return;
 if(kind==='artifact'){
  if(files.length!==1)throw Error('공유 파일은 하나만 선택하세요. 여러 파일은 ZIP으로 묶어주세요.');
  if(!/\.(zip|exe|msi|ps1|md)$/i.test(files[0].name)||files[0].size>128*1048576||!files[0].size)throw Error('ZIP·EXE·MSI·PS1·MD 파일을 선택하세요. 빈 파일은 등록할 수 없고 최대 128MB입니다.');
  captureDraft();runtime.draft.file=files[0];runtime.draft.mode='file';runtime.draft.packageInspection=null;runtime.draft.workflow=null;wizard();
  if(typeof inspectSelectedPackage==='function')inspectSelectedPackage(files[0]);
 }else{
  const combined=[...(work.ideaFiles||[]),...files];
  if(combined.length>5||files.some(f=>f.size>20*1048576||!f.size||! /\.(png|jpe?g|webp|pdf|txt|csv|xlsx|docx|zip)$/i.test(f.name)))throw Error('이미지·PDF·TXT·CSV·XLSX·DOCX·ZIP을 최대 5개, 파일당 20MB까지 첨부하세요.');
  work.ideaFiles=combined;refreshAttachments();
 }
}
function refreshAttachments(){const area=$('[data-upload="attachments"]');if(area){area.outerHTML=uploadArea('attachments',work.ideaFiles);mountIcons();}}
root.addEventListener('click',e=>{
 const pick=e.target.closest('[data-file-pick]');if(pick){e.preventDefault();pick.closest('[data-upload]').querySelector('input[type=file]').click();return;}
 const remove=e.target.closest('[data-file-remove]');if(!remove)return;e.preventDefault();
 if(remove.dataset.fileRemove==='artifact'){captureDraft();runtime.draft.file=null;runtime.draft.packageInspection=null;runtime.draft.workflow=null;wizard();}else{work.ideaFiles.splice(+remove.dataset.index,1);refreshAttachments();}
});
// Capture before the legacy file input handler so validation and drops share one path.
root.addEventListener('change',e=>{const input=e.target;if(input.type!=='file'||!input.closest('[data-upload]'))return;e.stopImmediatePropagation();try{selectFiles(input.name,[...input.files]);}catch(error){input.value='';showError(error);}},true);
for(const type of ['dragenter','dragover','dragleave','drop'])root.addEventListener(type,e=>{
 const area=e.target.closest('[data-upload]');if(!area)return;e.preventDefault();
 area.classList.toggle('is-dragging',type==='dragenter'||type==='dragover');
 if(type==='drop')try{selectFiles(area.dataset.upload,[...e.dataTransfer.files]);}catch(error){showError(error);}
});

// Inspect a declaration, never run or transform uploaded code.
function packagePanel(d){
 const p=d.packageInspection;if(!p)return '';
 if(p.state==='loading')return '<div class="ws-package" role="status"><strong>배포 정보를 확인하고 있습니다.</strong><p>파일을 임시 전송하여 확인합니다. 게시 전에는 보관하지 않습니다.</p></div>';
 if(p.state==='error')return `<div class="ws-package is-error" role="alert"><strong>배포 정보를 읽지 못했습니다.</strong><p>${esc(p.error)}</p><p>입력 항목을 직접 작성하면 그대로 게시할 수 있습니다. 게시 시 기본 파일 검사는 다시 진행합니다.</p><button type="button" class="sq-link" data-package-retry>다시 검사</button></div>`;
 if(!p.result.recognized)return `<div class="ws-package"><strong>${p.result.warning?'배포 정보를 읽지 못했습니다':'일반 파일 등록'}</strong><p>${esc(p.result.warning||p.result.notice)}</p><p>이름·유형·설치 안내를 직접 입력하고 게시하세요.</p></div>`;
 const info=p.result.package;
 return `<div class="ws-package"><div class="ws-package-heading">${icon('file-check-2')}<strong>배포 정보 확인 완료</strong><span class="ws-badge">${esc(info.type)}</span></div><p>${esc(info.name)} · ${esc(info.platform)}</p><small>필수 파일 확인 · 원본 그대로 배포 · 실행 검증 제외</small>${info.workflow?.steps?.length?`<p>동작 흐름 ${info.workflow.steps.length}단계가 상세 화면에 함께 표시됩니다.</p>`:''}<div class="ws-package-facts"><span>시작 파일 <b>${esc(info.entryPoint)}</b></span><span>필요 환경 <b>${esc(info.requirements.join(' · ')||'별도 기재 없음')}</b></span></div><button type="button" class="sq-link" data-package-apply>${p.applied?'ZIP 정보 다시 적용':'ZIP 정보를 입력란에 적용'}</button><small>이름·소개·유형·설치 안내 등이 바뀝니다. 조직·업무 분야·담당자·조회 권한은 유지됩니다.</small></div>`;
}
function decoratePackageForm(form){
 if(form.id!=='sq-register-form')return;
 const d=runtime.draft;
 if(runtime.step===1){
  form.insertAdjacentHTML('afterbegin',`<div class="ws-package-import"><div>${icon('package-open')}<strong>배포 Skill로 준비하셨나요?</strong><p>ZIP의 배포 정보로 유형과 설명을 채워드려요. 읽지 못해도 직접 입력하여 등록할 수 있어요.</p></div><label class="sq-secondary">ZIP에서 불러오기<input type="file" name="artifact" accept=".zip" class="sq-sr" data-package-import aria-label="배포 ZIP에서 정보 불러오기"></label></div>`);
 }
 if(d.mode==='file'&&d.file){
  const anchor=form.querySelector('[data-upload="artifact"]')||form.querySelector('.ws-package-import');
  if(anchor)anchor.insertAdjacentHTML('afterend',packagePanel(d));
  else form.insertAdjacentHTML('afterbegin',packagePanel(d));
 }
}
function applyPackageFields(d,result){
 for(const key of ['name','desc','platform','type','environment','changes','guide'])d[key]=result.metadata[key];
 d.workflow=result.metadata.workflow||null;
 d.workTags=result.metadata.workTags.join(', ');
 d.mode='file';d.packageInspection.applied=true;
}
async function inspectSelectedPackage(file){
 const d=runtime.draft;
 const check={state:'loading'};d.packageInspection=check;
 if($('#sq-register-form'))wizard();
 const body=new FormData();body.append('artifact',file);
 try{
  const result=await requestAPI('/api/packages/inspect','POST',body);
  if(runtime.draft!==d||d.file!==file||d.packageInspection!==check)return;
  // Keep edits entered while the request was in flight.
  captureDraft();check.state='ready';check.result=result;
  if(result.recognized&&!runtime.releaseId&&!d.name.trim()&&!d.desc.trim())applyPackageFields(d,result);
 }catch(error){
  if(runtime.draft!==d||d.file!==file||d.packageInspection!==check)return;
  check.state='error';check.error=error.message;
 }
 if(runtime.draft===d&&$('#sq-register-form'))wizard();
}
function packageBlockingError(d){
 // Metadata inspection is advisory. Publish validates the actual file independently.
 return '';
}
root.addEventListener('change',e=>{
 if(!e.target.matches('[data-package-import]'))return;e.stopImmediatePropagation();
 try{selectFiles('artifact',[...e.target.files]);}catch(error){showError(error);}
},true);
root.addEventListener('click',e=>{
 if(e.target.closest('[data-package-retry]')){e.preventDefault();captureDraft();inspectSelectedPackage(runtime.draft.file);}
 if(e.target.closest('[data-package-apply]')){e.preventDefault();captureDraft();applyPackageFields(runtime.draft,runtime.draft.packageInspection.result);wizard();}
});
function deploymentLinks(x,tab){
 const versions=tab==='versions'?x.versions.filter(v=>v.deploymentUrl):x.versions.filter(v=>v.n===x.active&&v.deploymentUrl);
 if(!versions.length||!['connect','versions'].includes(tab))return;
 $('#sq-dialog-body').insertAdjacentHTML('beforeend',`<section class="ws-package"><strong>배포 정보</strong><p>파일은 원본 그대로 제공됩니다. 아래 JSON에는 도구 ID·배포 번호·필수 파일·버전 확인 주소가 연결되어 있습니다.</p>${versions.map(v=>`<a class="sq-link" href="${esc(v.deploymentUrl)}" download>v${v.n} 배포 정보 JSON 받기</a>`).join(' ')}<small>이 정보만으로 PC 설치나 실행 시 버전 확인 코드가 자동 적용되지는 않습니다.</small></section>`);
}

// Commands are shown and copied only. The web server never executes them.
function commandFields(d){
 return `<section class="ws-command-fields"><div class="sq-callout"><strong>파일 없이 명령어로 설치하는 도구</strong><br>지원하는 범위에 실제 명령어를 적어주세요. 비워 둔 범위는 ‘지원 안 함’으로 표시됩니다. 사용자는 범위를 직접 선택한 다음 명령어를 복사합니다. 토큰·비밀번호는 넣지 마세요.</div><div class="sq-form-grid"><label class="sq-field"><span>현재 디렉토리 · 프로젝트</span><small>사용자가 사용할 프로젝트 폴더에서 실행하는 명령어</small><textarea name="commandProject" maxlength="8000" spellcheck="false" placeholder="해당 도구가 지원하는 프로젝트 설치 명령어">${esc(d.commandProject||'')}</textarea></label><label class="sq-field"><span>전역 · 내 계정</span><small>현재 사용자 계정의 여러 프로젝트에서 사용하는 명령어</small><textarea name="commandUser" maxlength="8000" spellcheck="false" placeholder="해당 도구가 지원하는 사용자 범위 설치 명령어">${esc(d.commandUser||'')}</textarea></label></div></section>`;
}
function commandScopePanel(x,v){
 return `<section class="ws-command-install" data-command-tool="${x.id}" data-command-version="${v?.n}"><h3>어디에 설치할까요?</h3><p class="sq-note">범위를 먼저 선택하세요. 현재 디렉토리는 터미널에서 열어 둔 프로젝트 폴더, 전역은 내 계정 기준입니다.</p><div class="ws-scope-grid">${[['project','folder','현재 디렉토리','이 프로젝트에서 사용'],['user','user','전역 · 내 계정','여러 프로젝트에서 사용']].map(([scope,ic,title,desc])=>`<button type="button" class="ws-scope-choice" data-action="choose-command-scope" data-scope="${scope}" aria-pressed="false" ${v?.commands?.[scope]?'':'disabled'}>${icon(ic)}<strong>${title}</strong><small>${v?.commands?.[scope]?desc:'등록자가 지원하지 않은 범위'}</small></button>`).join('')}</div><div class="ws-command-result" hidden><p data-command-hint class="sq-note"></p><pre tabindex="0"><code data-command-text></code></pre>${button('copy-install-command','명령어 복사','sq-primary','type="button"')}<p class="sq-note">복사 후 안내된 터미널에서 직접 실행하세요. 웹에서 실행하지 않습니다. 실제 적용 범위는 등록자가 제공한 명령어를 확인하세요.</p></div></section>`;
}
async function selectedCommand(panel,scope){
 const x=await requestAPI(`/api/tools/${panel.dataset.commandTool}`);
 const v=x.versions.find(v=>v.n===Number(panel.dataset.commandVersion));
 if(!v||v.deleted||v.withdrawn||!v.commands?.[scope])throw Error('사용할 수 없는 명령어입니다. 권한·배포 상태를 확인하세요.');
 return v.commands[scope];
}
actions['choose-command-scope']=async b=>{
 const panel=b.closest('[data-command-tool]'),scope=b.dataset.scope,token=Symbol();
 panel._scopeRequest=token;delete panel.dataset.selectedScope;
 panel.querySelector('.ws-command-result').hidden=true;
 panel.querySelectorAll('[data-scope]').forEach(el=>el.setAttribute('aria-pressed','false'));
 const command=await selectedCommand(panel,scope);
 if(!panel.isConnected||panel._scopeRequest!==token)return;
 panel.dataset.selectedScope=scope;
 panel.querySelectorAll('[data-scope]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.scope===scope)));
 panel.querySelector('[data-command-text]').textContent=command;
 panel.querySelector('[data-command-hint]').textContent=scope==='project'?'먼저 터미널에서 설치할 프로젝트 폴더로 이동하세요.':'내 사용자 계정의 설정에 적용됩니다. 다른 프로젝트에서도 영향을 받을 수 있습니다.';
 panel.querySelector('.ws-command-result').hidden=false;
};
actions['copy-install-command']=async b=>{
 const panel=b.closest('[data-command-tool]');
 if(!panel.dataset.selectedScope)throw Error('설치 범위를 먼저 선택하세요.');
 const scope=panel.dataset.selectedScope,token=panel._scopeRequest,command=await selectedCommand(panel,scope);
 if(!panel.isConnected||panel._scopeRequest!==token||panel.dataset.selectedScope!==scope)return;
 try{await navigator.clipboard.writeText(command);announce('선택한 범위의 명령어를 복사했습니다.');b.textContent='복사 완료';}
 catch{throw Error('브라우저에서 자동 복사를 허용하지 않습니다. 표시된 명령어를 선택하여 복사하세요.');}
};

function storageSize(bytes){return bytes==null?'확인 불가':bytes>=1073741824?`${(bytes/1073741824).toFixed(2)} GB`:`${(bytes/1048576).toFixed(1)} MB`;}
async function fetchStorageCapacity(){
 const token=runtime.storageToken=(runtime.storageToken||0)+1;let result;
 try{result=await requestAPI('/api/storage/limits');}catch(error){if(token!==runtime.storageToken)return false;throw error;}
 if(token!==runtime.storageToken)return false;
 server.storage={...server.storage,...result.storage};return true;
}
function storageCapacityPanel(){
 const s=server.storage||{},dummy=server.dataMode==='dummy',auto=s.mode==='auto';
 const pct=s.quota>0?Math.min(100,s.used/s.quota*100):0;
 return `<div class="ws-panel-head"><div><h2>파일을 위한 여유 공간</h2><p>배포 파일·요청 첨부의 사용량과 서버 디스크 상태를 함께 확인하세요.</p></div><div class="sq-row-actions">${button('storage-refresh',icon('refresh-cw')+' 새로고침','sq-secondary')}${button('storage-dialog','이전 버전 정리','sq-primary')}</div></div><div class="ws-capacity-cards"><article><span>${icon('package')} 플랫폼 파일</span><strong>${storageSize(s.used)}</strong><small>이전 버전·첨부파일 포함</small></article><article><span>${icon('hard-drive')} 디스크 남은 공간</span><strong>${storageSize(s.diskFree)}</strong><small>전체 ${storageSize(s.diskTotal)} 중 사용 가능한 공간</small></article><article><span>${icon('upload-cloud')} 현재 추가 저장 가능</span><strong>${storageSize(s.available)}</strong><small>한도와 확보할 여유 공간을 모두 반영</small></article></div><div class="ws-capacity-meter"><div><strong>${auto?'자동 계산한 현재 플랫폼 한도':'플랫폼 파일 저장 한도'}</strong><span>${storageSize(s.used)} / ${storageSize(s.quota)}</span></div><div class="ws-capacity-track" role="meter" aria-label="플랫폼 저장 한도 대비 사용량" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct.toFixed(1)}"><span style="width:${pct}%"></span></div></div>${!s.diskKnown?'<p class="ws-capacity-warning" role="status">디스크 용량을 확인할 수 없습니다. 서버 저장소 연결·권한을 확인하세요. 확인 전에는 파일 업로드를 허용하지 않습니다.</p>':s.overLimit?'<p class="ws-capacity-warning" role="status">저장 한도 또는 여유 공간 기준에 도달했습니다. 기존 파일은 유지되며 새 파일 업로드가 제한됩니다.</p>':''}<form id="sq-capacity-form" data-revision="${s.limitRevision||0}"><fieldset ${dummy?'disabled':''}><legend>저장 한도 설정</legend><div class="ws-capacity-choices"><label><input type="radio" name="mode" value="manual" ${!auto?'checked':''}><span><strong>직접 지정</strong><small>이 플랫폼에 사용할 최대 용량을 정합니다.</small></span></label><label><input type="radio" name="mode" value="auto" ${auto?'checked':''}><span><strong>서버 여유 공간에 맞추기</strong><small>다른 프로그램의 사용량이 바뀌면 함께 계산합니다.</small></span></label></div><div class="sq-form-grid"><label class="sq-field"><span>플랫폼 최대 용량 (GB)</span><input name="quotaGB" type="number" min="0.001" max="1048576" step="any" value="${(s.configuredQuota||s.quota||5*1073741824)/1073741824}" ${auto?'disabled':''} required><small>직접 지정할 때 적용합니다. GB는 1,024 MB 기준입니다.</small></label><label class="sq-field"><span>서버에 남겨둘 여유 공간 (GB)</span><input name="reserveGB" type="number" min="0" max="1048576" step="any" value="${(s.reserve??1073741824)/1073741824}" required><small>예: 10을 입력하면 디스크에 최소 10GB를 남깁니다.</small></label></div><p class="sq-note" id="ws-capacity-rule">${auto?'자동 계산: 현재 플랫폼 파일 사용량 + 디스크 남은 공간 − 남겨둘 여유 공간':'추가 저장 가능량은 설정한 한도와 실제 디스크 여유 공간 중 작은 쪽을 따릅니다.'}</p><p class="sq-note">설정은 저장 즉시 다음 업로드부터 적용됩니다. 사용량보다 낮게 설정해도 기존 파일은 지우지 않습니다.</p><div class="sq-actions"><button class="sq-primary" type="submit">한도 저장</button></div></fieldset><p id="ws-capacity-message" role="status" aria-live="polite"></p></form><div class="ws-capacity-foot"><p>${dummy?'샘플 용량입니다. 실제 서버를 조회하지 않으며 설정을 저장할 수 없습니다.':`확인 시각 ${s.checkedAt?new Date(s.checkedAt*1000).toLocaleTimeString('ko-KR'):''} · ${s.source==='admin'?'관리자가 저장한 설정':'설정 파일의 기본값'}`}</p><p>디스크 용량은 파일 저장 폴더가 있는 드라이브·마운트 기준입니다. 서버 전체의 다른 드라이브나 원격 MongoDB 저장 공간은 포함하지 않습니다. 용량 계산만으로 기존 파일을 자동 삭제하지 않습니다.</p></div>`;
}
actions['storage-refresh']=async()=>{await fetchStorageCapacity();renderWorkspace();};
root.addEventListener('change',e=>{
 if(!e.target.matches('#sq-capacity-form [name=mode]'))return;
 const form=e.target.form,auto=e.target.value==='auto';
 form.elements.quotaGB.disabled=auto;
 form.querySelector('#ws-capacity-rule').textContent=auto?'자동 계산: 현재 플랫폼 파일 사용량 + 디스크 남은 공간 − 남겨둘 여유 공간':'추가 저장 가능량은 설정한 한도와 실제 디스크 여유 공간 중 작은 쪽을 따릅니다.';
});
root.addEventListener('submit',e=>{
 const form=e.target;if(form.id!=='sq-capacity-form')return;
 e.preventDefault();e.stopImmediatePropagation();if(form.dataset.busy)return;
 const message=form.querySelector('#ws-capacity-message'),quota=Number(form.elements.quotaGB.value),reserve=Number(form.elements.reserveGB.value);
 const quotaBytes=Math.round(quota*1073741824),reserveBytes=Math.round(reserve*1073741824);
 if(!Number.isFinite(quota)||!Number.isFinite(reserve)||quotaBytes<1048576||reserve<0){showError({message:'한도는 최소 1MB, 여유 공간은 0 이상으로 입력하세요.'},message);return;}
 form.dataset.busy='true';const button=form.querySelector('[type=submit]');button.disabled=true;message.setAttribute('role','status');message.setAttribute('aria-live','polite');message.textContent='저장하고 있습니다.';
 return requestAPI('/api/storage/limits','PUT',{mode:form.elements.mode.value,quotaBytes,reserveBytes,expectedRevision:Number(form.dataset.revision)})
 .then(result=>{
  // A bootstrap started before this save must not restore an older policy/revision.
  runtime.refreshToken=(runtime.refreshToken||0)+1;
  runtime.storageToken=(runtime.storageToken||0)+1;
  server.storage={...server.storage,...result.storage};form.dataset.revision=String(server.storage.limitRevision);
  renderWorkspace();
  const status=$('#ws-capacity-message');if(status){status.setAttribute('role','status');status.setAttribute('aria-live','polite');status.textContent=result.pending?'한도 설정은 저장되었습니다. 이력은 다음 조회 시 동기화됩니다.':'저장했습니다. 기존 파일은 그대로 유지됩니다.';}
 })
 .catch(error=>{showError(error,$('#ws-capacity-message'));})
 .finally(()=>{delete form.dataset.busy;button.disabled=false;});
},true);

// People, connection entry and declared workflows share the existing page shell.
let peopleRanks=null,peopleRanksError='',peopleRanksLoading=false,peopleLoadSerial=0,profileSignature='';
const baseRankItems=rankItems,baseRankRow=rankRowHTML,baseRenderRanks=renderRanks;
const basePeopleRender=render,basePeopleRefresh=refresh,baseRankInfo=actions['rank-info'];
const peopleModes=$('.sq-rank-modes');
peopleModes.setAttribute('aria-label','도구·구성원 순위');
peopleModes.insertAdjacentHTML('beforeend',button('rank-mode','기여도 순위','','type="button" data-mode="people" aria-pressed="false"'));
$('.sq-chart-controls').insertAdjacentHTML('beforeend','<span id="sq-my-rank" class="sq-my-rank" hidden></span>');
$('#sq-session').classList.add('sq-profile');
$('#sq-session').insertAdjacentHTML('afterend',`<a id="sq-connection-key" class="sq-quiet sq-key-link" href="/local-access" aria-label="내 연결 KEY 발급·관리" title="연결 KEY 발급·관리">${icon('key-round')}</a>`);
// Equal hitboxes and one shared gap keep all personal action icons evenly spaced.
const headerIconGroup=document.createElement('div');
headerIconGroup.className='sq-header-icon-group';
headerIconGroup.setAttribute('role','group');headerIconGroup.setAttribute('aria-label','개인 도구');
$('#sq-session').after(headerIconGroup);
headerIconGroup.append($('.ws-bell'),$('#sq-connection-key'),...$$('.sq-header-actions>[data-action="fullscreen"],.sq-header-actions>[data-action="logout"]'));
$('#sq-connection-key').addEventListener('click',event=>{
 if(server.dataMode==='dummy'){
  event.preventDefault();openModal('나의 연결 KEY','개인 연결',`<div class="sq-detail-hero"><h3>내 사번으로, 안전하게 연결.</h3><p>실제 데이터 모드에서 연결 KEY를 발급할 수 있습니다. 사번당 활성 키는 하나이며 재발급하면 이전 키는 즉시 사용할 수 없습니다.</p></div>`);
 }
});
root.addEventListener('error',event=>{
 if(event.target.matches?.('.sq-profile-photo,.sq-person-photo')){event.target.hidden=true;event.target.closest('.sq-profile-avatar,.sq-person-avatar')?.classList.add('is-fallback');}
},true);
function renderProfile(){
 const u=server.user||{},name=u.emp_name||u.name||'사용자',org=u.dept||u.org||'공통';
 const photo=server.dataMode!=='dummy'&&u.photoUrl==='/api/me/photo'?u.photoUrl:'';
 const signature=JSON.stringify([u.id,name,org,photo]);
 // Base refresh writes the session label, so rebuild only if that text replaced the profile.
 if(signature===profileSignature&&$('#sq-session .sq-profile-name'))return;
 profileSignature=signature;
 $('#sq-session').innerHTML=`<span class="sq-profile-copy"><strong class="sq-profile-name">${esc(name)}${/\bTL$/.test(name)?'':' <span>TL</span>'}</strong><small>${esc(org)}</small></span><span class="sq-profile-avatar"><span aria-hidden="true">${esc([...name][0]||'?')}</span>${photo?`<img class="sq-profile-photo" src="${photo}" width="34" height="34" alt="" referrerpolicy="no-referrer">`:''}</span>`;
 $('#sq-session').setAttribute('aria-label',`${name} · ${org}`);
}
async function loadPeopleRanks(){
 const serial=++peopleLoadSerial;peopleRanksLoading=true;peopleRanksError='';
 try{const result=await requestAPI('/api/people/ranking');if(serial===peopleLoadSerial)peopleRanks=result;}
 catch(error){if(serial===peopleLoadSerial){peopleRanks=null;peopleRanksError=error.message;}}
 finally{if(serial===peopleLoadSerial)peopleRanksLoading=false;}
}
rankItems=function(){return state.rankMode==='people'?(peopleRanks?.items||[]):baseRankItems();};
rankRowHTML=function(row,rank){
 if(state.rankMode!=='people')return baseRankRow(row,rank);
 const name=row.name||'구성원',dept=row.org||'공통';
 const photo=server.dataMode!=='dummy'&&/^\/api\/people\/[0-9]{1,20}\/photo$/.test(row.photoUrl||'')?row.photoUrl:'';
 return `<div class="sq-rank-row sq-person-rank${row.isMe?' is-me':''}" data-rank="${rank}"><span class="sq-rank-number">${rank}</span><div class="sq-person-info"><div class="sq-person-identity"><span class="sq-person-dept" title="${esc(dept)}">${esc(dept)}</span><span class="sq-person-name-group"><strong class="sq-person-name" title="${esc(name)}">${esc(name)}</strong>${row.isMe?'<span class="sq-me-badge">나</span>':''}<span class="sq-person-avatar" aria-hidden="true"><span>${esc([...name][0]||'?')}</span>${photo?`<img class="sq-person-photo" src="${photo}" width="28" height="28" alt="" referrerpolicy="no-referrer">`:''}</span></span></div><span class="sq-person-counts"><span title="등록한 도구">${icon('package')}${num(row.registered)}</span><span title="받은 좋아요">${icon('heart')}${num(row.likes)}</span><span title="고유 다운로드">${icon('arrow-down-to-line')}${num(row.downloads)}</span></span></div><span class="sq-person-score"><strong>${num(row.score)}</strong><small>점</small></span></div>`;
};
renderRanks=function(){
 baseRenderRanks();const isPeople=state.rankMode==='people';
 $('.sq-chart').dataset.rankType=isPeople?'people':'tools';
 $('#sq-chart-title').innerHTML=isPeople?'기여도 순위 <span lang="en">TOP 10</span>':'인기 <span lang="en">TOP 10</span>';
 $('.sq-chart-labels>span:last-child').textContent=isPeople?'공유 기여도':'좋아요 · 다운로드';
 const me=$('#sq-my-rank');me.hidden=!isPeople;
 if(!isPeople)return;
 $('#sq-rank-range').textContent='기여도 순위';$('#sq-rank-period').textContent='전체 기간 · 구성원 기여도';
 const own=peopleRanks?.me;me.textContent=own?.rank?`내 순위 ${num(own.rank)}위 · ${num(own.score)}점`:'도구를 공유하고 함께 성장해요';
 if(peopleRanks?.asOf)$('#sq-chart-time').textContent=new Date(peopleRanks.asOf*1000).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',timeZone:'Asia/Seoul'});
 if(peopleRanksLoading&&!peopleRanks)$('#sq-rank-list').innerHTML='<div class="sq-empty" role="status">공유 기여도를 집계하고 있어요.</div>';
 else if(peopleRanksError)$('#sq-rank-list').innerHTML=`<div class="sq-empty" role="status"><p>${esc(peopleRanksError)}</p>${button('rank-retry','다시 불러오기','sq-link')}</div>`;
 else if(!peopleRanks?.items?.length)$('#sq-rank-list').innerHTML='<div class="sq-empty">첫 번째 도구를 공유하고<br>함께 성장해요.</div>';
};
render=function(){basePeopleRender();renderProfile();};
refresh=async function(){
 if(state.rankMode==='people')await loadPeopleRanks();
 await basePeopleRefresh();
};
actions['rank-mode']=async b=>{
 const mode=b.dataset.mode;if(!['recent','total','people'].includes(mode)||mode===state.rankMode)return;
 runtime.token++;runtime.busy=false;stopAuto();state.rankMode=mode;state.rankPage=0;
 if(mode==='people'){
  const pending=loadPeopleRanks();render();await pending;
  if(state.rankMode==='people')render();
 }else render();
};
actions['rank-retry']=async()=>{const pending=loadPeopleRanks();render();await pending;render();};
actions['rank-info']=()=>{
 if(state.rankMode!=='people')return baseRankInfo();
 const weights=peopleRanks?.weights||{registered:5,likes:2,downloads:1};
 openModal('함께 쓰는 도구를 만든 사람들.','기여도 순위 · 전체 기간',`<div class="sq-detail-hero"><h3>나눈 노하우가 쌓이는 순위.</h3><p>등록한 도구와 그 도구를 이용한 동료들의 반응을 모아 공유 기여도를 보여드립니다.</p></div><div class="sq-power-formula"><span>등록 도구 <strong>× ${weights.registered}</strong></span><span>받은 좋아요 <strong>× ${weights.likes}</strong></span><span>고유 다운로드 <strong>× ${weights.downloads}</strong></span></div><div class="sq-callout">전체 기간을 기준으로 집계합니다. 도구는 버전 수와 관계없이 한 번만 반영합니다. 좋아요 취소·삭제된 도구·비활성 사용자는 순위에 반영하지 않습니다.<br><br>본인 도구에 대한 좋아요·다운로드, 같은 사람이 같은 도구를 반복 다운로드하거나 업데이트한 이력은 추가 점수가 없습니다. 조회 승인이 필요한 도구의 개별 정보는 이 화면에 표시하지 않습니다.</div><p class="sq-note">${esc(peopleRanks?.tieBreak||'동점이면 등록 도구 수 → 받은 좋아요 수 → 고유 다운로드 수 → 사번 순으로 정렬합니다.')}</p>${button('rank-refresh','집계 새로고침','sq-primary')}`);
};
function workflowDiagram(workflow){
 const steps=Array.isArray(workflow?.steps)?workflow.steps.slice(0,8):[];
 if(!steps.length)return '';
 return `<details class="sq-workflow" aria-labelledby="sq-workflow-title"><summary class="sq-workflow-heading"><span class="sq-workflow-heading-copy"><span class="sq-workflow-eyebrow" lang="en">HOW IT WORKS</span><strong id="sq-workflow-title">이렇게 동작해요.</strong></span><span class="sq-workflow-toggle"><span class="sq-workflow-count">${steps.length}단계</span><span class="sq-workflow-expand">펼치기</span><span class="sq-workflow-collapse">접기</span><span class="sq-workflow-chevron" aria-hidden="true">${icon('chevron-down')}</span></span></summary><div class="sq-workflow-body"><ol class="sq-workflow-steps" aria-label="동작 순서">${steps.map((step,i)=>`<li><span class="sq-workflow-number" aria-hidden="true">${String(i+1).padStart(2,'0')}</span><div class="sq-workflow-step"><strong>${esc(step.title)}</strong>${step.description?`<p>${esc(step.description)}</p>`:''}</div></li>`).join('')}</ol><p class="sq-note"><span class="sq-workflow-source">배포 정보 기반</span>등록자가 정리한 동작 순서입니다. 실제 실행 상태를 표시하지 않습니다.</p></div></details>`;
}
const basePeopleDetail=detail;
detail=async function(id,tab='intro'){
 const rendered=await basePeopleDetail(id,tab);
 if(!rendered||tab!=='intro'||!$('#sq-dialog').open||runtime.detailId!==+id||runtime.detailTab!=='intro')return;
 const x=getItem(id);if(x?.access!=='approved')return;
 $('#sq-workflow-title')?.closest('.sq-workflow').remove();
 const diagram=workflowDiagram(x.workflow);
 if(diagram){const anchor=$('#sq-dialog-body .sq-detail-hero');anchor?.insertAdjacentHTML('afterend',diagram);mountIcons();}
};

// Administrator-published downloads are kept separate from community tool rankings.
const axCategories={workspace:'AX Workspace',plugin:'플러그인',integration:'연동 도구',other:'기타'};
let axFiles=[],axFilter='all',axFile=null,axLoadToken=0,axUploadBusy=false,axMaxFileBytes=128*1048576-65536;
async function loadAxWorkspace(){
 const token=++axLoadToken,result=await requestAPI('/api/ax-workspace');
 if(token!==axLoadToken)return false;
 axFiles=result.files;if(Number.isSafeInteger(result.maxFileBytes)&&result.maxFileBytes>=0)axMaxFileBytes=result.maxFileBytes;return true;
}
function renderAxWorkspace(){
 const admin=server.user.role==='admin',rows=axFiles.filter(x=>axFilter==='all'||x.category===axFilter);
 workspace.innerHTML=`<div class="ws-ax-intro"><span class="ws-ax-symbol">${icon('monitor-down')}</span><div><h2>설치부터 연결까지, 한곳에서.</h2><p>AX Workspace 설치 파일과 업무에 필요한 플러그인·연동 도구를 내려받으세요.</p></div>${admin?button('ax-register',icon('plus')+' 파일 등록','sq-primary'):''}</div><div class="ws-board-head"><div class="ws-segment ws-ax-filters">${Object.entries({all:'전체',...axCategories}).map(([key,label])=>button('ax-filter',label,'',`data-category="${key}" aria-pressed="${axFilter===key}"`)).join('')}</div><span class="ws-ax-count">${rows.length}개 파일</span></div><div class="ws-ax-grid">${rows.map(x=>`<article class="ws-ax-card"><div class="ws-ax-card-top"><span class="ws-ax-symbol">${icon(x.category==='workspace'?'monitor-down':x.category==='plugin'?'blocks':'cable')}</span>${badge(axCategories[x.category]||'기타')}</div><h2>${esc(x.name)}</h2><p>${esc(x.description)}</p><div class="ws-ax-file"><strong>${esc(x.fileName)}</strong><span>${esc(x.version?'v'+x.version:'버전 미입력')} · ${fileSize(x.size)}</span></div><div class="ws-ax-card-footer"><small>${dated(x.created)} 등록</small><a class="sq-primary" href="${esc(x.downloadUrl)}" download aria-label="${esc(x.name)} 다운로드">${icon('download')} 다운로드</a></div></article>`).join('')||blank('folder-down',axFilter==='all'?'아직 등록된 파일이 없습니다.':'이 분류에 등록된 파일이 없습니다.',admin?'파일 등록을 눌러 설치 파일이나 플러그인을 공유하세요.':'관리자가 파일을 등록하면 이곳에서 내려받을 수 있습니다.')}</div>`;
 mountIcons();
}
function axUploadArea(){
 return `<section class="ws-upload-area" data-ax-drop><div class="ws-drop-zone"><span class="ws-upload-icon">${icon('cloud-upload')}</span><h3>배포할 파일을 여기에 놓으세요</h3><p>ZIP · EXE · MSI · PS1 · MD · 최대 ${fileSize(axMaxFileBytes)}</p><button type="button" class="sq-secondary" data-action="ax-pick">${icon('plus')} 파일 선택</button><input class="sq-sr" type="file" id="sq-ax-file" aria-label="AX Workspace 배포 파일 선택" accept=".zip,.exe,.msi,.ps1,.md"></div><div class="ws-selected-files" aria-live="polite">${axFile?`<div class="ws-selected-file">${icon('file')}<span><strong>${esc(axFile.name)}</strong><small>${fileSize(axFile.size)}</small></span>${button('ax-remove',icon('x'),'sq-icon','type="button" aria-label="선택한 파일 취소"')}</div>`:''}</div></section>`;
}
function chooseAxFile(files){
 if(!files.length)return;
 if(files.length!==1||!files[0].size||files[0].size>axMaxFileBytes||!(/\.(zip|exe|msi|ps1|md)$/i.test(files[0].name)))throw Error(`ZIP·EXE·MSI·PS1·MD 파일을 하나 선택하세요. 빈 파일은 등록할 수 없고 최대 ${fileSize(axMaxFileBytes)}입니다.`);
 axFile=files[0];refreshAxFile();
}
function refreshAxFile(){const area=$('[data-ax-drop]');if(area){area.outerHTML=axUploadArea();mountIcons();}}
Object.assign(actions,{
 'ax-workspace':async()=>{closeModal();navigate('ax');const token=runtime.detailLoadToken;try{await loadAxWorkspace();if(token===runtime.detailLoadToken&&state.route==='ax')renderAxWorkspace();}catch(error){if(token===runtime.detailLoadToken&&state.route==='ax')throw error;}},
 'ax-filter':b=>{axFilter=b.dataset.category;renderAxWorkspace();},
 'ax-register':()=>{
  if(server.user.role!=='admin')return;axFile=null;
  openModal('배포 파일 등록','AX Workspace · 관리자',`<form id="sq-ax-form"><div class="sq-form-grid"><label class="sq-field wide"><span>이름 *</span><input name="name" maxlength="100" required placeholder="예: AX Workspace Windows 설치 파일"></label><label class="sq-field wide"><span>설명 *</span><textarea name="description" maxlength="2000" required placeholder="어떤 파일인지, 설치 전에 알아둘 내용을 적어주세요."></textarea></label><label class="sq-field"><span>분류</span><select name="category">${Object.entries(axCategories).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select></label><label class="sq-field"><span>배포 버전 *</span><input name="version" required maxlength="40" placeholder="예: 1.0.0"></label></div>${axUploadArea()}<p class="sq-note">등록하면 사내 사용자가 바로 내려받을 수 있습니다. 선택한 파일 형식 그대로 배포됩니다.</p><div class="sq-actions"><button class="sq-primary">파일 등록</button></div></form>`);
 },
 'ax-pick':()=>$('#sq-ax-file')?.click(),
 'ax-remove':()=>{if(!axUploadBusy){axFile=null;refreshAxFile();}}
});
root.addEventListener('change',e=>{if(e.target.id!=='sq-ax-file')return;try{chooseAxFile([...e.target.files]);}catch(error){e.target.value='';showError(error);}});
for(const type of ['dragenter','dragover','dragleave','drop'])root.addEventListener(type,e=>{
 const area=e.target.closest('[data-ax-drop]');if(!area)return;e.preventDefault();if(axUploadBusy)return;
 area.classList.toggle('is-dragging',type==='dragenter'||type==='dragover');
 if(type==='drop')try{chooseAxFile([...e.dataTransfer.files]);}catch(error){showError(error);}
});
root.addEventListener('submit',e=>{
 const form=e.target;if(form.id!=='sq-ax-form')return;e.preventDefault();e.stopImmediatePropagation();
 if(axUploadBusy||form.dataset.saved)return;
 if(!axFile){showError(Error('등록할 파일을 선택해 주세요.'));return;}
 const token=runtime.detailLoadToken,body=new FormData();let errorToken=token;body.append('metadata',JSON.stringify(Object.fromEntries(new FormData(form))));body.append('file',axFile);
 axUploadBusy=true;form.querySelectorAll('button,input,textarea,select').forEach(x=>x.disabled=true);
 (async()=>{
  await requestAPI('/api/ax-workspace','POST',body);form.dataset.saved='true';
  if(token!==runtime.detailLoadToken)return;
  axFile=null;axFilter='all';closeModal();navigate('ax');const listToken=runtime.detailLoadToken;errorToken=listToken;
  await afterWorkspaceSave(async()=>{await loadAxWorkspace();if(listToken===runtime.detailLoadToken&&state.route==='ax'){renderAxWorkspace();announce('배포 파일을 등록했습니다.');}},form);
 })().catch(error=>{if(errorToken===runtime.detailLoadToken)showError(error);}).finally(()=>{axUploadBusy=false;form.querySelectorAll('button,input,textarea,select').forEach(x=>x.disabled=!!form.dataset.saved);});
},true);

// END WORKSPACE EXTENSION
refresh().catch(showError);setInterval(()=>{if(!document.hidden&&!$('#sq-dialog').open&&!runtime.requestBusy)refresh().catch(showError);},300000);

})();
