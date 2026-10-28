import hashlib
import io
import json
import threading
import zipfile
from http.cookiejar import CookieJar
from urllib.request import Request,build_opener,HTTPCookieProcessor
from pathlib import Path
import pytest
from pt_ai_square import create_app
from pt_ai_square.backend.storage import db
from .conftest import ready,publish

@pytest.mark.parametrize('mode',['mock','sso'])
def test_same_publish_update_rollback_workflow(app,mode):
    uid='0012345'
    app.config.update(AUTH_MODE=mode,MOCK_USER=uid,MOCK_NAME='시험 등록자',MOCK_ADMIN=False)
    client,_=ready(app,uid)
    bootstrap=client.get('/api/bootstrap').json
    headers={'X-CSRF-Token':bootstrap['csrf']}
    assert bootstrap['user']['id']==uid and bootstrap['activityBackend']=='mongodb'
    first=publish(client,headers,owner='표시 담당자')
    assert first.status_code==201 and first.json['version']==1
    tid=first.json['id']
    assert client.get(f'/api/tools/{tid}').json['ownerId']==uid
    assert client.patch(f'/api/tools/{tid}',json={'name':'수정된 도구','expectedRevision':1},headers=headers).status_code==200
    assert publish(client,headers,tid=tid,revision=2,guide='두 번째 설치 안내',changes='v2').status_code==201
    manifest=client.get(f'/api/tools/{tid}/manifest').json
    data=client.get(manifest['downloadUrl']).data
    assert hashlib.sha256(data).hexdigest()==manifest['sha256'] and manifest['release']==2
    assert client.put(f'/api/tools/{tid}/like',json={'liked':True},headers=headers).status_code==200
    assert client.get(f'/api/tools/{tid}/version-check?release=1').json['status']=='update_available'
    assert client.post(f'/api/tools/{tid}/rollback',json={'version':1,'expectedRevision':3},headers=headers).status_code==200
    assert client.get(f'/api/tools/{tid}/version-check?release=2').json['status']=='rollback_available'
    assert client.get(f'/download/{tid}/2').status_code==404
    assert client.get(f'/download/{tid}/1').status_code==200
    assert client.delete(f'/api/tools/{tid}/versions/2',headers=headers).status_code==200
    with app.app_context():
        row=db().tools.find_one({'_id':tid})
        assert row['owner']==uid and row['active']==1 and row['versions'][1]['deleted']
        assert db().activity.count_documents({'tool':tid,'user':uid})>=2
        assert db().audit.count_documents({'user':uid})>=4
        assert list(Path(app.config['DATA_DIR']).joinpath('artifacts').rglob('*'))
    # A fresh app instance must read the same owner, likes, versions and files.
    keys=['TESTING','AUTH_MODE','SSO_FACTORY','MOCK_USER','MOCK_NAME','MOCK_ADMIN','ADMIN_IDS','SECRET_KEY','SESSION_COOKIE_SECURE','DATA_DIR','MONGODB_URI','MONGODB_DATABASE']
    restarted=create_app({k:app.config[k] for k in keys})
    try:
        again,_=ready(restarted,uid)
        item=again.get(f'/api/tools/{tid}').json
        assert item['ownerId']==uid and item['active']==1 and item['likes']==1
        assert again.get(f'/download/{tid}/1').status_code==200
    finally:restarted.extensions['square_mongo_client'].close()

