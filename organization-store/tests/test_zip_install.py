"""Legacy Skill ZIP inspection uses real archive/hash/cache and installer paths."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'worker.py'
spec = importlib.util.spec_from_file_location('zip_store_worker', SCRIPT)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
from pt_square_mcp.client import Client, automatic_download_directory


SKILL = '---\nname: verified-skill\ndescription: Fixture skill\n---\n# Verified skill\nUse only when requested.\n'


def zipped(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


class ArchiveClient(Client):
    def __init__(self, settings):
        super().__init__(settings)
        self.transfers = []
        self.content = zipped([('SKILL.md', SKILL), ('scripts/install.py', 'raise RuntimeError("must not execute")')])
        self.release = 1
        self.profile = None
        self.extra = {}
        self.corrupt = False

    def manifest(self, tool_id):
        return copy.deepcopy(dict(toolId=tool_id, release=self.release, filename='fixture.zip',
                                  downloadUrl=f'/download/{tool_id}/{self.release}', bytes=len(self.content),
                                  sha256=hashlib.sha256(self.content).hexdigest(), installProfile=self.profile,
                                  **self.extra))

    def open(self, path, method='GET', body=None, content_type=None):
        assert method == 'GET' and path.startswith('/download/1/')
        self.transfers.append(path)
        return io.BytesIO(b'corrupted' if self.corrupt else self.content)

    def json(self, path, method='GET', data=None):
        assert method == 'GET'
        if path == '/api/integration/me':
            return {'user': {'id': 'E1'}}
        assert path == '/api/tools/1'
        return {'id': 1, 'name': 'Verified archive'}


@pytest.fixture
def configured(tmp_path, monkeypatch):
    data, home, project = (tmp_path / part for part in ('data', 'home', 'project'))
    for path in (data, home, project):
        path.mkdir()
    store = worker.Store(data, {'workspace': str(project)}, home=home, existing_config=tmp_path/'unused.json')
    worker.save_config(store.config_path, 'https://zip.example.test', [data], download_directory=data)
    worker.atomic_json(store.selection_path, {'mode': 'local'})
    client = ArchiveClient(store.settings())
    store.client_factory = lambda _: client
    monkeypatch.setattr(worker.Installer, '_launch_installer', lambda *a: pytest.fail('ZIP script was executed'))
    return store, client, project, home


@pytest.mark.parametrize('scope', ['project', 'user'])
def test_root_skill_zip_is_reviewed_then_installed_and_rolled_back(configured, scope):
    store, client, project, home = configured
    detail = store.dispatch('detail', {'toolId': 1})
    assert not detail['canInstall'] and detail['canInspectInstall']
    assert not client.transfers
    plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': scope})
    target = (project if scope == 'project' else home)/'.claude/skills/verified-skill'
    assert plan['canInstall'] and plan['destination'] == str(target)
    assert '명령은 실행하지 않습니다' in plan['detectionNotice']
    assert not target.exists() and len(client.transfers) == 1
    with pytest.raises(worker.SquareError, match='확인한 뒤'):
        store.dispatch('install', plan)
    installed = store.dispatch('install', dict(plan, confirmed=True))
    assert installed['installed'] and installed['status'] == 'installed'
    assert (target/'SKILL.md').read_text(encoding='utf-8') == SKILL
    assert (target/'scripts/install.py').is_file()
    assert client.transfers == ['/download/1/1', '/download/1/1']  # Revalidated for the current account; server deduplicates.
    assert store.dispatch('verify', {'installationId': installed['installationId']})['filesIntact']
    assert not ((home if scope == 'project' else project)/'.claude').exists()
    store.dispatch('rollback', dict(installationId=installed['installationId'], confirmed=True))
    assert not target.exists()


@pytest.mark.parametrize('entries', [
    [('setup.py', 'raise Exception("never run")')],
    [('nested/SKILL.md', SKILL)],
    [('SKILL.md', '# No installation metadata')],
    [('SKILL.md', SKILL.replace('verified-skill', '../outside'))],
    [('SKILL.md', SKILL.replace('verified-skill', 'synced'))],
    [('SKILL.md', SKILL.replace('name: verified-skill', 'name: one\nname: two'))],
    [('SKILL.md', '---\nname: verified-skill\n---\n')],
    [('SKILL.md', 'x' * (worker.zip_install.MAX_SKILL_BYTES + 1))],
])
def test_ambiguous_or_generic_zip_never_guesses_a_command(configured, entries):
    store, client, project, home = configured
    client.content = zipped(entries)
    plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project',
                                             'installProfile': {'kind': 'mcp'}, 'command': 'python setup.py'})
    assert plan['canInstall'] is False and plan['installed'] is False
    assert '실행 명령' in plan['reason']
    assert not (project/'.claude').exists() and not (home/'.claude').exists()
    assert not (store.settings().state/'plans').exists()


@pytest.mark.parametrize('bad_path', ['../outside.txt', '/outside.txt', 'C:/outside.txt', 'skill.md'])
def test_unsafe_zip_paths_or_case_collisions_are_rejected(configured, bad_path):
    store, client, project, home = configured
    client.content = zipped([('SKILL.md', SKILL), (bad_path, 'bad')])
    with pytest.raises(worker.SquareError):
        store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    assert not (project/'.claude').exists() and not (home/'.claude').exists()


def test_cached_file_tampering_after_review_stops_install(configured):
    store, client, project, _ = configured
    plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    artifact = next(automatic_download_directory(store.settings(), client.manifest(1)).glob('*.zip'))
    artifact.write_bytes(b'changed locally')
    with pytest.raises(worker.SquareError):
        store.dispatch('install', dict(plan, confirmed=True))
    assert not (project/'.claude').exists() and len(client.transfers) == 1


@pytest.mark.parametrize('change', ['release', 'bytes', 'profile', 'commands'])
def test_changed_server_release_or_metadata_requires_new_review(configured, change):
    store, client, project, _ = configured
    plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    if change == 'release':
        client.release += 1
    elif change == 'bytes':
        client.content = zipped([('SKILL.md', SKILL + 'Changed')])
    elif change == 'profile':
        client.profile = {'schemaVersion': 1, 'kind': 'manual', 'host': 'claude', 'slug': 'verified-skill', 'scopes': ['user']}
    else:
        client.extra['commands'] = {'project': 'python unexpected.py'}
    with pytest.raises(worker.SquareError, match='변경'):
        store.dispatch('install', dict(plan, confirmed=True))
    assert not (project/'.claude').exists() and len(client.transfers) == 1


@pytest.mark.parametrize('profile', [{}, {'schemaVersion': 99},
    {'schemaVersion': 1, 'kind': 'manual', 'host': 'claude', 'slug': 'manual-skill', 'scopes': ['project']},
    {'schemaVersion': 1, 'kind': 'skill', 'host': 'other', 'slug': 'other-skill', 'scopes': ['project'], 'entrypoint': 'SKILL.md'},
])
def test_explicit_invalid_manual_or_other_host_profile_is_never_overridden(configured, profile):
    store, client, project, _ = configured
    client.profile = profile
    detail = store.dispatch('detail', {'toolId': 1})
    assert not detail['canInspectInstall'] and not detail['canInstall']
    assert not store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})['canInstall']
    assert not client.transfers and not (project/'.claude').exists()


def test_source_hash_mismatch_fails_before_inspection(configured):
    store, client, project, _ = configured
    client.corrupt = True
    with pytest.raises(worker.SquareError, match='SHA-256'):
        store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    assert not (project/'.claude').exists()


def test_install_destination_comes_from_skill_name_not_package_id_or_payload(configured):
    store, client, project, _ = configured
    client.content = zipped([('SKILL.md', SKILL), ('ai-square.json', json.dumps({
        'packageId': 'unrelated-package', 'entryPoint': 'SKILL.md', 'type': 'Skill', 'platform': 'Claude'}))])
    plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project',
                                             'installProfile': {'slug': 'ignored'}, 'projectPath': 'C:/ignored'})
    assert plan['destination'] == str(project/'.claude/skills/verified-skill')
    assert plan.get('command') is None
    assert store.dispatch('install', dict(plan, confirmed=True))['installed']


@pytest.mark.parametrize('declaration', [
    {'type': 'MCP/Tool'}, {'type': '플러그인/하네스'}, {'platform': 'ChatGPT'},
    {'host': 'other'}, {'entryPoint': 'server.py'}, {'installProfile': {'kind': 'manual'}},
    ['not an object'],
])
def test_conflicting_server_package_is_not_offered_as_skill(configured, declaration):
    store, client, project, _ = configured
    client.extra['package'] = declaration
    detail = store.dispatch('detail', {'toolId': 1})
    assert not detail['canInspectInstall'] and not detail['canInstall']
    assert not store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})['canInstall']
    assert not client.transfers and not (project/'.claude').exists()


@pytest.mark.parametrize('encoded', [
    json.dumps({'type': 'MCP/Tool'}), json.dumps({'platform': 'ChatGPT'}),
    json.dumps({'entryPoint': 'install.py'}), json.dumps({'installProfile': {}}),
    '{"type":"Skill","type":"MCP/Tool"}', '{malformed', 'null', '[]',
    json.dumps({'schemaVersion': True}), json.dumps({'desc': 'x' * (64 * 1024)}),
], ids=['mcp', 'other-platform', 'other-entrypoint', 'embedded-profile',
        'duplicate-type', 'malformed-json', 'null', 'array', 'invalid-schema-type', 'oversized'])
def test_conflicting_ambiguous_or_oversized_embedded_declaration_is_rejected(configured, encoded):
    store, client, project, _ = configured
    client.content = zipped([('SKILL.md', SKILL), ('ai-square.json', encoded)])
    plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    assert plan['canInstall'] is False and plan['installed'] is False
    assert not (project/'.claude').exists()


def test_uppercase_verified_zip_artifact_is_extracted_and_installed(configured):
    store, client, project, _ = configured
    raw_download = client.download
    def uppercase_download(manifest, directory, *, update=False):
        upper = directory/'tool-1-v1.ZIP'
        if upper.exists():
            return upper
        artifact = raw_download(manifest, directory, update=update)
        artifact.rename(upper)
        return upper
    client.download = uppercase_download
    plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    result = store.dispatch('install', dict(plan, confirmed=True))
    assert result['installed'] is True
    assert (project/'.claude/skills/verified-skill/SKILL.md').read_text(encoding='utf-8') == SKILL
    assert len(client.transfers) == 1


def test_repeat_inspection_and_updates_do_not_add_fake_download_counts(configured):
    store, client, project, _ = configured
    first = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    second = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    assert len(client.transfers) == 2
    store.dispatch('install', dict(first, confirmed=True))
    with pytest.raises(worker.SquareError, match='설치 상태가 변경'):
        store.dispatch('install', dict(second, confirmed=True))
    client.release += 1
    client.content = zipped([('SKILL.md', SKILL + 'Version two')])
    update = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    store.dispatch('install', dict(update, confirmed=True))
    assert client.transfers == ['/download/1/1', '/download/1/1', '/download/1/1', '/download/1/1',
                                '/download/1/2?purpose=update', '/download/1/2?purpose=update']
    assert (project/'.claude/skills/verified-skill/SKILL.md').read_text(encoding='utf-8').endswith('Version two')


@pytest.mark.parametrize('scope', ['project-a', 'project-b', 'user'])
def test_stale_automatic_cache_recovers_without_touching_it(configured, scope):
    store, client, project, home = configured
    other = project.parent / 'another-project'
    other.mkdir()
    if scope == 'project-b':
        store.context['workspace'] = str(other)
    manifest = client.manifest(1)
    legacy = automatic_download_directory(store.settings(), manifest)
    legacy.mkdir(parents=True)
    old = legacy / 'tool-1-v1.zip'
    old.write_bytes(b'previous different archive')
    target_scope = 'user' if scope == 'user' else 'project'
    plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': target_scope})
    assert plan['canInstall']
    assert old.read_bytes() == b'previous different archive'
    installed = store.dispatch('install', dict(plan, confirmed=True))
    root = home if scope == 'user' else other if scope == 'project-b' else project
    assert installed['installed'] and (root/'.claude/skills/verified-skill/SKILL.md').is_file()
    assert old.read_bytes() == b'previous different archive'
    assert client.transfers == ['/download/1/1', '/download/1/1']


def test_changed_server_content_same_version_does_not_collide_with_prior_cache(configured):
    store, client, project, _ = configured
    first = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    cached = next(automatic_download_directory(store.settings(), client.manifest(1)).glob('*.zip'))
    original = cached.read_bytes()
    client.content = zipped([('SKILL.md', SKILL + 'Updated content')])
    second = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    assert second['canInstall'] and cached.read_bytes() == original
    result = store.dispatch('install', dict(second, confirmed=True))
    assert result['installed']
    assert (project/'.claude/skills/verified-skill/SKILL.md').read_text(encoding='utf-8').endswith('Updated content')
    with pytest.raises(worker.SquareError):
        store.dispatch('install', dict(first, confirmed=True))


def test_user_selected_download_conflict_still_preserves_existing_file(configured):
    store, client, _, _ = configured
    directory = store.directory / 'manual'
    directory.mkdir()
    target = directory / 'tool-1-v1.zip'
    target.write_bytes(b'user existing file')
    with pytest.raises(worker.SquareError, match='다른 내용'):
        client.download(client.manifest(1), directory)
    assert target.read_bytes() == b'user existing file'
    assert not client.transfers


def test_stale_cache_recovery_still_rejects_wrong_server_data(configured):
    store, client, project, _ = configured
    legacy = automatic_download_directory(store.settings(), client.manifest(1))
    legacy.mkdir(parents=True)
    (legacy/'tool-1-v1.zip').write_bytes(b'stale')
    client.corrupt = True
    with pytest.raises(worker.SquareError, match='SHA-256|크기'):
        store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    assert not (project/'.claude').exists()
    assert (legacy/'tool-1-v1.zip').read_bytes() == b'stale'


def test_simultaneous_cached_downloads_reuse_only_the_same_verified_bytes(configured):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    store, client, _, _ = configured
    directory = store.directory / 'racing-downloads'
    directory.mkdir()
    manifest = client.manifest(1)
    raw_open = client.open
    barrier = Barrier(2)
    def simultaneous_open(path, method='GET', body=None, content_type=None):
        barrier.wait(timeout=5)
        return raw_open(path, method=method, body=body, content_type=content_type)
    client.open = simultaneous_open
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.download, manifest, directory) for _ in range(2)]
        files = [future.result(timeout=10) for future in futures]
    assert files[0] == files[1]
    assert files[0].read_bytes() == client.content
    assert not list(directory.glob('*.part'))
