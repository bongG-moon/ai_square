root.addEventListener('submit',event=>{
 event.preventDefault();const form=event.target;if(form.dataset.busy)return;const values=new FormData(form),data=Object.fromEntries(values);
 if(form.id==='sq-search-form'){clearTimeout(runtime.searchTimer);state.query=$('#sq-query').value.trim();state.type='전체';state.category='모든 업무';navigate('browse','discovery');return;}
 if(form.id==='sq-access-form'){void submitAccessRequest(form,data.reason);return;}
 if(form.id==='sq-register-form'){captureDraft();const error=packageBlockingError(runtime.draft)||Core.validate(runtime.draft,runtime.step);if(error){$('#sq-register-error').textContent=error;return;}if(runtime.step===3)return;runtime.step++;wizard();return;}
 form.dataset.busy='true';form.querySelectorAll('button').forEach(b=>b.disabled=true);
 (async()=>{
  const id=runtime.detailId;
  if(form.id==='sq-comment-form'){await requestAPI(`/api/tools/${id}/comments`,'POST',{kind:data.kind,text:data.comment});await refresh();detail(id,'comments');}
  if(form.id==='sq-policy-form'){await requestAPI('/api/storage/policy','PUT',{keep:+data.keep,days:+data.days});await refresh();manage('storage');}
  if(form.id==='sq-edit-tool-form'){await requestAPI(`/api/tools/${id}`,'PATCH',{...data,approval:form.elements.approval.checked,audience:values.getAll('audience'),expectedRevision:getItem(id).revision});await refresh();manage();}
  if(form.id==='sq-org-form'){await requestAPI('/api/organizations','POST',{...data,previous:organizations[runtime.orgIndex]?.name});await refresh();manage('orgs');}
  if(form.id==='sq-reject-form'){await requestAPI(`/api/requests/${form.dataset.request}/decision`,'POST',{status:'반려',reason:data.reason,expectedRevision:form.dataset.requestRevision});await refresh();manage('requests');}
  if(form.id==='sq-idea-form'){await requestAPI('/api/ideas','POST',data);openModal('아이디어를 남겼습니다.','제안 등록 완료',`<div class="sq-success"><h3>${esc(data.name)}</h3><p>운영 관리의 아이디어 목록에 저장했습니다.</p>${button('close-dialog','확인','sq-primary')}</div>`);}
 })().catch(showError).finally(()=>{delete form.dataset.busy;form.querySelectorAll('button').forEach(b=>b.disabled=false);});
});
