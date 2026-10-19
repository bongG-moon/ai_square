function fileSize(n){return n<1048576?`${(n/1024).toFixed(1)} KB`:`${(n/1048576).toFixed(1)} MB`;}
function uploadArea(kind,files=[]){
 const multi=kind==='attachments';
 return `<section class="ws-upload-area" data-upload="${kind}"><div class="ws-drop-zone"><span class="ws-upload-icon">${icon(multi?'paperclip':'cloud-upload')}</span><h3>${multi?'요청을 설명할 자료를 첨부하세요':'공유할 파일을 여기에 놓으세요'}</h3><p>${multi?'이미지·PDF·문서·ZIP · 최대 5개, 파일당 20MB':'ZIP · EXE · MSI · PS1 · 최대 128MB · 원본 형식으로 배포'}</p><button type="button" class="sq-secondary" data-file-pick="${kind}">${icon('plus')} 파일 선택</button><input class="sq-sr" type="file" name="${kind}" aria-label="${multi?'요청 첨부파일':'공유 파일'} 선택" ${multi?'multiple':''} accept="${multi?'.png,.jpg,.jpeg,.webp,.pdf,.txt,.csv,.xlsx,.docx,.zip':'.zip,.exe,.msi,.ps1'}"></div><div class="ws-selected-files" aria-live="polite">${files.map((f,i)=>`<div class="ws-selected-file">${icon('file')}<span><strong>${esc(f.name)}</strong><small>${fileSize(f.size)} · 게시할 때 업로드</small></span><button type="button" class="sq-icon" data-file-remove="${kind}" data-index="${i}" aria-label="${esc(f.name)} 선택 취소">${icon('x')}</button></div>`).join('')}</div></section>`;
}
function attachmentLinks(files){return files.length?`<section class="ws-attachments"><h3>첨부 자료 <span>${files.length}</span></h3>${files.map(f=>`<a class="ws-selected-file" href="${esc(f.url)}" download>${icon('file')}<span><strong>${esc(f.name)}</strong><small>${fileSize(f.size)}</small></span>${icon('download')}</a>`).join('')}</section>`:'';}
function selectFiles(kind,files){
 if(!files.length)return;
 if(kind==='artifact'){
  if(files.length!==1)throw Error('공유 파일은 하나만 선택하세요. 여러 파일은 ZIP으로 묶어주세요.');
  if(!/\.(zip|exe|msi|ps1)$/i.test(files[0].name)||files[0].size>128*1048576||!files[0].size)throw Error('ZIP·EXE·MSI·PS1 파일을 선택하세요. 빈 파일은 등록할 수 없고 최대 128MB입니다.');
  captureDraft();runtime.draft.file=files[0];wizard();
 }else{
  const combined=[...(work.ideaFiles||[]),...files];
  if(combined.length>5||files.some(f=>f.size>20*1048576||!f.size||! /\.(png|jpe?g|webp|pdf|txt|csv|xlsx|docx|zip)$/i.test(f.name)))throw Error('이미지·PDF·TXT·CSV·XLSX·DOCX·ZIP을 최대 5개, 파일당 20MB까지 첨부하세요.');
  work.ideaFiles=combined;refreshAttachments();
 }
}
function refreshAttachments(){const area=$('[data-upload="attachments"]');if(area){area.outerHTML=uploadArea('attachments',work.ideaFiles);mountIcons();}}
root.addEventListener('click',e=>{
 const pick=e.target.closest('[data-file-pick]');if(pick){e.preventDefault();pick.closest('[data-upload]').querySelector('input[type=file]').click();return;}
 const remove=e.target.closest('[data-file-remove]');if(!remove)return;e.preventDefault();
 if(remove.dataset.fileRemove==='artifact'){captureDraft();runtime.draft.file=null;wizard();}else{work.ideaFiles.splice(+remove.dataset.index,1);refreshAttachments();}
});
// Capture before the legacy file input handler so validation and drops share one path.
root.addEventListener('change',e=>{const input=e.target;if(input.type!=='file'||!input.closest('[data-upload]'))return;e.stopImmediatePropagation();try{selectFiles(input.name,[...input.files]);}catch(error){input.value='';showError(error);}},true);
for(const type of ['dragenter','dragover','dragleave','drop'])root.addEventListener(type,e=>{
 const area=e.target.closest('[data-upload]');if(!area)return;e.preventDefault();
 area.classList.toggle('is-dragging',type==='dragenter'||type==='dragover');
 if(type==='drop')try{selectFiles(area.dataset.upload,[...e.dataTransfer.files]);}catch(error){showError(error);}
});
