import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
import pytest
from werkzeug.serving import make_server
from pt_ai_square.backend.storage import db
from .conftest import ready, publish

SCRIPT = Path(__file__).resolve().parents[1] / 'receiver/pt-square-receiver/scripts/square_client.py'
spec = importlib.util.spec_from_file_location('square_receiver', SCRIPT)
receiver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receiver)


def key(app, uid='owner'):
    c, h = ready(app, uid)
    r = c.post('/api/local-tokens', json={'name': 'test PC'}, headers=h)
    assert r.status_code == 201
    return r.json, {'Authorization': 'Bearer ' + r.json['token']}


def test_token_lifecycle_permissions_and_no_cookie_fallback(app):
    owner, h = ready(app)
    publish(owner, h, approval=True)
    issued, auth = key(app, 'member')
    client = app.test_client()
    assert client.get('/api/catalog?q=점검', headers=auth).json['items'][0]['access'] == 'permission_required'
    for path in ['/api/tools/1', '/api/tools/1/manifest', '/download/1/1', '/api/tools/1/version-check?release=1']:
        assert client.get(path, headers=auth).status_code == 403
    # Cookies and CSRF cannot broaden a read token's powers.
    for method, path in [('post', '/api/tools'), ('post', '/api/local-tokens'), ('delete', '/api/tools/1'), ('get', '/api/bootstrap'), ('get', '/api/users')]:
        assert getattr(owner, method)(path, headers={**h, **auth}).status_code == 403
    with app.app_context():
        db().access.insert_one({'tool': 1, 'user': 'member', 'granted': True})
    assert client.get('/download/1/1', headers=auth).status_code == 200
    with app.app_context():
        db().access.update_one({'tool': 1, 'user': 'member'}, {'$set': {'granted': False}})
    assert client.get('/download/1/1', headers=auth).status_code == 403
    member, mh = ready(app, 'member')
    assert member.post('/api/local-tokens', json={}).status_code == 403
    # A different user cannot revoke another user's key.
    owner.delete('/api/local-tokens/' + issued['id'], headers=h)
    assert client.get('/api/catalog', headers=auth).status_code == 200
    member.delete('/api/local-tokens/' + issued['id'], headers=mh)
    assert client.get('/api/catalog', headers=auth).status_code == 401
    assert owner.get('/api/catalog', headers={'Authorization': 'Bearer invalid'}).status_code == 401
    with app.app_context():
        row = db().local_tokens.find_one({'id': issued['id']})
        assert issued['token'] not in json.dumps(row)


def test_expiry_disabled_user_and_mock_boundary(app):
    issued, auth = key(app)
    with app.app_context():
        db().users.update_one({'_id': 'owner'}, {'$set': {'enabled': False}})
    assert app.test_client().get('/api/catalog', headers=auth).status_code == 401
    with app.app_context():
        db().users.update_one({'_id': 'owner'}, {'$set': {'enabled': True}})
        db().local_tokens.update_one({'id': issued['id']}, {'$set': {'expires': time.time() - 1}})
    assert app.test_client().get('/api/catalog', headers=auth).status_code == 401
    app.config.update(AUTH_MODE='mock', MOCK_USER='owner')
    assert app.test_client().get('/api/catalog').status_code == 200
    assert app.test_client().get('/api/catalog', environ_base={'REMOTE_ADDR': '10.0.0.2'}).status_code == 403
    assert app.test_client().get('/api/catalog', headers=auth, environ_base={'REMOTE_ADDR': '10.0.0.2'}).status_code == 403


def test_search_pagination_filters_redaction_and_deleted(app):
    owner, h = ready(app)
    for i in range(3):
        assert publish(owner, h, name=f'회의 {i}', approval=True).status_code == 201
    _, auth = key(app, 'member')
    client = app.test_client()
    r = client.get('/api/catalog?q=보고서&type=Skill&orgId=organization-0&limit=2', headers=auth)
    assert r.status_code == 200 and r.json['total'] == 3 and r.json['nextOffset'] == 2
    assert all('versions' not in x and 'guide' not in x for x in r.json['items'])
    assert len(client.get('/api/catalog?offset=2', headers=auth).json['items']) == 1
    assert client.get('/api/catalog?q=.*', headers=auth).json['total'] == 0
    assert client.get('/api/catalog?type=MCP%2FTool', headers=auth).json['total'] == 0
    assert client.get('/api/catalog?limit=0', headers=auth).status_code == 400
    owner.delete('/api/tools/1', json={'expectedRevision':1}, headers=h)
    assert client.get('/api/catalog', headers=auth).json['total'] == 2


