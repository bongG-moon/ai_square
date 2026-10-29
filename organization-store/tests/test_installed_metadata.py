"""Installed display and update reads never mutate installation authority."""
import io
import json
import threading
from urllib.error import HTTPError

import pytest

from test_worker import configured, worker


def seed(store, project, count=1):
    rows = {f'install-{i}': dict(origin=store.settings().url, toolId=i, release=1,
            scope='project', scopeDir=str(project), target=str(project / f'skill-{i}'),
            status='installed', created=1) for i in range(1, count + 1)}
    worker.atomic_json(store.settings().state / 'installations.json', rows)
    return rows


def test_remove_from_list_preserves_files_authority_and_other_scope(configured):
    store, client, project, _ = configured
    rows = seed(store, project)
    rows['another-scope'] = dict(rows['install-1'], scope='user', target=str(project / 'other'))
    path = store.settings().state / 'installations.json'
    worker.atomic_json(path, rows)
    target = project / 'skill-1'
    target.mkdir()
    (target / 'SKILL.md').write_text('my instructions', encoding='utf-8')
    before = path.read_bytes()
    reader(client, lambda p: version(tid(p)) if 'version-check' in p else {'id': tid(p), 'name': 'Same name'})
    listed = store.dispatch('installations')['items']
    chosen = next(row for row in listed if row['installationId'] == 'install-1')
    args = dict(installationId='install-1', recordDigest=chosen['recordDigest'], confirmed=True)
    assert store.dispatch('removeInstallationRecord', args)['removed']
    assert store.dispatch('removeInstallationRecord', args)['removed']  # safe retry
    assert [row['installationId'] for row in store.dispatch('installations')['items']] == ['another-scope']
    assert [row['installationId'] for row in store.dispatch('checkUpdates')['items']] == ['another-scope']
    assert path.read_bytes() == before
    assert (target / 'SKILL.md').read_text(encoding='utf-8') == 'my instructions'
    # A fresh install at the same location (even the same version) has a new
    # record identity and must reappear without losing other scope choices.
    rows['install-1']['created'] = 2
    worker.atomic_json(path, rows)
    assert {row['installationId'] for row in store.dispatch('installations')['items']} == {'install-1', 'another-scope'}
    with pytest.raises(worker.SquareError, match='변경'):
        store.dispatch('removeInstallationRecord', args)
    assert worker.read_json(path) == rows


def test_remove_requires_explicit_confirmation_and_validates_scope(configured):
    store, client, project, _ = configured
    seed(store, project)
    reader(client, lambda p: {'id': tid(p), 'name': 'Test'})
    row = store.dispatch('installations')['items'][0]
    args = dict(installationId=row['installationId'], recordDigest=row['recordDigest'])
    with pytest.raises(worker.SquareError): store.dispatch('removeInstallationRecord', args)
    with pytest.raises(worker.SquareError): store.dispatch('removeInstallationRecord', {**args, 'confirmed':True, 'installationId':'missing'})
    with pytest.raises(worker.SquareError): store.dispatch('removeInstallationRecord', {**args, 'confirmed':True, 'extra':'x'})
    assert len(store.dispatch('installations')['items']) == 1


def test_real_install_same_version_can_reappear_without_losing_ownership(configured):
    store, client, project, _ = configured
    reader(client, lambda p: {'id': tid(p), 'name': '실제 도구'})
    plan = store.dispatch('prepareInstall', dict(toolId=1, scope='project'))
    first = store.dispatch('install', dict(plan, confirmed=True))
    item = store.dispatch('installations')['items'][0]
    target = project / '.claude' / 'skills' / 'fixture-store' / 'SKILL.md'
    original = target.read_bytes()
    state_path = store.settings().state / 'installations.json'
    canonical_before = state_path.read_bytes()
    store.dispatch('removeInstallationRecord', dict(installationId=item['installationId'], recordDigest=item['recordDigest'], confirmed=True))
    assert store.dispatch('installations')['items'] == []
    assert target.read_bytes() == original and state_path.read_bytes() == canonical_before
    again = store.dispatch('prepareInstall', dict(toolId=1, scope='project'))
    assert again['canInstall'] is True
    second = store.dispatch('install', dict(again, confirmed=True))
    assert first['installationId'] == second['installationId']
    assert store.dispatch('installations')['items'][0]['release'] == 1
    assert target.read_bytes() == original


