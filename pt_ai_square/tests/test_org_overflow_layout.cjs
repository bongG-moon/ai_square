const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const source=fs.readFileSync(path.join(__dirname,'../frontend/frontend_org_filter.js'),'utf8');
const code=source.slice(source.indexOf('function fitOrgFilter(){'),source.indexOf('\nfunction scheduleOrgFilter(){'));

function runLayout({width,selected,widths}){
 const buttons=widths.map((size,i)=>({hidden:false,dataset:{org:i===0?'전체 조직':i===selected?'아주 긴 조직 이름 테스트':'다른 조직'},innerHTML:`조직 ${i}`,
  getAttribute:()=>i===selected?'true':'false',getBoundingClientRect:()=>({width:size})}));
 const group={clientWidth:width,style:{setProperty(name,value){this[name]=value;}}};
 const trigger={firstChild:{nodeValue:''},style:{},classList:{toggle(){}},setAttribute(){},
  getBoundingClientRect(){const max=parseFloat(group.style['--sq-org-more-limit'])||Infinity;return {width:Math.min(this.firstChild.nodeValue.startsWith('선택:')?160:100,max)};}};
 const more={hidden:true},list={innerHTML:''};
 const context={state:{route:'browse'},orgFilterToolbar:{hidden:false},orgFilterFrame:0,orgFilterTabs:{querySelectorAll:()=>buttons},
  orgFilterGroup:group,orgFilterMore:more,orgMoreTrigger:trigger,orgMoreList:list,
  getComputedStyle:()=>({columnGap:'8px'}),esc:s=>s,closeOrgMore(){},filterOrgMore(){},positionOrgMore(){}};
 vm.runInNewContext(code+'\nfitOrgFilter();',context);
 return {buttons,group,trigger,more};
}

test('a long selected organization accounts for the actual selected label width',()=>{
 const {buttons,group,trigger,more}=runLayout({width:240,selected:2,widths:[70,40,200]});
 assert.equal(more.hidden,false);
 assert.equal(buttons[2].hidden,true);
 assert.match(trigger.firstChild.nodeValue,/^선택:/);
 const shown=buttons.filter(b=>!b.hidden).reduce((sum,b)=>sum+b.getBoundingClientRect().width,0);
 const count=buttons.filter(b=>!b.hidden).length;
 assert.ok(shown+8*Math.max(0,count-1)+8+trigger.getBoundingClientRect().width<=group.clientWidth-8);
});

test('an organization that fits remains visible with its ordinary more button',()=>{
 const {buttons,trigger}=runLayout({width:300,selected:1,widths:[70,60,120,120]});
 assert.equal(buttons[1].hidden,false);
 assert.match(trigger.firstChild.nodeValue,/^조직 더보기/);
});

test('the selected-name button is capped to the space beside 전체 on a narrow screen',()=>{
 const {buttons,group,trigger}=runLayout({width:180,selected:2,widths:[70,40,200]});
 assert.equal(buttons[2].hidden,true);
 assert.equal(trigger.getBoundingClientRect().width,94);
 assert.ok(buttons[0].getBoundingClientRect().width+8+trigger.getBoundingClientRect().width<=group.clientWidth-8);
});
