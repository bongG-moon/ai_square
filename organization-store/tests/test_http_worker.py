"""Fresh isolated worker processes against a temporary loopback HTTP service."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from urllib.parse import urlsplit, parse_qs

import pytest

SCRIPT = Path(__file__).resolve().parents[1]/'worker.py'
TOKEN = 'ptsq_' + 'X' * 43


@pytest.fixture
def service():
    state = {'release': 1, 'body': b'---\nname: store-fixture\ndescription: Fixture\n---\n# First\n',
             'liked': False, 'transfers': [], 'badHash': False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def reply(self, value, status=200, content_type='application/json'):
            data = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers(); self.wfile.write(data)
        def allowed(self):
            if self.headers.get('Authorization') == 'Bearer ' + TOKEN:
                return True
            self.reply({'error': 'unapproved key'}, 401)
            return False
        def do_GET(self):
            if not self.allowed():
                return
            parsed = urlsplit(self.path)
            if parsed.path == '/api/integration/me':
                return self.reply({'user': {'id': 'fixture'}, 'capabilities': {'like': True}})
            if parsed.path == '/api/tools/1/manifest':
                return self.reply({'toolId': 1, 'release': state['release'], 'filename': 'SKILL.md',
                    'bytes': len(state['body']), 'sha256': '0'*64 if state['badHash'] else hashlib.sha256(state['body']).hexdigest(),
                    'downloadUrl': '/download/1/' + str(state['release']),
                    'installProfile': {'schemaVersion': 1, 'kind': 'skill', 'host': 'claude', 'slug': 'store-fixture',
                                       'scopes': ['project'], 'entrypoint': 'SKILL.md'}})
            if parsed.path.startswith('/download/1/'):
                state['transfers'].append(parse_qs(parsed.query).get('purpose', ['download'])[0])
                return self.reply(state['body'], content_type='application/octet-stream')
            if parsed.path == '/api/tools/1/version-check':
                current = int(parse_qs(parsed.query)['release'][0])
                return self.reply({'toolId': 1, 'installedRelease': current, 'activeRelease': state['release'],
                                   'status': 'current' if current == state['release'] else 'update_available'})
            return self.reply({'error': 'missing'}, 404)
        def do_PUT(self):
            if not self.allowed():
                return
            if self.path != '/api/tools/1/like':
                return self.reply({'error': 'unsupported'}, 403)
            raw = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['liked'] = raw['liked']
            return self.reply({'liked': state['liked'], 'count': int(state['liked'])})
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield 'http://127.0.0.1:' + str(server.server_port), state
    server.shutdown(); server.server_close(); thread.join(timeout=3)


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI credential persistence')
def test_fresh_stdio_processes_download_hash_install_update_and_rollback(service, tmp_path):
    url, state = service
    data, project = tmp_path/'data', tmp_path/'project'
    project.mkdir()
    def call(action, payload=None):
        request = {'protocol': 1, 'action': action, 'payload': payload or {},
                   'dataDirectory': str(data), 'context': {'workspace': str(project)}}
        env = {key: value for key, value in os.environ.items() if key not in {'PTAI_API_TOKEN', 'CLAUDE_CONFIG_DIR'}}
        response = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(SCRIPT)],
                                  input=json.dumps(request).encode(), capture_output=True, timeout=15, env=env)
        assert response.returncode == 0 and not response.stderr
        assert TOKEN.encode() not in response.stdout
        return json.loads(response.stdout)
    connected = call('connect', {'url': url, 'key': TOKEN, 'allowHttp': True})
    assert connected['ok'], connected
    assert call('status')['result']['configured']
    first = call('download', {'toolId': 1, 'update': True})['result']
    assert first['downloaded'] and not first['installed'] and first['purpose'] == 'download'
    assert Path(first['file']).read_bytes() == state['body']
    assert call('installations')['result']['items'] == []
    plan = call('prepareInstall', {'toolId': 1, 'scope': 'project'})['result']
    installed = call('install', dict(plan, confirmed=True))['result']
    target = Path(installed['destination'])/'SKILL.md'
    old = target.read_bytes()
    assert old == state['body'] and state['transfers'] == ['download']
    assert call('like', {'toolId': 1, 'liked': True})['result']['count'] == 1
    assert call('like', {'toolId': 1, 'liked': True})['result']['count'] == 1
    state.update(release=2, body=b'# Second\n')
    assert call('checkUpdates')['result']['items'][0]['result']['status'] == 'update_available'
    plan = call('prepareInstall', {'toolId': 1, 'scope': 'project'})['result']
    updated = call('install', dict(plan, confirmed=True))['result']
    assert state['transfers'] == ['download', 'update'] and target.read_bytes() == state['body']
    assert call('verify', {'installationId': updated['installationId']})['result']['filesIntact']
    assert call('rollback', {'installationId': updated['installationId'], 'confirmed': True})['result']['restored']
    assert target.read_bytes() == old
    assert call('disconnect')['result']['configured'] is False
    assert target.read_bytes() == old


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI credential persistence')
def test_sha_mismatch_never_becomes_a_completed_download(service, tmp_path):
    # Same real HTTP client path, direct Store API to inspect the failed cache.
    from test_worker import worker
    url, state = service
    store = worker.Store(tmp_path/'store', home=tmp_path, existing_config=tmp_path/'unused')
    store.dispatch('connect', {'url': url, 'key': TOKEN, 'allowHttp': True})
    state['badHash'] = True
    with pytest.raises(worker.SquareError):
        store.dispatch('download', {'toolId': 1})
    assert not list(store.directory.rglob('*.part'))
    assert not list(store.directory.rglob('tool-1-v1.md'))
    assert store.dispatch('installations')['items'] == []
