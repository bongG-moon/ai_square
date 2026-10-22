import importlib.util
import io
import json
import threading
from contextlib import contextmanager
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import HTTPError, URLError
import pytest
from flask import Flask, redirect, request
from werkzeug.serving import make_server
from .conftest import ready,publish


def startup_helper():
    path=Path(__file__).parents[1]/'static/guides/pt-file-distribution/scripts/version_check.py'
    spec=importlib.util.spec_from_file_location('startup_version_check',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@contextmanager
def serve_locally(app):
    server=make_server('127.0.0.1',0,app)
    thread=threading.Thread(target=lambda:server.serve_forever(poll_interval=0.01),daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown();thread.join(timeout=2);server.server_close()


def test_launch_check_releases_rollback_and_permissions(app):
    owner,h=ready(app);publish(owner,h,approval=True)
    c,_=ready(app,'member')
    assert app.test_client().get('/api/tools/1/version-check?release=1').status_code==401
    assert c.get('/api/tools/1/version-check?release=1').status_code==403
    for value in ['','0','-1','abc','1.0','1000000000']:
        assert owner.get('/api/tools/1/version-check?release='+value).status_code==400
    assert owner.get('/api/tools/1/version-check?release=1').json['status']=='current'
    publish(owner,h,tid=1,revision=1)
    result=owner.get('/api/tools/1/version-check?release=1').json
    assert result['status']=='update_available' and result['activeRelease']==2 and result['checkOnly']
    assert 'downloadUrl' not in result
    assert owner.get('/api/tools/1/version-check?release=99').json['status']=='unknown_release'
    owner.post('/api/tools/1/rollback',json={'version':1,'expectedRevision':2},headers=h)
    result=owner.get('/api/tools/1/version-check?release=2').json
    assert result['status']=='rollback_available' and result['installedWithdrawn'] and result['updatePaused']
    assert owner.get('/api/tools/1').json['downloads']==0

def test_startup_helper_auth_timeout_and_response_validation():
    module=startup_helper()
    class Opener:
        def __init__(self,result):self.result=result
        def open(self,request,timeout):
            assert request.full_url=='https://example.com/api/tools/1/version-check?release=1'
            assert timeout==2.0
            if isinstance(self.result,Exception):raise self.result
            return io.BytesIO(json.dumps(self.result).encode())
    def check(result):return module.check_version('https://example.com',1,1,opener=Opener(result))
    data=dict(schemaVersion=1,toolId=1,installedRelease=1,activeRelease=2,status='update_available',message='v2',checkOnly=True)
    assert check(data)['status']=='update_available'
    assert check({**data,'toolId':2})['status']=='unavailable'
    assert check(URLError('offline'))['status']=='unavailable'
    assert check(IncompleteRead(b'partial'))['status']=='unavailable'
    for code,status in [(401,'authentication_required'),(403,'permission_required'),(404,'not_found'),(503,'unavailable')]:
        assert check(HTTPError('https://example.com',code,'failed',{},None))['status']==status


def test_startup_key_rejects_invalid_input_before_network(monkeypatch):
    module=startup_helper()
    monkeypatch.setattr(module,'build_opener',lambda *args:pytest.fail('Invalid credentials must not reach transport'))
    for token in ['bad-private-key','ptsq_'+'a'*42,'ptsq_'+'a'*43+'\n',None,123]:
        with pytest.raises(ValueError) as error:
            module.check_version('https://example.com',1,1,token=token)
        assert str(error.value)=='Use a valid personal connection key.'
    token='ptsq_'+'a'*43
    with pytest.raises(ValueError,match='either a connection key'):
        module.check_version('https://example.com',1,1,token=token,opener=object())
    with pytest.raises(ValueError,match='Use HTTPS'):
        module.check_version('http://example.com',1,1,token=token)


@pytest.mark.parametrize('code',[301,302,303,307,308])
def test_startup_key_never_follows_redirects(code):
    module=startup_helper()
    site=Flask('redirect-test')
    received=[]
    token='ptsq_'+'a'*43

    @site.get('/api/tools/1/version-check')
    def version():
        received.append((request.path,request.headers.get('Authorization')))
        # A different host spelling also checks that keys cannot cross origins.
        return redirect(f'http://localhost:{request.host.rsplit(":",1)[1]}/unexpected',code=code)

    @site.get('/unexpected')
    def unexpected():
        received.append((request.path,request.headers.get('Authorization')))
        return {'error':'A redirect must never reach this endpoint.'}

    with serve_locally(site) as url:
        result=module.check_version(url,1,1,token=token)
    assert result['status']=='unavailable'
    assert received==[('/api/tools/1/version-check','Bearer '+token)]
    assert token not in json.dumps(result)


def test_startup_key_checks_real_api_without_browser_session(app):
    module=startup_helper()
    owner,headers=ready(app)
    assert publish(owner,headers,approval=True).status_code==201

    def issue(client,csrf):
        response=client.post('/api/local-tokens',json={'name':'실행 버전 확인','scope':'read'},headers=csrf)
        assert response.status_code==201 and response.json['expires'] is None
        return response.json

    first=issue(owner,headers)
    member,member_headers=ready(app,'member')
    outsider=issue(member,member_headers)
    with serve_locally(app) as url:
        assert module.check_version(url,1,1)['status']=='authentication_required'
        assert module.check_version(url,1,1,token=first['token'])['status']=='current'
        assert module.check_version(url,1,1,token=outsider['token'])['status']=='permission_required'
        second=issue(owner,headers)
        assert module.check_version(url,1,1,token=first['token'])['status']=='authentication_required'
        assert module.check_version(url,1,1,token=second['token'])['status']=='current'
        owner.delete('/api/local-tokens/'+second['id'],headers=headers)
        assert module.check_version(url,1,1,token=second['token'])['status']=='authentication_required'
    assert owner.get('/api/tools/1').json['downloads']==0
