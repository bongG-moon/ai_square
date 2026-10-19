function canAuto(){return state.route==='home'&&runtime.inView&&!runtime.busy&&!document.hidden&&!$('#sq-dialog').open&&rankItems().length>5;}
function schedule(){
 stopAuto();const count=rankItems().length;$('#sq-rank-all').hidden=count>5;

 if(!canAuto())return;
 const meter=$(`[data-action=rank-page][data-page="${state.rankPage}"] span`);
 if(!motion.matches&&meter?.animate)runtime.progress=meter.animate([{transform:'scaleX(0)'},{transform:'scaleX(1)'}],{duration:5000,fill:'forwards'});
 runtime.timer=setTimeout(()=>{if(canAuto())changeRank(1-state.rankPage);else schedule();},5000);
}
