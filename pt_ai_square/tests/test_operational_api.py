"""Exercise each added source-write/follow-up boundary through actual APIs."""
import pytest
import time
from pymongo.collection import Collection
from pymongo.errors import OperationFailure

from .conftest import ready, publish
from .test_post_commit import fail_update
from .test_storage_capacity import limits
from pt_ai_square.backend.storage import db
from pt_ai_square.backend import mongo_api


@pytest.mark.parametrize('action', ['edit','delete','restore','rollback','delete-version',
                                  'taxonomy','administrator','retention','grant','decision'])
def test_mutation_and_audit_are_durable_even_when_audit_delivery_fails(app,monkeypatch,action):
    c,h=ready(app,'admin')
    assert publish(c,h,approval=action in {'grant','decision'}).status_code==201
    collection,key='tools',1
    if action=='restore':
        assert c.delete('/api/tools/1',headers=h,json={'expectedRevision':1}).status_code==200
    if action in {'rollback','delete-version'}:
        assert publish(c,h,tid=1,revision=1).status_code==201
    if action=='delete-version':
        assert publish(c,h,tid=1,revision=2).status_code==201
    if action=='decision':
        member,mh=ready(app,'member')
        assert member.post('/api/tools/1/requests',headers=mh,json={'reason':'need'}).status_code==200
    with monkeypatch.context() as fault:
        fail_update(fault,lambda name,q,u:name=='audit')
        if action=='edit': r=c.patch('/api/tools/1',headers=h,json={'name':'updated','expectedRevision':1})
        elif action=='delete': r=c.delete('/api/tools/1',headers=h,json={'expectedRevision':1})
        elif action=='restore': r=c.post('/api/tools/1/restore',headers=h,json={'expectedRevision':2})
        elif action=='rollback': r=c.post('/api/tools/1/rollback',headers=h,json={'expectedRevision':2,'version':1})
        elif action=='delete-version': r=c.delete('/api/tools/1/versions/1',headers=h)
        elif action=='taxonomy':
            r=c.post('/api/taxonomy',headers=h,json={'kind':'category','name':'new category'})
            collection,key='taxonomy',r.json.get('id')
        elif action=='administrator':
            r=c.put('/api/admins/member',headers=h,json={'active':True});collection,key='administrators','member'
        elif action=='retention':
            r=c.put('/api/storage/policy',headers=h,json={'keep':5,'days':180});collection,key='settings','retention'
        elif action=='grant':
            r=c.post('/api/tools/1/grants',headers=h,json={'user':'member'});collection,key='access','1:member'
        else:
            r=c.post('/api/requests/1:member/decision',headers=h,json={'status':'승인','reason':''});collection,key='access','1:member'
    assert r.status_code==200,r.json
    assert r.json['pending'] is True
    with app.app_context():
        row=db()[collection].find_one({'_id':key})
        entries=[e for e in row['outbox'] if e.get('audit')]
        assert len(entries)==1
        audit_id=entries[0]['audit']['_id']
        if action=='edit': assert row['data']['name']=='updated'
        elif action in {'delete','restore'}: assert row['deleted']==(action=='delete')
        elif action=='rollback': assert row['active']==1 and row['paused'] is True
        elif action=='delete-version': assert row['versions'][0]['deleted'] is True
        elif action=='taxonomy': assert row['name']=='new category'
        elif action=='administrator': assert row['active'] is True
        elif action=='retention': assert row['keep']==5 and row['days']==180
        else: assert row['granted'] is True
    assert c.get('/api/notifications').status_code==200
    assert c.get('/api/notifications').status_code==200
    with app.app_context():
        assert db()[collection].find_one({'_id':key})['outbox']==[]
        assert db().audit.count_documents({'_id':audit_id})==1


def test_capacity_calculation_failure_happens_before_policy_write(app,monkeypatch):
    c,h=ready(app,'admin')
    def fail(**kwargs): raise OSError('Filesystem unavailable')
    monkeypatch.setattr(mongo_api,'storage_snapshot',fail)
    assert limits(c,h).status_code==500
    with app.app_context(): assert db().settings.find_one({'_id':'storage_limits'}) is None


