"""Unicode archive names stay metadata, never download URL path components."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from urllib.parse import quote
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'integrations' / 'pt-square-mcp'))
from pt_square_mcp.client import Client
from pt_square_mcp.files import extract

spec = importlib.util.spec_from_file_location(
    'unicode_square_receiver', ROOT / 'receiver/pt-square-receiver/scripts/square_client.py')
receiver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(receiver)

KEY = 'ptsq_' + 'u' * 43
INNER_NAME = '참고 자료/사용 안내.md'
INNER_TEXT = '# 사용 안내\n한글 파일과 공백을 그대로 보존합니다.\n'


@pytest.fixture
def unicode_download_service():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('SKILL.md', '# Example Skill\n')
        archive.writestr(INNER_NAME, INNER_TEXT)
    raw = buffer.getvalue()
    state = {'filename': '한글 업무 도구.zip', 'requests': [], 'uploads': []}
    manifest = {'toolId': 7, 'release': 3, 'downloadUrl': '/download/7/3',
                'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                'installProfile': None}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, body, content_type='application/json'):
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            if content_type == 'application/zip':
                self.send_header('Content-Disposition',
                                 'attachment; filename=archive.zip; filename*=UTF-8\'\''
                                 + quote(state['filename']))
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            state['requests'].append(self.path)
            if self.headers.get('Authorization') == 'Bearer ' + KEY:
                return True
            self.send_error(401)
            return False

        def do_GET(self):
            if not self.authorized():
                return
            if self.path == '/api/tools/7/manifest':
                self.reply(json.dumps(dict(manifest, filename=state['filename']),
                                      ensure_ascii=False).encode('utf-8'))
            elif self.path == '/download/7/3?purpose=update':
                self.reply(raw, 'application/zip')
            else:
                # The fixture has no filename-based download route at all.
                self.send_error(404)

        def do_POST(self):
            if not self.authorized():
                return
            if self.path != '/api/publish-drafts':
                self.send_error(404)
                return
            state['uploads'].append(self.rfile.read(int(self.headers['Content-Length'])))
            self.reply(b'{"id":"fixture-draft"}')

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port), state, raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize('suffix', ['.zip', '.axextension'])
@pytest.mark.parametrize('client_type', ['mcp', 'receiver'])
def test_unicode_archives_download_by_ascii_id_and_preserve_inner_paths(
        unicode_download_service, tmp_path, suffix, client_type):
    url, state, raw = unicode_download_service
    state['filename'] = '한글 업무 도구 v1.2' + suffix
    destination = tmp_path / '받은 파일'
    if client_type == 'mcp':
        client = Client(SimpleNamespace(url=url, token=lambda: KEY))
        manifest = client.manifest(7)
        downloaded = client.download(manifest, destination, update=True)
    else:
        result = receiver.Client(url, KEY).download(7, destination, update=True)
        downloaded = Path(result['file'])
        assert result['originalFilename'] == state['filename']
        assert result['installed'] is False

    assert downloaded.name == 'tool-7-v3' + suffix
    assert downloaded.read_bytes() == raw
    assert hashlib.sha256(downloaded.read_bytes()).hexdigest() == hashlib.sha256(raw).hexdigest()
    assert state['requests'] == ['/api/tools/7/manifest', '/download/7/3?purpose=update',
                                 '/api/tools/7/manifest']
    assert all(path.isascii() and '%' not in path for path in state['requests'])
    assert not list(destination.glob('*.part'))

    unpacked = tmp_path / '압축 해제'
    extract(downloaded, unpacked)
    assert (unpacked / INNER_NAME).read_text(encoding='utf-8') == INNER_TEXT
    assert (unpacked / 'SKILL.md').read_text(encoding='utf-8') == '# Example Skill\n'


@pytest.mark.parametrize('suffix', ['.zip', '.axextension'])
def test_unicode_publish_archive_uses_fixed_ascii_multipart_filename(
        unicode_download_service, tmp_path, suffix):
    url, state, raw = unicode_download_service
    source = tmp_path / ('한글 확장 프로그램' + suffix)
    source.write_bytes(raw)
    client = Client(SimpleNamespace(url=url, token=lambda: KEY))
    result = client.draft({'name': '한글 이름 도구', 'guide': '설치 안내'}, source)
    assert result['id'] == 'fixture-draft'
    assert state['requests'] == ['/api/publish-drafts']
    body = state['uploads'][0]
    assert ('filename="artifact' + suffix + '"').encode('ascii') in body
    assert source.name.encode('utf-8') not in body
    assert '한글 이름 도구'.encode('utf-8') in body
    assert raw in body
