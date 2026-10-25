"""KEY recovery uses only fixture origins, isolated files and private test keys."""
import asyncio
from datetime import timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError

import pytest

PACKAGE = Path(__file__).parents[1] / 'integrations' / 'pt-square-mcp'
sys.path.insert(0, str(PACKAGE))
from pt_square_mcp import config, connection_ui, onboarding
from pt_square_mcp.client import Client
from pt_square_mcp.config import AuthenticationRequired, Settings, SquareError, atomic_json, save_config
from pt_square_mcp.runtime import Runtime

KEY = 'ptsq_' + 'a' * 43
NEW_KEY = 'ptsq_' + 'b' * 43
ORIGIN = 'https://current.example.test'
FOREIGN = 'https://untrusted.example.test/steal'


@pytest.fixture
def settings(tmp_path, monkeypatch):
    home = tmp_path / 'private-test-home'
    downloads = home / 'AI_SQUARE' / 'downloads'
    downloads.mkdir(parents=True)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    if os.name != 'nt':
        monkeypatch.setattr(config, 'protect', lambda data, decrypt=False: data[::-1])
    path = tmp_path / 'private' / 'config.json'
    save_config(path, ORIGIN, [downloads], download_directory=downloads)
    monkeypatch.setenv('PTAI_API_TOKEN', KEY)
    return Settings(path)


class FailingOpener:
    def __init__(self, status=401):
        self.status, self.calls = status, []

    def open(self, request, timeout):
        self.calls.append((request.full_url, request.method))
        if self.status == 'network':
            raise URLError('private transport text ' + KEY + ' ' + FOREIGN)
        raise HTTPError(request.full_url, self.status, KEY,
                        {'Location': FOREIGN}, io.BytesIO((KEY + ' ' + FOREIGN).encode()))


@pytest.mark.parametrize('missing', [False, True])
def test_auth_recovery_is_normalized_clickable_and_contains_no_credential(missing):
    error = AuthenticationRequired('https://CURRENT.example.test:443/', missing=missing)
    assert isinstance(error, SquareError)
    assert error.auth_url == ORIGIN + '/local-access'
    assert '[연결 KEY 발급·관리](<' + error.auth_url + '>)' in str(error)
    assert '재발급' in str(error) and '숨김 입력창' in str(error) and '채팅' in str(error)
    assert error.recovery() == {
        'authRequired': True, 'errorCode': 'KEY_AUTH_REQUIRED', 'authUrl': error.auth_url,
        'message': str(error), 'reconnectTool': 'reconnect_key',
    }
    assert KEY not in str(error) and NEW_KEY not in json.dumps(error.recovery())


@pytest.mark.parametrize('origin', [FOREIGN, 'https://user:password@example.test',
                                   'https://example.test?next=evil', '//example.test',
                                   'javascript:alert(1)'])
def test_recovery_never_accepts_a_non_origin_link(origin):
    with pytest.raises(SquareError):
        AuthenticationRequired(origin)


@pytest.mark.parametrize('path,method', [('/api/catalog', 'GET'),
    ('/api/publish-drafts/12345678-1234-1234-1234-123456789abc/commit', 'POST')])
def test_401_becomes_typed_recovery_without_redirect_body_or_automatic_replay(settings, path, method):
    opener = FailingOpener()
    with pytest.raises(AuthenticationRequired) as caught:
        Client(settings, opener).json(path, method, {} if method == 'POST' else None)
    assert caught.value.recovery()['authUrl'] == ORIGIN + '/local-access'
    assert KEY not in str(caught.value) and FOREIGN not in str(caught.value)
    assert len(opener.calls) == 1


