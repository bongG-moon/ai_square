from urllib.parse import parse_qs,urlsplit,quote
import time
import pytest
from pt_ai_square.backend.storage import db
from .conftest import ready,publish

@pytest.fixture
def hcp(app):
    seen=[]
    class SSO:
        redirect_url='https://sso.example.test/'
        def __init__(self,request):
            self.request=request;seen.append(request.args.get('ORIGIN'))
        def check_day_cookie(self,cookie):return self.request.cookies.get('company')=='valid'
        def get_sso_info(self,cookie):return ('0012345','시험 직원','Test Employee','시험 부서','employee@example.test','D001')
    app.config.update(AUTH_MODE='sso',SSO_FACTORY=SSO)
    return app.test_client(),seen,SSO

def test_hcp_origin_redirect_nested_login_and_six_session_fields(app,hcp):
    client,seen,_=hcp
    original='http://localhost/?tab=browse'
    response=client.get('/?tab=browse')
    assert response.status_code==302
    login=urlsplit(response.location)
    assert login.path=='/login' and parse_qs(login.query)['ORIGIN']==[original]
    response=client.get(response.location)
    assert response.location=='https://sso.example.test/' and seen[-1]==original
    client.set_cookie('company','valid')
    response=client.get('/login/tools/17?ORIGIN='+quote(original,safe=''))
    assert response.status_code==302 and response.location=='https://sso.example.test/tools/17'
    with client.session_transaction() as session:
        assert session['logFlag'] is True
        assert [session[k] for k in ['emp_no','emp_name','emp_name_en','dept','email','dept_cd']]==['0012345','시험 직원','Test Employee','시험 부서','employee@example.test','D001']
    bootstrap=client.get('/api/bootstrap').json
    assert bootstrap['user']['id']=='0012345' and bootstrap['user']['org']=='시험 부서'
    assert [bootstrap['user'][k] for k in ['emp_no','emp_name','dept','dept_cd']]==['0012345','시험 직원','시험 부서','D001']
    with app.app_context():
        row=db().users.find_one({'_id':'0012345'})
        assert [row[k] for k in ['emp_no','emp_name','dept','dept_cd']]==['0012345','시험 직원','시험 부서','D001']
    assert app.config['TEMPLATES_AUTO_RELOAD'] is True


def test_company_flask_instance_keeps_sso_routes_and_template_identity(app,hcp):
    """The company-created app receives the full platform, not a second app."""
    from flask import Flask, template_rendered
    from pt_ai_square import init_app

    company = Flask('company_web_main', root_path=app.root_path)
    assert init_app(company, dict(app.config)) is company
    rendered = []
    def capture(sender, template, context, **extra):
        rendered.append((template.name, context))
    try:
        for path in ['/', '/login', '/login/<path:sub_path>']:
            assert sum(rule.rule == path for rule in company.url_map.iter_rules()) == 1
        client = company.test_client()
        assert client.get('/').status_code == 302
        client.set_cookie('company', 'valid')
        assert client.get('/login').status_code == 302
        with template_rendered.connected_to(capture, company):
            response = client.get('/')
        assert response.status_code == 200
        name, context = rendered[-1]
        assert name == 'index.html'
        assert [context[key] for key in ['emp_no', 'emp_name', 'emp_name_en', 'dept', 'email', 'dept_cd']] == [
            '0012345', '시험 직원', 'Test Employee', '시험 부서', 'employee@example.test', 'D001']
        assert client.get('/api/bootstrap').json['user']['id'] == '0012345'
    finally:
        company.extensions['square_mongo_client'].close()


