"""Real disposable-Mongo catalog scale, response parity and authorization tests."""
import copy
import json
import time
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import g, session
from pymongo.collection import Collection

from pt_ai_square.backend import mongo_api
from pt_ai_square.backend.catalog_snapshot import CatalogSnapshot
from pt_ai_square.backend.storage import db


NOW = 1792890000


def seed_catalog(app, count=12):
    rows=[]; comments=[]; decisions=[]
    for tid in range(1,count+1):
        data=dict(name=f'도구 {tid}',desc='업무 설명',owner='문의 담당자',
                  org='예전 조직',orgId='organization-0',category='예전 업무',categoryId='category-0',
                  platform='Claude',type='Skill',workTags=['보고서'],approval=tid%3==0,
                  visibility='전체 공개',audience=[],guide=f'PRIVATE GUIDE {tid}',
                  environment='Python',changes='개선',workflow={'steps':[{'title':'PRIVATE FLOW'}]})
        versions=[dict(n=n,created=NOW-100,size=20,note=f'배포 {n}',sha='a'*64,name='skill.zip',
                       url='',path=f'PRIVATE PATH {tid}',data=copy.deepcopy(data),commands={}) for n in [1,2]]
        rows.append(dict(_id=tid,owner='owner',data=data,created=NOW-200,versions=versions,
                         active=2,fallback=1,revision=2,deleted=False))
        decisions.append(dict(_id=f'ask-{tid}',tool=tid,user='other',status='대기',granted=False,
                              updated=tid,reason='요청',history=[{'status':'대기'}]))
        if tid%6==0:
            decisions.append(dict(_id=f'grant-{tid}',tool=tid,user='member',status='승인',
                                  granted=True,updated=tid,reason='승인'))
        for ci in range(4):
            comments.append(dict(_id=f'comment-{tid}-{ci}',tool=tid,user='author',kind='의견',
                                 body=f'PRIVATE COMMENT {tid}-{ci}',created=NOW+ci,
                                 replies=[dict(user='reply',text=f'답변 {j}',created=NOW+j) for j in range(2)]))
    with app.app_context():
        database=db()
        database.users.insert_many([dict(_id='author',name='댓글 작성자',enabled=True),dict(_id='reply',name='답변 작성자',enabled=True)])
        database.users.update_one({'_id':'member'},{'$set':{'dept':'동일한 부서명','dept_cd':'D001'}})
        database.taxonomy.update_one({'_id':'organization-0'},{'$set':{'name':'바뀐 조직'}})
        database.taxonomy.update_one({'_id':'category-0'},{'$set':{'name':'바뀐 업무'}})
        database.tools.insert_many(rows);database.feedback.insert_many(comments);database.access.insert_many(decisions)
        database.subscriptions.insert_many([dict(tool=t['_id'],user='member',enabled=t['_id']%2==0) for t in rows])
    return rows


def viewer(uid='member', **extra):
    return dict(id=uid,name=uid,role='admin' if uid=='admin' else 'user',enabled=True,
                dept='편집된 카탈로그 별칭',dept_cd='UNTRUSTED',**extra)


def response(app, uid='member', profile=None):
    with app.test_request_context('/api/bootstrap'):
        g.user=profile or viewer(uid);session['csrf']='test-csrf'
        with patch.object(mongo_api,'time',SimpleNamespace(time=lambda:NOW)):
            return mongo_api.bootstrap().get_json()


@pytest.mark.parametrize('count',[1,100])
def test_catalog_bulk_reads_stay_bounded_with_comments_and_replies(app,monkeypatch,count):
    seed_catalog(app,count)
    calls=Counter();original_find=Collection.find;original_aggregate=Collection.aggregate
    def find(collection,*args,**kwargs):
        calls['find:'+collection.name]+=1
        return original_find(collection,*args,**kwargs)
    def aggregate(collection,*args,**kwargs):
        calls['aggregate:'+collection.name]+=1
        return original_aggregate(collection,*args,**kwargs)
    monkeypatch.setattr(Collection,'find',find);monkeypatch.setattr(Collection,'aggregate',aggregate)
    started=time.perf_counter();data=response(app);elapsed=time.perf_counter()-started
    assert len(data['items'])==count
    assert sum(calls.values())<=12,dict(calls)
    for collection in ['tools','taxonomy','users','access','subscriptions','feedback','administrators']:
        assert calls['find:'+collection]==1,dict(calls)
    assert data['items'][0]['org']=='바뀐 조직'
    assert len(data['items'][0]['comments'])==4
    assert data['items'][0]['comments'][0]['author']=='댓글 작성자'
    assert data['items'][0]['comments'][0]['replies'][0]['author']=='답변 작성자'
    print(f'{count} tools: {sum(calls.values())} repository reads, {elapsed*1000:.2f} ms')


@pytest.mark.parametrize('uid',['member','owner','admin'])
def test_bulk_snapshot_matches_existing_single_item_serialization_and_requests(app,uid):
    rows=seed_catalog(app)
    with app.app_context():
        db().tools.update_one({'_id':3},{'$set':{'departmentGrants':[{'code':'D001','name':'동일한 부서명'}]}})
        db().feedback.update_one({'_id':'comment-1-0'},{'$set':{'user':'missing-user','replies':[{'user':'missing-reply','text':'보존','created':NOW}]}})
        db().tools.update_one({'_id':2},{'$set':{'data.orgId':'missing-taxonomy','owner':'missing-owner'}})
        rows=list(db().tools.find().sort('_id',1))
    with app.test_request_context('/api/bootstrap'):
        g.user=viewer(uid);stats=mongo_api.activity.statistics([t['_id'] for t in rows],uid,NOW)
        expected=[mongo_api.serialize(t,stats[t['_id']],NOW) for t in rows]
        expected_requests=mongo_api.access_rows()
        snapshot=CatalogSnapshot(rows,g.user,list(db().taxonomy.find()))
        actual=[mongo_api.serialize(t,stats[t['_id']],NOW,snapshot=snapshot) for t in rows]
        assert actual==expected
        assert mongo_api.access_rows(snapshot)==expected_requests


