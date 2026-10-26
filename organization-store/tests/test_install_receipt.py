"""Installation status can reconcile only the exact committed local plan."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_worker import configured, worker


PLAN_ID = '0123456789abcdef0123456789abcdef'


@pytest.mark.parametrize('status', ['installed', 'configured'])
def test_items_expose_committed_plan_without_backup_path_or_record_mutation(configured, status):
    store, client, project, _ = configured
    settings = store.settings()
    record = dict(origin=settings.url, toolId=1, release=2, scope='project',
                  scopeDir=str(project), target=str(project / 'tool'), status=status,
                  created=1, backup=str(settings.state / 'backups' / PLAN_ID))
    path = settings.state / 'installations.json'
    worker.atomic_json(path, {'owned': record, 'other-origin': dict(record, origin='https://other.test')})
    before = path.read_bytes()
    response = store.dispatch('installations')
    assert len(response['items']) == 1
    item = response['items'][0]
    assert item['completedPlanId'] == PLAN_ID
    assert item['status'] == status and item['toolId'] == 1 and item['release'] == 2
    assert 'backup' not in item and 'previous' not in item
    assert path.read_bytes() == before


@pytest.mark.parametrize('name', [None, '', 'a' * 31, 'a' * 33, 'A' * 32, 'g' * 32, 'plan.json'])
def test_malformed_backup_names_never_become_receipts(tmp_path, name):
    runtime = SimpleNamespace(settings=SimpleNamespace(state=tmp_path / 'state'))
    backup = str(runtime.settings.state / 'backups' / name) if name is not None else None
    assert worker.Store.completed_plan_id(runtime, {'status': 'installed', 'backup': backup}) is None


@pytest.mark.parametrize('value', [42, [], {}, True])
def test_non_path_backup_never_becomes_receipt(tmp_path, value):
    runtime = SimpleNamespace(settings=SimpleNamespace(state=tmp_path / 'state'))
    assert worker.Store.completed_plan_id(runtime, {'status': 'installed', 'backup': value}) is None


@pytest.mark.parametrize('status', ['ready-to-launch', 'launched', 'verified-file', 'failed', None])
def test_only_committed_skill_or_mcp_states_expose_receipts(tmp_path, status):
    runtime = SimpleNamespace(settings=SimpleNamespace(state=tmp_path / 'state'))
    record = {'status': status, 'backup': str(runtime.settings.state / 'backups' / PLAN_ID)}
    assert worker.Store.completed_plan_id(runtime, record) is None


@pytest.mark.parametrize('location', ['outside', 'nested', 'traversal', 'relative'])
def test_wrong_parent_is_rejected_before_resolving_any_record_path(tmp_path, monkeypatch, location):
    runtime = SimpleNamespace(settings=SimpleNamespace(state=tmp_path / 'state'))
    root = runtime.settings.state
    paths = {'outside': tmp_path / 'elsewhere' / PLAN_ID,
             'nested': root / 'backups' / 'child' / PLAN_ID,
             'traversal': root / 'backups' / '..' / 'backups' / PLAN_ID,
             'relative': Path('backups') / PLAN_ID}
    monkeypatch.setattr(worker, 'no_links', lambda path: pytest.fail('Untrusted parent must not be resolved'))
    assert worker.Store.completed_plan_id(runtime, {'status': 'installed', 'backup': str(paths[location])}) is None


def test_preparing_new_plan_does_not_relabel_old_install_and_rollback_restores_original_receipt(configured):
    store, client, _, _ = configured
    first_plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    first = store.dispatch('install', dict(first_plan, confirmed=True))
    assert store.dispatch('installations')['items'][0]['completedPlanId'] == first_plan['planId']

    client.release = 2
    client.content = b'---\nname: fixture-store\ndescription: Updated fixture\n---\n# Two\n'
    next_plan = store.dispatch('prepareInstall', {'toolId': 1, 'scope': 'project'})
    prior = store.dispatch('installations')['items'][0]
    assert prior['completedPlanId'] == first_plan['planId'] != next_plan['planId']
    assert prior['release'] == 1
    store.dispatch('install', dict(next_plan, confirmed=True))
    current = store.dispatch('installations')['items'][0]
    assert current['completedPlanId'] == next_plan['planId'] and current['release'] == 2

    store.dispatch('rollback', {'installationId': first['installationId'], 'confirmed': True})
    restored = store.dispatch('installations')['items'][0]
    assert restored['completedPlanId'] == first_plan['planId'] and restored['release'] == 1


def test_live_install_lock_does_not_return_a_false_empty_receipt_list(configured):
    store, _, _, _ = configured
    with worker.operation_lock(store.settings().state):
        with pytest.raises(worker.SquareError, match='로컬 작업을 처리 중'):
            store.dispatch('installations')