@pytest.mark.parametrize('status', [403, 500, 'network'])
def test_non_auth_failure_does_not_offer_reissuance(settings, status):
    client = Client(settings, FailingOpener(status))
    with pytest.raises(SquareError) as caught:
        client.json('/api/catalog')
    assert not isinstance(caught.value, AuthenticationRequired)
    assert KEY not in str(caught.value) and FOREIGN not in str(caught.value)
    result = Runtime(settings, client).connection_status()
    assert result['connected'] is False and result['authRequired'] is False
    assert 'authUrl' not in result and 'reconnectTool' not in result
    assert '/local-access' not in result['message']


@pytest.mark.parametrize('token', [None, '', 'not-a-personal-key'])
def test_missing_or_malformed_local_key_is_recoverable_before_network(settings, monkeypatch, token):
    if token is None:
        monkeypatch.delenv('PTAI_API_TOKEN')
    else:
        monkeypatch.setenv('PTAI_API_TOKEN', token)
    opener = FailingOpener()
    with pytest.raises(AuthenticationRequired) as caught:
        Client(settings, opener).json('/api/catalog')
    assert caught.value.auth_url == ORIGIN + '/local-access'
    assert opener.calls == []


def test_connection_status_returns_actionable_auth_result(settings):
    result = Runtime(settings, Client(settings, FailingOpener())).connection_status()
    assert result['connected'] is False and result['authRequired'] is True
    assert result['authUrl'] == ORIGIN + '/local-access'
    assert result['errorCode'] == 'KEY_AUTH_REQUIRED' and result['reconnectTool'] == 'reconnect_key'
    assert result['databaseAccess'] is False
    assert KEY not in json.dumps(result) and FOREIGN not in json.dumps(result)


class AuthClient:
    def __init__(self, origin):
        self.origin, self.calls = origin, []

    def json(self, *args, **kwargs):
        self.calls.append(args)
        raise AuthenticationRequired(self.origin)

    manifest = json


@pytest.mark.parametrize('operation', ['search', 'detail', 'download', 'updates', 'inspect',
                                       'prepare_publish', 'publish_status', 'publish', 'prepare_install'])
def test_network_tools_preserve_auth_error_at_each_entry(settings, operation):
    source = settings.roots[0] / 'SKILL.md'
    source.write_text('# A fixture Skill\n', encoding='utf-8')
    client = AuthClient(settings.url)
    runtime = Runtime(settings, client)
    if operation == 'updates':
        atomic_json(runtime.installer.record_path, {'test-installation': {
            'origin': settings.url, 'toolId': 1, 'release': 1, 'status': 'installed',
            'scope': 'project', 'scopeDir': str(settings.roots[0]),
        }})
    calls = {
        'search': lambda: runtime.search_items('fixture'),
        'detail': lambda: runtime.get_item(1),
        'download': lambda: runtime.download_item(1),
        'updates': lambda: runtime.check_updates(),
        'inspect': lambda: runtime.inspect_source(str(source)),
        'prepare_publish': lambda: runtime.prepare_publish({}, target='review'),
        'publish_status': lambda: runtime.get_publish_status('12345678-1234-1234-1234-123456789abc'),
        'publish': lambda: runtime.publish_item('12345678-1234-1234-1234-123456789abc'),
        'prepare_install': lambda: runtime.installer.prepare(1, 'project', str(settings.roots[0])),
    }
    with pytest.raises(AuthenticationRequired):
        calls[operation]()
    assert len(client.calls) == 1


def test_install_auth_failure_does_not_consume_plan_or_mutate_destination(settings):
    from .test_local_mcp import FakeClient
    runtime = Runtime(settings, FakeClient())
    plan = runtime.installer.prepare(1, 'project', str(settings.roots[0]))
    runtime.installer.client = AuthClient(settings.url)
    before = (settings.state / 'plans' / (plan['planId'] + '.json')).read_bytes()
    with pytest.raises(AuthenticationRequired):
        runtime.installer.install(plan['planId'], plan['approvalDigest'], confirmed=True)
    assert not Path(plan['destination']).exists()
    assert not runtime.installer.record_path.exists()
    assert (settings.state / 'plans' / (plan['planId'] + '.json')).read_bytes() == before


