"""Native choice jobs respond immediately and grant only completed user choices."""
from pathlib import Path
from types import SimpleNamespace
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'integrations' / 'pt-square-mcp'))
from pt_square_mcp import workspace_selection as jobs
from pt_square_mcp.config import Settings, SquareError, atomic_json, read_json, save_config


@pytest.fixture
def setup(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    downloads = home / 'AI_SQUARE' / 'downloads'
    downloads.mkdir(parents=True)
    project = tmp_path / 'project with spaces'
    project.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    config = tmp_path / 'private' / 'config.json'
    save_config(config, 'https://company.example', [downloads], download_directory=downloads)
    launches = []
    child = SimpleNamespace(poll=lambda: None)
    def launch(path):
        launches.append(path)
        return child
    monkeypatch.setattr(jobs, '_launch', launch)
    monkeypatch.setattr(jobs, '_children', {})
    candidate = {'path': str(project), 'name': 'Project', 'source': 'mcp-roots'}
    choices = {'options': [{'scope': 'user', 'path': str(home)}],
               'currentProject': candidate, 'projectCandidates': [candidate]}
    return SimpleNamespace(config=config, home=home, downloads=downloads, project=project,
                           choices=choices, launches=launches, child=child)


def start(setup, purpose='install'):
    return jobs.start_selection(setup.config, purpose, setup.choices if purpose == 'install' else None)


def complete(setup, result):
    atomic_json(setup.launches[-1].with_name('result.json'), dict(completedAt=time.time(), **result))


def test_pending_is_immediate_and_repeated_open_reuses_window(setup):
    before = setup.config.read_bytes()
    first = start(setup)
    assert first['status'] == 'pending' and first['waitingForUser']
    assert first['nextTool'] == 'get_workspace_selection'
    assert first['pollAfterSeconds'] >= 3
    assert start(setup)['requestId'] == first['requestId']
    assert jobs.selection_status(setup.config, first['requestId'])['status'] == 'pending'
    assert len(setup.launches) == 1
    assert setup.config.read_bytes() == before
    assert not (setup.project / '.claude').exists()
    content = setup.launches[0].read_text(encoding='utf-8')
    assert 'credential' not in content and 'company.example' not in content


def test_custom_directory_only_granted_after_completed_selection(setup, tmp_path):
    path = tmp_path / 'chosen folder'
    path.mkdir()
    result = start(setup)
    assert path not in Settings(setup.config).roots
    complete(setup, dict(selected=True, selection='other', scope='project', path=str(path)))
    selected = jobs.selection_status(setup.config, result['requestId'])
    assert selected['status'] == 'selected' and selected['path'] == str(path)
    assert Settings(setup.config).roots == [setup.downloads, path]
    assert jobs.selection_status(setup.config, result['requestId']) == selected
    assert not (path / '.claude').exists()


@pytest.mark.parametrize('selection,scope', [('user', 'user'), ('current', 'project')])
def test_common_and_current_do_not_permanently_expand_trust(setup, selection, scope):
    before = setup.config.read_bytes()
    result = start(setup)
    path = setup.home if selection == 'user' else setup.project
    complete(setup, dict(selected=True, selection=selection, scope=scope, path=str(path)))
    selected = jobs.selection_status(setup.config, result['requestId'])
    assert selected['selected'] and selected['scope'] == scope
    assert setup.config.read_bytes() == before


@pytest.mark.parametrize('kind', ['unexpected_current', 'wrong_user', 'relative', 'drive', 'missing'])
def test_unverified_selection_never_expands_trust(setup, tmp_path, kind):
    before = setup.config.read_bytes()
    result = start(setup)
    selection, scope, path = 'other', 'project', str(tmp_path / 'missing')
    if kind == 'unexpected_current':
        selection, path = 'current', str(tmp_path)
    if kind == 'wrong_user':
        selection, scope, path = 'user', 'user', str(setup.project)
    if kind == 'relative':
        path = 'relative'
    if kind == 'drive':
        path = setup.project.anchor
    complete(setup, dict(selected=True, selection=selection, scope=scope, path=path))
    assert jobs.selection_status(setup.config, result['requestId'])['status'] == 'failed'
    assert setup.config.read_bytes() == before


def test_changed_project_directory_identity_is_rejected(setup, monkeypatch):
    result = start(setup)
    complete(setup, dict(selected=True, selection='current', scope='project', path=str(setup.project)))
    monkeypatch.setattr(jobs, '_identity', lambda path: [-1, -1])
    assert jobs.selection_status(setup.config, result['requestId'])['status'] == 'failed'


def test_untrusted_start_folder_requires_explicit_ui_confirmation_before_grant(setup):
    setup.choices['confirmationCandidates'] = setup.choices['projectCandidates']
    setup.choices['projectCandidates'] = []
    setup.choices['currentProject'] = None
    result = start(setup)
    assert Settings(setup.config).roots == [setup.downloads]
    complete(setup, dict(selected=True, selection='confirmed-current', scope='project', path=str(setup.project)))
    assert jobs.selection_status(setup.config, result['requestId'])['status'] == 'selected'
    assert Settings(setup.config).roots == [setup.downloads, setup.project]


def test_confirmation_cannot_grant_an_unlisted_start_folder(setup):
    result = start(setup)
    complete(setup, dict(selected=True, selection='confirmed-current', scope='project', path=str(setup.project)))
    assert jobs.selection_status(setup.config, result['requestId'])['status'] == 'failed'
    assert Settings(setup.config).roots == [setup.downloads]


@pytest.mark.parametrize('change', ['origin', 'credential', 'trust'])
def test_connection_changes_cancel_pending_grant(setup, change):
    result = start(setup)
    data = read_json(setup.config)
    if change == 'origin':
        data['baseUrl'] = 'https://another.example'
    elif change == 'credential':
        data['credentialRef'] = 'windows-dpapi:credential.' + 'a' * 32 + '.dpapi.json'
    else:
        data['trustedRoots'].append(str(setup.home))
    atomic_json(setup.config, data)
    complete(setup, dict(selected=True, selection='other', scope='project', path=str(setup.project)))
    assert jobs.selection_status(setup.config, result['requestId'])['status'] == 'cancelled'
    assert setup.project not in Settings(setup.config).roots


def test_cancel_prevents_late_result_from_granting_folder(setup):
    before = setup.config.read_bytes()
    result = start(setup)
    assert jobs.cancel_selection(setup.config, result['requestId'])['status'] == 'cancelled'
    assert setup.launches[0].with_name('cancel.marker').exists()
    complete(setup, dict(selected=True, selection='other', scope='project', path=str(setup.project)))
    assert jobs.selection_status(setup.config, result['requestId'])['status'] == 'cancelled'
    assert setup.config.read_bytes() == before
    assert start(setup)['requestId'] != result['requestId']


def test_ui_cancel_does_not_change_roots(setup):
    result = start(setup)
    complete(setup, dict(selected=False))
    assert jobs.selection_status(setup.config, result['requestId'])['status'] == 'cancelled'
    assert Settings(setup.config).roots == [setup.downloads]


def test_expired_window_has_finite_wait_and_rejects_late_result(setup, monkeypatch):
    before = setup.config.read_bytes()
    result = start(setup)
    request = read_json(setup.launches[0])
    monkeypatch.setattr(jobs.time, 'time', lambda: request['expiresAt'] + 1)
    complete(setup, dict(selected=True, selection='other', scope='project', path=str(setup.project)))
    assert jobs.selection_status(setup.config, result['requestId'])['status'] == 'expired'
    assert setup.config.read_bytes() == before


def test_completed_in_time_survives_delayed_status_read(setup, monkeypatch):
    result = start(setup)
    complete(setup, dict(selected=True, selection='current', scope='project', path=str(setup.project)))
    request = read_json(setup.launches[0])
    monkeypatch.setattr(jobs.time, 'time', lambda: request['expiresAt'] + 30)
    assert jobs.selection_status(setup.config, result['requestId'])['status'] == 'selected'


def test_exit_without_result_and_launch_error_are_reported(setup, monkeypatch):
    result = start(setup)
    setup.child.poll = lambda: 1
    assert jobs.selection_status(setup.config, result['requestId'])['status'] == 'failed'
    def fail(_):
        raise OSError('sensitive contents must not be returned')
    monkeypatch.setattr(jobs, '_launch', fail)
    result = start(setup)
    assert result['status'] == 'failed'
    assert 'sensitive' not in str(result)


def test_publish_selection_uses_same_nonblocking_path(setup):
    result = start(setup, 'publish')
    assert read_json(setup.launches[0])['locations'] == {}
    complete(setup, dict(selected=True, selection='other', scope='project', path=str(setup.project)))
    assert jobs.selection_status(setup.config, result['requestId'])['purpose'] == 'publish'
    assert Settings(setup.config).roots == [setup.downloads, setup.project]


def test_unknown_request_and_path_traversal_do_not_open_or_read_arbitrary_files(setup):
    with pytest.raises(SquareError):
        jobs.start_selection(setup.config, 'unknown')
    with pytest.raises(SquareError):
        jobs.selection_status(setup.config, '../config')
    with pytest.raises(SquareError):
        jobs.cancel_selection(setup.config, '../config')
    with pytest.raises(SquareError):
        jobs.selection_status(setup.config, 'f' * 32)
    assert not setup.launches


def test_launcher_hides_console_and_does_not_forward_key_environment(tmp_path, monkeypatch):
    # Exercise the real launcher separately from the setup fixture replacement.
    seen = []
    monkeypatch.setenv('PTAI_API_TOKEN', 'test-only-secret')
    monkeypatch.setattr(jobs.subprocess, 'Popen', lambda *a, **k: seen.append((a, k)))
    jobs._launch(tmp_path / 'request.json')
    args, kwargs = seen[0]
    assert 'test-only-secret' not in str(args)
    assert 'PTAI_API_TOKEN' not in kwargs['env']
    assert kwargs['stdin'] == kwargs['stdout'] == kwargs['stderr'] == jobs.subprocess.DEVNULL
    assert 'workspace_ui' in ' '.join(args[0])