def test_interrupted_install_blocks_removing_its_list_record(configured, monkeypatch):
    store, client, project, _ = configured
    seed(store, project)
    reader(client, lambda p: {'id': tid(p), 'name': 'Test'})
    row = store.dispatch('installations')['items'][0]
    monkeypatch.setattr(worker.Installer, 'recover', lambda self: {'blocked': [{'toolId': 1}], 'recovered': []})
    with pytest.raises(worker.SquareError, match='중단된 설치'):
        store.dispatch('removeInstallationRecord', dict(installationId=row['installationId'], recordDigest=row['recordDigest'], confirmed=True))
    assert len(store.dispatch('installations')['items']) == 1


def version(tool_id, release=1, active=2, status='update_available', **extra):
    return dict(toolId=tool_id, installedRelease=release, activeRelease=active,
                status=status, updatePaused=False, **extra)


def reader(client, handler):
    calls = []
    guard = threading.Lock()
    def read(path):
        with guard:
            calls.append(path)
        return handler(path)
    client.read_installation_json = read
    return calls


def tid(path):
    return int(path.split('/')[3])


def test_legacy_names_are_authorized_deduplicated_cached_and_records_unchanged(configured):
    store, client, project, _ = configured
    records = seed(store, project)
    records['another-scope'] = dict(records['install-1'], scope='user')
    records['other-origin'] = dict(records['install-1'], toolId=2, origin='https://another.test')
    record_path = store.settings().state / 'installations.json'
    worker.atomic_json(record_path, records)
    before = record_path.read_bytes()
    def detail(path):
        # Would fail if metadata still held the common install lock.
        with worker.operation_lock(store.settings().state):
            return dict(id=1, name='공정 자료 정리', desc='짧은 설명', type='Skill',
                        platform='Claude', owner='담당자', registrantName='등록자', token='do-not-copy')
    calls = reader(client, detail)
    items = store.dispatch('installations')['items']
    assert len(items) == 2 and calls == ['/api/tools/1']
    assert all(row['name'] == '공정 자료 정리' and row['registrantName'] == '등록자' for row in items)
    assert all('token' not in row and row['metadataStatus'] == 'available' for row in items)
    assert record_path.read_bytes() == before
    client.read_installation_json = lambda path: pytest.fail('Cached names must work without network')
    assert all(row['metadataStatus'] == 'cached' for row in store.dispatch('installations')['items'])
    assert record_path.read_bytes() == before


def test_detail_snapshot_survives_install_update_and_rollback(configured):
    store, client, project, _ = configured
    original_manifest = client.manifest
    def manifest(tool_id):
        value = original_manifest(tool_id)
        value.pop('name')  # Current web manifests do not carry a title.
        return value
    client.manifest = manifest
    client.json = lambda path, *args: dict(id=1, name='실제 도구 이름', type='Skill', registrantName='이등록')
    store.dispatch('detail', {'toolId': 1})
    first_plan = store.dispatch('prepareInstall', dict(toolId=1, scope='project'))
    first = store.dispatch('install', dict(first_plan, confirmed=True))
    client.release = 2
    client.content = b'# Updated\n'
    plan = store.dispatch('prepareInstall', dict(toolId=1, scope='project'))
    store.dispatch('install', dict(plan, confirmed=True))
    store.dispatch('rollback', dict(installationId=first['installationId'], confirmed=True))
    client.read_installation_json = lambda path: pytest.fail('No new lookup after snapshot')
    row = store.dispatch('installations')['items'][0]
    assert row['name'] == '실제 도구 이름' and row['release'] == 1
    canonical = worker.read_json(store.settings().state / 'installations.json')[first['installationId']]
    assert 'name' not in canonical and 'registrantName' not in canonical
    assert store.dispatch('verify', dict(installationId=first['installationId']))['filesIntact']


def test_display_write_failure_does_not_fail_completed_install(configured, monkeypatch):
    store, client, _, _ = configured
    plan = store.dispatch('prepareInstall', dict(toolId=1, scope='project'))
    original = worker.atomic_json
    def save(path, value):
        if 'display-metadata' in str(path):
            raise PermissionError('Fixture denied display cache only')
        return original(path, value)
    monkeypatch.setattr(worker, 'atomic_json', save)
    result = store.dispatch('install', dict(plan, confirmed=True))
    assert result['installed']
    assert store.dispatch('verify', dict(installationId=result['installationId']))['filesIntact']


