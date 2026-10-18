import importlib.util
import io
import json
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import HTTPError, URLError
from .conftest import ready,publish

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
    path=Path(__file__).parents[1]/'static/guides/pt-file-distribution/scripts/version_check.py'
    spec=importlib.util.spec_from_file_location('startup_version_check',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
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
