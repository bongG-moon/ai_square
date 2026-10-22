"""Render the maintained Markdown guides as standalone, offline HTML."""
import base64
import argparse
import html
import re
from pathlib import Path

BASE=Path(__file__).resolve().parents[1]
OUT=BASE.parent/'outputs/pt-ai-square-web-20261018'
OUT.mkdir(parents=True,exist_ok=True)

def inline(s):
    s=html.escape(s)
    s=re.sub(r'`([^`]+)`',r'<code>\1</code>',s)
    s=re.sub(r'\*\*([^*]+)\*\*',r'<strong>\1</strong>',s)
    s=re.sub(r'\[([^]]+)\]\((https?://[^)]+)\)',r'<a href="\2">\1</a>',s)
    return s

def render(source):
    rows=source.splitlines();out=[];toc=[];i=0
    while i<len(rows):
        line=rows[i];i+=1
        if not line.strip():continue
        if line.startswith('```'):
            code=[]
            while i<len(rows) and not rows[i].startswith('```'):code.append(rows[i]);i+=1
            i+=1;out.append('<pre><code>'+html.escape('\n'.join(code))+'</code></pre>');continue
        if line.startswith('|'):
            cells=lambda l:[inline(x.strip()) for x in l.strip().strip('|').split('|')]
            head=cells(line);i+=1;body=[]
            while i<len(rows) and rows[i].startswith('|'):body.append(cells(rows[i]));i+=1
            out.append('<div class="table-wrap"><table><thead><tr>'+''.join('<th>'+x+'</th>' for x in head)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+x+'</td>' for x in r)+'</tr>' for r in body)+'</tbody></table></div>');continue
        if line.startswith('#'):
            level=len(line)-len(line.lstrip('#'));title=line[level:].strip();key='section-'+str(len(toc)) if level==2 else 'heading-'+str(i)
            if level==2:toc.append((key,title))
            out.append(f'<h{level} id="{key}">'+inline(title)+f'</h{level}>');continue
        if line.startswith('- ') or re.match(r'\d+\. ',line):
            ordered=not line.startswith('- ');tag='ol' if ordered else 'ul';lis=[]
            while True:
                lis.append(re.sub(r'^(- |\d+\. )','',line))
                if i>=len(rows) or not (re.match(r'\d+\. ',rows[i]) if ordered else rows[i].startswith('- ')):break
                line=rows[i];i+=1
            out.append('<'+tag+'>'+''.join('<li>'+inline(x)+'</li>' for x in lis)+'</'+tag+'>');continue
        out.append('<p>'+inline(line)+'</p>')
    return ''.join(out),toc

font=base64.b64encode((BASE/'static/fonts/PretendardVariable.woff2').read_bytes()).decode()
style='''*{box-sizing:border-box}body{margin:0;background:#f5f5f7;color:#1d1d1f;font-family:Pretendard,Arial,sans-serif;font-size:15px;line-height:1.85}header{padding:25px 5%;border-bottom:1px solid #e5e5ea;background:#ffffffc9;display:flex;justify-content:space-between;align-items:center}header strong{letter-spacing:-.5px}header span{font-size:12px;color:#89898f}main{display:grid;grid-template-columns:230px minmax(0,860px);gap:55px;max-width:1250px;margin:45px auto;padding:0 30px 80px}nav{position:sticky;top:25px;height:fit-content;font-size:12px}nav a{display:block;color:#808087;text-decoration:none;margin:0 0 12px}article{background:#fff;border:1px solid #fff;border-radius:26px;padding:42px;box-shadow:0 8px 30px #20203008}h1{font-size:31px;line-height:1.4;letter-spacing:-1.1px;margin-top:0}h2{margin:55px 0 22px;font-size:23px;letter-spacing:-.7px;border-top:1px solid #ededf2;padding-top:30px}h3{font-size:18px;margin:30px 0 15px}p,li{color:#595960}li{margin-bottom:8px}strong{font-weight:650;color:#28282e}a{color:#2868b5}code{font-family:Consolas,monospace;font-size:12px;background:#f4f4f7;padding:2px 5px;border-radius:5px;overflow-wrap:anywhere}pre{overflow:auto;padding:18px;background:#f3f4f7;border:1px solid #e7e8ee;border-radius:14px;line-height:1.7}pre code{background:none;padding:0;white-space:pre}table{width:100%;border-collapse:collapse;font-size:12px}th,td{text-align:left;border-bottom:1px solid #e6e6ed;padding:13px 12px;vertical-align:top}th{background:#f6f6f9;color:#4a4a53;font-weight:600}td{color:#6e6e76}.table-wrap{overflow:auto;border:1px solid #e6e6ed;border-radius:14px;margin:22px 0}@media(max-width:850px){main{display:block;margin-top:24px;padding:0 15px 40px}nav{display:none}article{padding:25px}h1{font-size:26px}}@media print{header,nav{display:none}body{background:white}main{display:block;margin:0;padding:0}article{box-shadow:none;border:0;padding:0}h2{break-after:avoid}pre,tr{break-inside:avoid}a{color:inherit}}'''
style=f"@font-face{{font-family:Pretendard;font-weight:100 900;src:url(data:font/woff2;base64,{font}) format('woff2')}}"+style
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--only',help='Render one docs filename, for example SSO_OPERATIONS_GUIDE.md')
args=parser.parse_args()
documents=[('PLAN_V3.md','P&T_AI_SQUARE_상세기획서_v3.html'),('OPERATOR_GUIDE.md','P&T_AI_SQUARE_실행_운영가이드.html'),('USER_GUIDE.md','P&T_AI_SQUARE_사용자_등록자가이드.html'),('LOCAL_RECEIVER.md','P&T_AI_SQUARE_로컬다운로드_가이드.html'),('SSO_OPERATIONS_GUIDE.md','P&T_AI_SQUARE_SSO_운영설정_상세가이드.html')]
if args.only and args.only not in {source for source,_ in documents}:
    parser.error('Unknown guide filename: '+args.only)
for source,name in documents:
    if args.only and source!=args.only:continue
    content,toc=render((BASE/'docs'/source).read_text(encoding='utf-8'))
    title='P&T AI SQUARE · '+('SSO 운영 설정 상세 가이드' if source.startswith('SSO_') else '상세 기획서' if source.startswith('PLAN') else '사용자·등록자 가이드' if source.startswith('USER') else '로컬 다운로드 가이드' if source.startswith('LOCAL') else '실행·운영 가이드')
    result='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+'</title><style>'+style+'</style><header><strong>P&T AI SQUARE</strong><span>v3.3 · P&T AI SQUARE</span></header><main><nav>'+''.join(f'<a href="#{key}">{html.escape(label)}</a>' for key,label in toc)+'</nav><article>'+content+'</article></main></html>'
    (OUT/name).write_text(result,encoding='utf-8')
    if source.startswith('USER'):(BASE/'static/guides/PT_AI_SQUARE_등록가이드.html').write_text(result,encoding='utf-8')
    print(name)
