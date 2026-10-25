"""Chat KEY setup: synthetic credentials, isolated files, no native window."""
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import pytest

PACKAGE = Path(__file__).parents[1] / 'integrations' / 'pt-square-mcp'
sys.path.insert(0, str(PACKAGE))
from pt_square_mcp import config, connection_ui, onboarding
from pt_square_mcp.config import Settings, SquareError, save_config

ORIGIN = 'https://fixture-square.example.test'
HTTP = 'http://fixture-square.example.test:5000'
SAVED_ORIGIN = 'https://saved-square.example.test'
KEY = 'ptsq_' + 'z' * 43

@pytest.fixture
def fresh(tmp_path, monkeypatch):
    home = tmp_path / 'isolated-user'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    path = home / '.pt-ai-square' / 'mcp' / 'config.json'
    manifest = tmp_path / 'connection.json'
    manifest.write_text(json.dumps({'schemaVersion': 1, 'baseUrl': ORIGIN}), encoding='utf-8')
    monkeypatch.setattr(onboarding, 'PACKAGE_MANIFEST', manifest)
    monkeypatch.setenv('PTAI_API_TOKEN', KEY)
    def no_window(*args, **kwargs):
        pytest.fail('Chat setup must not open a native KEY window')
    monkeypatch.setattr(connection_ui, '_show_connection', no_window)
    monkeypatch.setattr(connection_ui, 'reconnect_key', no_window)
    return SimpleNamespace(home=home, path=path, manifest=manifest)

def payload(result):
    if isinstance(result, tuple): return result[1]
    if isinstance(result, dict): return result
    return json.loads(''.join(block.text for block in result if hasattr(block, 'text')))

def server(path):
    pytest.importorskip('mcp')
    from pt_square_mcp.server import make_server
    return make_server(path)

class ConsentContext:
    def __init__(self, capability='form', action='accept', accepted=True):
        from mcp.types import ElicitationCapability, FormElicitationCapability, UrlElicitationCapability
        options = {'form': ElicitationCapability(form=FormElicitationCapability()),
                   'legacy': ElicitationCapability(),
                   'url': ElicitationCapability(url=UrlElicitationCapability()), 'none': None}
        self.session = SimpleNamespace(client_params=SimpleNamespace(
            capabilities=SimpleNamespace(elicitation=options[capability])))
        self.action, self.accepted = action, accepted
        self.requests, self.progress = [], []
    async def elicit(self, message, schema):
        doc = schema.model_json_schema()
        self.requests.append({'message': message, 'schema': doc})
        assert set(doc['properties']) == {'acceptHttp'}
        assert doc['properties']['acceptHttp']['type'] == 'boolean'
        assert KEY not in message
        return SimpleNamespace(action=self.action,
            data=schema(acceptHttp=self.accepted) if self.action == 'accept' else None)
    async def report_progress(self, progress, total=None, message=None):
        assert KEY not in (message or '')
        self.progress.append((progress, total, message))

def invoke(path, context=None, key='', origin='', tool='connect_account'):
    return asyncio.run(server(path)._tool_manager.get_tool(tool).fn(
        context or ConsentContext(), key=key, accept_http_origin=origin))

def set_http(fresh):
    fresh.manifest.write_text(json.dumps({'schemaVersion': 1, 'baseUrl': HTTP}), encoding='utf-8')

def fake_api(monkeypatch):
    seen = []
    class VerifiedClient:
        def __init__(self, settings): self.settings = settings
        def json(self, route):
            assert route == '/api/integration/me', 'Never replay business operations'
            assert self.settings.token() == KEY
            seen.append((self.settings.url, route))
            return identity()
    monkeypatch.setattr(onboarding, 'Client', VerifiedClient)
    return seen

@pytest.mark.parametrize('tool', ['connect_account', 'reconnect_key'])
def test_empty_chat_asks_key_without_gui_forms_network_or_writes(fresh, monkeypatch, tool):
    seen = fake_api(monkeypatch)
    context = ConsentContext()
    result = invoke(fresh.path, context, tool=tool)
    assert result['keyRequired'] and not result['connected']
    assert result['baseUrl'] == ORIGIN and result['authUrl'] == ORIGIN+'/local-access'
    assert '기록' in result['notice'] and result['connectionMethod'] == 'chat'
    assert not context.requests and not seen and not fresh.path.exists()
    assert KEY not in json.dumps(result)

def test_fresh_status_and_business_tools_give_actionable_setup(fresh):
    mcp = server(fresh.path)
    status = payload(asyncio.run(mcp.call_tool('connection_status', {})))
    assert status['setupRequired'] and status['connectTool'] == 'connect_account'
    for name, args in [('search_items', {}), ('download_item', {'tool_id': 1}),
                       ('prepare_publish', {'metadata': {'name': 'fixture'}})]:
        with pytest.raises(Exception) as caught:
            asyncio.run(mcp.call_tool(name, args))
        assert 'connect_account' in str(caught.value) and KEY not in str(caught.value)

