// Registration drafts stay in this browser tab and belong to one authenticated account.
// Only descriptive fields are persisted: never files, URLs, commands, credentials or inspections.
const registrationDraftFields={name:50,desc:200,workTags:300,platform:30,type:30,org:80,category:80,owner:80,environment:200,changes:1000};
const registrationDraftStorageKey=()=>server.user.id?'ptai.registration-drafts.v1:'+String(server.user.id):null;
function readRegistrationDrafts(){
 try{const raw=sessionStorage.getItem(registrationDraftStorageKey());if(!raw||raw.length>60000)return {};const saved=JSON.parse(raw);return saved&&typeof saved==='object'&&!Array.isArray(saved)?saved:{};}catch{return {};}
}
function clearRegistrationDraft(owner=server.user.id,target=runtime.releaseId,expectedAt=undefined){
 const key=owner?'ptai.registration-drafts.v1:'+String(owner):null;if(!key)return;
 let saved;try{saved=JSON.parse(sessionStorage.getItem(key)||'{}');}catch{return;}
 if(!saved||typeof saved!=='object'||Array.isArray(saved))return;
 const entry=String(target||'new');if(expectedAt!==undefined&&saved[entry]?.at!==expectedAt)return;
 delete saved[entry];
 try{if(Object.keys(saved).length)sessionStorage.setItem(key,JSON.stringify(saved));else sessionStorage.removeItem(key);}catch{}
 if(owner===server.user.id&&target===runtime.releaseId)runtime.draftRestored=false;
}
function registrationDraftRevision(){return readRegistrationDrafts()[String(runtime.releaseId||'new')]?.at??null;}
function saveRegistrationDraft(){
 const d=runtime.draft,key=registrationDraftStorageKey();
 if(!d||!key||runtime.draftOwner!==server.user.id)return false;
 const data={};for(const [name,limit]of Object.entries(registrationDraftFields))data[name]=String(d[name]||'').slice(0,limit);
 data.approval=d.approval===true;data.mode=['file','url','command'].includes(d.mode)?d.mode:'file';
 if(!data.name.trim()&&!data.desc.trim()&&!data.workTags.trim()){clearRegistrationDraft();return true;}
 const saved=readRegistrationDrafts(),now=Date.now(),target=String(runtime.releaseId||'new');
 const step=Math.min(2,Math.max(1,runtime.step||1)),previous=saved[target],identity=runtime.savedDraftIdentity;
 const unchanged=previous&&JSON.stringify(previous.data)===JSON.stringify(data)&&previous.step===step&&identity?.draft===d&&identity.file===d.file&&identity.sequence===(runtime.draftChangeSequence||0);
 saved[target]={at:unchanged?previous.at:Math.max(now,(previous?.at||0)+1),step,data};
 runtime.savedDraftIdentity={draft:d,file:d.file,sequence:runtime.draftChangeSequence||0};
 const entries=Object.entries(saved).filter(([,value])=>value&&Number.isFinite(value.at)&&now-value.at<86400000).sort((a,b)=>b[1].at-a[1].at).slice(0,5);
 try{sessionStorage.setItem(key,JSON.stringify(Object.fromEntries(entries)));runtime.draftStorageFailed=false;return true;}catch{runtime.draftStorageFailed=true;return false;}
}
const experienceCaptureDraft=captureDraft;
captureDraft=function(){if(!runtime.draft)return;experienceCaptureDraft();saveRegistrationDraft();};
register=function(id){
 captureDraft();
 const target=id?Number(id):null,same=runtime.draft&&runtime.draftOwner===server.user.id&&runtime.releaseId===target;
 if(!same){
  runtime.releaseId=target;runtime.draft=freshDraft(target?getItem(target):null);runtime.step=1;runtime.draftOwner=server.user.id;runtime.draftRestored=false;
  const saved=readRegistrationDrafts()[String(target||'new')];
  if(saved?.data&&Number.isFinite(saved.at)&&Date.now()-saved.at<86400000){
   for(const [name,limit]of Object.entries(registrationDraftFields))if(typeof saved.data[name]==='string')runtime.draft[name]=saved.data[name].slice(0,limit);
   if(typeof saved.data.approval==='boolean')runtime.draft.approval=saved.data.approval;
   if(['file','url','command'].includes(saved.data.mode))runtime.draft.mode=saved.data.mode;
   runtime.step=[1,2].includes(saved.step)?saved.step:1;runtime.draftRestored=true;
  }
 }
 wizard();
};
actions.register=b=>register(b?.dataset?.id);
const experienceWizard=wizard;
wizard=function(){
 experienceWizard();saveRegistrationDraft();const form=$('#sq-register-form');if(!form)return;
 const notice=document.createElement('div');notice.className='ws-draft-note';
 notice.innerHTML=`<span>${runtime.draftRestored?'작성 중이던 기본 정보를 불러왔어요. 파일과 설치 안내는 다시 확인해 주세요.':'기본 정보는 이 탭에 임시 보관됩니다. 파일과 연결 정보는 저장하지 않아요.'}</span>${button('discard-registration-draft','초안 지우기','sq-link','type="button"')}`;
 form.prepend(notice);
};
actions['discard-registration-draft']=()=>ask('작성 중인 내용을 지울까요?','현재 등록 초안을 지웁니다. 이미 게시한 도구는 바뀌지 않습니다.',()=>{
 clearRegistrationDraft();runtime.draft=freshDraft(runtime.releaseId?getItem(runtime.releaseId):null);runtime.step=1;wizard();
},'초안 지우기');
const experienceOpenModal=openModal,experienceCloseModal=closeModal;
openModal=function(...args){if(runtime.draft&&$('#sq-register-form')&&!String(args[2]||'').includes('id="sq-register-form"'))captureDraft();return experienceOpenModal(...args);};
closeModal=function(){if($('#sq-register-form'))captureDraft();return experienceCloseModal();};
actions['close-dialog']=closeModal;
$('#sq-dialog').addEventListener('cancel',()=>{if($('#sq-register-form'))captureDraft();});
root.addEventListener('input',event=>{if(!event.target.closest('#sq-register-form'))return;runtime.draftChangeSequence=(runtime.draftChangeSequence||0)+1;clearTimeout(runtime.draftSaveTimer);runtime.draftSaveTimer=setTimeout(()=>{if($('#sq-register-form'))captureDraft();},250);});
root.addEventListener('change',event=>{if(event.target.closest('#sq-register-form')){runtime.draftChangeSequence=(runtime.draftChangeSequence||0)+1;captureDraft();}});
window.addEventListener('pagehide',()=>{if($('#sq-register-form'))captureDraft();});
window.addEventListener('beforeunload',event=>{if($('#sq-register-form'))captureDraft();if(runtime.draftStorageFailed&&runtime.draft){event.preventDefault();event.returnValue='';}});

