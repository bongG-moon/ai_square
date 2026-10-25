"""Direct KEY and saved MCP parity; all credentials and profiles are synthetic."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from test_worker import FakeClient, SCRIPT, worker

KEY = 'ptsq_' + 'C' * 43
NEXT_KEY = 'ptsq_' + 'N' * 43


@pytest.fixture
def connected(tmp_path):
    store = worker.Store(tmp_path / 'data', home=tmp_path / 'profile',
                         existing_config=tmp_path / 'mcp' / 'config.json', client_factory=FakeClient)
    store.connect({'url': FakeClient.origin, 'key': KEY})
    return store


def snapshot(store):
    return {path: path.read_bytes() for path in [store.selection_path, store.config_path,
            *store.config_path.parent.glob('credential.*.dpapi.json')] if path.is_file()}


@pytest.mark.parametrize('failure', ['encrypt', 'readback', 'replace'])
def test_direct_secure_save_failure_preserves_working_connection(connected, monkeypatch, failure):
    store = connected
    before = snapshot(store)
    if failure == 'encrypt':
        monkeypatch.setattr(worker, 'save_config', lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError('blocked')))
    elif failure == 'readback':
        original = worker.Settings.token
        def token(settings):
            if settings.path.name.endswith('.pending.json'):
                raise worker.SquareError('Windows encryption readback unavailable')
            return original(settings)
        monkeypatch.setattr(worker.Settings, 'token', token)
    else:
        original = Path.replace
        def replace(path, target):
            if path.name.endswith('.pending.json') and target == store.config_path:
                raise PermissionError('blocked')
            return original(path, target)
        monkeypatch.setattr(Path, 'replace', replace)
    with pytest.raises(worker.SquareError, match='KEY는 서버에서 확인했지만.*기존 연결은 그대로 유지'):
        store.connect({'url': 'https://new.example.test', 'key': NEXT_KEY})
    assert snapshot(store) == before
    assert store.settings().url == FakeClient.origin and store.settings().token() == KEY
    assert not list(store.config_path.parent.glob('*.pending.json*'))


def test_selection_save_failure_preserves_existing_mcp_and_prior_local_config(connected, monkeypatch):
    store = connected
    worker.save_config(store.existing_config, 'https://mcp.example.test', [store.directory], KEY)
    store.connect({'reuseExisting': True})
    before = snapshot(store)
    mcp_before = {path: path.read_bytes() for path in store.existing_config.parent.rglob('*') if path.is_file()}
    original = worker.atomic_json
    def save(path, value):
        if path == store.selection_path:
            raise PermissionError('selection denied')
        return original(path, value)
    monkeypatch.setattr(worker, 'atomic_json', save)
    with pytest.raises(worker.SquareError, match='기존 연결은 그대로 유지'):
        store.connect({'url': 'https://new.example.test', 'key': NEXT_KEY})
    assert snapshot(store) == before
    assert {path: path.read_bytes() for path in mcp_before} == mcp_before
    assert store.settings().url == 'https://mcp.example.test' and store.settings().token() == KEY


def test_reconnect_replaces_only_local_config_and_removes_old_encrypted_key(connected, monkeypatch):
    store = connected
    original_selection = store.selection_path.read_bytes()
    old_ref = worker.read_json(store.config_path)['credentialRef']
    def no_selection_write(*args):
        pytest.fail('Local reconnect must not rewrite an already-correct connection selection')
    monkeypatch.setattr(worker, 'atomic_json', no_selection_write)
    store.connect({'url': FakeClient.origin, 'key': NEXT_KEY})
    assert store.selection_path.read_bytes() == original_selection
    assert store.settings().token() == NEXT_KEY
    assert not (store.config_path.parent / old_ref.split(':', 1)[1]).exists()
    assert len(list(store.config_path.parent.glob('credential.*.dpapi.json'))) == 1


@pytest.fixture
def service():
    state = {'requests': [], 'redirect': False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            state['requests'].append(self.path)
            if state['redirect']:
                self.send_response(302)
                self.send_header('Location', '/never-follow')
                self.end_headers()
                return
            authorized = self.headers.get('Authorization') == 'Bearer ' + KEY
            value = ({'user': {'id': 'test-owner'}, 'capabilities': {'publishDraft': True}}
                     if authorized else {'error': 'key'})
            raw = json.dumps(value).encode()
            self.send_response(200 if authorized else 401)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port), state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI plus fresh worker process')
def test_direct_and_saved_mcp_fresh_workers_http_and_dpapi_parity(service, tmp_path):
    url, state = service
    profile = tmp_path / 'isolated-profile'
    profile.mkdir()
    data = tmp_path / 'data'
    mcp = profile / '.pt-ai-square' / 'mcp' / 'config.json'
    worker.save_config(mcp, url, [profile], KEY, True)
    original_mcp = {path: path.read_bytes() for path in mcp.parent.rglob('*') if path.is_file()}
    environment = {key: value for key, value in os.environ.items() if key not in {'PTAI_API_TOKEN', 'CLAUDE_CONFIG_DIR'}}
    environment['USERPROFILE'] = str(profile)
    def call(action, payload=None):
        request = dict(protocol=1, action=action, payload=payload or {}, dataDirectory=str(data), context={})
        result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(SCRIPT)],
                                input=json.dumps(request).encode(), capture_output=True, timeout=20, env=environment)
        assert result.returncode == 0 and not result.stderr
        assert KEY.encode() not in result.stdout and NEXT_KEY.encode() not in result.stdout
        return json.loads(result.stdout)
    assert call('status')['result']['existingConnectionAvailable']
    assert call('connect', {'reuseExisting': True})['result']['connectionMode'] == 'existing'
    # Every call is a fresh worker. Case-normalized HTTP still requires exact consent.
    count = len(state['requests'])
    assert not call('connect', {'url': url.upper(), 'key': KEY})['ok']
    assert len(state['requests']) == count
    for _ in range(3):
        result = call('connect', {'url': url, 'key': KEY, 'allowHttp': True})
        assert result['ok'] and result['result']['connectionMode'] == 'local'
        assert call('options')['ok']
    config = data / 'connection' / 'config.json'
    before = config.read_bytes()
    rejected = call('connect', {'url': url, 'key': NEXT_KEY, 'allowHttp': True})
    assert not rejected['ok'] and config.read_bytes() == before
    assert rejected['code'] == 'store_auth_required'
    assert '웹에서 KEY 확인' in rejected['error'] and '이 화면에 다시 입력' in rejected['error']
    assert all(text not in rejected['error'] for text in ('connect_account', 'reconnect_key', 'AI에게', '](', '<http'))
    assert call('options')['ok']
    state['redirect'] = True
    refused = call('connect', {'url': url, 'key': KEY, 'allowHttp': True})
    assert not refused['ok'] and '이동하지 않았습니다' in refused['error']
    assert config.read_bytes() == before and '/never-follow' not in state['requests']
    state['redirect'] = False
    assert call('connect', {'reuseExisting': True})['result']['connectionMode'] == 'existing'
    assert {path: path.read_bytes() for path in original_mcp} == original_mcp
    assert len(list(config.parent.glob('credential.*.dpapi.json'))) == 1
    assert all(KEY not in path.read_text(encoding='utf-8') for path in tmp_path.rglob('*.json'))
