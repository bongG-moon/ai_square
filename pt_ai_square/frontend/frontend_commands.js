// Commands are shown and copied only. The web server never executes them.
function commandFields(d){
 return `<section class="ws-command-fields"><div class="sq-callout"><strong>파일 없이 명령어로 설치하는 도구</strong><br>지원하는 범위에 실제 명령어를 적어주세요. 비워 둔 범위는 ‘지원 안 함’으로 표시됩니다. 사용자는 범위를 직접 선택한 다음 명령어를 복사합니다. 토큰·비밀번호는 넣지 마세요.</div><div class="sq-form-grid"><label class="sq-field"><span>현재 디렉토리 · 프로젝트</span><small>사용자가 사용할 프로젝트 폴더에서 실행하는 명령어</small><textarea name="commandProject" maxlength="8000" spellcheck="false" placeholder="해당 도구가 지원하는 프로젝트 설치 명령어">${esc(d.commandProject||'')}</textarea></label><label class="sq-field"><span>전역 · 내 계정</span><small>현재 사용자 계정의 여러 프로젝트에서 사용하는 명령어</small><textarea name="commandUser" maxlength="8000" spellcheck="false" placeholder="해당 도구가 지원하는 사용자 범위 설치 명령어">${esc(d.commandUser||'')}</textarea></label></div></section>`;
}
function commandScopePanel(x,v){
 return `<section class="ws-command-install" data-command-tool="${x.id}" data-command-version="${v?.n}"><h3>어디에 설치할까요?</h3><p class="sq-note">범위를 먼저 선택하세요. 현재 디렉토리는 터미널에서 열어 둔 프로젝트 폴더, 전역은 내 계정 기준입니다.</p><div class="ws-scope-grid">${[['project','folder','현재 디렉토리','이 프로젝트에서 사용'],['user','user','전역 · 내 계정','여러 프로젝트에서 사용']].map(([scope,ic,title,desc])=>`<button type="button" class="ws-scope-choice" data-action="choose-command-scope" data-scope="${scope}" aria-pressed="false" ${v?.commands?.[scope]?'':'disabled'}>${icon(ic)}<strong>${title}</strong><small>${v?.commands?.[scope]?desc:'등록자가 지원하지 않은 범위'}</small></button>`).join('')}</div><div class="ws-command-result" hidden><p data-command-hint class="sq-note"></p><pre tabindex="0"><code data-command-text></code></pre>${button('copy-install-command','명령어 복사','sq-primary','type="button"')}<p class="sq-note">복사 후 안내된 터미널에서 직접 실행하세요. 웹에서 실행하지 않습니다. 실제 적용 범위는 등록자가 제공한 명령어를 확인하세요.</p></div></section>`;
}
async function selectedCommand(panel,scope){
 const x=await requestAPI(`/api/tools/${panel.dataset.commandTool}`);
 const v=x.versions.find(v=>v.n===Number(panel.dataset.commandVersion));
 if(!v||v.deleted||v.withdrawn||!v.commands?.[scope])throw Error('사용할 수 없는 명령어입니다. 권한·배포 상태를 확인하세요.');
 return v.commands[scope];
}
actions['choose-command-scope']=async b=>{
 const panel=b.closest('[data-command-tool]'),scope=b.dataset.scope,token=Symbol();
 panel._scopeRequest=token;delete panel.dataset.selectedScope;
 panel.querySelector('.ws-command-result').hidden=true;
 panel.querySelectorAll('[data-scope]').forEach(el=>el.setAttribute('aria-pressed','false'));
 const command=await selectedCommand(panel,scope);
 if(!panel.isConnected||panel._scopeRequest!==token)return;
 panel.dataset.selectedScope=scope;
 panel.querySelectorAll('[data-scope]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.scope===scope)));
 panel.querySelector('[data-command-text]').textContent=command;
 panel.querySelector('[data-command-hint]').textContent=scope==='project'?'먼저 터미널에서 설치할 프로젝트 폴더로 이동하세요.':'내 사용자 계정의 설정에 적용됩니다. 다른 프로젝트에서도 영향을 받을 수 있습니다.';
 panel.querySelector('.ws-command-result').hidden=false;
};
actions['copy-install-command']=async b=>{
 const panel=b.closest('[data-command-tool]');
 if(!panel.dataset.selectedScope)throw Error('설치 범위를 먼저 선택하세요.');
 const scope=panel.dataset.selectedScope,token=panel._scopeRequest,command=await selectedCommand(panel,scope);
 if(!panel.isConnected||panel._scopeRequest!==token||panel.dataset.selectedScope!==scope)return;
 try{await navigator.clipboard.writeText(command);announce('선택한 범위의 명령어를 복사했습니다.');b.textContent='복사 완료';}
 catch{throw Error('브라우저에서 자동 복사를 허용하지 않습니다. 표시된 명령어를 선택하여 복사하세요.');}
};
