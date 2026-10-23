"""Exercise the company's HTTP deployment using a real cookie-aware client."""
import json
import threading
from http.cookiejar import Cookie,CookieJar
from urllib.request import Request,build_opener,HTTPCookieProcessor

from .conftest import ready,publish


def test_http_login_refresh_and_admin_delete_with_session_cookie(app):
    from werkzeug.serving import make_server

    owner,headers=ready(app,'owner')
    assert publish(owner,headers).status_code==201
    seen=[]
    class CompanySSO:
        def __init__(self,request):
            seen.append(request.path)
            assert request.path=='/login'
            self.request=request
            self.redirect_url=request.args.get('ORIGIN') or request.host_url
        def check_day_cookie(self,cookie):return self.request.cookies.get('company')=='valid'
        def get_sso_info(self,cookie):return ('admin','관리자','','공통','','D1')
    app.config.update(AUTH_MODE='sso',SESSION_COOKIE_SECURE=False,SSO_FACTORY=CompanySSO)
    server=make_server('127.0.0.1',0,app)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    jar=CookieJar()
    jar.set_cookie(Cookie(version=0,name='company',value='valid',port=None,port_specified=False,
        domain='127.0.0.1',domain_specified=False,domain_initial_dot=False,path='/',path_specified=True,
        secure=False,expires=None,discard=True,comment=None,comment_url=None,rest={},rfc2109=False))
    browser=build_opener(HTTPCookieProcessor(jar))
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        with browser.open(base+'/',timeout=5) as response:
            assert response.status==200 and response.url==base+'/'
        session_cookie=next(cookie for cookie in jar if cookie.name==app.config['SESSION_COOKIE_NAME'])
        assert not session_cookie.secure
        # The app session, not another company-cookie check, authenticates refresh.
        jar.clear('127.0.0.1','/','company')
        with browser.open(base+'/',timeout=5) as response:assert response.status==200
        with browser.open(base+'/api/bootstrap',timeout=5) as response:bootstrap=json.load(response)
        assert bootstrap['user']['id']=='admin' and bootstrap['user']['role']=='admin'
        request=Request(base+'/api/tools/1',method='DELETE',data=json.dumps({'expectedRevision':1}).encode(),
            headers={'Content-Type':'application/json','X-CSRF-Token':bootstrap['csrf']})
        with browser.open(request,timeout=5) as response:assert json.load(response)['ok'] is True
        assert seen==['/login']
    finally:
        server.shutdown();thread.join(timeout=5);server.server_close()


def test_private_python_config_supports_http_sso(monkeypatch,tmp_path):
    from pt_ai_square import config
    monkeypatch.setattr(config,'BASE',tmp_path)
    for name in ['PTAI_AUTH_MODE','PTAI_COOKIE_SECURE']:monkeypatch.delenv(name,raising=False)
    (tmp_path/'runtime_config.py').write_text("PTAI_AUTH_MODE = 'sso'\nPTAI_COOKIE_SECURE = False\n",encoding='utf-8')
    settings=config.settings()
    assert settings['AUTH_MODE']=='sso' and settings['SESSION_COOKIE_SECURE'] is False
