async function publish(){
 const d=runtime.draft,error=Core.validate(d,1)||Core.validate(d,2);if(runtime.step!==3||error){if(error)throw Error(error);return;}
 const form=new FormData();form.append('metadata',JSON.stringify({...d,file:undefined,sample:undefined}));if(d.mode==='file')form.append('artifact',d.file);
 const result=await requestAPI(runtime.releaseId?`/api/tools/${runtime.releaseId}/versions`:'/api/tools','POST',form);
 runtime.newId=result.id;runtime.draft=null;await refresh();
 openModal('공유할 준비가 되었습니다.','게시 완료',`<div class="sq-success"><span class="sq-feature-icon">${icon('check')}</span><h3>${esc(getItem(result.id).name)}</h3><p>v${result.version}을 서버에 저장했습니다.<br>설치·연결 안내와 공개 범위를 확인해 주세요.</p><div class="sq-actions" style="justify-content:center">${button('published-detail','상세 화면 보기','sq-primary')}${button('manage','등록 도구 관리')}</div></div>`);
}
