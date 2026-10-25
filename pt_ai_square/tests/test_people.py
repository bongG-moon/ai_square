from email.message import Message
import io
from urllib.error import URLError

import pytest

from pt_ai_square.backend import mongo_activity
from pt_ai_square.backend import people as people_module
from pt_ai_square.backend.storage import db, ensure_user, public_user
from .conftest import ready, publish


@pytest.fixture
def people_app(app):
    app.config['EMPLOYEE_PHOTO_BASE_URL'] = 'https://photos.company.example/pictures/'
    if 'people' not in app.blueprints:
        app.register_blueprint(people_module.people)
    with people_module._photo_lock:
        people_module._photo_cache.clear()
    return app


def test_received_contribution_uses_unique_downloads_excludes_self_updates_and_deleted(people_app):
    app=people_app
    owner,h=ready(app)
    assert publish(owner,h,approval=True).status_code==201
    assert publish(owner,h,tid=1,revision=1).status_code==201
    with app.app_context():
        mongo_activity.set_like(1,'member',True)
        mongo_activity.set_like(1,'owner',True)
        mongo_activity.record_download(1,'member',1)
        mongo_activity.record_download(1,'member',2)
        mongo_activity.record_download(1,'owner',1)
        mongo_activity.record_download(1,'other',2,update=True)
        # Multiple old daily rows still mean one employee received one tool.
        for n in range(2):
            db().activity_state.insert_one({'_id':'legacy-'+str(n),'tool':1,'user':'legacy-user','kind':'download','count':10,'created':100+n})
        db().tools.insert_one({'_id':90,'owner':'owner','deleted':True})
        mongo_activity.set_like(90,'member',True)
        db().tools.insert_one({'_id':91,'owner':'other','deleted':False})
        db().users.update_one({'_id':'other'},{'$set':{'enabled':False}})
    member,_=ready(app,'member')
    response=member.get('/api/people/ranking')
    assert response.status_code==200
    data=response.json
    assert data['period']=='all' and data['totalUsers']==1
    row=data['items'][0]
    assert (row['id'],row['registered'],row['likes'],row['downloads'],row['score'])==('owner',1,1,2,9)
    assert data['me']['id']=='member' and data['me']['rank'] is None
    assert 'SECRET INSTALL GUIDE' not in response.text and '장비 점검' not in response.text
    with app.app_context():mongo_activity.set_like(1,'member',False)
    assert member.get('/api/people/ranking').json['items'][0]['score']==7


def test_top_ten_ties_and_current_employee_outside_top_ten(people_app):
    app=people_app
    with app.app_context():
        for n in range(12):
            uid=f'person-{n:02}'
            ensure_user(uid,f'직원 {n}')
            db().tools.insert_one({'_id':100+n,'owner':uid,'deleted':False})
    client,_=ready(app,'person-11')
    data=client.get('/api/people/ranking').json
    assert data['totalUsers']==12 and len(data['items'])==10
    assert [r['id'] for r in data['items']]==[f'person-{n:02}' for n in range(10)]
    assert data['me']['id']=='person-11' and data['me']['rank']==12 and data['me']['score']==5


def test_old_user_documents_have_backward_compatible_profile(people_app):
    with people_app.app_context():
        old={'_id':'001','name':'이전 사용자','enabled':True,'orgId':'organization-0'}
        user=public_user(old)
        assert user['emp_no']=='001' and user['emp_name']=='이전 사용자'
        assert user['dept']=='공통' and user['dept_cd']==''
        assert user['photoUrl']=='/api/me/photo'


class FakePhoto(io.BytesIO):
    status=200
    def __init__(self,data,mime='image/jpeg'):
        super().__init__(data)
        self.headers=Message()
        self.headers['Content-Type']=mime
        self.headers['Content-Length']=str(len(data))


def test_photo_is_fixed_host_current_employee_only_and_no_forwarded_credentials(people_app,monkeypatch):
    calls=[]
    class Opener:
        def open(self,request,timeout):
            calls.append((request.full_url,dict(request.header_items()),timeout))
            return FakePhoto(b'\xff\xd8\xffphoto')
    monkeypatch.setattr(people_module,'build_opener',lambda *handlers:Opener())
    client,_=ready(people_app,'0012345')
    response=client.get('/api/me/photo',headers={'Cookie':'sensitive-value'})
    assert response.status_code==200 and response.mimetype=='image/jpeg'
    assert response.data==b'\xff\xd8\xffphoto'
    assert calls==[(people_app.config['EMPLOYEE_PHOTO_BASE_URL']+'0012345.jpg',{'Accept':'image/jpeg,image/png,image/webp,image/gif'},3)]
    assert response.headers['Cache-Control'].startswith('private')
    assert 'no-store' in response.headers['Cache-Control']
    # Same employee uses a bounded in-memory cache.
    assert client.get('/api/me/photo').status_code==200 and len(calls)==1
    assert people_app.test_client().get('/api/me/photo').status_code==401


@pytest.mark.parametrize('data,mime',[(b'<html>login</html>','text/html'),(b'<svg></svg>','image/jpeg'),(b'\xff\xd8\xffjpeg','image/png'),(b'x'*20,'image/jpeg')])
def test_invalid_or_oversized_photo_uses_fallback(people_app,monkeypatch,data,mime):
    class Opener:
        def open(self,request,timeout):return FakePhoto(data,mime)
    monkeypatch.setattr(people_module,'build_opener',lambda *handlers:Opener())
    monkeypatch.setattr(people_module,'PHOTO_MAX_BYTES',16)
    client,_=ready(people_app,'0012345')
    assert client.get('/api/me/photo').status_code==404