@pytest.fixture
def server(app):
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def test_live_client_download_updates_and_cli(app, server, tmp_path):
    owner, h = ready(app)
    publish(owner, h)
    issued, _ = key(app)
    client = receiver.Client(server, issued['token'])
    assert client.search('보고서')['items'][0]['id'] == 1
    assert client.details(1)['guide'] == 'SECRET INSTALL GUIDE'
    result = client.download(1, tmp_path / 'received')
    assert not result['installed'] and result['downloaded']
    assert hashlib.sha256(Path(result['file']).read_bytes()).hexdigest() == result['sha256']
    with pytest.raises(receiver.ClientError, match='이미'):
        client.download(1, tmp_path / 'received')
    assert client.check(1, 1)['status'] == 'current'
    publish(owner, h, tid=1, revision=1)
    assert client.check(1, 1)['status'] == 'update_available'
    assert client.download(1, tmp_path / 'received')['release'] == 2
    owner.post('/api/tools/1/rollback', json={'version':1,'expectedRevision':2}, headers=h)
    assert client.check(1, 2)['status'] == 'rollback_available'
    with pytest.raises(receiver.ClientError):
        client.get('/download/1/2')
    config = tmp_path / 'client.json'
    prefix = [sys.executable, str(SCRIPT), '--config', str(config)]
    env = {**os.environ, 'PTAI_READ_TOKEN': issued['token']}
    for command in [
        ['configure', '--url', server],
        ['search', '보고서'],
        ['download', '1', '--output', str(tmp_path / 'cli-received')],
        ['check', '1', '--release', '2'],
    ]:
        proc = subprocess.run(prefix + command, env=env, capture_output=True, encoding='utf-8', timeout=20)
        assert proc.returncode == 0, proc.stderr
        assert issued['token'] not in proc.stdout + proc.stderr
        assert isinstance(json.loads(proc.stdout), dict)
    assert issued['token'] not in config.read_text()


def test_live_mock_cli_and_non_file_modes(app, server, tmp_path):
    owner, h = ready(app)
    publish(owner, h, mode='command', commandProject='echo example')
    publish(owner, h, mode='url', url='https://example.org/tool')
    app.config.update(AUTH_MODE='mock', MOCK_USER='owner')
    client = receiver.Client(server)
    for tid in [1, 2]:
        r = client.download(tid, tmp_path / 'no-files')
        assert not r['downloaded'] and not r['installed']
    assert not (tmp_path / 'no-files').exists()
    assert client.details(1)['versions'][0]['commands']['project'] == 'echo example'


class FakeOpener:
    def __init__(self, manifests, data=b'abc'):
        self.manifests = iter(manifests)
        self.data = data
        self.urls = []
    def open(self, request, timeout):
        self.urls.append(request.full_url)
        if '/download/' in request.full_url:
            return io.BytesIO(self.data)
        return io.BytesIO(json.dumps(next(self.manifests)).encode())


def manifest(**changes):
    return dict(dict(toolId=1, release=1, filename='../../evil.exe', downloadUrl='/download/1/1',
                     sha256=hashlib.sha256(b'abc').hexdigest(), bytes=3), **changes)


@pytest.mark.parametrize('change,data', [
    ({'sha256': '0'*64}, b'abc'),
    ({'bytes': 4}, b'abc'),
    ({'bytes': 2}, b'abc'),
    ({'downloadUrl':'https://evil.example/file'}, b'abc'),
])
def test_failed_download_never_publishes_or_leaves_partial(tmp_path, change, data):
    client = receiver.Client('https://square.example/prefix', opener=FakeOpener([manifest(**change)], data))
    with pytest.raises(receiver.ClientError):
        client.download(1, tmp_path)
    assert not list(tmp_path.iterdir())


def test_release_changes_during_download_and_safe_filename(tmp_path):
    op = FakeOpener([manifest(), manifest(release=2)])
    with pytest.raises(receiver.ClientError, match='변경'):
        receiver.Client('https://square.example/prefix', opener=op).download(1, tmp_path)
    assert not list(tmp_path.iterdir())
    op = FakeOpener([manifest(), manifest()])
    r = receiver.Client('https://square.example/prefix', opener=op).download(1, tmp_path)
    assert Path(r['file']).name == 'tool-1-v1.exe'
    assert all(u.startswith('https://square.example/prefix/') for u in op.urls)


def test_axextension_download_preserves_file_association_without_installing(tmp_path):
    info=manifest(filename='PNT-AI-Square.axextension')
    result=receiver.Client('https://square.example',opener=FakeOpener([info,info])).download(1,tmp_path)
    assert Path(result['file']).name=='tool-1-v1.axextension'
    assert Path(result['file']).read_bytes()==b'abc'
    assert result['installed'] is False


def test_unsafe_urls_and_redirects_rejected():
    for url in ['http://company.example', 'https://user:pass@example.org', 'https://example.org?q=x', 'file:///x']:
        with pytest.raises(receiver.ClientError):
            receiver.Client(url)
    assert receiver.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example') is None


def test_local_page_and_key_inputs(app):
    c, h = ready(app)
    assert c.get('/local-access').status_code == 200
    assert '로컬에서 받기' in c.get('/').text
    for data in [{'days':True}, {'days':365}, {'name':''}, ['bad']]:
        assert c.post('/api/local-tokens', json=data, headers=h).status_code == 400
    issued, auth = key(app)
    assert c.get('/api/local-tokens').headers['Cache-Control'] == 'no-store'
    assert issued['token'] not in c.get('/api/local-tokens').text