def test_mock_employee_cannot_be_overridden_and_permissions_apply(app):
    app.config.update(AUTH_MODE='mock',MOCK_USER='0012345',MOCK_NAME='첫 등록자',MOCK_ADMIN=False)
    owner=app.test_client()
    with owner.session_transaction() as s:s['user_id']='admin'
    data=owner.get('/api/bootstrap',headers={'X-User-ID':'admin'}).json
    assert data['user']['id']=='0012345' and data['user']['role']=='member'
    h={'X-CSRF-Token':data['csrf']}
    publish(owner,h,approval=True)
    app.config.update(MOCK_USER='0099999',MOCK_NAME='다른 사용자')
    member=app.test_client();other=member.get('/api/bootstrap').json;mh={'X-CSRF-Token':other['csrf']}
    assert other['user']['id']=='0099999' and other['items'][0]['ownerId']=='0012345'
    assert not other['items'][0]['canManage']
    assert member.get('/api/tools/1').status_code==403
    assert member.patch('/api/tools/1',json={'expectedRevision':1,'name':'임의 수정'},headers=mh).status_code==403
    assert member.post('/api/tools/1/requests',json={'reason':'업무에 필요'},headers=mh).status_code==200
    app.config.update(MOCK_USER='0012345')
    bootstrap=owner.get('/api/bootstrap').json
    assert bootstrap['requests'][0]['user']=='0099999' and bootstrap['unread']==1
    rid=bootstrap['requests'][0]['id']
    assert owner.post(f'/api/requests/{rid}/decision',json={'status':'승인','reason':'','expectedRevision':bootstrap['requests'][0]['requestRevision']},headers=h).status_code==200
    app.config.update(MOCK_USER='0099999')
    assert member.get('/api/tools/1').status_code==200
    assert member.get('/api/notifications').json['unread']==1
    assert member.get('/api/bootstrap',environ_overrides={'REMOTE_ADDR':'192.0.2.1'}).status_code==403
    with app.app_context():db().users.update_one({'_id':'0099999'},{'$set':{'enabled':False}})
    assert member.get('/api/bootstrap').status_code==401

def test_removed_local_mode_and_empty_mock_id_fail_at_startup(monkeypatch,tmp_path):
    from pt_ai_square import config
    monkeypatch.setattr(config,'BASE',tmp_path)
    monkeypatch.setenv('PTAI_AUTH_MODE','local')
    with pytest.raises(ValueError,match='sso'):config.settings()
    monkeypatch.setenv('PTAI_AUTH_MODE','mock')
    with pytest.raises(ValueError,match='sso'):create_app({'AUTH_MODE':'local','MONGODB_URI':''})
    with pytest.raises(ValueError,match='PTAI_MOCK_USER'):create_app({'MOCK_USER':'   ','MONGODB_URI':''})

def test_mock_real_http_upload_update_and_download(app):
    """Exercise a real loopback HTTP server with cookies and multipart uploads."""
    from werkzeug.serving import make_server
    app.config.update(AUTH_MODE='mock',MOCK_USER='0007001',MOCK_ADMIN=False)
    server=make_server('127.0.0.1',0,app)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    browser=build_opener(HTTPCookieProcessor(CookieJar()))
    base=f'http://127.0.0.1:{server.server_port}'
    def call(path,body=None,headers=None):
        with browser.open(Request(base+path,data=body,headers=headers or {}),timeout=5) as response:return response.read()
    try:
        initial=json.loads(call('/api/bootstrap'))
        assert initial['user']['id']=='0007001'
        meta=dict(name='HTTP 업로드 검증',desc='로컬 실제 요청',owner='표시 담당자',org='공통',category='공통 업무',platform='Claude',type='Skill',guide='설치 안내',approval=False,workTags=['검증'],mode='file')
        for version in [1,2]:
            buf=io.BytesIO()
            with zipfile.ZipFile(buf,'w') as archive:archive.writestr('SKILL.md',f'# HTTP release {version}')
            if version==2:meta['expectedRevision']=1
            boundary='ptai-http-multipart-test'
            body=(f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n'+json.dumps(meta)+f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="artifact"; filename="skill.zip"\r\nContent-Type: application/zip\r\n\r\n').encode()+buf.getvalue()+f'\r\n--{boundary}--\r\n'.encode()
            result=json.loads(call('/api/tools' if version==1 else '/api/tools/1/versions',body,{'Content-Type':f'multipart/form-data; boundary={boundary}','X-CSRF-Token':initial['csrf']}))
            assert result['version']==version
            assert call(f'/download/1/{version}')==buf.getvalue()
        check=json.loads(call('/api/tools/1/version-check?release=1'))
        assert check['status']=='update_available'
        with app.app_context():assert db().tools.find_one({'_id':1})['owner']=='0007001'
    finally:
        server.shutdown();thread.join(timeout=5);server.server_close()
