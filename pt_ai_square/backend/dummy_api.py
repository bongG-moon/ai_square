"""Read-only fixture preview. Never used as a fallback for an unavailable database."""
import copy
import json
import time
from pathlib import Path
from flask import jsonify, request
from werkzeug.exceptions import NotFound

MESSAGE='샘플 데이터는 조회 전용입니다. 저장·다운로드는 실제 데이터 모드에서 이용해 주세요.'

def install_dummy(app):
    fixture=json.loads((Path(__file__).resolve().parents[1]/'dummy'/'catalog.json').read_text(encoding='utf-8'))
    now=time.time()
    uid=app.config['MOCK_USER']
    admin=app.config['MOCK_ADMIN'] or uid in [x.strip() for x in app.config['ADMIN_IDS'].split(',')]
    app.config['SECRET_KEY']=app.config['SECRET_KEY'] or 'dummy-local-read-only'
    fixture['users'].insert(0,dict(id=uid,name=app.config['MOCK_NAME']))
    items=[]
    for i, source in enumerate(fixture['tools'],1):
        versions=[dict(n=n,age=3-n,size=0,bytes=0,refs=0,note='샘플 화면용 배포 이력',deleted=False,withdrawn=False,sha256='',filename='sample.zip',created=now-(3-n)*86400,url='') for n in [2,1]]
        items.append(dict(source,id=i,ownerId=uid if i<=3 else 'sample-colleague',owner='예시 등록자',orgId='organization-0',categoryId='category-0',platform='Claude',workTags=source['tags'],approval=False,visibility='전체 공개',audience=[],guide='샘플 화면용 예시입니다. 실제 실행 파일은 포함되어 있지 않습니다.',environment='도구별 설치 안내 확인',changes='예시 개선 사항',created=now-i*3600,editorial=i,hidden=False,deleted=False,active=2,fallback=1,revision=2,updatePaused=False,likes=48-i*3,downloads=220-i*17,liked=False,rankScore=2*(i%4+1)+(i%5)*3,recentLikes=i%4+1,recentDownloads=(i%5)*3,totalRankScore=2*(48-i*3)+(220-i*17),canManage=admin or i<=3,access='approved',accessDecision='',versions=versions,comments=[],url='',mode='zip',support='설치·연결 안내',subscribed=False,icon={'MCP/Tool':'plug','Skill':'file-text','플러그인/하네스':'braces'}[source['type']]))
        items[-1]['orgId']=f"organization-{fixture['organizations'].index(source['org'])}"
        items[-1]['categoryId']=f"category-{fixture['categories'].index(source['category'])}"
    def taxonomy(kind,names):
        return [dict(id=f'{kind}-{i}',name=name,kind=kind,enabled=True,order=i,owner='') for i,name in enumerate(names)]
    user=dict(id=uid,name=app.config['MOCK_NAME'],org='공통',orgId='organization-0',role='admin' if admin else 'user',baseAdmin=admin)
    bootstrap=dict(dummy=True,items=items,user=user,csrf='',authMode='mock',dataMode='dummy',organizations=taxonomy('organization',fixture['organizations']),categories=taxonomy('category',fixture['categories']),requests=fixture['requests'],policy=dict(keep=3,days=30),rankAsOf=now,activityBackend='dummy',unread=0,audit=['더미 데이터로 화면을 체험 중입니다.'],storage=dict(fixture['storage'],checkedAt=now) if admin else None)

    @app.before_request
    def readonly():
        if request.method not in {'GET','HEAD','OPTIONS'} or request.path.startswith('/download/'):
            return jsonify(error=MESSAGE,dummy=True),409

    @app.get('/api/bootstrap')
    def dummy_bootstrap(): return jsonify(bootstrap)

    @app.get('/api/tools/<int:tid>')
    def dummy_detail(tid):
        item=next((x for x in items if x['id']==tid),None)
        if not item: raise NotFound()
        return jsonify(item)

    @app.get('/api/people/ranking')
    def dummy_people_ranking():
        rows=copy.deepcopy(fixture.get('peopleRanking',[]))
        for row in rows:
            row['score']=row['registered']*5+row['likes']*2+row['downloads']
            row['isMe']=False
        rows.sort(key=lambda row:(-row['score'],-row['registered'],-row['likes'],-row['downloads'],row['id']))
        for rank,row in enumerate(rows,1):row['rank']=rank
        return jsonify(items=rows[:10],me=None,totalUsers=len(rows),period='all',asOf=now,dummy=True,
                       weights=dict(registered=5,likes=2,downloads=1),
                       method='등록 도구 × 5 + 받은 좋아요 × 2 + 고유 다운로드 × 1 · 전체 기간',
                       tieBreak='동점은 등록 수, 좋아요, 다운로드, 사번 순입니다. 샘플 데이터입니다.')

    @app.get('/api/<path:path>')
    def dummy_reads(path):
        responses={'ideas':dict(ideas=fixture['ideas']), 'notifications':dict(notifications=[],nextCursor=None,unread=0), 'admins':dict(admins=[dict(id=user['id'],name=user['name'],base=True)] if admin else []), 'activity':dict(events=[],nextCursor=None,backend='dummy'), 'storage/candidates':dict(candidates=[]), 'storage/limits':dict(storage=bootstrap['storage'])}
        if path=='users':
            q=request.args.get('q','').casefold()
            return jsonify(users=[x for x in fixture['users'] if q in (x['id']+x['name']).casefold()])
        if path not in responses: raise NotFound()
        return jsonify(copy.deepcopy(responses[path]))
