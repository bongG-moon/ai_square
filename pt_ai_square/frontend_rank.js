function canAuto(){return state.route==='home'&&runtime.inView&&!runtime.busy&&!document.hidden&&!$('#sq-dialog').open&&rankItems().length>5;}
function schedule(){
 stopAuto();const count=rankItems().length;$('#sq-rank-all').hidden=count>5;
 $('#sq-chart-hint').textContent=count<=5?'현재 조건에 맞는 도구를 모두 표시하고 있어요.':'6초마다 1–5위와 6–10위를 자동으로 보여드려요.';
 if(!canAuto())return;
 const meter=$(`[data-action=rank-page][data-page="${state.rankPage}"] span`);
 if(!motion.matches&&meter?.animate)runtime.progress=meter.animate([{transform:'scaleX(0)'},{transform:'scaleX(1)'}],{duration:6000,fill:'forwards'});
 runtime.timer=setTimeout(()=>{if(canAuto())changeRank(1-state.rankPage);else schedule();},6000);
}
