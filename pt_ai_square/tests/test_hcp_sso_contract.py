from urllib.parse import parse_qs,urlsplit,quote
import pytest
from pt_ai_square.backend.storage import db

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
    client.set_cookie('company','valid');client.get('/api/bootstrap')
    with app.app_context():
        old=db().users.find_one({'_id':'0012345'})
        db().users.update_one({'_id':'0012345'},{'$set':{'activeConnectionKeyId':'keep-key'}})
        db().tools.insert_one({'_id':77,'owner':'0012345','deleted':False})
        db().access.insert_one({'tool':77,'user':'0012345','granted':True})
    SSO.get_sso_info=lambda self,cookie: ('0012345','바뀐 이름','Test Employee','변경 부서','employee@example.test','D001')
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

def test_session_flag_cannot_replace_valid_sso_cookie(app,hcp):
    client,_,_=hcp
    with client.session_transaction() as session:session.update(logFlag=True,emp_no='admin')
    response=client.get('/api/bootstrap')
    assert response.status_code==401
    assert parse_qs(urlsplit(response.json['login']).query)['ORIGIN']==['http://localhost/']
    with client.session_transaction() as session:assert 'emp_no' not in session and 'logFlag' not in session
    client.set_cookie('company','valid');assert client.get('/api/bootstrap').status_code==200
    client.set_cookie('company','expired');assert client.get('/api/bootstrap').status_code==401
    with client.session_transaction() as session:assert 'logFlag' not in session

def test_disabled_account_does_not_loop_through_sso(app,hcp):
    client,_,_=hcp;client.set_cookie('company','valid');client.get('/api/bootstrap')
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

@pytest.mark.parametrize('target',['http://sso.example.test/','https://[broken'])
def test_invalid_sdk_redirect_is_configuration_error(hcp,target):
    client,_,SSO=hcp;SSO.redirect_url=target
    assert client.get('/login').status_code==503