@pytest.mark.parametrize('failure_at', ['transfer', 'recheck'])
def test_download_auth_failure_discards_partial_file_and_never_installs(settings, failure_at):
    raw = b'# fixture download\n'
    manifest = {'toolId': 1, 'release': 1, 'filename': 'SKILL.md', 'downloadUrl': '/download/1/1',
                'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    class DownloadOpener(FailingOpener):
        def open(self, request, timeout):
            if failure_at == 'recheck' and request.full_url.endswith('/download/1/1'):
                self.calls.append((request.full_url, request.method))
                return io.BytesIO(raw)
            return super().open(request, timeout)
    opener = DownloadOpener()
    output = settings.downloads / 'failed-download'
    with pytest.raises(AuthenticationRequired):
        Client(settings, opener).download(manifest, output)
    assert list(output.iterdir()) == []
    assert not (settings.state / 'installations.json').exists()
    assert len(opener.calls) == (1 if failure_at == 'transfer' else 2)


@pytest.mark.parametrize('completed', [False, True])
def test_reconnect_uses_current_settings_origin_not_zip_and_cancel_keeps_settings(settings, tmp_path, monkeypatch, completed):
    manifest = tmp_path / 'connection.json'
    manifest.write_text(json.dumps({'schemaVersion': 1, 'baseUrl': 'https://different-package.example.test'}), encoding='utf-8')
    monkeypatch.setattr(onboarding, 'PACKAGE_MANIFEST', manifest)
    previous = settings.path.read_bytes()
    seen = []
    def dialog(path, url):
        seen.append((path, url))
        return completed
    def no_network(*args, **kwargs):
        pytest.fail('Opening/cancelling the private input dialog must not make an API request')
    monkeypatch.setattr(Client, 'json', no_network)
    result = connection_ui.reconnect_key(settings.path, show_dialog=dialog)
    assert result == {'reconnected': completed, 'baseUrl': ORIGIN, 'authUrl': ORIGIN + '/local-access'}
    assert seen == [(settings.path, ORIGIN)]
    assert settings.path.read_bytes() == previous


def tool_payload(result):
    if isinstance(result, tuple):
        result = result[1]
    if isinstance(result, dict):
        return result
    return json.loads(''.join(block.text for block in result if hasattr(block, 'text')))


def test_reconnect_mcp_tool_cancel_does_not_authenticate_or_repeat_work(settings, monkeypatch):
    pytest.importorskip('mcp')
    from pt_square_mcp.server import make_server
    before = settings.path.read_bytes()
    seen = []
    def cancel(path):
        seen.append(path)
        return {'reconnected': False, 'baseUrl': ORIGIN, 'authUrl': ORIGIN + '/local-access'}
    def unexpected(*args, **kwargs):
        pytest.fail('Cancelling reconnection must not call the server or repeat a pending operation')
    monkeypatch.setattr(connection_ui, 'reconnect_key', cancel)
    monkeypatch.setattr(Client, 'json', unexpected)
    monkeypatch.setattr(Runtime, 'connection_status', unexpected)
    result = tool_payload(asyncio.run(make_server(settings.path).call_tool('reconnect_key', {})))
    assert result['reconnected'] is False
    assert seen == [settings.path] and settings.path.read_bytes() == before


@pytest.mark.parametrize('status_result', ['connected', 'auth_failed', 'network_failed'])
def test_reconnect_mcp_tool_checks_new_key_and_does_not_replay_mutations(settings, monkeypatch, status_result):
    pytest.importorskip('mcp')
    from pt_square_mcp.server import make_server
    checked = []
    def save_new_key(path):
        save_config(path, ORIGIN, settings.roots, NEW_KEY, download_directory=settings.downloads)
        return {'reconnected': True, 'baseUrl': ORIGIN, 'authUrl': ORIGIN + '/local-access'}
    def status(runtime):
        checked.append(runtime.settings.token())
        if status_result == 'auth_failed':
            return dict(connected=False, **AuthenticationRequired(ORIGIN).recovery())
        if status_result == 'network_failed':
            return {'connected': False, 'authRequired': False, 'message': 'Network unavailable'}
        return {'connected': True, 'user': {'id': 'E1'}, 'key': {'id': 'new-key', 'scope': 'read'}}
    def unexpected(*args, **kwargs):
        pytest.fail('Reconnection must not upload, download or install automatically')
    monkeypatch.setattr(connection_ui, 'reconnect_key', save_new_key)
    monkeypatch.setattr(Runtime, 'connection_status', status)
    monkeypatch.setattr(Client, 'open', unexpected)
    result = tool_payload(asyncio.run(make_server(settings.path).call_tool('reconnect_key', {})))
    assert checked == [NEW_KEY]
    assert result['keySaved'] is True
    assert result['reconnected'] is (status_result == 'connected')
    assert KEY not in json.dumps(result) and NEW_KEY not in json.dumps(result)


@pytest.fixture
def auth_http_server():
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            calls.append(self.path)
            if self.headers.get('Authorization') != 'Bearer ' + NEW_KEY:
                self.send_response(401)
                self.send_header('Location', FOREIGN)
                self.end_headers()
                self.wfile.write((KEY + ' ' + FOREIGN).encode())
                return
            if self.path == '/api/integration/me':
                body = {'user': {'id': 'E1', 'name': 'Fixture', 'dept': 'Test', 'dept_cd': 'T1'},
                        'key': {'id': 'new-fixture-key', 'scope': 'read'}}
            else:
                body = {'items': [{'id': 1, 'name': 'fixture tool'}]}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_address[1]), calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.skipif(os.name != 'nt', reason='The persistent stdio host must decrypt an actual Windows DPAPI generation')
