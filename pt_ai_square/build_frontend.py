"""One-time import of the approved prototype; generated web assets are committed.
Historical design import only, not needed to run or edit the committed web app.
"""
from pathlib import Path
import re
import shutil
import argparse

BASE=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description='Historical prototype importer. Replaces generated UI; not required for normal development.')
parser.add_argument('--prototype-directory',type=Path,required=True)
parser.add_argument('--fragment',type=Path,required=True)
parser.add_argument('--lucide-package',type=Path,required=True)
args=parser.parse_args()
SOURCE=args.prototype_directory
fragment=args.fragment.read_text(encoding='utf-8')
standalone=(SOURCE/'PT_AI_SQUARE_전체화면_체험.html').read_text(encoding='utf-8')
static=BASE/'static';static.mkdir(exist_ok=True)
(BASE/'templates').mkdir(exist_ok=True)
basecss=re.search(r'<style>(.*?)</style>',standalone,re.S)[1]
basecss=re.sub(r'@font-face\s*\{[^}]*\}','',basecss)
css=basecss+'\n'+re.search(r'<style>(.*?)</style>',fragment,re.S)[1]
css=css.replace('padding-right:max(100px,4%)','padding-right:4%').replace('padding-right:95px','padding-right:5%').replace('padding-right:88px','padding-right:5%')
css+="\n@font-face{font-family:Pretendard;font-style:normal;font-weight:100 900;font-display:swap;src:url('fonts/PretendardVariable.woff2') format('woff2')}\n"
inter=(SOURCE/'standalone-assets/inter-source.css').read_text()
urls=list(dict.fromkeys(re.findall(r'url\(([^)]+)\)',inter)))
for i,url in enumerate(urls): inter=inter.replace(url,f'fonts/inter-{i}.font')
css+=inter+'\n#square-app .sq-session{font-size:11px;color:#6e6e73;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap} @media(max-width:850px){#square-app .sq-session{display:none}}\n'
css+='\n'+(static/'brand.css').read_text(encoding='utf-8')
(static/'app.css').write_text(css,encoding='utf-8')
(static/'fonts').mkdir(exist_ok=True)
for p in (SOURCE/'standalone-assets').iterdir():
    if p.suffix in {'.woff2','.font'} or 'LICENSE' in p.name: shutil.copy2(p,static/'fonts'/p.name)
lucide=args.lucide_package
shutil.copy2(lucide/'dist/umd/lucide.min.js',static/'lucide.min.js')
shutil.copy2(lucide/'LICENSE',static/'lucide-LICENSE')
shutil.copytree(SOURCE/'publisher-resources',static/'guides',dirs_exist_ok=True)
guide=static/'guides/PT_AI_SQUARE_등록가이드.html'
guide_text=guide.read_text(encoding='utf-8').replace('초안 v1','웹 구현 v2.0').replace('검사 통과 예시로 게시','게시').replace('웹에서 자동으로 발급하도록 설계되어 있습니다.','웹에서 자동으로 발급합니다.')
guide_text=guide_text.replace('운영 서비스에서는 파일 구조와 배포 규칙 등의 검사를 통과해야 게시됩니다. 현재 HTML 시안에서는 <strong>게시</strong>를 눌러 화면 흐름만 체험합니다.','<strong>게시</strong>를 누르면 서버에서 입력값·크기·기본 파일 형식·ZIP 경로를 검사하고 실제 저장합니다. 악성코드 검사와 실행 검증을 대신하지 않습니다.')
guide_text=guide_text.replace('현재 배포·복구용·사용 중인 파일은 보존합니다.','현재 배포와 복구용 파일은 보존합니다. PC 설치 현황은 아직 수집하지 않습니다.')
guide.write_text(guide_text,encoding='utf-8')
markup=fragment[:fragment.index('<style>')]
markup=re.sub(r'<link\b[^>]*>','',markup)
markup=markup.replace('체험 모드','사내 공유')
markup=re.sub(r'<button id="sq-autoplay".*?</button>','',markup,flags=re.S)
markup=markup.replace('01 — 05</span>','실시간 순위</span>')
markup=markup.replace('lang="en">P&amp;T AI SQUARE','lang="en"><img class="sq-logo" src="/static/brand/pt-ai-square-symbol.svg" width="34" height="34" alt="">P&amp;T AI SQUARE',1)
markup=markup.replace('기준 · 예시','기준 · 접속 시 집계').replace('예시 데이터 · 실제 업로드·설치·권한 변경은 실행하지 않습니다.','사내 도구 공유 · PC 자동 설치는 후속 앱 연동으로 지원합니다.')
markup=markup.replace('<div class="sq-header-actions">','<div class="sq-header-actions"><span class="sq-session" id="sq-session"></span><button class="sq-quiet cursor-interaction" data-action="fullscreen" aria-label="전체화면 전환"><i data-lucide="maximize"></i></button><button class="sq-quiet cursor-interaction" data-action="logout" title="로그아웃"><i data-lucide="log-out"></i></button>',1)
(BASE/'templates/index.html').write_text('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>P&amp;T AI SQUARE</title><link rel="icon" type="image/svg+xml" href="/static/brand/pt-ai-square-symbol.svg"><link rel="stylesheet" href="/static/app.css"><script defer src="/static/lucide.min.js"></script><script defer src="/static/app.js"></script></head><body>'+markup+'</body></html>',encoding='utf-8')
js=re.search(r'<script>(.*?)</script>',fragment,re.S)[1]
def between(start,end,replacement):
    global js
    a=js.index(start);b=js.index(end,a);js=js[:a]+replacement+'\n'+js[b:]