@pytest.mark.parametrize('tool', ['connect_account', 'reconnect_key'])
def test_https_chat_key_verifies_identity_and_saves_dpapi_without_echo(fresh, monkeypatch, tool):
    seen = fake_api(monkeypatch)
    context = ConsentContext()
    result = invoke(fresh.path, context, '  '+KEY+'  ', tool=tool)
    assert result['connected'] and result['keySaved'] and result['scope'] == 'read'
    assert result['connectionKeyId'] == 'fixture-key-id'
    assert result['user']['id'] == 'E-fixture' and not context.requests
    assert seen == [(ORIGIN, '/api/integration/me')]
    assert Settings(fresh.path).token() == KEY
    assert KEY not in fresh.path.read_text() and KEY not in json.dumps(result)
    assert result['credentialStored'] == 'windows-dpapi'

def test_saved_origin_and_saved_exact_http_acknowledgement_are_reused(fresh, monkeypatch):
    seen = fake_api(monkeypatch)
    folder = fresh.home / 'downloads'; folder.mkdir()
    save_config(fresh.path, HTTP, [folder], allow_http=True, download_directory=folder)
    context = ConsentContext()
    result = invoke(fresh.path, context, KEY)
    assert result['connected'] and result['baseUrl'] == HTTP
    assert seen == [(HTTP, '/api/integration/me')] and not context.requests

@pytest.mark.parametrize('capability', ['form', 'legacy'])
def test_http_form_is_boolean_consent_only(fresh, monkeypatch, capability):
    set_http(fresh); seen = fake_api(monkeypatch)
    context = ConsentContext(capability)
    result = invoke(fresh.path, context, KEY)
    assert result['connected'] and len(context.requests) == 1
    assert HTTP in context.requests[0]['message'] and seen == [(HTTP, '/api/integration/me')]

@pytest.mark.parametrize('action,accepted', [('decline', True), ('cancel', True), ('accept', False)])
def test_http_decline_or_cancel_never_transmits_key(fresh, monkeypatch, action, accepted):
    set_http(fresh); seen = fake_api(monkeypatch)
    result = invoke(fresh.path, ConsentContext(action=action, accepted=accepted), KEY)
    assert result['cancelled'] and not result['connected']
    assert not seen and not fresh.path.exists()

@pytest.mark.parametrize('capability', ['url', 'none'])
def test_http_without_form_requires_exact_explicit_origin(fresh, monkeypatch, capability):
    set_http(fresh); seen = fake_api(monkeypatch)
    context = ConsentContext(capability)
    pending = invoke(fresh.path, context, KEY)
    assert pending['httpApprovalRequired'] and not seen and not context.requests
    result = invoke(fresh.path, context, KEY, HTTP)
    assert result['connected'] and seen == [(HTTP, '/api/integration/me')]

@pytest.mark.parametrize('wrong_origin', ['http://another.example.test', 'http://user:secret@example.test', KEY])
def test_wrong_http_ack_is_not_forwarded_or_echoed(fresh, monkeypatch, wrong_origin):
    set_http(fresh); seen = fake_api(monkeypatch)
    result = invoke(fresh.path, key=KEY, origin=wrong_origin)
    assert result['errorCode'] == 'HTTP_ORIGIN_MISMATCH' and not seen
    assert wrong_origin not in json.dumps(result) and not fresh.path.exists()

def test_http_form_exception_is_sanitized_without_fallback(fresh, monkeypatch):
    set_http(fresh); seen = fake_api(monkeypatch)
    class Broken(ConsentContext):
        async def elicit(self, *args, **kwargs): raise RuntimeError(KEY)
    result = invoke(fresh.path, Broken(), KEY)
    assert result['errorCode'] == 'CONNECTION_CONFIRMATION_FAILED'
    assert not seen and KEY not in json.dumps(result)


def test_connection_changed_during_http_consent_is_not_overwritten_or_contacted(fresh, monkeypatch):
    set_http(fresh); seen = fake_api(monkeypatch)
    folder = fresh.home / 'other-downloads'; folder.mkdir()
    changed = []
    class Switched(ConsentContext):
        async def elicit(self, message, schema):
            answer = await super().elicit(message, schema)
            save_config(fresh.path, SAVED_ORIGIN, [folder], download_directory=folder)
            changed.append(fresh.path.read_bytes())
            return answer
    result = invoke(fresh.path, Switched(), KEY)
    assert result['errorCode'] == 'CONNECTION_CHANGED' and not result['connected']
    assert not seen and fresh.path.read_bytes() == changed[0]


