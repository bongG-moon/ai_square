"""Real isolated stdio + HTTP + multipart; the local fixture owns approvals."""
from email.parser import BytesParser
from email.policy import default
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
import zipfile

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'worker.py'
TOKEN = 'ptsq_' + 'T' * 43


@pytest.fixture
def service():
    state = {'drafts': {}, 'uploads': [], 'commits': 0, 'requests': [], 'canPublish': True, 'owner': 'owner', 'slowIdentity': False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def reply(self, value, status=200):
            content = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers(); self.wfile.write(content)

        def authorized(self):
            state['requests'].append((self.command, self.path))
            if self.headers.get('Authorization') != 'Bearer ' + TOKEN:
                self.reply({'error': 'key'}, 401)
                return False
            return True

        def do_GET(self):
            if not self.authorized(): return
            if self.path == '/api/integration/me':
                identity = dict(user={'id': 'owner', 'name': '등록자'}, key={'id': 'test-key', 'scope': 'publish'},
                                capabilities={'publishDraft': state['canPublish']})
                if state['slowIdentity']:
                    content = json.dumps(identity).encode()
                    self.send_response(200); self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(content))); self.end_headers()
                    try:
                        for byte in content:
                            self.wfile.write(bytes([byte])); self.wfile.flush(); time.sleep(.1)
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    return
                return self.reply(identity)
            if self.path == '/api/catalog/options':
                return self.reply(dict(organizations=[{'id': 'org', 'name': '조직'}], categories=[{'id': 'work', 'name': '업무'}]))
            if self.path.startswith('/api/publish-targets?'):
                return self.reply({'items': []})
            if self.path == '/api/tools/7':
                return self.reply({'id': 7, 'ownerId': state['owner'], 'canManage': True})
            if self.path.startswith('/api/publish-drafts/'):
                return self.reply(state['drafts'][self.path.split('/')[3]])
            return self.reply({'error': 'missing'}, 404)

        def do_POST(self):
            if not self.authorized(): return
            if self.path == '/api/publish-drafts':
                raw = self.rfile.read(int(self.headers['Content-Length']))
                message = BytesParser(policy=default).parsebytes(
                    ('Content-Type: ' + self.headers['Content-Type'] + '\r\n\r\n').encode() + raw)
                values, artifact = None, b''
                for part in message.iter_parts():
                    if part.get_param('name', header='content-disposition') == 'metadata':
                        values = json.loads(part.get_payload(decode=True))
                    else:
                        artifact = part.get_payload(decode=True)
                draft_id = str(uuid.uuid5(uuid.NAMESPACE_URL, values['clientRequestId']))
                state['uploads'].append(artifact)
                state['drafts'].setdefault(draft_id, dict(id=draft_id, status='pending', metadata=values,
                    reviewUrl='/publish-review/' + draft_id, reviewDigest='a' * 64,
                    artifact=dict(bytes=len(artifact), sha256=hashlib.sha256(artifact).hexdigest())))
                return self.reply(state['drafts'][draft_id], 201)
            if self.path.endswith('/commit'):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                draft = state['drafts'][self.path.split('/')[3]]
                if body.get('confirmed') is True and body.get('reviewDigest') == draft['reviewDigest']:
                    draft['status'] = 'approved'
                if draft['status'] not in {'approved', 'committed'}:
                    return self.reply({'error': 'browser approval required'}, 409)
                if draft['status'] != 'committed': state['commits'] += 1
                draft['status'] = 'committed'; draft['result'] = {'id': 55, 'version': 1}
                return self.reply(draft['result'])
            return self.reply({'error': 'no client approval route'}, 403)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port), state
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


@pytest.mark.skipif(os.name != 'nt', reason='Windows account DPAPI connection persistence')
@pytest.mark.parametrize('source_kind', ['md', 'zip'])
def test_registration_fresh_workers_native_file_context_http_browser_review(service, tmp_path, source_kind):
    url, state = service
    guide = '# 설치 안내\n공통 또는 업무 폴더를 선택하고 요약을 요청하세요.\n'
    if source_kind == 'zip':
        source = tmp_path / 'summary.zip'
        declaration = dict(schemaVersion=1, packageId='summary-helper', name='메모 요약', desc='요약 도구',
                           platform='Claude', type='Skill', entryPoint='SKILL.md', guideFile='GUIDE.md',
                           requiredFiles=['SKILL.md', 'GUIDE.md'], requirements=[], workTags=['문서'],
                           environment='Windows', changes='설치 안내 보완',
                           workflow=dict(steps=[dict(title='요약', description='첨부한 문서를 요약합니다.')]))
        with zipfile.ZipFile(source, 'w') as archive:
            archive.writestr('ai-square.json', json.dumps(declaration, ensure_ascii=False))
            archive.writestr('SKILL.md', '# 메모\n요약합니다.\n')
            archive.writestr('GUIDE.md', guide)
    else:
        source = tmp_path / 'SKILL.md'; source.write_text('# 메모\n요약합니다.\n', encoding='utf-8')
    info = source.stat()
    context = dict(selectedFile=str(source), selectedFileIdentity=[info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns])
    data = tmp_path / 'data'
    def call(action, payload=None, selected=True):
        request = dict(protocol=1, action=action, payload=payload or {}, dataDirectory=str(data), context=context if selected else {})
        env = {key: value for key, value in os.environ.items() if key not in {'PTAI_API_TOKEN', 'CLAUDE_CONFIG_DIR'}}
        result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(SCRIPT)], input=json.dumps(request).encode(),
                                capture_output=True, timeout=20, env=env)
        assert result.returncode == 0 and not result.stderr
        assert TOKEN.encode() not in result.stdout
        response = json.loads(result.stdout)
        assert response['ok'], response
        return response['result']
    assert call('connect', {'url': url, 'key': TOKEN, 'allowHttp': True})['configured']
    assert call('publishOptions')['canPublish']
    inspected = call('inspectPublishSource')
    assert inspected['source']['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    metadata = dict(
        name='메모', desc='요약 도구', platform='Claude', type='Skill', guide='설치 안내', orgId='org', categoryId='work',
        approval=False, mode='file')
    if source_kind == 'zip':
        assert inspected['packageWarning'] == ''
        assert inspected['metadata']['guide'] == guide.strip()
        assert inspected['metadata']['workflow'] == declaration['workflow']
        assert inspected['metadata']['packageId'] == declaration['packageId']
        assert not {'orgId', 'categoryId', 'approval'} & inspected['metadata'].keys()
        metadata.update(inspected['metadata'])
        metadata['desc'] = '자동 입력 후 직접 다듬은 요약 설명'
    pending = call('preparePublish', dict(target='new', requestId=str(uuid.uuid4()), metadata=metadata))
    assert pending['status'] == 'pending' and state['uploads'] == [source.read_bytes()]
    for key, value in metadata.items():
        assert pending['metadata'][key] == value
    assert call('publish', {'draftId': pending['id']}, selected=False)['published'] is False
    assert state['commits'] == 0
    assert call('publishStatus', {'draftId': pending['id']}, selected=False)['status'] == 'pending'
    assert call('publish', {'draftId': pending['id'], 'confirmed': True, 'reviewDigest': pending['reviewDigest']}, selected=False)['id'] == 55
    assert call('publish', {'draftId': pending['id']}, selected=False)['version'] == 1
    assert state['commits'] == 1 and not any(path.endswith('/approve') for _, path in state['requests'])
    assert not any((data / 'publish-staging').iterdir())