// Use the same authenticated catalog endpoint as the extension. One bounded page
// is requested at a time, and a late response can never replace another search.
let catalogSearch=null;
let catalogPageSummaries=[];
function clearCatalogPageSummaries(){
 for(const row of catalogPageSummaries){const at=items.indexOf(row);if(at>=0)items.splice(at,1);}
 catalogPageSummaries=[];
}
function resetCatalogSearch(){catalogSearch=null;clearCatalogPageSummaries();}
function webCatalogKey(){return JSON.stringify([server.user.id,state.query,state.type,state.org,state.category,state.sort,state.page]);}
function remoteCatalogActive(){return state.route==='browse'&&!!state.query&&server.dataMode!=='dummy';}
function catalogSearchLive(search){return catalogSearch===search&&remoteCatalogActive()&&webCatalogKey()===search.key;}
function paintCatalogSearch(search){
 if(!catalogSearchLive(search))return;
 const count=$('#sq-result-count'),catalog=$('#sq-catalog'),pages=$('#sq-catalog-pages');
 $$('.sq-filter-count').forEach(node=>node.remove()); // Local counts are not server search counts.
 catalog.setAttribute('aria-busy',String(search.phase==='loading'));
 if(search.phase==='loading'){count.textContent='검색 결과를 확인하고 있어요.';catalog.innerHTML='<div class="sq-empty" role="status"><p>잠시만 기다려 주세요.</p></div>';pages.innerHTML='';return;}
 if(search.phase==='error'){count.textContent='검색 결과를 불러오지 못했어요.';catalog.innerHTML=`<div class="sq-empty"><p role="alert">${esc(search.error)}</p>${button('retry-catalog-search','다시 시도')}</div>`;pages.innerHTML='';mountIcons();return;}
 const result=search.result,total=result.total,rows=result.items.map(row=>{
  const metric=row.statistics||{},existing=getItem(row.id);
  const acceptLike=search.likeGeneration===(runtime.catalogLikeGeneration||0)&&!search.pendingLikes.has(row.id)&&!runtime.likeRequests?.has(row.id);
  if(acceptLike&&typeof row.liked==='boolean'){
   row.liked?state.liked.add(row.id):state.liked.delete(row.id);
   if(existing)existing.likes=Number(metric.likes||0)-(row.liked?1:0);
  }
  const publicCard={...row,icon:existing?.icon||'package',likes:!acceptLike&&existing?existing.likes:Number(metric.likes||0)-(state.liked.has(row.id)?1:0),downloads:Number(metric.downloads||0)};
  // New public summaries can open details through the existing permission check.
  if(!existing){const summary={...publicCard,versions:[],comments:[]};items.push(summary);catalogPageSummaries.push(summary);}
  return publicCard;
 });
 count.textContent=`“${state.query}” 검색 결과 ${num(total)}개${result.complete===false?' (일부 후보 확인)':''}`;
 catalog.innerHTML=rows.map(row=>card(row)).join('')||`<div class="sq-empty"><h3>검색 결과가 없습니다.</h3><p>업무명이나 도구 이름으로 다시 검색해 보세요.${state.org!=='전체 조직'||state.type!=='전체'||state.category!=='모든 업무'?' 선택한 필터도 확인해 주세요.':''}</p>${button('clear-filters','전체 도구 보기')}</div>`;
 if(result.warning)catalog.insertAdjacentHTML('beforeend',`<p class="sq-note">${esc(result.warning)}</p>`);
 pages.innerHTML=state.page||result.nextOffset!==null?`${button('catalog-prev',icon('chevron-left'),'sq-icon',state.page===0?'disabled aria-label="이전 페이지"':'aria-label="이전 페이지"')}<span>${state.page+1} / ${Math.max(1,Math.ceil((result.evaluatedCount??total)/12))}</span>${button('catalog-next',icon('chevron-right'),'sq-icon',result.nextOffset===null?'disabled aria-label="다음 페이지"':'aria-label="다음 페이지"')}`:'';
 mountIcons();revealElements();
}
function loadCatalogSearch(force=false){
 const key=webCatalogKey();
 if(!force&&catalogSearch?.key===key){paintCatalogSearch(catalogSearch);return;}
 clearCatalogPageSummaries();
 const search=catalogSearch={key,phase:'loading',likeGeneration:runtime.catalogLikeGeneration||0,pendingLikes:new Set(runtime.likeRequests?.keys()||[])};paintCatalogSearch(search);
 const params=new URLSearchParams({q:state.query,sort:({discovery:'recommended',recent:'newest',downloads:'downloads',name:'name'})[state.sort]||'recommended',limit:'12',offset:String(state.page*12)});
 if(state.type!=='전체')params.set('type',state.type);
 if(state.org!=='전체 조직'){const org=organizations.find(row=>row.name===state.org);params.set(org?.id?'orgId':'org',org?.id||state.org);}
 if(state.category!=='모든 업무')params.set('category',state.category);
 void requestAPI('/api/catalog?'+params.toString(),'GET',undefined,{timeoutMs:15000}).then(result=>{
  if(!catalogSearchLive(search))return;
  if(!Array.isArray(result.items)||!Number.isFinite(result.total)||result.total<0)throw Error('검색 응답을 확인하지 못했어요. 다시 시도해 주세요.');
  search.phase='success';search.result=result;paintCatalogSearch(search);
 }).catch(error=>{if(!catalogSearchLive(search))return;search.phase='error';search.error=error.message||'연결 상태를 확인한 뒤 다시 시도해 주세요.';paintCatalogSearch(search);});
}
const experienceSearchNavigate=navigate;
navigate=function(...args){if(args[0]!=='browse')resetCatalogSearch();return experienceSearchNavigate(...args);};
const experienceCatalog=renderCatalog;
renderCatalog=function(){
 if(!remoteCatalogActive())resetCatalogSearch();
 const page=state.page;experienceCatalog();
 if(remoteCatalogActive()){state.page=page;loadCatalogSearch();}
};
const experienceLike=actions.like;
actions.like=function(...args){runtime.catalogLikeGeneration=(runtime.catalogLikeGeneration||0)+1;return experienceLike(...args);};
const experienceSearchRefresh=refresh;
refresh=async function(...args){catalogSearch=null;return experienceSearchRefresh(...args);};
actions['retry-catalog-search']=()=>{if(remoteCatalogActive())loadCatalogSearch(true);};

// Zero activity is a list of available tools, not evidence of popularity.
function updateCatalogActivityLabels(){
 if(state.route!=='home')return;
 const rows=filtered(true),hasRank=rows.some(row=>rankMetrics(row).score>0),hasDownloads=rows.some(row=>row.downloads>0);
 $('#sq-chart-title').textContent=hasRank?'동료들이 많이 찾는 도구':'등록된 도구';
 $('#sq-rank-range').textContent=hasRank?(state.rankMode==='recent'?'실시간 순위':'누적 순위'):'등록 도구';
 $('#sq-download-title').textContent=hasDownloads?'최다 다운로드 도구':'먼저 살펴볼 도구';
 const subtitle=$('#sq-download-title')?.parentElement?.querySelector('p');if(subtitle)subtitle.textContent=hasDownloads?'동료들이 자주 꺼내 쓰는 도구.':'아직 다운로드 기록이 없습니다. 필요한 도구를 살펴보세요.';
 $$('.sq-rank-number').forEach(node=>{node.hidden=!hasRank;});
}
const experienceRanks=renderRanks;
renderRanks=function(){experienceRanks();updateCatalogActivityLabels();};