def test_sso_profile_refresh_keeps_employee_references_and_connection_key(app,hcp):
    client,_,SSO=hcp
    client.set_cookie('company','valid');client.get('/login')
    with app.app_context():
        old=db().users.find_one({'_id':'0012345'})
        db().users.update_one({'_id':'0012345'},{'$set':{'activeConnectionKeyId':'keep-key'}})
        db().tools.insert_one({'_id':77,'owner':'0012345','deleted':False})
        db().access.insert_one({'tool':77,'user':'0012345','granted':True})
    SSO.get_sso_info=lambda self,cookie: ('0012345','바뀐 이름','Test Employee','변경 부서','employee@example.test','D001')
    with client.session_transaction() as session:session.clear()
    # Use the profile-only endpoint so the deliberately minimal ownership
    # fixture is not rendered as a catalog item.
    response=client.get('/login')
    assert response.status_code==302
    with app.app_context():
        row=db().users.find_one({'_id':'0012345'})
        assert row['orgId']==old['orgId']
        assert row['dept']=='변경 부서' and row['dept_cd']=='D001'
        assert row['name']=='바뀐 이름' and row['activeConnectionKeyId']=='keep-key'
        assert db().tools.find_one({'_id':77})['owner']=='0012345'
        assert db().access.find_one({'tool':77})['user']=='0012345'

def test_session_flag_alone_cannot_replace_verified_sso_login(app,hcp):
    client,_,_=hcp
    with client.session_transaction() as session:session.update(logFlag=True,emp_no='admin')
    response=client.get('/api/bootstrap')
    assert response.status_code==401
    assert parse_qs(urlsplit(response.json['login']).query)['ORIGIN']==['http://localhost/']
    with client.session_transaction() as session:assert 'emp_no' not in session and 'logFlag' not in session
    client.set_cookie('company','valid')
    assert client.get('/api/bootstrap').status_code==401
    assert client.get('/login').status_code==302
    assert client.get('/api/bootstrap').status_code==200
    # Local login is bounded independently of SDK cookies on API requests.
    with client.session_transaction() as session:session['_hcp_login']['at']=time.time()-8*3600-1;session.modified=True
    client.set_cookie('company','expired');assert client.get('/api/bootstrap').status_code==401
    with client.session_transaction() as session:assert 'logFlag' not in session

def test_disabled_account_does_not_loop_through_sso(app,hcp):
    client,_,_=hcp;client.set_cookie('company','valid');client.get('/login')
    with app.app_context():db().users.update_one({'_id':'0012345'},{'$set':{'enabled':False}})
    assert client.get('/login').status_code==403
    with client.session_transaction() as session:assert 'logFlag' not in session

@pytest.mark.parametrize('origin',['https://outside.example/','//outside.example/','/\\outside.example/','/%0d%0aLocation:outside','http://[broken'])
def test_login_rejects_untrusted_origin(hcp,origin):
    client,seen,_=hcp
    assert client.get('/login?ORIGIN='+quote(origin,safe='')).status_code==400
    assert not seen

def test_mock_bypasses_hcp_and_sets_employee_session(app):
    class Unavailable:
        def __init__(self,request):raise AssertionError('mock must not load SSO')
    app.config.update(AUTH_MODE='mock',SSO_FACTORY=Unavailable,MOCK_USER='0000099',MOCK_NAME='시험 사용자')
    client=app.test_client()
    assert client.get('/api/bootstrap').json['user']['id']=='0000099'
    with client.session_transaction() as session:
        assert session['emp_no']=='0000099' and session['logFlag'] is True

@pytest.mark.parametrize('target,reason',[
    (None,'missing_url'),('', 'missing_url'),(17,'missing_url'),
    ('https://[broken','malformed_url'),('https://sso.example.test:bad/','malformed_url'),
    ('https://sso.example.test:99999/','malformed_url'),('https:///login','missing_host'),
    ('javascript:alert(1)','unsupported_scheme'),('data:text/html,hello','unsupported_scheme'),
    ('//sso.example.test/','network_path'),('///sso.example.test/','network_path'),
    ('/\\sso.example.test/','backslash'),('https://@sso.example.test/','userinfo'),
    ('https://user:private-password@sso.example.test/','userinfo'),
    (' https://sso.example.test/','invalid_whitespace'),
    ('https://sso.example.test/\r\nLocation: https://outside.example/','invalid_whitespace'),
    ('login/continue','invalid_relative_path'),
])
def test_invalid_sdk_redirect_is_configuration_error(hcp,target,reason,caplog):
    client,_,SSO=hcp;SSO.redirect_url=target
    assert client.get('/login').status_code==503
    assert f'HCP SSO failure stage=redirect_url reason={reason}' in caplog.text
    assert 'private-password' not in caplog.text
    with client.session_transaction() as session:assert '_hcp_login' not in session


