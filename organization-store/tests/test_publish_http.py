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
import uuid
import zipfile

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'worker.py'
TOKEN = 'ptsq_' + 'T' * 43


@pytest.fixture
def service():
    state = {'drafts': {}, 'uploads': [], 'commits': 0, 'requests': [], 'canPublish': True}
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
                return self.reply(dict(user={'id': 'owner', 'name': '등록자'}, key={'id': 'test-key', 'scope': 'publish'},
                                       capabilities={'publishDraft': state['canPublish']}))
            if self.path == '/api/catalog/options':
                return self.reply(dict(organizations=[{'id': 'org', 'name': '조직'}], categories=[{'id': 'work', 'name': '업무'}]))
            if self.path.startswith('/api/publish-targets?'):
                return self.reply({'items': []})
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
                    reviewUrl='/publish-review/' + draft_id, reviewDigest='test-digest',
                    artifact=dict(bytes=len(artifact), sha256=hashlib.sha256(artifact).hexdigest())))
                return self.reply(state['drafts'][draft_id], 201)
            if self.path.endswith('/commit'):
                self.rfile.read(int(self.headers['Content-Length']))
                draft = state['drafts'][self.path.split('/')[3]]
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
    assert call('publish', {'draftId': pending['id'], 'confirmed': True}, selected=False)['published'] is False
    assert state['commits'] == 0
    state['drafts'][pending['id']]['status'] = 'approved'  # Browser-side fixture approval only.
    assert call('publishStatus', {'draftId': pending['id']}, selected=False)['status'] == 'approved'
    assert call('publish', {'draftId': pending['id']}, selected=False)['id'] == 55
    assert call('publish', {'draftId': pending['id']}, selected=False)['version'] == 1
    assert state['commits'] == 1 and not any(path.endswith('/approve') for _, path in state['requests'])
    assert not any((data / 'publish-staging').iterdir())
