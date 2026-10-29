// Keep the catalog organization choices on one line and put overflow in a
// searchable popover outside the scrolling filter element.
const orgFilterToolbar=$('.sq-toolbar'),orgFilterTabs=$('#sq-filter-tabs');
const orgFilterGroup=document.createElement('div');
orgFilterGroup.className='sq-org-filter-group';
orgFilterTabs.before(orgFilterGroup);
orgFilterGroup.append(orgFilterTabs);
const orgFilterMore=document.createElement('div');
orgFilterMore.className='sq-org-more';
orgFilterMore.hidden=true;
orgFilterMore.innerHTML=`<button type="button" class="sq-org-more-trigger" aria-expanded="false" aria-controls="sq-org-more-panel">조직 더보기 <span aria-hidden="true">⌄</span></button><div class="sq-org-more-panel" id="sq-org-more-panel" hidden><label class="sq-sr" for="sq-org-more-search">조직 검색</label><input type="search" id="sq-org-more-search" placeholder="조직 검색" autocomplete="off"><div class="sq-org-more-list"></div><p class="sq-org-more-empty" hidden>검색 결과가 없습니다.</p></div>`;
orgFilterGroup.append(orgFilterMore);
const orgMoreTrigger=orgFilterMore.querySelector('.sq-org-more-trigger');
const orgMorePanel=orgFilterMore.querySelector('.sq-org-more-panel');
const orgMoreSearch=orgFilterMore.querySelector('input');
const orgMoreList=orgFilterMore.querySelector('.sq-org-more-list');
const orgMoreEmpty=orgFilterMore.querySelector('.sq-org-more-empty');
let orgFilterFrame=0;
function closeOrgMore(restoreFocus=false){
 const wasOpen=!orgMorePanel.hidden;
 orgMorePanel.hidden=true;orgMoreTrigger.setAttribute('aria-expanded','false');
 if(restoreFocus&&wasOpen&&!orgFilterMore.hidden)orgMoreTrigger.focus();
}
function filterOrgMore(){
 const query=orgMoreSearch.value.trim().toLocaleLowerCase();let found=false;
 orgMoreList.querySelectorAll('button').forEach(b=>{const match=b.dataset.org.toLocaleLowerCase().includes(query);b.hidden=!match;if(match)found=true;});
 orgMoreEmpty.hidden=found;
}
function positionOrgMore(){
 if(orgMorePanel.hidden)return;
 const anchor=orgFilterMore.getBoundingClientRect();
 const panelWidth=orgMorePanel.getBoundingClientRect().width;
 const left=Math.max(8,Math.min(anchor.left,window.innerWidth-panelWidth-8));
 orgMorePanel.style.left=`${left-anchor.left}px`;
}
function fitOrgFilter(){
 orgFilterFrame=0;
 if(state.route!=='browse'||orgFilterToolbar.hidden){orgFilterMore.hidden=true;closeOrgMore();return;}
 const buttons=Array.from(orgFilterTabs.querySelectorAll('button[data-org]'));
 if(!buttons.length)return;
 // Measure the real rendered labels, including counts, before deciding which
 // choices fit. The selected choice is kept visible alongside 전체 when possible.
 buttons.forEach(b=>{b.hidden=false;});
 const gap=parseFloat(getComputedStyle(orgFilterTabs).columnGap)||0;
 const width=Math.max(0,orgFilterGroup.clientWidth-8); // tabs' horizontal padding
 if(!width)return;
 const sizes=buttons.map(b=>b.getBoundingClientRect().width);
 const total=sizes.reduce((a,b)=>a+b,0)+gap*Math.max(0,buttons.length-1);
 if(total<=width){orgFilterMore.hidden=true;closeOrgMore();return;}
 orgFilterMore.hidden=false;
 const toolbarGap=parseFloat(getComputedStyle(orgFilterGroup).columnGap)||0;
 // Keep the selected-name trigger within the space left beside 전체, even
 // when a long organization name is selected on a very narrow screen.
 orgFilterGroup.style.setProperty('--sq-org-more-limit',`${Math.max(0,width-sizes[0]-toolbarGap)}px`);
 orgMoreTrigger.firstChild.nodeValue='조직 더보기 ';
 const selected=buttons.findIndex(b=>b.getAttribute('aria-pressed')==='true');
 function visibleChoices(moreWidth,includeSelected=true){
  const budget=Math.max(0,width-moreWidth-toolbarGap);
  const keep=new Set([0]);let used=sizes[0];
  if(includeSelected&&selected>0&&used+gap+sizes[selected]<=budget){keep.add(selected);used+=gap+sizes[selected];}
  for(let i=1;i<buttons.length;i++){
   if(!includeSelected&&i===selected)continue;
   if(keep.has(i))continue;
   if(used+gap+sizes[i]>budget)break;
   keep.add(i);used+=gap+sizes[i];
  }
  return keep;
 }
 let keep=visibleChoices(orgMoreTrigger.getBoundingClientRect().width);
 // The selected-name label can be wider than '조직 더보기'. Measure it and
 // recalculate the visible choices before hiding anything.
 if(selected>=0&&!keep.has(selected)){
  orgMoreTrigger.firstChild.nodeValue=`선택: ${buttons[selected].dataset.org} `;
  keep=visibleChoices(orgMoreTrigger.getBoundingClientRect().width,false);
 }
 const overflow=[];
 buttons.forEach((b,i)=>{if(!keep.has(i)){b.hidden=true;overflow.push(b);}});
 // A very long selected organization remains discoverable in the menu and
 // appears on the trigger if it cannot fit next to 전체.
 const selectionInMenu=selected>=0&&!keep.has(selected);
 orgMoreTrigger.classList.toggle('has-selection',selectionInMenu);
 orgMoreTrigger.firstChild.nodeValue=selectionInMenu?`선택: ${buttons[selected].dataset.org} `:'조직 더보기 ';
 orgMoreTrigger.setAttribute('aria-label',selectionInMenu?`조직 더보기, 선택됨: ${buttons[selected].dataset.org}`:'조직 더보기');
 orgMoreList.innerHTML=overflow.map(b=>`<button type="button" data-org="${esc(b.dataset.org)}" aria-pressed="${b.getAttribute('aria-pressed')}">${b.innerHTML}</button>`).join('');
 filterOrgMore();
 positionOrgMore();
}
function scheduleOrgFilter(){
 if(orgFilterFrame)cancelAnimationFrame(orgFilterFrame);
 orgFilterFrame=requestAnimationFrame(fitOrgFilter);
}
const originalRenderFilterTabs=renderFilterTabs;
renderFilterTabs=function(){originalRenderFilterTabs();scheduleOrgFilter();};
orgMoreTrigger.addEventListener('click',()=>{
 if(orgMorePanel.hidden){orgMorePanel.hidden=false;orgMoreTrigger.setAttribute('aria-expanded','true');orgMoreSearch.value='';filterOrgMore();positionOrgMore();orgMoreSearch.focus();}
 else closeOrgMore();
});
orgMoreSearch.addEventListener('input',filterOrgMore);
document.addEventListener('click',e=>{if(!orgFilterMore.contains(e.target))closeOrgMore();},true);
orgMoreList.addEventListener('click',e=>{
 const b=e.target.closest('button[data-org]');if(!b)return;
 const name=b.dataset.org;closeOrgMore();
 // The delegated handler rebuilds the buttons; focus the new selected control.
 requestAnimationFrame(()=>{const selected=Array.from(orgFilterTabs.querySelectorAll('button[data-org]')).find(x=>x.dataset.org===name&&!x.hidden);(selected||orgMoreTrigger).focus();});
},true);
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!orgMorePanel.hidden){e.preventDefault();closeOrgMore(true);}});
if(globalThis.ResizeObserver)new ResizeObserver(scheduleOrgFilter).observe(orgFilterGroup);
else window.addEventListener('resize',scheduleOrgFilter);
if(document.fonts?.ready)document.fonts.ready.then(scheduleOrgFilter);