@pytest.mark.parametrize('target',[
    'http://sso.example.test/return?ticket=private-ticket',
    'https://sso.example.test:8443/return?ticket=private-ticket',
    '/return?ticket=private-ticket',
])
def test_sdk_web_redirect_preserves_scheme_host_port_and_query(hcp,target,caplog):
    client,_,SSO=hcp;SSO.redirect_url=target
    response=client.get('/login')
    assert response.status_code==302 and response.location==target
    client.set_cookie('company','valid')
    response=client.get('/login')
    assert response.status_code==302 and response.location==target
    assert client.get('/api/bootstrap').json['user']['id']=='0012345'
    assert client.get('/').status_code==200
    assert 'private-ticket' not in caplog.text


@pytest.mark.parametrize('base',['http://platform.example.test:8081/portal','/portal'])
def test_nested_login_preserves_sdk_http_or_relative_target(hcp,base):
    client,_,SSO=hcp;SSO.redirect_url=base+'?ticket=value'
    response=client.get('/login/tools/17')
    assert response.status_code==302
    assert response.location==base+'/tools/17?ticket=value'


def test_refresh_and_admin_delete_do_not_reenter_login_sdk(app):
    """Reproduce an SDK that only accepts login requests with ORIGIN."""
    calls=[]
    class LoginOnlySSO:
        redirect_url='https://platform.example.test/'
        def __init__(self,request):
            calls.append((request.method,request.path))
            if request.method!='GET' or request.path!='/login' or not request.args.get('ORIGIN'):
                raise RuntimeError('SDK requires login context')
            self.uid=request.cookies.get('employee')
        def check_day_cookie(self,cookie):return bool(self.uid)
        def get_sso_info(self,cookie):return (self.uid,self.uid,'','공통','','D1')
    app.config['SSO_FACTORY']=LoginOnlySSO
    clients={}
    for uid in ['owner','admin','other']:
        client=app.test_client();client.set_cookie('employee',uid)
        first=client.get('/')
        assert first.status_code==302
        assert client.get(first.location).status_code==302
        bootstrap=client.get('/api/bootstrap').json
        clients[uid]=(client,{'X-CSRF-Token':bootstrap['csrf']})
    owner,h=clients['owner'];admin,ah=clients['admin'];other,oh=clients['other']
    # A valid platform session works even if the SSO cookie is absent on APIs.
    for client,_ in clients.values():client.delete_cookie('employee')
    for _ in range(3):
        assert owner.get('/').status_code==200
        assert owner.get('/api/bootstrap').status_code==200
    assert publish(owner,h).status_code==201
    assert publish(owner,h,tid=1,revision=1,changes='update').status_code==201
    assert owner.get('/download/1/2').status_code==200
    assert other.delete('/api/tools/1',json={'expectedRevision':2},headers=oh).status_code==403
    assert admin.delete('/api/tools/1',json={'expectedRevision':2}).status_code==403
    assert admin.delete('/api/tools/1',json={'expectedRevision':2},headers=ah).status_code==200
    with app.app_context():assert db().tools.find_one({'_id':1})['deleted'] is True
    assert calls==[('GET','/login')]*3