def test_bad_and_cross_origin_metadata_cache_are_ignored(configured):
    store, client, project, _ = configured
    seed(store, project)
    runtime = worker.Runtime(store.settings(), client, store.home)
    worker.atomic_json(store.display_path(runtime), dict(schemaVersion=1, origin='https://other.test',
        items={'1': {'name': 'Other server name', 'fetchedAt': worker.time.time()}}))
    calls = reader(client, lambda path: dict(id=2, name='Wrong ID', token='private'))
    result = store.dispatch('installations')['items'][0]
    assert 'name' not in result and result['metadataStatus'] == 'invalid_response'
    assert calls == ['/api/tools/1']
    # Error cooldown prevents repeated tab switches from requerying it.
    store.dispatch('installations')
    assert len(calls) == 1


def test_legacy_lookup_limit_progresses_on_next_refresh(configured):
    store, client, project, _ = configured
    seed(store, project, 15)
    calls = reader(client, lambda path: dict(id=tid(path), name=f'도구 {tid(path)}'))
    first = store.dispatch('installations')['items']
    assert len(calls) == 12 and sum(bool(row.get('name')) for row in first) == 12
    second = store.dispatch('installations')['items']
    assert len(calls) == 15 and all(row.get('name') for row in second)


def test_updates_first_resolves_legacy_available_name(configured):
    store, client, project, _ = configured
    seed(store, project)
    calls = reader(client, lambda path: version(1) if 'version-check' in path else dict(id=1, name='보고서 자동화'))
    row = store.dispatch('checkUpdates')['items'][0]
    assert row['name'] == '보고서 자동화' and row['updateAvailable']
    assert calls == ['/api/tools/1/version-check?release=1', '/api/tools/1']


def test_updates_only_newer_active_releases_are_actionable_and_reads_release_lock(configured):
    store, client, project, _ = configured
    rows = seed(store, project, 6)
    rows['install-3']['release'] = 3
    worker.atomic_json(store.settings().state / 'installations.json', rows)
    responses = {1: version(1), 2: version(2, active=1, status='current'),
                 3: version(3, release=3, active=2, status='rollback_available'),
                 4: version(4, status='unknown_release'), 5: dict(version(5), updatePaused=True),
                 6: version(6, active=1)}
    fixture_lock = threading.Lock()
    def read(path):
        # Serialize this assertion itself so the four fake HTTP reads don't
        # conflict with each other while proving the outer lock was released.
        with fixture_lock, worker.operation_lock(store.settings().state):
            return responses[tid(path)] if 'version-check' in path else dict(id=tid(path), name='Available tool')
    reader(client, read)
    response = store.dispatch('checkUpdates')
    assert [row['toolId'] for row in response['items'] if row['updateAvailable']] == [1]
    assert response['summary'] == dict(total=6, checked=5, available=1, current=1, attention=3, failed=1, pending=0, cached=0)
    assert not response['complete'] and not response['automaticallyUpdated']


@pytest.mark.parametrize('bad', [dict(toolId=99), dict(toolId=True), dict(installedRelease=2),
                               dict(activeRelease=True), dict(activeRelease='2'),
                               dict(updatePaused='false'), dict(status='newest'), dict(status={}),
                               dict(status=[]), dict(activeRelease=0)])
def test_malformed_version_identity_never_claims_update(configured, bad):
    store, client, project, _ = configured
    seed(store, project)
    reader(client, lambda path: dict(version(1), **bad))
    response = store.dispatch('checkUpdates')
    assert response['summary']['failed'] == 1 and not response['complete']
    assert response['items'][0]['updateStatus'] == 'invalid_response'
    assert not response['items'][0]['updateAvailable']


def test_partial_forbidden_deleted_results_do_not_hide_good_updates(configured):
    store, client, project, _ = configured
    seed(store, project, 4)
    def read(path):
        tool_id = tid(path)
        if tool_id in {2, 3}:
            raise worker.StoreReadError('forbidden' if tool_id == 2 else 'not_found')
        return version(tool_id) if 'version-check' in path else dict(id=tool_id, name=f'도구 {tool_id}')
    reader(client, read)
    response = store.dispatch('checkUpdates')
    assert response['summary']['available'] == 2 and response['summary']['attention'] == 2
    assert [row['updateStatus'] for row in response['items']] == ['update_available', 'forbidden', 'not_found', 'update_available']
    assert not response['complete']


@pytest.mark.parametrize('status', ['offline', 'auth_required'])
def test_connection_failure_is_one_short_batch_not_one_timeout_per_tool(configured, status):
    store, client, project, _ = configured
    seed(store, project, 40)
    def fail(path):
        raise worker.StoreReadError(status)
    calls = reader(client, fail)
    response = store.dispatch('checkUpdates')
    assert len(calls) == 4
    assert response['summary']['failed'] == 4 and response['summary']['pending'] == 36
    assert not response['complete'] and not any(row['updateAvailable'] for row in response['items'])


