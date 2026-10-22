function storageSize(bytes){return bytes==null?'확인 불가':bytes>=1073741824?`${(bytes/1073741824).toFixed(2)} GB`:`${(bytes/1048576).toFixed(1)} MB`;}
async function fetchStorageCapacity(){const r=await requestAPI('/api/storage/limits');server.storage={...server.storage,...r.storage};}
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
 if(!Number.isFinite(quota)||!Number.isFinite(reserve)||quotaBytes<1048576||reserve<0){message.textContent='한도는 최소 1MB, 여유 공간은 0 이상으로 입력하세요.';return;}
 form.dataset.busy='true';const button=form.querySelector('[type=submit]');button.disabled=true;message.textContent='저장하고 있습니다.';
 requestAPI('/api/storage/limits','PUT',{mode:form.elements.mode.value,quotaBytes,reserveBytes,expectedRevision:Number(form.dataset.revision)})
 .then(async()=>{await refresh();const status=$('#ws-capacity-message');if(status)status.textContent='저장했습니다. 기존 파일은 그대로 유지됩니다.';})
 .catch(error=>{message.textContent=error.message;})
 .finally(()=>{delete form.dataset.busy;button.disabled=false;});
},true);