def test_invalid_saved_config_does_not_fall_back_to_zip_or_echo_values(fresh):
    fresh.path.parent.mkdir(parents=True)
    fresh.path.write_text('{"broken":"'+KEY+'"}', encoding='utf-8')
    before = fresh.path.read_bytes()
    with pytest.raises(SquareError) as caught:
        invoke(fresh.path, key=KEY)
    assert KEY not in str(caught.value) and fresh.path.read_bytes() == before

@pytest.mark.parametrize('exception', [RuntimeError, SquareError])
def test_auth_exception_hides_key_and_raw_response(fresh, monkeypatch, exception):
    def fail(*args, **kwargs): raise exception('private-server-body '+KEY)
    monkeypatch.setattr(onboarding, 'connect', fail)
    result = invoke(fresh.path, key=KEY)
    assert result['errorCode'] == 'CONNECTION_FAILED' and not result['connected']
    assert KEY not in json.dumps(result) and 'private-server-body' not in json.dumps(result)

@pytest.mark.parametrize('bad_args', [{'key': [KEY]}, {'key': {'secret': KEY}},
                                    {'key': KEY, 'accept_http_origin': [KEY]}])
def test_bad_tool_types_never_reflect_key_in_validation_errors(fresh, bad_args):
    result = payload(asyncio.run(server(fresh.path).call_tool('connect_account', bad_args)))
    assert result['errorCode'] == 'INVALID_CONNECTION_INPUT'
    assert KEY not in json.dumps(result) and not fresh.path.exists()

def test_host_cancellation_signals_authentication_worker(fresh, monkeypatch):
    started, ended = threading.Event(), threading.Event()
    seen = []
    def waiting_connect(path, url, token, *, cancel_event, **kwargs):
        seen.append(cancel_event); started.set()
        assert cancel_event.wait(timeout=5)
        ended.set()
        raise config.ConnectionCancelled('cancelled')
    monkeypatch.setattr(onboarding, 'connect', waiting_connect)
    async def scenario():
        task = asyncio.create_task(server(fresh.path)._tool_manager.get_tool('connect_account').fn(ConsentContext(), key=KEY))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert await asyncio.to_thread(ended.wait, 5)
        finally:
            for event in seen: event.set()
    asyncio.run(scenario())
    assert len(seen) == 1 and seen[0].is_set() and not fresh.path.exists()


def identity():
    return {'user': {'id': 'E-fixture', 'name': 'Fixture', 'dept': 'Test', 'dept_cd': 'T1'},
            'key': {'id': 'fixture-key-id', 'scope': 'read'}}


@pytest.mark.parametrize('existing', [False, True])
def test_setup_does_not_overwrite_a_connection_changed_during_authentication(fresh, existing):
    downloads = fresh.home / 'downloads'
    downloads.mkdir()
    if existing:
        save_config(fresh.path, ORIGIN, [downloads], download_directory=downloads)
    expected = config.connection_fingerprint(fresh.path)
    changed = []
    class ConcurrentClient:
        def __init__(self, settings):
            self.settings = settings
        def json(self, route):
            assert route == '/api/integration/me' and self.settings.token() == KEY
            save_config(fresh.path, SAVED_ORIGIN, [downloads], download_directory=downloads)
            changed.append(fresh.path.read_bytes())
            return identity()
    with pytest.raises(SquareError):
        onboarding.connect(fresh.path, ORIGIN, token_from_env=True,
                           client_factory=ConcurrentClient, expected_state=expected)
    assert len(changed) == 1 and fresh.path.read_bytes() == changed[0]
    assert Settings(fresh.path).url == SAVED_ORIGIN


@pytest.mark.parametrize('cancel_before_network', [True, False])
def test_cancelled_authentication_never_commits_config(fresh, cancel_before_network):
    event, calls = threading.Event(), []
    if cancel_before_network:
        event.set()
    class CancellingClient:
        def __init__(self, settings):
            self.settings = settings
        def json(self, route):
            calls.append(route)
            event.set()
            return identity()
    with pytest.raises(SquareError):
        onboarding.connect(fresh.path, ORIGIN, token_from_env=True,
                           client_factory=CancellingClient, expected_state=None, cancel_event=event)
    assert calls == ([] if cancel_before_network else ['/api/integration/me'])
    assert not fresh.path.exists()


