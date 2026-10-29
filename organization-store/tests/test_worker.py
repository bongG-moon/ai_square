"""Isolated protocol/connection/install regressions; never touch the real profile."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'worker.py'
spec = importlib.util.spec_from_file_location('organization_store_worker', SCRIPT)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class FakeClient:
    origin = 'https://store.example.test'
    def __init__(self, settings):
        self.settings = settings
        self.downloads = []
        self.release = 1
        self.kind = 'skill'
        self.content = b'---\nname: test-store\ndescription: Fixture\n---\n# One\n'

    def manifest(self, tool_id):
        profile = dict(schemaVersion=1, kind=self.kind, host='claude', slug='fixture-store',
                       scopes=['project', 'user'], entrypoint='SKILL.md')
        suffix = '.md'
        if self.kind == 'installer':
            profile.update(entrypoint='setup.exe', installerArgs={'project': [], 'user': []})
            suffix = '.exe'
        if self.kind == 'mcp':
            profile.update(entrypoint='server.py', command={'executable': 'python', 'args': ['{entrypoint}']})
            suffix = '.zip'
        return dict(toolId=tool_id, release=self.release, name='Fixture', filename='fixture'+suffix,
                    downloadUrl=f'/download/{tool_id}/{self.release}', bytes=len(self.content),
                    sha256=hashlib.sha256(self.content).hexdigest(), installProfile=profile)

    def download(self, manifest, directory, *, update=False):
        self.downloads.append(update)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / manifest['filename']
        path.write_bytes(self.content)
        return path

    def json(self, path, method='GET', data=None):
        if path == '/api/integration/me':
            return {'user': {'id': 'fixture', 'name': 'Test'}, 'capabilities': {'like': True}}
        if path.startswith('/api/tools/'):
            return {'id': 1, 'name': 'Fixture'}
        return {'items': []}


def test_ax_extension_is_download_only_even_with_a_claude_install_profile():
    manifest = dict(filename='PNT-AI-Square.axextension', downloadUrl='/download/1/1',
                    installProfile=dict(schemaVersion=1, kind='skill', host='claude',
                                        slug='fixture', scopes=['user'], entrypoint='SKILL.md'))
    supported, notice = worker.Store.install_support(manifest)
    assert supported is False
    assert '더블클릭' in notice


@pytest.fixture
def configured(tmp_path):
    data, home, project = (tmp_path / part for part in ('extension-data', 'home', 'project'))
    for path in (data, home, project):
        path.mkdir()
    store = worker.Store(data, {'workspace': str(project)}, home=home, existing_config=tmp_path/'unused.json')
    worker.save_config(store.config_path, FakeClient.origin, [data], download_directory=data)
    worker.atomic_json(store.selection_path, {'mode': 'local'})
    client = FakeClient(store.settings())
    store.client_factory = lambda settings: client
    return store, client, project, home


@pytest.mark.parametrize('profile', [None, {}, {'schemaVersion': 99}, {'kind': 'skill'}])
def test_missing_or_invalid_install_metadata_is_explained_and_download_only(configured, profile):
    store, client, project, home = configured
    manifest = client.manifest(1)
    manifest['installProfile'] = profile
    client.manifest = lambda _: manifest
    detail = store.dispatch('detail', {'toolId': 1})
    assert detail['canInstall'] is False
    assert '등록자가 앱 설치 정보(지원 범위·설치 방식)를 등록해야' in detail['installNotice']
    prepared = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    assert prepared['canInstall'] is False and prepared['installed'] is False
    assert not client.downloads
    assert not (project/'.claude').exists() and not (home/'.claude').exists()
    assert store.dispatch('download', {'toolId': 1})['installed'] is False


@pytest.mark.parametrize('scope', ['user', 'project'])
def test_single_declared_scope_installs_only_in_supported_location(configured, scope):
    store, client, project, home = configured
    manifest = client.manifest(1)
    manifest['installProfile']['scopes'] = [scope]
    client.manifest = lambda _: manifest
    assert store.dispatch('detail', {'toolId': 1})['canInstall'] is True
    other_scope = 'project' if scope == 'user' else 'user'
    with pytest.raises(worker.SquareError, match='범위를 지원하지'):
        store.dispatch('prepareInstall', {'toolId': 1, 'scope': other_scope})
    plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': scope})
    result = store.dispatch('install', dict(plan, confirmed=True))
    expected, untouched = (home, project) if scope == 'user' else (project, home)
    assert result['installed'] is True
    assert (expected/'.claude/skills/fixture-store/SKILL.md').read_bytes() == client.content
    assert not (untouched/'.claude').exists()


@pytest.mark.parametrize('suffix', ['.EXE', '.msi', '.ps1'])
def test_external_file_cannot_claim_to_be_a_directly_installable_skill(configured, suffix, monkeypatch):
    store, client, project, _ = configured
    manifest = client.manifest(1)
    manifest['filename'] = 'setup' + suffix
    client.manifest = lambda _: manifest
    monkeypatch.setattr(worker.Installer, 'install', lambda *a: pytest.fail('external file installed'))
    detail = store.dispatch('detail', {'toolId': 1})
    assert detail['canInstall'] is False
    assert '별도 설치 프로그램' in detail['installNotice']
    assert store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})['canInstall'] is False
    assert not client.downloads and not (project/'.claude').exists()


def test_status_disconnected_does_not_load_personal_config_or_network(tmp_path):
    def fail(_):
        pytest.fail('status must never contact server')
    store = worker.Store(tmp_path/'store', home=tmp_path, existing_config=tmp_path/'absent', client_factory=fail)
    assert store.dispatch('status')['configured'] is False
    assert store.dispatch('status')['storeVersion'] == '0.1.0'


def test_project_install_update_rollback_retry_and_count_purpose(configured):
    store, client, project, _ = configured
    plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project', 'projectPath': 'C:/ignored'})
    assert plan['scopeDir'] == str(project)
    with pytest.raises(worker.SquareError):
        store.dispatch('install', plan)
    installed = store.dispatch('install', dict(plan, confirmed=True))
    target = project/'.claude/skills/fixture-store/SKILL.md'
    assert target.read_bytes() == client.content
    with pytest.raises((worker.SquareError, FileNotFoundError)):
        store.dispatch('install', dict(plan, confirmed=True))
    assert client.downloads == [False]
    first = client.content
    client.release = 2
    client.content = b'# Two\n'
    plan2 = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    result = store.dispatch('install', dict(plan2, confirmed=True))
    assert client.downloads == [False, True]
    assert store.dispatch('verify', {'installationId': result['installationId']})['filesIntact']
    store.dispatch('rollback', dict(installationId=result['installationId'], confirmed=True))
    assert target.read_bytes() == first
    assert store.dispatch('installations')['items'][0]['release'] == 1
    download = store.dispatch('download', {'toolId': 1, 'update': False})
    assert download['purpose'] == 'update' and client.downloads[-1] is True


def test_download_cannot_claim_update_without_authoritative_install(configured):
    store, client, _, _ = configured
    assert store.dispatch('download', {'toolId': 1, 'update': True})['purpose'] == 'download'
    assert client.downloads == [False]
    assert store.dispatch('installations')['items'] == []


def test_other_directory_requires_host_grant_and_matches_plan_on_commit(configured, tmp_path):
    store, client, project, home = configured
    chosen = tmp_path/'explicit chosen'; chosen.mkdir()
    with pytest.raises(worker.SquareError, match='선택 창'):
        store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'directory',
                                         'directoryToken': 'a'*43, 'path': str(chosen)})
    info = chosen.stat()
    store.context.update(selectedDirectory=str(chosen), selectedDirectoryIdentity=[info.st_dev, info.st_ino], directoryToken='a'*43)
    plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'directory'})
    assert plan['scope'] == 'project' and plan['scopeDir'] == str(chosen)
    store.context['directoryToken'] = 'b'*43
    with pytest.raises(worker.SquareError, match='선택이 변경'):
        store.dispatch('install', dict(plan, confirmed=True))
    store.context['directoryToken'] = 'a'*43
    installed = store.dispatch('install', dict(plan, confirmed=True))
    assert installed['installed']
    assert (chosen/'.claude/skills/fixture-store/SKILL.md').read_bytes() == client.content
    assert not (project/'.claude').exists() and not (home/'.claude').exists()
    assert store.settings().roots == [store.directory]


@pytest.mark.parametrize('permission', [True, False])
def test_detail_preserves_owner_update_capability(configured, permission):
    store, client, _, _ = configured
    client.json = lambda path, *args: {'id': 1, 'name': 'Fixture', 'canPublishOwnUpdate': permission}
    assert store.dispatch('detail', {'toolId': 1})['item']['canPublishOwnUpdate'] is permission


def test_detail_counts_only_explicit_open_and_old_server_does_not_block(configured):
    store, client, *_ = configured
    calls = []
    original = client.json
    def response(path, method='GET', data=None):
        calls.append((path, method, data))
        if path.endswith('/view'):
            return {'views': 8, 'counted': True}
        return original(path, method, data)
    client.json = response
    assert 'views' not in store.dispatch('detail', {'toolId': 1})['item']
    assert not any(path.endswith('/view') for path, _, _ in calls)
    assert store.dispatch('detail', {'toolId': 1, 'recordView': True})['item']['views'] == 8
    assert calls[-1] == ('/api/tools/1/view', 'POST', {})
    def older(path, method='GET', data=None):
        if path.endswith('/view'):
            raise worker.SquareError('unsupported server')
        return original(path, method, data)
    client.json = older
    assert store.dispatch('detail', {'toolId': 1, 'recordView': True})['item']['name'] == 'Fixture'


def test_chosen_directory_replaced_during_download_is_not_written(configured, tmp_path):
    store, client, project, home = configured
    chosen = tmp_path/'chosen'; chosen.mkdir()
    info = chosen.stat()
    store.context.update(selectedDirectory=str(chosen), selectedDirectoryIdentity=[info.st_dev, info.st_ino], directoryToken='a'*43)
    plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'directory'})
    original = client.download
    moved = tmp_path/'original chosen'
    def replace_folder(manifest, directory, *, update=False):
        result = original(manifest, directory, update=update)
        chosen.rename(moved)
        chosen.mkdir()
        return result
    client.download = replace_folder
    with pytest.raises(worker.SquareError, match='설치 폴더가 변경'):
        store.dispatch('install', dict(plan, confirmed=True))
    assert not list(chosen.iterdir()) and not list(moved.iterdir())
    assert not (project/'.claude').exists() and not (home/'.claude').exists()
    assert store.dispatch('installations')['items'] == []


def test_scope_change_and_unmanaged_files_block_install(configured, tmp_path):
    store, client, project, _ = configured
    plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    other = tmp_path/'other'; other.mkdir()
    store.context['workspace'] = str(other)
    with pytest.raises(worker.SquareError, match='업무 폴더'):
        store.dispatch('install', dict(plan, confirmed=True))
    store.context['workspace'] = str(project)
    destination = project/'.claude/skills/fixture-store'
    destination.mkdir(parents=True)
    (destination/'personal.md').write_text('keep')
    with pytest.raises(worker.SquareError):
        store.dispatch('install', dict(plan, confirmed=True))
    assert (destination/'personal.md').read_text() == 'keep'
    assert not client.downloads


def test_explicit_user_scope_and_mcp_merge_preserve_unrelated_settings(configured):
    store, client, _, home = configured
    client.kind = 'mcp'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('server.py', 'print("fixture, never launched")')
    client.content = buffer.getvalue()
    old = {'mcpServers': {'existing': {'command': 'keep', 'args': []}}, 'other': {'keep': True}}
    worker.atomic_json(home/'.claude.json', old)
    plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'user'})
    result = store.dispatch('install', dict(plan, confirmed=True))
    value = worker.read_json(home/'.claude.json')
    assert value['mcpServers']['existing'] == old['mcpServers']['existing'] and value['other'] == old['other']
    assert result['status'] == 'configured' and result['installed'] and result['connectionVerified'] is False
    store.dispatch('rollback', dict(installationId=result['installationId'], confirmed=True))
    assert worker.read_json(home/'.claude.json') == old


def test_external_installers_never_execute(configured, monkeypatch):
    store, client, project, _ = configured
    client.kind = 'installer'
    monkeypatch.setattr(worker.Installer, '_launch_installer', lambda *a: pytest.fail('external installer launched'))
    assert store.dispatch('detail', {'toolId': 1})['canInstall'] is False
    assert store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})['canInstall'] is False
    assert not (project/'.pt-ai-square').exists()
    assert store.dispatch('download', {'toolId': 1})['installed'] is False


def test_modified_files_stop_rollback_and_verification(configured):
    store, client, project, _ = configured
    plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    installed = store.dispatch('install', dict(plan, confirmed=True))
    (project/'.claude/skills/fixture-store/SKILL.md').write_text('personal change')
    verification = store.dispatch('verify', {'installationId': installed['installationId']})
    assert verification['filesIntact'] is False and '변경되었습니다' in verification['notice']
    with pytest.raises(worker.SquareError, match='수정'):
        store.dispatch('rollback', dict(installationId=installed['installationId'], confirmed=True))


def test_reuse_and_disconnect_leave_original_config_key_and_records_untouched(configured, tmp_path):
    store, client, project, _ = configured
    original = tmp_path/'mcp/config.json'
    worker.save_config(original, FakeClient.origin, [project])
    worker.atomic_json(original.parent/'state/installations.json', {'unrelated': {'origin': 'https://other.test'}})
    before = {p: p.read_bytes() for p in original.parent.rglob('*') if p.is_file()}
    store.existing_config = original
    assert store.dispatch('connect', {'reuseExisting': True})['connectionMode'] == 'existing'
    assert store.dispatch('disconnect')['configured'] is False
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI contract')
def test_new_connection_uses_dpapi_and_failed_connect_keeps_previous(configured):
    store, client, _, _ = configured
    token = 'ptsq_' + 'A'*43
    result = store.dispatch('connect', {'url': client.origin, 'key': token})
    assert result['configured'] and token not in json.dumps(result)
    assert store.settings().token() == token
    for file in store.directory.rglob('*.json'):
        assert token not in file.read_text(encoding='utf-8')
    before = store.config_path.read_bytes()
    def denied(settings):
        raise worker.SquareError('refused')
    store.client_factory = denied
    with pytest.raises(worker.SquareError):
        store.dispatch('connect', {'url': 'https://bad.example', 'key': token})
    assert store.config_path.read_bytes() == before
    assert store.settings().data['trustedRoots'] == [str(store.directory)]


def test_http_and_actions_are_explicit(configured):
    store, _, _, _ = configured
    with pytest.raises(worker.SquareError, match='HTTP'):
        store.dispatch('connect', {'url': 'http://internal.test', 'key': 'ptsq_'+'B'*43})
    for action in ('shell', 'publish', 'writeFile'):
        with pytest.raises(worker.SquareError):
            store.dispatch(action, {})
    with pytest.raises(worker.SquareError):
        store.dispatch('prepareInstall', {'toolId': 1})
    with pytest.raises(worker.SquareError):
        store.dispatch('like', {'toolId': 1, 'liked': 'true'})


def test_publish_access_client_only_permits_bounded_same_origin_gets():
    settings = type('Settings', (), {'url': 'https://fixture.test', 'token': lambda _: 'ptsq_' + 'Q' * 43})()
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, request.method, timeout))
            assert timeout == 2 and request.method == 'GET'
            return io.BytesIO(b'{"id":7,"ownerId":"owner"}')
    client = worker.StoreClient(settings, Opener())
    assert client.read_publish_access_json('/api/tools/7')['ownerId'] == 'owner'
    assert client.read_publish_access_json('/api/integration/me')['id'] == 7
    assert calls == [('https://fixture.test/api/tools/7', 'GET', 2),
                     ('https://fixture.test/api/integration/me', 'GET', 2)]
    for path in ('/api/tools/0', '/api/tools/7?extra=1', '/api/tools/7/manifest',
                 'https://evil.test/api/tools/7', '/api/integration/me#fragment'):
        with pytest.raises(worker.SquareError):
            client.read_publish_access_json(path)
    assert len(calls) == 2


def test_publish_access_timeout_is_sanitized_and_not_retried():
    settings = type('Settings', (), {'url': 'https://fixture.test', 'token': lambda _: 'secret-fixture'})()
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(timeout)
            raise TimeoutError('private token and details must not be surfaced')
    client = worker.StoreClient(settings, Opener())
    with pytest.raises(worker.SquareError) as error:
        client.read_publish_access_json('/api/integration/me')
    assert 'private' not in str(error.value) and 'secret-fixture' not in str(error.value)
    assert calls == [2]


def test_publish_access_limits_response_and_rejects_invalid_json():
    settings = type('Settings', (), {'url': 'https://fixture.test', 'token': lambda _: 'fixture'})()
    class Opener:
        def __init__(self, payload): self.payload = payload
        def open(self, request, timeout):
            assert timeout == 2
            return io.BytesIO(self.payload)
    for payload in (b'x' * (512 * 1024 + 1), b'not-json', b'[]'):
        with pytest.raises(worker.SquareError):
            worker.StoreClient(settings, Opener(payload)).read_publish_access_json('/api/integration/me')


def test_publish_access_accepts_large_valid_tool_history_and_caps_both_endpoints(configured):
    store, *_ = configured
    settings = type('Settings', (), {'url': 'https://fixture.test', 'token': lambda _: 'fixture'})()
    class Opener:
        def open(self, request, timeout):
            assert timeout == 2 and request.method == 'GET'
            if request.full_url.endswith('/api/integration/me'):
                return io.BytesIO(json.dumps({'user': {'id': 'owner'}, 'key': {'id': 'key-one'},
                                              'capabilities': {'publishDraft': True}}).encode())
            assert request.full_url.endswith('/api/tools/7')
            return io.BytesIO(json.dumps({'id': 7, 'ownerId': 'owner',
                                           'history': 'x' * (512 * 1024)}).encode())
    runtime = type('Runtime', (), {'client': worker.StoreClient(settings, Opener())})()
    assert store.publish_update_access(runtime, {'toolId': 7}) == {'canUpdate': True}

    class TooLarge:
        def open(self, request, timeout):
            assert timeout == 2
            limit = 512 * 1024 if request.full_url.endswith('/api/integration/me') else 4 * 1024 * 1024
            return io.BytesIO(b'x' * (limit + 1))
    capped = worker.StoreClient(settings, TooLarge())
    for path in ('/api/integration/me', '/api/tools/7'):
        with pytest.raises(worker.SquareError):
            capped.read_publish_access_json(path)


def test_like_client_only_permits_exact_endpoint_and_boolean():
    settings = type('Settings', (), {'url': 'https://fixture.test', 'token': lambda _: 'ptsq_'+'C'*43})()
    class Opener:
        def open(self, request, timeout):
            assert request.method == 'PUT'
            assert timeout == 30
            assert request.full_url == 'https://fixture.test/api/tools/1/like'
            return io.BytesIO(b'{"liked":true,"count":1}')
    client = worker.StoreClient(settings, Opener())
    assert client.json('/api/tools/1/like', 'PUT', {'liked': True})['count'] == 1
    for path in ('/api/tools/1', '/api/tools/1/like?x=1', 'https://evil.test/api/tools/1/like'):
        with pytest.raises(worker.SquareError):
            client.json(path, 'PUT', {'liked': True})


def test_view_client_only_permits_explicit_empty_post_to_same_origin():
    settings = type('Settings', (), {'url': 'https://fixture.test', 'token': lambda _: 'ptsq_'+'E'*43})()
    class Opener:
        def open(self, request, timeout):
            assert request.method == 'POST'
            assert timeout == 2
            assert request.full_url == 'https://fixture.test/api/tools/1/view'
            assert json.loads(request.data) == {}
            return io.BytesIO(b'{"views":1,"counted":true,"pending":false}')
    client = worker.StoreClient(settings, Opener())
    assert client.json('/api/tools/1/view', 'POST', {})['views'] == 1
    for path in ('/api/tools/1/view?x=1', 'https://evil.test/api/tools/1/view', '/api/tools/1/settings'):
        with pytest.raises(worker.SquareError):
            client.json(path, 'POST', {})
    with pytest.raises(worker.SquareError):
        client.json('/api/tools/1/view', 'POST', {'user': 'other'})


def test_view_timeout_keeps_fetched_detail_and_never_retries(configured):
    store, fixture, *_ = configured
    calls = []
    manifest = fixture.manifest(1)
    settings = type('Settings', (), {'url': fixture.origin, 'token': lambda _: 'ptsq_'+'F'*43})()
    class Opener:
        def open(self, request, timeout):
            calls.append((request.method, request.full_url, timeout))
            if request.full_url.endswith('/view'):
                assert request.method == 'POST' and timeout == 2
                raise TimeoutError('optional view accounting timed out')
            assert request.method == 'GET' and timeout == 30
            result = manifest if request.full_url.endswith('/manifest') else {'id': 1, 'name': 'Fetched detail', 'guide': 'Keep this guide'}
            return io.BytesIO(json.dumps(result).encode())
    store.client_factory = lambda _: worker.StoreClient(settings, Opener())
    result = store.dispatch('detail', {'toolId': 1, 'recordView': True})
    assert result['item']['name'] == 'Fetched detail'
    assert result['item']['guide'] == 'Keep this guide'
    assert result['canInstall'] is True
    assert 'views' not in result['item']
    assert len([call for call in calls if call[0] == 'POST']) == 1


def test_actual_isolated_stdio_worker_and_malformed_payload(tmp_path):
    request = {'protocol': 1, 'action': 'status', 'payload': {}, 'dataDirectory': str(tmp_path/'data'), 'context': {}}
    result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT)], input=json.dumps(request).encode(), capture_output=True, timeout=10)
    assert result.returncode == 0 and not result.stderr
    assert json.loads(result.stdout)['result']['configured'] is False
    secret = 'ptsq_'+'D'*43
    result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT)], input=(secret+'malformed').encode(), capture_output=True, timeout=10)
    assert not json.loads(result.stdout)['ok'] and secret.encode() not in result.stdout and not result.stderr


@pytest.mark.parametrize('payload', [{}, {'toolId': 1, 'user': 'someone-else'},
                                    {'toolId': 1, 'granted': True}, {'toolId': 1, 'reason': 'override'}])
def test_access_request_payload_cannot_supply_identity_or_grant(configured, payload):
    store, client, *_ = configured
    client.request_access = lambda *args: pytest.fail('invalid request reached client')
    with pytest.raises(worker.SquareError, match='권한을 신청할 도구'):
        store.dispatch('requestAccess', payload)


@pytest.mark.parametrize('payload', [{}, {'toolId': 1}, {'toolId': 1, 'expectedRevision': 'a'*32, 'user': 'other'},
                                    {'toolId': 1, 'expectedRevision': 'a'*32, 'granted': False}])
def test_access_cancel_payload_cannot_supply_identity_or_grant(configured, payload):
    store, client, *_ = configured
    client.cancel_access_request = lambda *args: pytest.fail('invalid cancel reached client')
    with pytest.raises(worker.SquareError, match='취소할 신청 상태'):
        store.dispatch('cancelAccessRequest', payload)
