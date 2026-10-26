// No network or real employee photos: exercise maintained profile handlers.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
const source=fs.readFileSync(path.join(__dirname,'..','frontend','frontend_people.js'),'utf8');
const photoSource=source.slice(source.indexOf("root.addEventListener('error'"),source.indexOf('async function loadPeopleRanks()'));
const refreshSource=source.slice(source.indexOf('refresh=async function(){'),source.indexOf("actions['rank-mode']="));

function fixture(){
 let now=1000,photo=null,profilePresent=false,renderCount=0,refreshResult=true,refreshCount=0;
 const requests=[],listeners={},classes=new Set();
 const avatar={classList:{add:value=>classes.add(value),remove:value=>classes.delete(value)}};
 const session={setAttribute(){},set innerHTML(value){
  if(photo)photo.isConnected=false;
  renderCount++;profilePresent=true;photo=null;classes.clear();
  const found=value.match(/<img class="sq-profile-photo" src="([^"]+)"/);
  if(found){photo={hidden:false,dataset:{},isConnected:true,matches:()=>true,closest:()=>avatar,
    set src(url){requests.push(url);},get src(){return requests.at(-1);}};photo.src=found[1];}
 }};
 const context={server:{dataMode:'mongodb',user:{id:'fixture-one',name:'First',dept:'Team',photoUrl:'/api/me/photo'}},
  state:{rankMode:'recent'},Date:{now:()=>now},Number,String,JSON,
  esc:value=>String(value).replaceAll('&','&amp;').replaceAll('"','&quot;'),
  $:selector=>selector==='#sq-session'?session:selector==='#sq-session .sq-profile-name'?profilePresent?{}:null:selector==='#sq-session .sq-profile-photo'?photo:null,
  root:{addEventListener:(name,callback)=>{listeners[name]=callback;}},
  setTimeout:()=>assert.fail('Photos must not schedule automatic retries'),
  async loadPeopleRanks(){assert.fail('Non-people refresh must not load rankings');},
  async basePeopleRefresh(){refreshCount++;if(refreshResult instanceof Error)throw refreshResult;if(refreshResult!==false)context.renderProfile();return refreshResult;},
 };
 vm.createContext(context);
 vm.runInContext("let profileSignature='';\n"+photoSource+'\n'+refreshSource,context);
 context.renderProfile();
 return {context,requests,classes,get photo(){return photo;},get renderCount(){return renderCount;},get refreshCount(){return refreshCount;},
  advance:ms=>{now+=ms;},emit:name=>listeners[name]({target:photo}),refreshResult:value=>{refreshResult=value;}};
}

test('healthy profile survives app refresh without requesting the photo again',async()=>{
 const h=fixture(),photo=h.photo;h.emit('load');h.advance(60000);
 assert.equal(await h.context.refresh(),true);
 assert.equal(h.photo,photo);assert.equal(h.renderCount,1);assert.deepEqual(h.requests,['/api/me/photo']);
 assert.equal(h.refreshCount,1);
});

test('failed profile retries once after cache expiry and only on app refresh',async()=>{
 const h=fixture(),photo=h.photo;h.emit('error');
 assert.equal(photo.hidden,true);assert.equal(h.classes.has('is-fallback'),true);
 h.advance(30000);await h.context.refresh();assert.equal(h.requests.length,1);
 h.advance(1000);h.context.renderProfile();assert.equal(h.requests.length,1);
 await h.context.refresh();assert.equal(h.requests.length,2);assert.match(h.requests[1],/^\/api\/me\/photo\?retry=\d+$/);
 assert.equal(h.photo,photo);assert.equal(photo.hidden,true);
 h.advance(60000);await h.context.refresh();assert.equal(h.requests.length,2);
 h.emit('load');assert.equal(photo.hidden,false);assert.equal(h.classes.has('is-fallback'),false);
 assert.equal(photo.dataset.photoFailedAt,undefined);assert.equal(photo.dataset.photoRetrying,undefined);
 await h.context.refresh();assert.equal(h.requests.length,2);
});

test('a retry failure keeps the fallback and starts another bounded waiting period',async()=>{
 const h=fixture();h.emit('error');h.advance(31000);await h.context.refresh();h.emit('error');
 assert.equal(h.photo.dataset.photoRetrying,undefined);assert.equal(h.photo.hidden,true);
 for(let i=0;i<10;i++)await h.context.refresh();assert.equal(h.requests.length,2);
 h.advance(31000);h.context.renderProfile();assert.equal(h.requests.length,2);
 await h.context.refresh();assert.equal(h.requests.length,3);
});

test('failed or superseded bootstrap cannot start a photo retry',async()=>{
 const h=fixture();h.emit('error');h.advance(31000);
 h.refreshResult(false);assert.equal(await h.context.refresh(),false);assert.equal(h.requests.length,1);
 h.refreshResult(Error('bootstrap failed'));await assert.rejects(h.context.refresh(),/bootstrap failed/);
 assert.equal(h.requests.length,1);assert.equal(h.photo.hidden,true);
});

test('account switch creates a fresh photo node instead of exposing the previous portrait',async()=>{
 const h=fixture(),previous=h.photo;h.emit('error');h.advance(31000);await h.context.refresh();
 h.context.server.user={id:'fixture-two',name:'Second',dept:'Other',photoUrl:'/api/me/photo'};
 await h.context.refresh();
 assert.notEqual(h.photo,previous);assert.equal(previous.isConnected,false);
 assert.deepEqual(h.photo.dataset,{});assert.equal(h.renderCount,2);
 assert.equal(h.requests.at(-1),'/api/me/photo');assert.equal(h.requests.length,3);
});

test('turning off photos discards failed image state and never retries its old URL',async()=>{
 const h=fixture(),previous=h.photo;h.emit('error');h.advance(31000);
 h.context.server.dataMode='dummy';await h.context.refresh();
 assert.equal(h.photo,null);assert.equal(previous.isConnected,false);assert.equal(h.requests.length,1);
 h.advance(60000);await h.context.refresh();assert.equal(h.requests.length,1);
});