def test_actual_stdio_error_links_and_live_reconnection_pick_up_new_private_key(settings, auth_http_server):
    pytest.importorskip('mcp')
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    url, calls = auth_http_server
    save_config(settings.path, url, settings.roots, allow_http=True, download_directory=settings.downloads)
    async def scenario():
        params = StdioServerParameters(command=sys.executable,
            args=['-X', 'utf8', '-B', str(PACKAGE / 'run_mcp.py'), '--config', str(settings.path), 'serve'],
            env=dict(os.environ, PTAI_API_TOKEN=KEY, USERPROFILE=str(Path.home())))
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=15)) as session:
                await session.initialize()
                tools = await session.list_tools()
                reconnect = next(tool for tool in tools.tools if tool.name == 'reconnect_key')
                assert not reconnect.inputSchema.get('properties')
                failed = await session.call_tool('search_items', {'query': 'fixture'})
                text = '\n'.join(block.text for block in failed.content if hasattr(block, 'text'))
                assert failed.isError
                assert '[연결 KEY 발급·관리](<' + url + '/local-access>)' in text
                assert KEY not in text and FOREIGN not in text
                status = await session.call_tool('connection_status', {})
                text = '\n'.join(block.text for block in status.content if hasattr(block, 'text'))
                assert not status.isError and 'KEY_AUTH_REQUIRED' in text
                assert KEY not in text
                # The same validation and atomic cutover used by the private GUI.
                onboarding.connect(settings.path, url, NEW_KEY, allow_http=True)
                success = await session.call_tool('search_items', {'query': 'fixture'})
                text = '\n'.join(block.text for block in success.content if hasattr(block, 'text'))
                assert not success.isError and 'fixture tool' in text
                status = await session.call_tool('connection_status', {})
                text = '\n'.join(block.text for block in status.content if hasattr(block, 'text'))
                assert not status.isError and 'new-fixture-key' in text
                assert KEY not in text and NEW_KEY not in text
    asyncio.run(scenario())
    assert len(calls) == 5
