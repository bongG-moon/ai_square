// Search uses the same authenticated catalog as MCP and the store extension.
// The unsearched catalog and demo data keep their original editorial layout.
const catalogLocalRender=renderCatalog,catalogLocalTabs=renderFilterTabs,catalogOriginalDetail=detail;
const catalogSearch={key:'',generation:0,phase:'idle',result:null,error:'',promise:null};
function usesSharedCatalog(){return state.route==='browse'&&server.dataMode!=='dummy'&&!!state.query.trim();}
function catalogQuery(){
 const params=new URLSearchParams({q:state.query.trim(),sort:({discovery:'recommended',recent:'newest',downloads:'downloads',name:'name'})[state.sort]||'recommended',limit:'12',offset:String(state.page*12),facets:'organizations'});
 if(state.type!=='전체')params.set('type',state.type);
 if(state.org!=='전체 조직')params.set('orgId',organizations.find(row=>row.name===state.org)?.id||'__unknown_organization__');
 if(state.category!=='모든 업무')params.set('categoryId',(server.categories||[]).find(row=>row.name===state.category)?.id||'__unknown_category__');
 return params;
}
// rankAsOf changes only after a successful bootstrap, unlike refreshToken
// which changes before I/O and may belong to a failed refresh.
function catalogKey(){return JSON.stringify([server.user.id,server.rankAsOf||0,catalogQuery().toString()]);}
function catalogCurrent(key,generation){return usesSharedCatalog()&&catalogSearch.key===key&&catalogSearch.generation===generation&&catalogKey()===key;}
function catalogControls(){
 $('#sq-types').innerHTML=toolTypes.map(type=>`<button class="cursor-interaction" data-type="${esc(type)}" aria-pressed="${type===state.type}">${typeLabel(type)}</button>`).join('');
 $('#sq-category').value=state.category;$('#sq-sort').value=state.sort;
}
renderFilterTabs=function(){
 if(!usesSharedCatalog())return catalogLocalTabs();
 const tabs=$('#sq-filter-tabs'),facets=catalogSearch.key===catalogKey()&&catalogSearch.phase==='ready'?catalogSearch.result?.facets:null;
 const names=[...new Set([...organizations.filter(row=>row.enabled!==false||items.some(item=>!item.hidden&&item.org===row.name)).map(row=>row.name),...(facets?.organizations||[]).map(row=>row.name),state.org].filter(name=>name&&name!=='전체 조직'))];
 tabs.setAttribute('aria-label','등록 조직');tabs.classList.add('sq-organization-tabs');
 tabs.innerHTML=['전체 조직',...names].map(name=>{
  const count=facets?(name==='전체 조직'?facets.total:facets.organizations.filter(row=>row.name===name).reduce((sum,row)=>sum+row.count,0)):null;
  return `<button class="cursor-interaction" data-org="${esc(name)}" aria-pressed="${name===state.org}">${esc(name==='전체 조직'?'전체':name)}${count===null?'':` <span class="sq-filter-count">(${num(count)})</span>`}</button>`;
 }).join('');
 scheduleOrgFilter();
};
function catalogEmpty(){
 const filtered=state.org!=='전체 조직'||state.type!=='전체'||state.category!=='모든 업무';
 return `<div class="sq-empty"><h3>검색 결과가 없습니다.</h3><p>“보고서”나 “엑셀 비교”처럼 필요한 업무를 짧게 입력해 보세요.${filtered?' 선택한 조직, 유형 또는 업무 분야를 해제해도 됩니다.':''}</p><div class="sq-actions">${button('catalog-edit-query','검색어 바꾸기')}${filtered?button('catalog-reset-filters','필터 해제'):''}${button('clear-filters','전체 도구 보기')}</div></div>`;
}
function catalogSummary(row){
 const metric=row.statistics||{},existing=getItem(row.id);
 // Search summaries never become bootstrap state, installation authority, or
 // new home ranking rows. Existing shared like controls remain authoritative
 // when a click occurred after this search began.
 const currentLike=catalogSearch.likeGeneration===(runtime.catalogLikeGeneration||0)&&!catalogSearch.pendingLikes?.has(row.id)&&!runtime.likeRequests?.has(row.id);
 return {...existing,...row,likes:!currentLike&&existing?existing.likes:Number(metric.likes||0)-(row.liked===true?1:0),downloads:Number(metric.downloads||0),icon:existing?.icon||({'MCP/Tool':'plug',Skill:'file-text','플러그인/하네스':'layers-2'})[row.type]||'plug'};
}
detail=async function(id,tab='intro'){
 if(!getItem(id)&&catalogSearch.result?.items.some(row=>row.id===Number(id))){
  // A new catalog item can precede the next bootstrap poll. Obtain the normal
  // authenticated item mapping; never fabricate versions/permissions locally.
  const token=invalidateDetailLoad(),user=server.user.id;
  await refresh();
  if(token!==runtime.detailLoadToken||user!==server.user.id)return false;
 }
 return catalogOriginalDetail(id,tab);
};
function drawSharedCatalog(){
 catalogControls();renderFilterTabs();
 const list=$('#sq-catalog'),pages=$('#sq-catalog-pages'),label=$('#sq-result-count');
 pages.innerHTML='';
 if(catalogSearch.phase==='loading'){
  list.setAttribute('aria-busy','true');label.textContent='검색 결과를 확인하고 있습니다.';
  list.innerHTML='<div class="sq-empty" role="status"><h3>필요한 도구를 찾고 있습니다.</h3></div>';return;
 }
 list.removeAttribute('aria-busy');
 if(catalogSearch.phase==='error'){
  label.textContent='검색 결과를 불러오지 못했습니다.';
  list.innerHTML=`<div class="sq-empty" role="alert"><h3>검색을 완료하지 못했습니다.</h3><p>${esc(catalogSearch.error)}</p>${button('catalog-retry','다시 검색','sq-primary')}</div>`;return;
 }
 const result=catalogSearch.result,available=Math.min(result.total,result.evaluatedCount),count=Math.max(1,Math.ceil(available/12));
 label.textContent=`“${state.query}” 검색 결과 ${num(result.total)}개`;
 const warning=result.warning?`<p class="sq-callout" role="status">${esc(result.warning)}</p>`:'';
 list.innerHTML=warning+(result.items.map(row=>card(catalogSummary(row))).join('')||catalogEmpty());
 if(count>1)pages.innerHTML=`${button('catalog-prev',icon('chevron-left'),'sq-icon',state.page===0?'disabled aria-label="이전 페이지"':'aria-label="이전 페이지"')}<span>${state.page+1} / ${count}</span>${button('catalog-next',icon('chevron-right'),'sq-icon',result.nextOffset===null?'disabled aria-label="다음 페이지"':'aria-label="다음 페이지"')}`;
 revealElements();
}
renderCatalog=function(){
 if(!usesSharedCatalog()){
  catalogSearch.generation++;catalogSearch.key='';catalogSearch.phase='idle';catalogSearch.result=null;
  $('#sq-catalog').removeAttribute('aria-busy');
  return catalogLocalRender();
 }
 const key=catalogKey();
 if(catalogSearch.key===key&&catalogSearch.phase!=='idle'){drawSharedCatalog();return catalogSearch.promise;}
 const generation=++catalogSearch.generation;catalogSearch.key=key;catalogSearch.phase='loading';catalogSearch.result=null;
 catalogSearch.likeGeneration=runtime.catalogLikeGeneration||0;catalogSearch.pendingLikes=new Set(runtime.likeRequests?.keys()||[]);
 drawSharedCatalog();
 catalogSearch.promise=(async()=>{
  try{
   const result=await requestAPI('/api/catalog?'+catalogQuery(), 'GET', null, {timeoutMs:15000});
   if(!catalogCurrent(key,generation))return;
   if(!Array.isArray(result.items)||!Number.isSafeInteger(result.total)||!Number.isSafeInteger(result.evaluatedCount)||!result.facets||!Array.isArray(result.facets.organizations))throw Error('검색 결과 형식을 확인하지 못했습니다. 다시 시도해 주세요.');
   const lastPage=Math.max(0,Math.ceil(Math.min(result.total,result.evaluatedCount)/12)-1);
   if(state.page>lastPage){state.page=lastPage;catalogSearch.phase='idle';return renderCatalog();}
   // Reflect another client's latest like state only if no local like changed
   // during the request. Do not insert partial catalog rows into bootstrap data.
   if(catalogSearch.likeGeneration===(runtime.catalogLikeGeneration||0))for(const row of result.items){
    if(typeof row.liked!=='boolean'||catalogSearch.pendingLikes.has(row.id)||runtime.likeRequests?.has(row.id))continue;
    row.liked?state.liked.add(row.id):state.liked.delete(row.id);
    const existing=getItem(row.id);if(existing)existing.likes=Number(row.statistics?.likes||0)-(row.liked?1:0);
   }
   catalogSearch.result=result;catalogSearch.phase='ready';
  }catch(error){
   if(!catalogCurrent(key,generation))return;
   catalogSearch.phase='error';catalogSearch.error=error.message||'서버 연결을 확인한 뒤 다시 시도해 주세요.';
  }
  drawSharedCatalog();mountIcons();
 })();
 return catalogSearch.promise;
};
actions['catalog-retry']=()=>{catalogSearch.phase='idle';return renderCatalog();};
actions['catalog-edit-query']=()=>{$('#sq-query').focus();$('#sq-query').select();};
actions['catalog-reset-filters']=()=>{Object.assign(state,{org:'전체 조직',type:'전체',category:'모든 업무',page:0});render();persist();};
const catalogLike=actions.like;
actions.like=function(...args){runtime.catalogLikeGeneration=(runtime.catalogLikeGeneration||0)+1;return catalogLike?.(...args);};
const catalogRefresh=refresh;
refresh=async function(...args){
 const key=catalogSearch.key,result=await catalogRefresh(...args);
 // A real bootstrap normally changes rankAsOf and redraws immediately. A
 // successful same-stamp refresh still expires cached data on the next render.
 if(catalogSearch.key===key){catalogSearch.generation++;catalogSearch.key='';catalogSearch.phase='idle';}
 return result;
};
