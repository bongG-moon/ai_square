"""Attach workspace components to the approved Flask frontend. Safe to run again."""
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
p=BASE/'static/app.js';s=p.read_text(encoding='utf-8')
# Activity reporting is part of the live management surface. Keep its maintained
# source in the served bundle without rebuilding the historical base layout.
activity_start=s.index('function activityPanel(){')
activity_end=s.index("\nroot.addEventListener('click',event=>",activity_start)
s=s[:activity_start]+(BASE/'frontend/frontend_activity.js').read_text(encoding='utf-8').rstrip()+'\n'+s[activity_end:]
# The base handler is superseded by the workspace handler below, but retain
# source/bundle parity for callers that exercise the base management dialog.
source_api=(BASE/'frontend/frontend_api.js').read_text(encoding='utf-8')
admin_line=next(line for line in source_api.splitlines() if line.startswith("actions['admin-tab']="))
old_admin_line=next(line for line in s.splitlines() if line.startswith("actions['admin-tab']="))
s=s.replace(old_admin_line,admin_line,1)
start='// BEGIN WORKSPACE EXTENSION\n';end='// END WORKSPACE EXTENSION\n'
if start in s:
    a=s.index(start);b=s.index(end,a)+len(end);s=s[:a]+s[b:]
s=s.replace("throw Error(result.error||'요청을 처리하지 못했습니다.');", "const error=Error(result.error||'요청을 처리하지 못했습니다.');error.status=response.status;throw error;")
s=s.replace("tab==='comments'", "tab==='comments'")
anchor='refresh().catch(showError);setInterval('
at=s.rindex(anchor)
s=s[:at]+start+'\n'.join((BASE/'frontend'/name).read_text(encoding='utf-8') for name in ['frontend_workspace.js','frontend_upload.js','frontend_package.js','frontend_commands.js','frontend_storage.js','frontend_people.js','frontend_ax_workspace.js','frontend_grants.js'])+'\n'+end+s[at:]
p.write_text(s,encoding='utf-8')
p=BASE/'templates/index.html';s=p.read_text(encoding='utf-8')
if '/static/workspace.css' not in s:s=s.replace('</head>','<link rel="stylesheet" href="/static/workspace.css"></head>')
if '/static/grants.css' not in s:s=s.replace('</head>','<link rel="stylesheet" href="/static/grants.css"></head>')
p.write_text(s,encoding='utf-8')
print('Workspace UI built.')
