from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import io
import json
import time
import zipfile
from pt_ai_square.backend.storage import db, deliver_notifications, ensure_user
from pt_ai_square import create_app
from .conftest import ready, publish

def test_private_card_and_full_server_gate(app):
    owner,h=ready(app);assert publish(owner,h,approval=True).status_code==201
    c,mh=ready(app,'member');data=c.get('/api/bootstrap').json;x=data['items'][0]
    assert x['name']=='장비 점검' and x['access']=='none'
    assert x['guide']=='' and not x['versions'] and not x['comments'] and x['url']==''
    assert 'SECRET' not in json.dumps(data)
    for path in ['/api/tools/1','/download/1/1','/api/tools/1/manifest']:assert c.get(path).status_code==403
    assert c.patch('/api/tools/1',json={'name':'hacked','expectedRevision':1},headers=mh).status_code==403
    assert c.delete('/api/tools/1',json={'expectedRevision':1},headers=mh).status_code==403
    assert c.post('/api/tools/1/comments',json={'kind':'개선 의견','text':'blocked'},headers=mh).status_code==403
    assert c.put('/api/tools/1/like',json={'liked':True},headers=mh).status_code==403

def test_application_approval_revoke_reapply_and_notifications(app):
    owner,h=ready(app);publish(owner,h,approval=True)
    c,mh=ready(app,'member')
    assert c.post('/api/tools/1/requests',json={'reason':'업무에 필요'},headers=mh).status_code==200
    assert c.post('/api/tools/1/requests',json={'reason':'again'},headers=mh).status_code==409
    assert owner.get('/api/notifications').json['unread']==1
    r=owner.get('/api/bootstrap').json['requests'][0]
    assert r['status']=='대기' and not r['granted']
    assert owner.post(f'/api/requests/{r["id"]}/decision',json={'status':'승인','reason':'','expectedRevision':r['requestRevision']},headers=h).status_code==200
    assert c.get('/api/tools/1').json['guide']=='SECRET INSTALL GUIDE'
    assert owner.post(f'/api/requests/{r["id"]}/decision',json={'status':'승인','reason':'','expectedRevision':r['requestRevision']},headers=h).status_code==409
    assert owner.post(f'/api/requests/{r["id"]}/decision',json={'status':'회수','reason':'업무 종료'},headers=h).status_code==200
    assert c.get('/api/tools/1').status_code==403
    row=owner.get('/api/bootstrap').json['requests'][0];assert row['status']=='승인' and not row['granted'] and len(row['history'])==3
    assert c.post('/api/tools/1/requests',json={'reason':'재신청'},headers=mh).status_code==200
    assert c.get('/api/notifications').json['unread']==2

def test_grant_only_owner_admin_and_mine_ownerid(app):
    owner,h=ready(app);publish(owner,h,approval=True)
    other,oh=ready(app,'other');assert other.post('/api/tools/1/grants',json={'user':'member'},headers=oh).status_code==403
    assert owner.post('/api/tools/1/grants',json={'user':'member'},headers=h).status_code==200
    c,_=ready(app,'member');assert c.get('/api/tools/1').status_code==200
    a,_=ready(app,'admin');x=a.get('/api/bootstrap').json['items'][0];assert x['canManage'] and x['ownerId']=='owner'

def test_feedback_replies_status_and_recipient_isolation(app):
    owner,h=ready(app);publish(owner,h)
    c,mh=ready(app,'member');r=c.post('/api/tools/1/comments',json={'kind':'개선 의견','text':'Excel 결과를 주세요'},headers=mh);assert r.status_code==201
    fid=r.json['id'];other,oh=ready(app,'other')
    assert other.post(f'/api/feedback/{fid}/reply',json={'text':'no'},headers=oh).status_code==403
    assert c.post(f'/api/feedback/{fid}/reply',json={'text':'test','status':'반영 완료'},headers=mh).status_code==403
    assert owner.post(f'/api/feedback/{fid}/reply',json={'text':'개발하겠습니다.','status':'반영 중'},headers=h).status_code==200
    feedback=c.get('/api/tools/1').json['comments'][0];assert feedback['status']=='반영 중' and len(feedback['replies'])==1
    notices=c.get('/api/notifications').json;assert notices['unread']==1
    assert other.put('/api/notifications/read',json={'id':notices['notifications'][0]['id']},headers=oh).status_code==200
    assert c.get('/api/notifications').json['unread']==1
    assert c.put('/api/notifications/read',json={'all':True},headers=mh).status_code==200
    assert c.get('/api/notifications').json['unread']==0