def test_session_reads_current_admin_and_enabled_status(app):
    owner,h=ready(app);assert publish(owner,h).status_code==201
    with app.app_context():db().administrators.insert_one({'_id':'extra-admin','active':True})
    admin,ah=ready(app,'extra-admin')
    assert admin.get('/api/bootstrap').json['user']['role']=='admin'
    with app.app_context():db().administrators.update_one({'_id':'extra-admin'},{'$set':{'active':False}})
    assert admin.delete('/api/tools/1',json={'expectedRevision':1},headers=ah).status_code==403
    with app.app_context():db().users.update_one({'_id':'owner'},{'$set':{'enabled':False}})
    assert owner.get('/api/bootstrap').status_code==401
    assert owner.delete('/api/tools/1',json={'expectedRevision':1},headers=h).status_code==401


@pytest.mark.parametrize('bad_stamp',[None,0,'yesterday',True,float('inf')])
def test_missing_or_invalid_session_stamp_requires_login(hcp,bad_stamp):
    client,seen,_=hcp;client.set_cookie('company','valid');client.get('/login')
    calls=len(seen)
    with client.session_transaction() as session:
        session['_hcp_login']['at']=bad_stamp;session.modified=True
    assert client.get('/api/bootstrap').status_code==401
    assert len(seen)==calls  # API responds with a login URL, never calls SDK.


def test_session_lifetime_is_absolute_and_logout_clears_identity(app,hcp,monkeypatch):
    from pt_ai_square.backend import auth
    client,seen,_=hcp;client.set_cookie('company','valid')
    start=time.time();monkeypatch.setattr(auth.time,'time',lambda:start)
    client.get('/login');csrf=client.get('/api/bootstrap').json['csrf']
    monkeypatch.setattr(auth.time,'time',lambda:start+7*3600)
    assert client.get('/api/bootstrap').status_code==200
    with client.session_transaction() as session:assert session['_hcp_login']['at']==start
    monkeypatch.setattr(auth.time,'time',lambda:start+8*3600+1)
    assert client.get('/api/bootstrap').status_code==401
    assert len(seen)==1
    # Login again, then explicit logout clears the verified session too.
    client.get('/login');csrf=client.get('/api/bootstrap').json['csrf']
    assert client.post('/api/logout',headers={'X-CSRF-Token':csrf}).status_code==200
    assert client.get('/api/bootstrap').status_code==401


def test_mock_identity_cannot_be_reused_as_sso(app):
    app.config.update(AUTH_MODE='mock',MOCK_USER='admin')
    client=app.test_client();assert client.get('/api/bootstrap').status_code==200
    app.config['AUTH_MODE']='sso'
    assert client.get('/api/bootstrap').status_code==401


@pytest.mark.parametrize('stage',['initialize','check_day_cookie','get_sso_info'])
def test_sdk_error_logs_stage_without_sensitive_exception_values(app,hcp,caplog,stage):
    client,_,SSO=hcp;client.set_cookie('company','valid')
    def broken(*args):raise RuntimeError('secret-cookie-secret-token')
    setattr(SSO,'__init__' if stage=='initialize' else stage,broken)
    assert client.get('/login').status_code==503
    assert f'HCP SSO failure stage={stage} error=RuntimeError' in caplog.text
    assert 'secret-cookie-secret-token' not in caplog.text
    assert client.get('/api/bootstrap').status_code==401
    with client.session_transaction() as session:assert '_hcp_login' not in session


def test_login_database_error_is_not_reported_as_sso_error(app,hcp,monkeypatch,caplog):
    from pymongo.errors import AutoReconnect
    from pt_ai_square.backend import auth
    client,_,_=hcp;client.set_cookie('company','valid')
    def unavailable(*args,**kwargs):raise AutoReconnect('private database address')
    monkeypatch.setattr(auth,'ensure_user',unavailable)
    response=client.get('/login')
    assert response.status_code==503 and 'MongoDB' in response.json['error']
    assert 'HCP SSO failure' not in caplog.text
    assert 'private database address' not in caplog.text
    with client.session_transaction() as session:assert '_hcp_login' not in session