def test_denied_feedback_and_unmanaged_applicants_are_not_prefetched(app,monkeypatch):
    seed_catalog(app,3)
    with app.app_context():
        db().feedback.update_many({'tool':3},{'$set':{'user':'private-author','body':'DENIED COMMENT'}})
        db().users.insert_one({'_id':'private-author','name':'DENIED PERSON','enabled':True})
        db().access.update_one({'_id':'ask-1'},{'$set':{'user':'private-requester'}})
    queries=[];original=Collection.find
    def find(collection,*args,**kwargs):
        queries.append((collection.name,copy.deepcopy(args[0] if args else kwargs.get('filter',{}))))
        return original(collection,*args,**kwargs)
    monkeypatch.setattr(Collection,'find',find)
    data=response(app);private=data['items'][2]
    assert private['access']=='none' and private['comments']==[] and private['versions']==[]
    assert private['guide']=='' and private['url']=='' and 'workflow' not in private
    assert data['requests']==[]
    assert 'DENIED' not in json.dumps(data)
    feedback_query=next(q for name,q in queries if name=='feedback')
    assert set(feedback_query['tool']['$in'])=={1,2}
    names=next(q for name,q in queries if name=='users')['_id']['$in']
    assert 'private-author' not in names and 'private-requester' not in names


def test_fresh_snapshot_observes_personal_and_department_revocation_without_alias_trust(app):
    seed_catalog(app,3)
    def access():return response(app)['items'][2]['access']
    assert access()=='none'
    with app.app_context():
        db().access.insert_one(dict(_id='member-grant',tool=3,user='member',granted=True,status='승인',updated=NOW))
    assert access()=='approved'
    with app.app_context():
        db().access.update_one({'_id':'member-grant'},{'$set':{'granted':False}})
    assert access()=='none'
    with app.app_context():
        db().tools.update_one({'_id':3},{'$set':{'departmentGrants':[{'code':'D002','name':'동일한 부서명'}]}})
    assert access()=='none'  # Same display name is insufficient when department codes differ.
    with app.app_context():
        db().users.update_one({'_id':'member'},{'$set':{'dept_cd':'D002'}})
    assert access()=='approved'
    with app.app_context():
        db().users.update_one({'_id':'member'},{'$set':{'enabled':False}})
    assert access()=='none'


@pytest.mark.parametrize('uid',['member','owner','admin'])
def test_deleted_catalog_and_request_visibility_stays_scoped_to_manager(app,uid):
    seed_catalog(app,4)
    with app.app_context():
        db().tools.update_one({'_id':3},{'$set':{'deleted':True,'owner':'member'}})
        db().tools.update_one({'_id':4},{'$set':{'deleted':True,'owner':'other'}})
        db().access.insert_one(dict(_id='orphan',tool=999,user='member',granted=True,status='승인',updated=NOW))
    data=response(app,uid)
    expected_ids={'member':{1,2,3},'owner':{1,2},'admin':{1,2,3,4}}
    expected_requests={'member':{3},'owner':{1,2},'admin':{1,2,3,4}}
    assert {t['id'] for t in data['items']}==expected_ids[uid]
    assert {r['itemId'] for r in data['requests']}==expected_requests[uid]
    assert all(r['id']!='orphan' for r in data['requests'])


def test_bootstrap_empty_catalog_is_a_valid_response(app):
    data=response(app)
    assert data['items']==[] and data['requests']==[]
    assert data['policy']=={'keep':3,'days':90}


@pytest.mark.parametrize('uid',['member','owner','admin'])
@pytest.mark.parametrize('missing',[False,True])
def test_department_grants_keep_missing_or_disabled_profile_fail_closed(app,uid,missing):
    seed_catalog(app,3)
    with app.app_context():
        db().tools.update_one({'_id':3},{'$set':{'departmentGrants':[{'code':'D001','name':'같은 부서'}]}})
        if missing:db().users.delete_one({'_id':uid})
        else:db().users.update_one({'_id':uid},{'$set':{'enabled':False,'dept_cd':'D001'}})
    # Test the shared permission boundary directly, without letting the HTTP auth
    # layer reject the account before this narrower regression can be exercised.
    data=response(app,uid)
    private=next(t for t in data['items'] if t['id']==3)
    assert private['access']=='none' and private['versions']==[] and private['comments']==[]
    assert private['guide']==''


@pytest.mark.parametrize('malformed',['true','false',1])
def test_snapshot_does_not_treat_truthy_nonboolean_grants_as_approval(app,malformed):
    seed_catalog(app,3)
    with app.app_context():
        db().access.insert_one(dict(_id='malformed-grant',tool=3,user='member',granted=malformed,status='승인',updated=NOW))
    with app.test_request_context('/api/bootstrap'):
        g.user=viewer()
        target=db().tools.find_one({'_id':3})
        assert mongo_api.allowed(target) is False
    private=response(app)['items'][2]
    assert private['access']=='none' and private['versions']==[]