def test_idea_atomic_claim_status_link_and_reply(app):
    c,h=ready(app,'member');r=c.post('/api/ideas',json={'name':'자동 요약','desc':'검토 시간을 줄이고 싶어요','category':'공통 업무'},headers=h);assert r.status_code==201
    def claim(uid):
        client,headers=ready(app,uid);return client.patch('/api/ideas/1',json={'claim':True,'expectedRevision':0},headers=headers).status_code
    with ThreadPoolExecutor(2) as pool:codes=list(pool.map(claim,['owner','other']))
    assert sorted(codes)==[200,409]
    i=c.get('/api/ideas').json['ideas'][0];worker,wh=ready(app,i['assignee'])
    assert c.patch('/api/ideas/1',json={'status':'개발 중','expectedRevision':1},headers=h).status_code==403
    assert worker.patch('/api/ideas/1',json={'status':'개발 중','text':'작업 시작','expectedRevision':1},headers=wh).status_code==200
    assert worker.patch('/api/ideas/1',json={'status':'구현 완료','expectedRevision':2},headers=wh).status_code==400
    publish(worker,wh)
    assert worker.patch('/api/ideas/1',json={'status':'구현 완료','tool':1,'expectedRevision':2},headers=wh).status_code==200
    i=c.get('/api/ideas').json['ideas'][0];assert i['tool']==1 and i['status']=='구현 완료' and i['toolName']=='장비 점검'
    assert c.get('/api/notifications').json['unread']==3

def test_taxonomy_ids_rename_disable_and_registration(app):
    a,ah=ready(app,'admin');owner,h=ready(app)
    assert owner.post('/api/taxonomy',json={'kind':'category','name':'불가'},headers=h).status_code==403
    r=a.post('/api/taxonomy',json={'kind':'category','name':'신규업무','enabled':True,'order':8},headers=ah);cid=r.json['id']
    assert publish(owner,h,category='신규업무').status_code==201
    assert a.post('/api/taxonomy',json={'id':cid,'kind':'category','name':'분석업무','enabled':False,'order':8},headers=ah).status_code==200
    x=owner.get('/api/tools/1').json;assert x['category']=='분석업무' and x['categoryId']==cid
    assert publish(owner,h,category='분석업무').status_code==400
    assert owner.patch('/api/tools/1',json={'name':'정보 수정','expectedRevision':1},headers=h).status_code==200
    assert a.post('/api/taxonomy',json={'id':'organization-0','kind':'organization','name':'공통','enabled':False},headers=ah).status_code==400

def test_base_admin_and_extra_admin_revocation(app):
    a,ah=ready(app,'admin');owner,h=ready(app)
    assert owner.put('/api/admins/other',json={'active':True},headers=h).status_code==403
    assert a.put('/api/admins/owner',json={'active':True},headers=ah).status_code==200
    assert owner.get('/api/bootstrap').json['user']['role']=='admin'
    assert owner.put('/api/admins/other',json={'active':True},headers=h).status_code==403
    assert a.put('/api/admins/admin',json={'active':False},headers=ah).status_code==409
    assert a.put('/api/admins/owner',json={'active':False},headers=ah).status_code==200
    assert owner.get('/api/admins').status_code==403