def test_photo_network_failure_and_non_numeric_mock_identity(people_app,monkeypatch):
    calls=[]
    def fail(employee):calls.append(employee);raise URLError('not reachable')
    monkeypatch.setattr(people_module,'_fetch_photo',fail)
    client,_=ready(people_app,'owner')
    assert client.get('/api/me/photo').status_code==404 and calls==[]
    numeric,_=ready(people_app,'0012345')
    assert numeric.get('/api/me/photo').status_code==404
    assert numeric.get('/api/me/photo').status_code==404 and calls==['0012345']
    assert people_module._NoRedirect().redirect_request(None,None,302,'',{},'https://outside.test/') is None


def test_numeric_mock_employee_photo_never_reaches_company_service(people_app,monkeypatch):
    people_app.config.update(AUTH_MODE='mock', MOCK_USER='0012345', MOCK_NAME='로컬 직원')
    def unexpected(employee):raise AssertionError('mock must never request an intranet photo')
    monkeypatch.setattr(people_module,'_fetch_photo',unexpected)
    assert people_app.test_client().get('/api/me/photo').status_code==404


def add_contributor(app, employee='0012345', enabled=True, deleted=False):
    with app.app_context():
        ensure_user(employee, '공유 구성원', '융합기술')
        db().users.update_one({'_id':employee},{'$set':{'enabled':enabled,'dept':'융합기술'}})
        db().tools.insert_one({'_id':900,'owner':employee,'deleted':deleted})


def test_ranking_portrait_contract_and_fixed_host_without_forwarded_credentials(people_app,monkeypatch):
    add_contributor(people_app)
    calls=[]
    class Opener:
        def open(self,request,timeout):
            calls.append((request.full_url,dict(request.header_items()),timeout))
            return FakePhoto(b'\xff\xd8\xffportrait')
    monkeypatch.setattr(people_module,'build_opener',lambda *handlers:Opener())
    viewer,_=ready(people_app,'member')
    data=viewer.get('/api/people/ranking').json
    row=data['items'][0]
    assert (row['name'],row['org'],row['score'])==('공유 구성원','융합기술',5)
    assert row['photoUrl']=='/api/people/0012345/photo'
    assert data['me']['photoUrl'] is None
    response=viewer.get(row['photoUrl'])
    assert response.status_code==200 and response.mimetype=='image/jpeg'
    assert response.data==b'\xff\xd8\xffportrait'
    assert response.headers['Cache-Control']=='private, no-store'
    assert response.headers['X-Content-Type-Options']=='nosniff'
    assert calls==[(people_app.config['EMPLOYEE_PHOTO_BASE_URL']+'0012345.jpg',{'Accept':'image/jpeg,image/png,image/webp,image/gif'},3)]
    assert viewer.get(row['photoUrl']).status_code==200 and len(calls)==1
    # Cached portraits also become inaccessible when a contributor is disabled.
    with people_app.app_context():db().users.update_one({'_id':'0012345'},{'$set':{'enabled':False}})
    assert viewer.get(row['photoUrl']).status_code==404 and len(calls)==1


@pytest.mark.parametrize('case,employee',[
    ('unknown','0012345'),('disabled','0012345'),('no-tools','0012345'),
    ('deleted','0012345'),('nonnumeric','owner'),('too-long','1'*21),
])
def test_ineligible_contributor_portraits_never_fetch_upstream(people_app,monkeypatch,case,employee):
    if case not in {'unknown','no-tools'}:
        add_contributor(people_app,employee,enabled=case!='disabled',deleted=case=='deleted')
    elif case=='no-tools':
        with people_app.app_context():ensure_user(employee,'공유 전 구성원')
    def unexpected(employee):raise AssertionError('ineligible portrait must not reach company service')
    monkeypatch.setattr(people_module,'_fetch_photo',unexpected)
    viewer,_=ready(people_app,'member')
    response=viewer.get('/api/people/'+employee+'/photo')
    assert response.status_code==404
    assert response.headers['Cache-Control']=='private, no-store'


def test_unauthenticated_and_mock_ranking_portraits_do_not_fetch_company_service(people_app,monkeypatch):
    add_contributor(people_app)
    def unexpected(employee):raise AssertionError('unauthenticated/mock portrait must not reach company service')
    monkeypatch.setattr(people_module,'_fetch_photo',unexpected)
    assert people_app.test_client().get('/api/people/0012345/photo').status_code==401
    people_app.config.update(AUTH_MODE='mock',MOCK_USER='0012345',MOCK_NAME='로컬 구성원')
    viewer=people_app.test_client()
    assert viewer.get('/api/people/0012345/photo').status_code==404
    data=viewer.get('/api/people/ranking').json
    assert data['items'][0]['photoUrl'] is None and data['me']['photoUrl'] is None


def test_contributor_portrait_uses_existing_image_validation_and_failure_cache(people_app,monkeypatch):
    add_contributor(people_app)
    calls=[]
    class Opener:
        def open(self,request,timeout):
            calls.append(request.full_url)
            return FakePhoto(b'<svg>not a photograph</svg>','image/jpeg')
    monkeypatch.setattr(people_module,'build_opener',lambda *handlers:Opener())
    viewer,_=ready(people_app,'member')
    assert viewer.get('/api/people/0012345/photo').status_code==404
    assert viewer.get('/api/people/0012345/photo').status_code==404
    assert calls==[people_app.config['EMPLOYEE_PHOTO_BASE_URL']+'0012345.jpg']