def test_like_saved_even_when_count_cannot_be_read(app,monkeypatch):
    c,h=ready(app);assert publish(c,h).status_code==201
    original=Collection.count_documents
    def failed(collection,*args,**kwargs):
        if collection.name=='activity_state':raise OperationFailure('private',225)
        return original(collection,*args,**kwargs)
    with monkeypatch.context() as fault:
        fault.setattr(Collection,'count_documents',failed)
        r=c.put('/api/tools/1/like',headers=h,json={'liked':True})
    assert r.status_code==200 and r.json['liked'] is True and r.json['count'] is None
    assert r.json['countsPending'] is True
    with app.app_context(): assert db().activity_state.find_one({'_id':'like:1:owner'})['liked'] is True
    assert c.get('/api/bootstrap').json['items'][0]['likes']==1


def test_download_followup_failure_keeps_file_response_and_recovers(app,monkeypatch):
    c,h=ready(app);assert publish(c,h).status_code==201
    member,mh=ready(app,'member')
    with monkeypatch.context() as fault:
        fail_update(fault,lambda name,q,u:name in {'activity','subscriptions'})
        r=member.get('/download/1/1');assert r.status_code==200
        assert r.data.startswith(b'PK');r.close()
    with app.app_context():
        row=db().activity_state.find_one({'_id':'download:1:member'})
        assert row['count']==1 and len(row['outbox'])==1
    assert member.get('/api/notifications').status_code==200
    assert member.get('/api/notifications').status_code==200
    with app.app_context():
        assert db().activity.count_documents({'tool':1,'user':'member','kind':'download'})==1
        assert db().subscriptions.find_one({'tool':1,'user':'member'})['enabled'] is True


def test_primary_download_failure_is_not_hidden(app,monkeypatch):
    c,h=ready(app);assert publish(c,h).status_code==201
    fail_update(monkeypatch,lambda name,q,u:name=='activity_state')
    assert c.get('/download/1/1').status_code==503


def test_grant_delivers_to_preserved_legacy_access_id(app):
    c,h=ready(app);assert publish(c,h,approval=True).status_code==201
    with app.app_context():
        db().access.insert_one({'_id':'legacy-access-id','tool':1,'user':'member','granted':False})
    r=c.post('/api/tools/1/grants',headers=h,json={'user':'member'})
    assert r.status_code==200 and r.json['pending'] is False
    with app.app_context():
        row=db().access.find_one({'_id':'legacy-access-id'})
        assert row['granted'] is True and row['outbox']==[]
        assert db().subscriptions.find_one({'tool':1,'user':'member'})['enabled'] is True


def test_retention_response_does_not_expose_internal_events(app):
    c,h=ready(app,'admin')
    with app.app_context():
        db().settings.update_one({'_id':'retention'},{'$set':{'outbox':[{'private':'value'}],'postCommit':[{'private':'old'}]}})
    assert set(c.get('/api/bootstrap').json['policy'])=={'keep','days'}


@pytest.mark.parametrize('failure',['purge','count'])
def test_cleanup_keeps_success_after_deletion_markers_are_saved(app,monkeypatch,failure):
    c,h=ready(app,'admin')
    for n in range(4):
        args={} if n==0 else {'tid':1,'revision':n}
        assert publish(c,h,**args).status_code==201
    with app.app_context():
        db().tools.update_one({'_id':1},{'$set':{'versions.0.created':time.time()-100*86400}})
    if failure=='purge':
        def fail():raise OperationFailure('private',225)
        monkeypatch.setattr(mongo_api,'purge_deleted',fail)
    else:
        original=Collection.find
        def fail(collection,*args,**kwargs):
            if collection.name=='tools':raise OperationFailure('private',225)
            return original(collection,*args,**kwargs)
        # Activate the read fault only after the source mutation and cleanup.
        monkeypatch.setattr(mongo_api,'purge_deleted',lambda:monkeypatch.setattr(Collection,'find',fail))
    response=c.post('/api/storage/cleanup',headers=h,json={'candidates':[{'tool':1,'version':1}]})
    assert response.status_code==200 and response.json['ok'] is True and response.json['pending']
    if failure=='count':assert response.json['countsPending'] is True and response.json['pendingFiles'] is None
    monkeypatch.undo()
    with app.app_context():assert db().tools.find_one({'_id':1})['versions'][0]['deleted'] is True