def test_release_subscription_rollback_delete_and_restore(app):
    owner,h=ready(app);publish(owner,h)
    c,mh=ready(app,'member');assert c.put('/api/tools/1/subscription',json={'enabled':True},headers=mh).status_code==200
    assert publish(owner,h,tid=1,revision=1,changes='second',guide='SECOND').status_code==201
    assert c.get('/api/notifications').json['unread']==1
    assert publish(owner,h,tid=1,revision=1).status_code==409
    assert owner.delete('/api/tools/1/versions/1',headers=h).status_code==409
    assert owner.post('/api/tools/1/rollback',json={'version':1,'expectedRevision':2},headers=h).status_code==200
    assert c.get('/api/tools/1').json['guide']=='SECRET INSTALL GUIDE'
    assert c.get('/download/1/2').status_code==404
    assert owner.delete('/api/tools/1/versions/2',headers=h).status_code==200
    x=owner.get('/api/tools/1').json
    assert owner.delete('/api/tools/1',json={'expectedRevision':x['revision']},headers=h).status_code==200
    assert not c.get('/api/bootstrap').json['items'] and c.get('/download/1/1').status_code==404
    trash=owner.get('/api/bootstrap').json['items'][0];assert trash['deleted']
    assert owner.post('/api/tools/1/restore',json={'expectedRevision':trash['revision']},headers=h).status_code==200
    assert c.get('/api/tools/1').status_code==200

def test_no_sqlite_files_and_persistence(app):
    owner,h=ready(app);publish(owner,h);owner.put('/api/tools/1/like',json={'liked':True},headers=h)
    assert not list(Path(app.config['DATA_DIR']).rglob('*.sqlite*'))
    app2=create_app({k:app.config[k] for k in ['TESTING','AUTH_MODE','SSO_FACTORY','ADMIN_IDS','SECRET_KEY','SESSION_COOKIE_SECURE','DATA_DIR','MONGODB_URI','MONGODB_DATABASE']})
    c,_=ready(app2);x=c.get('/api/bootstrap').json['items'][0];assert x['likes']==1 and x['name']=='장비 점검'
    app2.extensions['square_mongo_client'].close()

def test_auth_csrf_xss_and_upload_validation(app):
    assert app.test_client().get('/api/bootstrap').status_code==401
    c,h=ready(app);assert c.post('/api/ideas',json={}).status_code==403
    assert publish(c,h,name='<script>alert(1)</script>').status_code==201
    assert c.get('/').headers['Content-Security-Policy'].startswith("default-src 'self'")
    m=dict(name='bad',desc='bad',owner='owner',org='공통',category='공통 업무',platform='Claude',type='Skill',guide='guide',approval=False)
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr('../outside.py','bad')
    b.seek(0)
    assert c.post('/api/tools',data={'metadata':json.dumps(m),'artifact':(b,'bad.zip')},headers=h).status_code==400
    assert db_tools_count(app)==1

def db_tools_count(app):
    with app.app_context():return db().tools.count_documents({})

def test_sso_disabled_user_and_removed_password_login(app):
    c,h=ready(app,'login-user')
    assert c.get('/api/bootstrap').status_code==200
    assert c.post('/login',data={'user_id':'login-user','password':'unused'},headers=h).status_code==405
    with app.app_context():db().users.update_one({'_id':'login-user'},{'$set':{'enabled':False}})
    assert c.get('/api/bootstrap').status_code==401
    page=c.get('/login').get_data(as_text=True)
    assert 'type="password"' not in page and 'name="user_id"' not in page

def test_outbox_replay_does_not_duplicate_inbox(app):
    owner,h=ready(app);publish(owner,h,approval=True)
    with app.app_context():
        e={'id':'retry-event','recipients':['member'],'title':'retry','target':{'type':'tool','id':1},'kind':'update','created':time.time()}
        db().tools.update_one({'_id':1},{'$push':{'outbox':e}});deliver_notifications()
        db().tools.update_one({'_id':1},{'$push':{'outbox':e}});deliver_notifications()
        assert db().notifications.count_documents({'user':'member'})==1

def test_mongo_outage_fails_closed(app):
    from pymongo import MongoClient
    c,_=ready(app)
    original=app.extensions['square_mongo'];bad=MongoClient('mongodb://127.0.0.1:1/',serverSelectionTimeoutMS=50)
    app.extensions['square_mongo']=bad['no_fallback']
    try:assert c.get('/api/bootstrap').status_code==503
    finally:app.extensions['square_mongo']=original;bad.close()