def test_update_limit_progresses_and_recent_results_are_explicitly_cached(configured):
    store, client, project, _ = configured
    seed(store, project, 40)
    calls = reader(client, lambda path: version(tid(path), active=1, status='current'))
    first = store.dispatch('checkUpdates')
    assert len(calls) == 32 and first['summary']['pending'] == 8
    calls.clear()
    second = store.dispatch('checkUpdates')
    assert {tid(path) for path in calls[:4]} == {33, 34, 35, 36}
    assert second['summary']['current'] == 40 and second['summary']['cached'] == 8
    assert second['complete']
    assert sum(row['fromCache'] for row in second['items']) == 8


def test_old_cached_result_never_masks_offline_or_counts_as_latest(configured, monkeypatch):
    store, client, project, _ = configured
    seed(store, project, 40)
    reader(client, lambda path: version(tid(path), active=1, status='current'))
    store.dispatch('checkUpdates')
    real_time = worker.time.time
    now = real_time()
    monkeypatch.setattr(worker.time, 'time', lambda: now + 90)
    def fail(path):
        raise worker.StoreReadError('offline')
    reader(client, fail)
    result = store.dispatch('checkUpdates')
    assert result['summary']['current'] == 0 and not result['complete']
    assert any(row['stale'] for row in result['items'])


def test_recovery_blocked_and_other_origin_are_never_update_candidates(configured, monkeypatch):
    store, client, project, _ = configured
    records = seed(store, project, 2)
    records['install-2']['origin'] = 'https://other.test'
    worker.atomic_json(store.settings().state / 'installations.json', records)
    monkeypatch.setattr(worker.Installer, 'recover', lambda self: {'blocked': [{'toolId': 1}], 'recovered': []})
    reader(client, lambda path: pytest.fail('Blocked/other origin must not be queried'))
    result = store.dispatch('checkUpdates')
    assert len(result['items']) == 1 and result['items'][0]['updateStatus'] == 'recovery_required'
    assert result['summary']['attention'] == 1 and not result['complete']


def test_any_interrupted_install_blocks_all_actions_like_the_canonical_installer(configured, monkeypatch):
    store, client, project, _ = configured
    seed(store, project, 2)
    monkeypatch.setattr(worker.Installer, 'recover', lambda self: {'blocked': [{'toolId': 1}], 'recovered': []})
    reader(client, lambda path: pytest.fail('Recovery must happen before any next install'))
    result = store.dispatch('checkUpdates')
    assert all(row['updateStatus'] == 'recovery_required' and not row['updateAvailable'] for row in result['items'])
    assert result['summary']['attention'] == 2


def test_cosmetic_cache_has_an_actual_byte_bound(configured):
    store, client, _, _ = configured
    runtime = worker.Runtime(store.settings(), client, store.home)
    rows = {str(i): dict(name='이름'*100, desc='설명'*600, type='Skill', fetchedAt=i, metadataStatus='available')
            for i in range(1, 513)}
    store.remember_display(runtime, rows)
    assert store.display_path(runtime).stat().st_size < 1024 * 1024
    assert 0 < len(store.display_cache(runtime)) < 512


@pytest.mark.parametrize(('code', 'status'), [(401, 'auth_required'), (403, 'forbidden'), (404, 'not_found'), (429, 'unavailable')])
def test_installation_reader_classifies_http_errors_without_raw_body(code, status):
    settings = type('Settings', (), {'url': 'https://fixture.test', 'token': lambda _: 'synthetic-key'})()
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == 'https://fixture.test/api/tools/4/version-check?release=1'
            assert request.method == 'GET' and timeout == 3
            raise HTTPError(request.full_url, code, 'synthetic-secret-body', {}, io.BytesIO(b'private'))
    client = worker.StoreClient(settings, Opener())
    with pytest.raises(worker.StoreReadError) as failure:
        client.read_installation_json('/api/tools/4/version-check?release=1')
    assert failure.value.status == status
    assert 'synthetic' not in str(failure.value) and 'private' not in str(failure.value)
    for path in ('https://other.test/api/tools/4', '/api/tools/4/view', '/api/tools/4?x=1', '/api/tools/4/manifest'):
        with pytest.raises(worker.SquareError):
            client.read_installation_json(path)
