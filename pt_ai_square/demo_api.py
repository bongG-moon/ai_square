"""Read-only fixture preview. Never used as a fallback for an unavailable database."""
import copy
import json
import time
from pathlib import Path
from flask import jsonify, request
from werkzeug.exceptions import NotFound

MESSAGE='데모 화면에서는 저장·다운로드할 수 없습니다. runtime_config.py에 MONGODB_URI를 입력하고 서버를 재시작해 주세요.'

def install_demo(app):
    fixture=json.loads((Path(__file__).parent/'demo'/'catalog.json').read_text(encoding='utf-8'))
    now=time.time()
    items=[]
    for i, source in enumerate(fixture['tools'],1):
        versions=[dict(n=n,age=3-n,size=0,bytes=0,refs=0,note='화면 체험용 배포 이력',deleted=False,withdrawn=False,sha256='',filename='sample.zip',created=now-(3-n)*86400,url='') for n in [2,1]]
        items.append(dict(source,id=i,ownerId='demo-owner' if i<=3 else 'demo-colleague',owner='예시 등록자',orgId='organization-0',categoryId='category-0',platform='Claude',workTags=source['tags'],approval=False,visibility='전체 공개',audience=[],guide='화면 체험용 예시입니다. 실제 실행 파일은 포함되어 있지 않습니다.',environment='도구별 설치 안내 확인',changes='예시 개선 사항',created=now-i*3600,editorial=i,hidden=False,deleted=False,active=2,fallback=1,revision=2,updatePaused=False,likes=48-i*3,downloads=220-i*17,liked=False,rankScore=100-i*7,canManage=True,access='approved',accessDecision='',versions=versions,comments=[],url='',mode='zip',support='설치·연결 안내',subscribed=False,icon={'MCP':'plug','Skill':'file-text','플러그인':'braces','하네스':'layers-2','Tool':'package'}[source['type']]))
        items[-1]['orgId']=f"organization-{fixture['organizations'].index(source['org'])}"
        items[-1]['categoryId']=f"category-{fixture['categories'].index(source['category'])}"
    def taxonomy(kind,names):
        return [dict(id=f'{kind}-{i}',name=name,kind=kind,enabled=True,order=i,owner='') for i,name in enumerate(names)]
    user=dict(id='demo-owner',name='체험 사용자',org='공통',orgId='organization-0',role='admin',baseAdmin=True)
    bootstrap=dict(demo=True,items=items,user=user,csrf='',authMode='demo',organizations=taxonomy('organization',fixture['organizations']),categories=taxonomy('category',fixture['categories']),requests=fixture['requests'],policy=dict(keep=3,days=30),rankAsOf=now,activityBackend='demo',unread=0,audit=['더미 데이터로 화면을 체험 중입니다.'],storage=dict(used=0,quota=5*1024**3,pending=0))

    @app.before_request
    def readonly():
        if request.method not in {'GET','HEAD','OPTIONS'} or request.path.startswith('/download/'):
            return jsonify(error=MESSAGE,demo=True),409

    @app.get('/api/bootstrap')
    def demo_bootstrap(): return jsonify(bootstrap)

    @app.get('/api/tools/<int:tid>')
    def demo_detail(tid):
        item=next((x for x in items if x['id']==tid),None)
        if not item: raise NotFound()
        return jsonify(item)

    @app.get('/api/<path:path>')
    def demo_reads(path):
        responses={'ideas':dict(ideas=fixture['ideas']), 'notifications':dict(notifications=[],nextCursor=None,unread=0), 'admins':dict(admins=[dict(id=user['id'],name=user['name'],base=True)]), 'activity':dict(events=[],nextCursor=None,backend='demo'), 'storage/candidates':dict(candidates=[])}
        if path=='users':
            q=request.args.get('q','').casefold()
            return jsonify(users=[x for x in fixture['users'] if q in (x['id']+x['name']).casefold()])
        if path not in responses: raise NotFound()
        return jsonify(copy.deepcopy(responses[path]))
