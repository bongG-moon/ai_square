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