@pytest.mark.skipif(os.name != 'nt', reason='Windows account DPAPI connection persistence')
def test_publish_update_access_stdio_http_checks_live_identity_and_owner(service, tmp_path):
    url, state = service
    data = tmp_path / 'data'
    def call(action, payload):
        request = dict(protocol=1, action=action, payload=payload, dataDirectory=str(data), context={})
        env = {key: value for key, value in os.environ.items() if key not in {'PTAI_API_TOKEN', 'CLAUDE_CONFIG_DIR'}}
        proc = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(SCRIPT)],
                              input=json.dumps(request).encode(), capture_output=True, timeout=20, env=env)
        assert proc.returncode == 0 and not proc.stderr
        assert TOKEN.encode() not in proc.stdout
        response = json.loads(proc.stdout)
        assert response['ok'], response
        return response['result']
    assert call('connect', {'url': url, 'key': TOKEN, 'allowHttp': True})['configured']
    state['requests'].clear()
    assert call('publishUpdateAccess', {'toolId': 7}) == {'canUpdate': True}
    assert state['requests'] == [('GET', '/api/integration/me'), ('GET', '/api/tools/7')]
    state['owner'] = 'other-person'  # Even a platform administrator is not the owner.
    assert call('publishUpdateAccess', {'toolId': 7}) == {'canUpdate': False}
    state['owner'] = 'owner'
    state['canPublish'] = False
    state['requests'].clear()
    assert call('publishUpdateAccess', {'toolId': 7}) == {'canUpdate': False}
    assert state['requests'] == [('GET', '/api/integration/me')]
    assert not state['uploads'] and state['commits'] == 0


@pytest.mark.skipif(os.name != 'nt', reason='Windows account DPAPI connection persistence')
@pytest.mark.parametrize('slow_mode', ['dns', 'stream'])
def test_publish_access_stdio_has_wall_deadline_even_when_dns_or_stream_stalls(service, tmp_path, slow_mode):
    url, state = service
    data = tmp_path / 'data'
    env = {key: value for key, value in os.environ.items() if key not in {'PTAI_API_TOKEN', 'CLAUDE_CONFIG_DIR'}}
    def request(action, payload):
        return json.dumps(dict(protocol=1, action=action, payload=payload,
                               dataDirectory=str(data), context={})).encode()
    setup = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(SCRIPT)],
                           input=request('connect', {'url': url, 'key': TOKEN, 'allowHttp': True}),
                           capture_output=True, timeout=20, env=env)
    assert setup.returncode == 0 and json.loads(setup.stdout)['ok']
    if slow_mode == 'dns':
        # Simulate a DNS resolver blocked well past the deadline; no real DNS.
        code = "import socket,time,runpy; socket.getaddrinfo=lambda *a,**k:time.sleep(30); runpy.run_path(" + repr(str(SCRIPT)) + ",run_name='__main__')"
        command = [sys.executable, '-I', '-B', '-X', 'utf8', '-c', code]
    else:
        state['slowIdentity'] = True  # One byte every 100ms avoids a socket idle timeout.
        command = [sys.executable, '-I', '-B', '-X', 'utf8', str(SCRIPT)]
    started = time.monotonic()
    proc = subprocess.run(command, input=request('publishUpdateAccess', {'toolId': 7}),
                          capture_output=True, timeout=10, env=env)
    elapsed = time.monotonic() - started
    assert proc.returncode == 0 and not proc.stderr
    assert TOKEN.encode() not in proc.stdout
    response = json.loads(proc.stdout)
    assert response['ok'] is False and '확인하지 못했어요' in response['error']
    assert 5.5 <= elapsed < 9, (slow_mode, elapsed)
    assert not state['uploads'] and state['commits'] == 0
