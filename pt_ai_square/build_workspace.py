"""Attach workspace components to the approved Flask frontend. Safe to run again."""
from pathlib import Path

BASE=Path(__file__).resolve().parent
p=BASE/'static/app.js';s=p.read_text(encoding='utf-8')
start='// BEGIN WORKSPACE EXTENSION\n';end='// END WORKSPACE EXTENSION\n'
if start in s:
    a=s.index(start);b=s.index(end,a)+len(end);s=s[:a]+s[b:]
s=s.replace("throw Error(result.error||'요청을 처리하지 못했습니다.');", "const error=Error(result.error||'요청을 처리하지 못했습니다.');error.status=response.status;throw error;")
s=s.replace("tab==='comments'", "tab==='comments'")
anchor='refresh().catch(showError);setInterval('
at=s.rindex(anchor)
s=s[:at]+start+(BASE/'frontend_workspace.js').read_text(encoding='utf-8')+'\n'+end+s[at:]
p.write_text(s,encoding='utf-8')
p=BASE/'templates/index.html';s=p.read_text(encoding='utf-8')
if '/static/workspace.css' not in s:s=s.replace('</head>','<link rel="stylesheet" href="/static/workspace.css"></head>')
p.write_text(s,encoding='utf-8')
print('Workspace UI built.')