between('const seed=[','const state=', 'const items=[];')
between('const organizations=','const policy=', 'const organizations=[],requests=[];')
between('const saved=','const persist=', '') if False else None
js=re.sub(r'^const saved=.*\n','',js,flags=re.M)
js=re.sub(r'^const persist=.*\n','const persist=()=>{};\n',js,flags=re.M)
js=re.sub(r'^function rankItems\(\).*\n',"function rankItems(){return filtered(true).sort((a,b)=>b.rankScore-a.rankScore||a.id-b.id).slice(0,10);}\n",js,flags=re.M)
js=js.replace("${state.snapshot&&x.id===6?'▲ 2':'—'}",'—')
js=js.replace("`14:${String(state.snapshot*5%60).padStart(2,'0')}`","new Date(server.rankAsOf*1000).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit',timeZone:'Asia/Seoul'})")
js=js.replace("org:x?.org||'제조팀'","org:x?.org||server.user.org").replace("owner:x?.owner||'김민수'","owner:x?.owner||server.user.name").replace("url:'',file:null","url:x?.url||'',expectedRevision:x?.revision,file:null")
js=js.replace('runtime.draft.file=f?{name:f.name,size:f.size}:null','runtime.draft.file=f||null')
js=js.replace("<div style=\"margin-top:12px\">${button('sample-file','예시 ZIP으로 체험','sq-link')}</div>",'')
js=js.replace('선택하거나 예시 파일을 사용해 주세요.','선택해 주세요.')
js=js.replace('ZIP · EXE · MSI · PS1 / 시안에서는 전송하지 않습니다.','ZIP · EXE · MSI · PS1 / 게시할 때 서버로 전송합니다.')
js=js.replace('검사 통과 예시로 게시','게시')
js=js.replace('입력값 확인 완료 · 실제 파일 검사는 아직 실행하지 않았습니다.','게시하면 서버에서 기본 파일 검사를 진행합니다.')
js=js.replace('운영 서비스에서는 파일 구조, 위험 파일, 배포 규칙을 검사한 뒤 게시합니다. EXE 생성이나 보안 검사가 완료된 것처럼 표시하지 않습니다.<br>여기서는 ‘게시’를 눌러 완료 화면을 체험합니다.','파일 크기·확장자·기본 형식·ZIP 경로를 확인하고 배포 번호를 발급합니다. 악성코드 검사와 실행 검증은 포함하지 않습니다. 등록한 코드를 서버에서 실행하거나 EXE로 변환하지 않습니다.')
between('function publish(){','function versionManager(', (BASE/'frontend_publish.js').read_text(encoding='utf-8'))
js=js.replace("${items.map(x=>`<div class=\"sq-admin-row\">","${items.filter(x=>x.canManage).map(x=>`<div class=\"sq-admin-row\">")
js=js.replace("[['tools','등록 도구'],['requests','권한 신청'],['orgs','조직 설정'],['storage','저장 공간']].map", "[['tools','등록 도구'],['requests','권한 신청'],...(server.user.role==='admin'?[['orgs','조직 설정'],['storage','저장 공간'],['ideas','아이디어'],['activity','사용 이력']]:[])].map")
js=js.replace('운영자 미리보기 · 실제 서비스에서는 역할별로 표시됩니다.','수정 권한이 있는 도구만 표시됩니다.')
js=js.replace('관리자·등록자 화면 체험','관리자·등록자 화면')
js=js.replace('실제 사용자의 소속과 운영자 권한은 사내 로그인 정보에 연계하는 구상입니다.','사용자의 소속과 권한은 로그인 계정으로 확인합니다. 조직 담당자 이름은 안내용이며, 실제 승인은 도구 등록자 또는 운영자가 처리합니다.')
js=js.replace('현재 배포, 복구용 버전, 사용 중인 파일은 삭제할 수 없습니다.','현재 배포와 복구용 버전은 삭제할 수 없습니다. PC별 설치 현황은 아직 수집하지 않습니다.')
js=js.replace('현재 배포·복구용·사용 중인 파일을 제외한 목록입니다.','현재 배포·복구용 파일을 제외한 목록입니다.')
js=js.replace('버전 번호는 웹에서 발급하는 구상입니다.','버전 번호는 웹에서 자동 발급합니다.')
js=js.replace('새 버전 알림 가능','배포 정보 API 제공')
js=js.replace("  if(x.guide)","  if(x.accessDecision)content+=`<div class=\"sq-callout\"><strong>신청 처리 사유</strong><br>${esc(x.accessDecision)}</div>`;\n  if(x.guide)")
js=js.replace("options(organizations.map(o=>o.name),d.org)","options(organizations.filter(o=>server.user.role==='admin'||o.name==='공통'||o.name===server.user.org).map(o=>o.name),d.org)")
js=js.replace("options(organizations.map(o=>o.name),x.org)","options(organizations.filter(o=>server.user.role==='admin'||o.name==='공통'||o.name===server.user.org).map(o=>o.name),x.org)")
js=js.replace("${button('manage-versions','버전 관리 화면 보기')}","${x.canManage?button('manage-versions','버전 관리 화면 보기'):''}")
js=js.replace("x.access==='pending'?button('manage','신청 상태 보기')", "x.access==='pending'?'<span class=\"sq-note\">승인 대기 중입니다.</span>'")
start=js.index("  else if(x.platform==='ChatGPT'&&x.mode!=='server')")
end=js.index('  if(x.guide)',start)
js=js[:start]+'''  else {content+=`<div class="sq-callout"><strong>사용 환경</strong><br>${esc(x.environment||x.platform)}</div>`;
  if(x.mode==='server')content+=`<div class="sq-callout"><strong>등록된 연결 주소</strong><br><a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.url)}</a></div><p class="sq-note">${x.platform==='ChatGPT'?'회사 ChatGPT 관리자에게 원격 연결 메뉴와 인증 방식의 지원 여부를 확인한 후 아래 안내를 따라 설정하세요.':'등록자가 제공한 안내에 따라 대상 프로그램에서 연결하세요.'} 웹이 연결 성공을 자동 확인하지는 않습니다.</p>`;
  else content+=`${button('download-file','파일 다운로드','sq-primary')}<div class="sq-callout">${x.platform==='ChatGPT'?'회사 계정에서 허용된 파일 첨부·지침 활용 방법을 확인하세요. Python 코드와 실행 파일은 ChatGPT에 첨부한다고 자동 설치되지 않습니다.':'파일을 받은 뒤 아래 설치 안내를 따라주세요.'} PC 자동 설치·업데이트는 후속 앱 연동 기능입니다.</div>`;
  }
'''+js[end:]
js=js.replace('좋아요 3점 · 다운로드 1점에 최근 1시간 4배, 1–6시간 2배, 6–24시간 1배를 적용하는 제안입니다.','좋아요 3점 · 다운로드 1점에 최근 1시간 4배, 1–6시간 2배, 6–24시간 1배를 적용합니다.')
js=js.replace('반복 다운로드와 자동 업데이트는 순위에서 제외합니다.<br>지금은 예시 데이터이며 집계 서버와 연결되어 있지 않습니다.','한 사용자·한 도구의 다운로드는 한국 시간 하루에 한 번 집계합니다. 현재 집계는 서버 다운로드 응답 기준이며 PC 설치 완료 수가 아닙니다.')
js=js.replace('다음 집계 화면 체험','집계 새로고침')
js=js.replace('callback?.();','return callback?.();')
between("root.addEventListener('submit',", "root.addEventListener('change',", (BASE/'frontend_submit.js').read_text(encoding='utf-8'))
js=js.replace('event.preventDefault();handler(b);',"event.preventDefault();b.disabled=true;Promise.resolve().then(()=>handler(b)).catch(showError).finally(()=>{if(b.isConnected)b.disabled=false;});")
between("window.addEventListener('openai:set_globals'", '})();', "refresh().catch(showError);setInterval(()=>{if(!document.hidden&&!$('#sq-dialog').open&&!runtime.requestBusy)refresh().catch(showError);},300000);\n")
integration=(BASE/'frontend_api.js').read_text(encoding='utf-8')+'\n'+(BASE/'frontend_activity.js').read_text(encoding='utf-8')
js=js.replace("root.addEventListener('click'",integration+"\nroot.addEventListener('click'",1)
# Server-only management panes keep the existing dialog and component styles.
js=js.replace(" openModal('운영 관리'", " if(tab==='ideas')content=server.ideas.map(i=>`<article class=\"sq-comment\"><strong>${esc(i.name)}</strong><small>${esc(i.author)} · ${esc(i.category)}</small><p>${esc(i.body)}</p></article>`).join('')||'<p class=\"sq-note\">접수된 아이디어가 없습니다.</p>';\n openModal('운영 관리'",1)
js=js.replace("const used=items.reduce((sum,x)=>sum+x.versions.filter(v=>!v.deleted).reduce((n,v)=>n+v.size,0),0)","const used=(server.storage?.used||0)/1048576")
js=js.replace('Flask 서버의 배포 파일 저장소 · 예시 용량','Flask 서버의 배포 파일 사용량 · DB와 로그 제외')
js=js.replace('/ 10 GB','/ ${((server.storage?.quota||0)/1073741824).toFixed(1)} GB').replace('aria-valuemax="10240"','aria-valuemax="${(server.storage?.quota||1)/1048576}"').replace('used/102.4','used/((server.storage?.quota||1)/1048576)*100')
js=js.replace("candidates.length?'':'disabled')}${audit.length", "'')}${audit.length")
# Use the two-tone treatment only for the home introduction, not every title.
between('function canAuto(){','async function changeRank(', (BASE/'frontend_rank.js').read_text(encoding='utf-8'))
js=re.sub(r"\$\('#sq-rank-range'\)\.textContent=.*?;", "$('#sq-rank-range').textContent='실시간 순위';",js,count=1)
js=js.replace('실제 순위는 5분마다 갱신하고, 화면만 6초마다 5개씩 전환합니다.','웹 접속·새로고침 시점까지 저장된 이력으로 순위를 계산합니다. 좋아요·다운로드 후에도 다시 계산하며, 화면은 6초마다 5개씩 전환합니다.')
js=js.replace('<span class="sq-tool-kind">${esc(item.platform)} · ${esc(item.type)}</span>','<span class="sq-tool-kind">${esc(item.platform)} · <span class="sq-type-label" data-type="${esc(item.type)}">${esc(item.type)}</span></span>')
js=js.replace('<span class="sq-tool-icon">${icon(item.icon)}</span>','<span class="sq-tool-icon" data-type="${esc(item.type)}">${icon(item.icon)}</span>')
js=js.replace('<span class="sq-tool-icon">${icon(x.icon)}</span>','<span class="sq-tool-icon" data-type="${esc(x.type)}">${icon(x.icon)}</span>')
js=js.replace('<span class="sq-delta">—</span>','<span class="sq-type-label" data-type="${esc(x.type)}">${esc(x.type)}</span>')
js=js.replace(" openModal('운영 관리'", " if(tab==='activity')content=activityPanel();\n openModal('운영 관리'",1)
js=js.replace("document.addEventListener('visibilitychange',schedule);", "document.addEventListener('visibilitychange',()=>{schedule();if(!document.hidden&&!$('#sq-dialog').open&&!runtime.requestBusy)refresh().catch(showError);});")
# Focus must not repeatedly restart the automatic six-second timer.
js=re.sub(r"const chart=\$\('\.sq-chart'\);chart\.addEventListener\('focusin'.*?\n",'',js)
heading_update="$('#sq-page-title').textContent=state.route==='home'?'좋은 도구가 모이는 곳.':'필요한 도구를 발견하세요.';$('#sq-page-description').textContent=state.route==='home'?'동료의 노하우를, 당신의 업무로.':'MCP부터 Skill까지. 당신의 업무에 맞는 도구를 둘러보세요.';"
assert heading_update in js, 'Prototype heading changed; review the home typography adapter.'
js=js.replace(heading_update,"""$('#sq-page-title').textContent=state.route==='home'?'좋은 도구가 모이는 곳.':'필요한 도구를 발견하세요.';
 if(state.route==='home'){
  const continuation=document.createElement('span');
  continuation.className='sq-heading-continuation';
  continuation.textContent=' 동료의 노하우를, 당신의 업무로.';
  $('#sq-page-title').append(continuation);
 }
 $('#sq-page-description').hidden=state.route==='home';
 $('#sq-page-description').textContent=state.route==='home'?'':'MCP부터 Skill까지. 당신의 업무에 맞는 도구를 둘러보세요.';""",1)
(static/'app.js').write_text(js,encoding='utf-8')
print('Imported approved layout and motion into Flask templates/static assets.')
import runpy
runpy.run_path(str(BASE/'build_workspace.py'))
runpy.run_path(str(BASE/'build_docs.py'))