def test_cancel_at_credential_write_keeps_previous_config_and_cleans_new_secret(fresh, monkeypatch):
    downloads = fresh.home / 'downloads'
    downloads.mkdir()
    save_config(fresh.path, ORIGIN, [downloads], download_directory=downloads)
    before, expected = fresh.path.read_bytes(), config.connection_fingerprint(fresh.path)
    event = threading.Event()
    class VerifiedClient:
        def __init__(self, settings):
            pass
        def json(self, route):
            return identity()
    original_write = config.atomic_json
    def cancel_after_credential(path, document):
        original_write(path, document)
        if Path(path).name.startswith('credential.'):
            event.set()
    monkeypatch.setattr(config, 'atomic_json', cancel_after_credential)
    monkeypatch.setattr(config, 'protect', lambda data, decrypt=False: b'fixture-encrypted-envelope')
    with pytest.raises(SquareError):
        onboarding.connect(fresh.path, ORIGIN, KEY, client_factory=VerifiedClient,
                           expected_state=expected, cancel_event=event)
    assert fresh.path.read_bytes() == before
    assert list(fresh.path.parent.glob('credential.*.dpapi.json')) == []


STDIO_FIXTURE = '''import json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from pt_square_mcp import connection_ui, onboarding
from pt_square_mcp.server import make_server
config_path, manifest, home, trace = map(Path, sys.argv[2:6])
Path.home = classmethod(lambda cls: home)
onboarding.PACKAGE_MANIFEST = manifest
def no_window(*args, **kwargs): raise AssertionError('No native UI in chat flow')
connection_ui._show_connection = no_window
class FixtureClient:
    def __init__(self, settings): self.settings = settings
    def json(self, route):
        assert route == '/api/integration/me', 'No business operation may be replayed'
        assert self.settings.token() == os.environ['PTAI_TEST_KEY']
        with trace.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'origin': self.settings.url, 'route': route}) + '\\n')
        return {'user': {'id': 'E-fixture', 'name': 'Fixture User', 'dept': 'Test'},
                'key': {'id': 'fixture-key-id', 'scope': 'read'}}
onboarding.Client = FixtureClient
make_server(config_path).run(transport='stdio')
'''


@pytest.mark.parametrize('http,action', [(False, 'accept'), (True, 'accept'),
                                        (True, 'decline'), (True, 'cancel')])
def test_actual_stdio_chat_input_uses_no_key_form_and_does_not_echo(fresh, tmp_path, http, action):
    pytest.importorskip('mcp')
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import ElicitResult
    if http: set_http(fresh)
    script, trace = tmp_path/'isolated_host.py', tmp_path/'trace.jsonl'
    script.write_text(STDIO_FIXTURE, encoding='utf-8')
    messages = []
    async def consent(_context, request):
        document = request.model_dump(mode='json')
        messages.append(document)
        properties = document['requestedSchema']['properties']
        assert document['mode'] == 'form' and set(properties) == {'acceptHttp'}
        assert properties['acceptHttp']['type'] == 'boolean' and KEY not in json.dumps(document)
        return ElicitResult(action=action, content={'acceptHttp': True} if action == 'accept' else None)
    async def scenario():
        params = StdioServerParameters(command=sys.executable,
            args=['-X', 'utf8', '-B', str(script), str(PACKAGE), str(fresh.path),
                  str(fresh.manifest), str(fresh.home), str(trace)],
            env=dict(os.environ, PTAI_TEST_KEY=KEY))
        with (tmp_path/'host-stderr.txt').open('w', encoding='utf-8') as errorlog:
            async with stdio_client(params, errlog=errorlog) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=20),
                                         elicitation_callback=consent) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    for name in ('connect_account', 'reconnect_key'):
                        tool = next(t for t in tools.tools if t.name == name)
                        assert set(tool.inputSchema['properties']) == {'key', 'accept_http_origin'}
                        assert tool.inputSchema['properties']['key']['type'] == 'string'
                    prompt = await session.call_tool('connect_account', {})
                    assert not prompt.isError and payload(prompt.content)['keyRequired']
                    assert messages == []
                    invalid = await session.call_tool('connect_account', {'key': [KEY]})
                    assert not invalid.isError and KEY not in json.dumps(payload(invalid.content))
                    result = await session.call_tool('connect_account', {'key': KEY})
                    assert not result.isError
                    data = payload(result.content)
                    assert KEY not in json.dumps(data)
                    assert data['connected'] is (action == 'accept')
                    if action == 'accept':
                        assert data['user']['id'] == 'E-fixture' and data['scope'] == 'read'
                        assert data['keySaved'] and data['connectionKeyId'] == 'fixture-key-id'
                    else: assert data['cancelled']
    asyncio.run(scenario())
    assert len(messages) == (1 if http else 0)
    assert fresh.path.exists() is (action == 'accept')
    events = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
    assert events == ([{'origin': HTTP if http else ORIGIN, 'route': '/api/integration/me'}]
                      if action == 'accept' else [])
    assert KEY not in (tmp_path/'host-stderr.txt').read_text()
