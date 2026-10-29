"""Chat folder choices never open a native UI or grant an unconfirmed path."""
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import time

import pytest

PACKAGE = Path(__file__).parents[1] / 'integrations' / 'pt-square-mcp'
sys.path.insert(0, str(PACKAGE))
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
    def forbidden(*args, **kwargs):
        pytest.fail('Chat location selection must not spawn a native chooser')
    monkeypatch.setattr(jobs, '_launch', forbidden, raising=False)
    import subprocess
    class ForbiddenProcess(subprocess.Popen):
        def __init__(self, *args, **kwargs):
            forbidden(*args, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', ForbiddenProcess)
    candidate = {'path': str(project), 'name': 'Project', 'source': 'mcp-roots'}
    choices = {'options': [{'scope': 'user', 'path': str(home)}],
               'currentProject': candidate, 'projectCandidates': [candidate],
               'confirmationCandidates': [], 'rootsStatus': 'available'}
    return SimpleNamespace(config=config, home=home, downloads=downloads, project=project,
                           choices=choices, base=tmp_path)


def start(setup, purpose='install'):
    return jobs.start_selection(setup.config, purpose, setup.choices)


def submit(setup, request, selection='current', path='', confirmed=True):
    return jobs.submit_selection(setup.config, request['requestId'], selection,
                                 path=path, confirmed=confirmed)


def test_pending_returns_chat_choices_and_defaults_only_to_verified_project(setup):
    before = setup.config.read_bytes()
    first = start(setup)
    assert first['status'] == 'pending' and first['waitingForUser']
    assert first['selected'] is False and first['selectionMethod'] == 'chat'
    assert first['defaultSelection'] == 'current' and first['defaultPath'] == str(setup.project)
    assert {option['selection'] for option in first['options']} == {'user', 'current', 'other'}
    assert first['projectCandidates'][0]['path'] == str(setup.project)
    assert start(setup)['requestId'] == first['requestId']
    assert jobs.selection_status(setup.config, first['requestId'])['status'] == 'pending'
    assert setup.config.read_bytes() == before
    assert not (setup.project / '.claude').exists()


@pytest.mark.parametrize('confirmed', [False, None, 1, 'true', []])
def test_tool_argument_without_strict_confirmation_never_grants_path(setup, confirmed):
    request = start(setup)
    before = setup.config.read_bytes()
    try:
        result = submit(setup, request, 'other', str(setup.project), confirmed=confirmed)
    except SquareError:
        pass
    else:
        assert result['selected'] is False
    assert setup.config.read_bytes() == before
    assert setup.project not in Settings(setup.config).roots


def test_other_directory_granted_only_after_explicit_confirmed_path(setup, tmp_path):
    path = tmp_path / 'chosen folder'
    path.mkdir()
    request = start(setup)
    assert path not in Settings(setup.config).roots
    selected = submit(setup, request, 'other', str(path))
    assert selected['status'] == 'selected' and selected['path'] == str(path)
    assert selected['scope'] == 'project'
    assert Settings(setup.config).roots == [setup.downloads, path]
    assert Settings(setup.config).downloads == setup.downloads
    assert jobs.selection_status(setup.config, request['requestId']) == selected
    assert not (path / '.claude').exists()


@pytest.mark.parametrize('purpose,selection', [('install', 'other'), ('publish', 'current')])
def test_selection_record_write_failure_never_grants_and_pending_request_can_retry(setup, monkeypatch, purpose, selection):
    request = start(setup, purpose)
    before = setup.config.read_bytes()
    original = jobs.atomic_json
    writes = []
    def fail_record(path, value):
        writes.append(Path(path))
        if Path(path).name == 'record.json':
            raise OSError('fixture result disk failure')
        return original(path, value)
    monkeypatch.setattr(jobs, 'atomic_json', fail_record)
    with pytest.raises(OSError):
        submit(setup, request, selection, str(setup.project))
    assert setup.config.read_bytes() == before
    assert setup.project not in Settings(setup.config).roots
    assert setup.config not in writes
    monkeypatch.setattr(jobs, 'atomic_json', original)
    assert jobs.selection_status(setup.config, request['requestId'])['status'] == 'pending'
    assert start(setup, purpose)['requestId'] == request['requestId']
    result = submit(setup, request, selection, str(setup.project))
    assert result['selected'] is True
    assert Settings(setup.config).roots == [setup.downloads, setup.project]


@pytest.mark.parametrize('first_recovery', ['status', 'cancel', 'submit', 'start'])
def test_config_cutover_failure_does_not_report_a_grant_or_reuse_incomplete_result(setup, monkeypatch, first_recovery):
    request = start(setup, 'publish')
    before = setup.config.read_bytes()
    original = jobs.atomic_json
    writes = []
    def fail_config(path, value):
        writes.append(Path(path))
        if Path(path) == setup.config:
            raise OSError('fixture config disk failure')
        return original(path, value)
    monkeypatch.setattr(jobs, 'atomic_json', fail_config)
    with pytest.raises(OSError):
        submit(setup, request, 'current')
    assert setup.config.read_bytes() == before
    assert setup.project not in Settings(setup.config).roots
    assert [path.name for path in writes] == ['record.json', 'config.json']
    monkeypatch.setattr(jobs, 'atomic_json', original)
    if first_recovery == 'status':
        recovered = jobs.selection_status(setup.config, request['requestId'])
    elif first_recovery == 'cancel':
        recovered = jobs.cancel_selection(setup.config, request['requestId'])
    elif first_recovery == 'submit':
        recovered = submit(setup, request, 'current')
    else:
        fresh = start(setup, 'publish')
        assert fresh['requestId'] != request['requestId'] and not fresh['selected']
        recovered = jobs.selection_status(setup.config, request['requestId'])
    assert recovered['status'] == 'cancelled' and recovered['selected'] is False
    assert setup.project not in Settings(setup.config).roots
    fresh = start(setup, 'publish')
    assert fresh['requestId'] != request['requestId']
    assert start(setup, 'publish')['requestId'] == fresh['requestId']
    assert submit(setup, fresh, 'current')['selected'] is True
    assert Settings(setup.config).roots == [setup.downloads, setup.project]


def test_config_write_exception_after_atomic_cutover_recovers_exact_selected_result(setup, monkeypatch):
    request = start(setup, 'publish')
    original = jobs.atomic_json
    writes = []
    def lose_config_ack(path, value):
        writes.append(Path(path))
        original(path, value)
        if Path(path) == setup.config:
            raise OSError('fixture response lost after config cutover')
    monkeypatch.setattr(jobs, 'atomic_json', lose_config_ack)
    selected = submit(setup, request, 'current')
    assert selected['selected'] is True and selected['status'] == 'selected'
    assert [path.name for path in writes] == ['record.json', 'config.json']
    assert Settings(setup.config).roots == [setup.downloads, setup.project]
    monkeypatch.setattr(jobs, 'atomic_json', original)
    assert jobs.selection_status(setup.config, request['requestId']) == selected
    assert jobs.cancel_selection(setup.config, request['requestId']) == selected
    assert submit(setup, request, 'current') == selected


@pytest.mark.parametrize('selection,scope', [('user', 'user'), ('current', 'project')])
def test_install_common_and_verified_current_keep_trusted_roots_and_downloads(setup, selection, scope):
    before = setup.config.read_bytes()
    request = start(setup)
    selected = submit(setup, request, selection)
    assert selected['selected'] and selected['scope'] == scope
    assert selected['path'] == str(setup.home if selection == 'user' else setup.project)
    assert setup.config.read_bytes() == before
    assert Settings(setup.config).downloads == setup.downloads


def test_multiple_host_roots_require_exact_choice_without_default(setup, tmp_path):
    second = tmp_path / 'another project'
    second.mkdir()
    setup.choices['projectCandidates'].append(
        {'path': str(second), 'name': 'Second', 'source': 'mcp-roots'})
    setup.choices['currentProject'] = None
    request = start(setup)
    assert request.get('defaultSelection') != 'current'
    assert not request.get('defaultPath')
    assert len(request['projectCandidates']) == 2
    with pytest.raises(SquareError):
        submit(setup, request, 'current')
    assert setup.project not in Settings(setup.config).roots
    chosen = submit(setup, request, 'current', str(second))
    assert chosen['selected'] and chosen['path'] == str(second)
    assert Settings(setup.config).roots == [setup.downloads]


def test_no_host_root_never_guesses_project_from_python_cwd(setup, monkeypatch):
    setup.choices['currentProject'] = None
    setup.choices['projectCandidates'] = []
    monkeypatch.chdir(setup.project)
    request = start(setup)
    assert not request.get('defaultPath') and request.get('defaultSelection') != 'current'
    with pytest.raises(SquareError):
        submit(setup, request, 'current')
    assert Settings(setup.config).roots == [setup.downloads]
    assert submit(setup, request, 'user')['scope'] == 'user'


def test_unconfirmed_launch_candidate_is_displayed_without_automatic_authority(setup):
    candidate = {**setup.choices['projectCandidates'][0],
                 'source': 'launch-cwd-unconfirmed', 'requiresUserSelection': True}
    setup.choices['confirmationCandidates'] = [candidate]
    setup.choices['projectCandidates'] = []
    setup.choices['currentProject'] = None
    request = start(setup)
    assert request['confirmationCandidates'][0]['path'] == str(setup.project)
    assert request.get('defaultSelection') != 'current' and not request.get('defaultPath')
    assert Settings(setup.config).roots == [setup.downloads]
    chosen = submit(setup, request, 'other', str(setup.project))
    assert chosen['selected'] and Settings(setup.config).roots == [setup.downloads, setup.project]


@pytest.mark.parametrize('kind', ['unexpected-current', 'wrong-user', 'relative', 'drive',
                                 'missing', 'file', 'home', 'home-parent', 'downloads',
                                 'private-state', 'program', 'system'])
def test_invalid_or_overbroad_paths_never_expand_trust(setup, tmp_path, monkeypatch, kind):
    from pt_square_mcp.install_locations import PACKAGE_DIRECTORY
    selection, path = 'other', str(tmp_path / 'missing')
    if kind == 'unexpected-current':
        unexpected = tmp_path / 'not-listed-project'
        unexpected.mkdir()
        selection, path = 'current', str(unexpected)
    elif kind == 'wrong-user':
        selection, path = 'user', str(setup.project)
    elif kind == 'relative':
        path = 'relative'
    elif kind == 'drive':
        path = setup.project.anchor
    elif kind == 'file':
        file = tmp_path / 'plain.txt'
        file.write_text('fixture')
        path = str(file)
    elif kind == 'home':
        path = str(setup.home)
    elif kind == 'home-parent':
        path = str(setup.home.parent)
    elif kind == 'downloads':
        path = str(setup.downloads)
    elif kind == 'private-state':
        path = str(setup.config.parent)
    elif kind == 'program':
        path = str(PACKAGE_DIRECTORY)
    elif kind == 'system':
        system = tmp_path / 'system'
        system.mkdir()
        monkeypatch.setenv('ProgramFiles', str(system))
        path = str(system)
    request = start(setup)
    before = setup.config.read_bytes()
    if kind == 'unexpected-current':
        result = submit(setup, request, selection, path)
        assert result['status'] == 'failed' and not result['selected']
    else:
        with pytest.raises(SquareError):
            submit(setup, request, selection, path)
    assert setup.config.read_bytes() == before
    assert Settings(setup.config).downloads == setup.downloads


def test_changed_verified_directory_identity_is_rejected(setup, monkeypatch):
    request = start(setup)
    monkeypatch.setattr(jobs, '_identity', lambda path: [-1, -1])
    before = setup.config.read_bytes()
    result = submit(setup, request)
    assert not result['selected'] and result['status'] in {'failed', 'cancelled'}
    assert setup.config.read_bytes() == before


@pytest.mark.parametrize('change', ['origin', 'credential', 'trust'])
def test_connection_changes_cancel_pending_grant(setup, change):
    request = start(setup)
    data = read_json(setup.config)
    if change == 'origin':
        data['baseUrl'] = 'https://another.example'
    elif change == 'credential':
        data['credentialRef'] = 'windows-dpapi:credential.' + 'a' * 32 + '.dpapi.json'
    else:
        data['trustedRoots'].append(str(setup.home))
    atomic_json(setup.config, data)
    result = submit(setup, request, 'other', str(setup.project))
    assert result['status'] == 'cancelled' and not result['selected']
    assert setup.project not in Settings(setup.config).roots


def test_cancel_prevents_late_chat_confirmation_from_granting_folder(setup):
    before = setup.config.read_bytes()
    request = start(setup)
    assert jobs.cancel_selection(setup.config, request['requestId'])['status'] == 'cancelled'
    result = submit(setup, request, 'other', str(setup.project))
    assert result['status'] == 'cancelled' and not result['selected']
    assert setup.config.read_bytes() == before
    assert start(setup)['requestId'] != request['requestId']


def test_expired_choice_rejects_late_chat_confirmation(setup, monkeypatch):
    before = setup.config.read_bytes()
    now = time.time()
    request = start(setup)
    monkeypatch.setattr(jobs.time, 'time', lambda: now + jobs.LIFETIME_SECONDS + 1)
    result = submit(setup, request, 'other', str(setup.project))
    assert result['status'] == 'expired' and not result['selected']
    assert setup.config.read_bytes() == before


def test_old_native_result_file_cannot_grant_path_without_chat_confirmation(setup):
    before = setup.config.read_bytes()
    request = start(setup)
    directory = Settings(setup.config).state / 'workspace-selections' / request['requestId']
    atomic_json(directory / 'result.json', {
        'completedAt': time.time(), 'selected': True, 'selection': 'other',
        'scope': 'project', 'path': str(setup.project)})
    assert jobs.selection_status(setup.config, request['requestId'])['status'] == 'pending'
    assert setup.config.read_bytes() == before


def test_legacy_native_pending_job_is_cancelled_without_consuming_result(setup):
    request = start(setup)
    directory = Settings(setup.config).state / 'workspace-selections' / request['requestId']
    record = read_json(directory / 'record.json')
    record.pop('selectionMethod')
    atomic_json(directory / 'record.json', record)
    atomic_json(directory / 'result.json', {'completedAt': time.time(), 'selected': True,
                'selection': 'other', 'scope': 'project', 'path': str(setup.project)})
    before = setup.config.read_bytes()
    result = jobs.selection_status(setup.config, request['requestId'])
    assert result['status'] == 'cancelled' and not result['selected']
    assert setup.config.read_bytes() == before
    assert start(setup)['requestId'] != request['requestId']


def test_publish_folder_requires_confirmation_and_does_not_install(setup):
    before = setup.config.read_bytes()
    request = start(setup, 'publish')
    assert setup.config.read_bytes() == before
    with pytest.raises(SquareError):
        submit(setup, request, 'user')
    chosen = submit(setup, request, 'current')
    assert chosen['purpose'] == 'publish' and chosen['scope'] == 'project'
    assert Settings(setup.config).roots == [setup.downloads, setup.project]
    assert Settings(setup.config).downloads == setup.downloads
    assert not (setup.project / '.claude').exists()


def test_completed_choice_cannot_be_reused_to_grant_another_path(setup, tmp_path):
    other = tmp_path / 'second choice'
    other.mkdir()
    request = start(setup)
    original = submit(setup, request, 'other', str(setup.project))
    assert submit(setup, request, 'other', str(other)) == original
    assert other not in Settings(setup.config).roots


def test_unknown_request_and_path_traversal_never_read_arbitrary_files(setup):
    with pytest.raises(SquareError):
        jobs.start_selection(setup.config, 'unknown')
    for request_id in ('../config', 'f' * 32):
        with pytest.raises(SquareError):
            jobs.selection_status(setup.config, request_id)
        with pytest.raises(SquareError):
            jobs.cancel_selection(setup.config, request_id)
        with pytest.raises(SquareError):
            jobs.submit_selection(setup.config, request_id, 'other',
                                  path=str(setup.project), confirmed=True)
    assert setup.project not in Settings(setup.config).roots


class ChatContext:
    def __init__(self, roots=(), *, capability='form', action='accept', selection='current', path='', hook=None):
        self.roots = list(roots)
        self.action, self.selection, self.path, self.hook = action, selection, path, hook
        self.prompts = []
        capability = {'form': SimpleNamespace(form=object(), url=None),
                      'url': SimpleNamespace(form=None, url=object()), 'none': None}[capability]
        self.session = SimpleNamespace(
            client_params=SimpleNamespace(capabilities=SimpleNamespace(roots=object(), elicitation=capability)),
            list_roots=self.list_roots)

    async def list_roots(self):
        return SimpleNamespace(roots=[SimpleNamespace(uri=path.as_uri(), name=path.name) for path in self.roots])

    async def elicit(self, message, schema):
        document = schema.model_json_schema()
        self.prompts.append(document)
        assert set(document['properties']) == {'selection', 'path'}
        if self.hook:
            result = self.hook()
            if hasattr(result, '__await__'):
                await result
        if self.action != 'accept':
            return SimpleNamespace(action=self.action, data=None)
        label = {'user': '공통 (내 계정)', 'other': '기타 경로'}.get(self.selection)
        if label is None:
            label = ('현재 프로젝트 · ' + self.path if self.path else
                     document['properties']['selection']['default'])
        return SimpleNamespace(action='accept', data=schema(selection=label, path=self.path))


def chat_tool(setup, monkeypatch):
    pytest.importorskip('mcp')
    from pt_square_mcp.server import make_server
    # An unrelated real checkout cwd must never enter this isolated test.
    monkeypatch.chdir(setup.base)
    return make_server(setup.config)._tool_manager.get_tool('select_workspace').fn


@pytest.mark.parametrize('purpose', ['install', 'publish'])
@pytest.mark.parametrize('capability', ['form', 'none', 'url'])
def test_server_always_asks_in_chat_before_granting_current(setup, monkeypatch, purpose, capability):
    fn = chat_tool(setup, monkeypatch)
    ctx = ChatContext([setup.project], capability=capability, action='cancel')
    before = setup.config.read_bytes()
    pending = asyncio.run(fn(ctx, purpose=purpose))
    assert pending['status'] == 'pending' and pending['defaultPath'] == str(setup.project)
    assert not ctx.prompts and setup.config.read_bytes() == before
    unconfirmed = asyncio.run(fn(ctx, purpose=purpose, request_id=pending['requestId'],
                                 selection='current', path=str(setup.project)))
    assert unconfirmed['confirmationRequired'] and setup.config.read_bytes() == before
    result = asyncio.run(fn(ctx, purpose=purpose, request_id=pending['requestId'],
                            selection='current', path=str(setup.project), confirmed=True))
    assert result['selected'] and result['path'] == str(setup.project)
    assert not ctx.prompts
    assert (setup.project in Settings(setup.config).roots) == (purpose == 'publish')


def test_multiple_projects_choose_only_confirmed_candidate(setup, monkeypatch, tmp_path):
    second = tmp_path / 'second'
    second.mkdir()
    fn = chat_tool(setup, monkeypatch)
    ctx = ChatContext([setup.project, second])
    pending = asyncio.run(fn(ctx, purpose='publish'))
    assert not pending['defaultPath'] and len(pending['projectCandidates']) == 2
    result = asyncio.run(fn(ctx, purpose='publish', request_id=pending['requestId'],
                            selection='current', path=str(second), confirmed=True))
    assert result['selected'] and result['path'] == str(second)
    assert second in Settings(setup.config).roots and setup.project not in Settings(setup.config).roots
    assert not ctx.prompts


def test_missing_host_root_can_only_grant_explicit_other_path(setup, monkeypatch):
    fn = chat_tool(setup, monkeypatch)
    ctx = ChatContext([])
    before = setup.config.read_bytes()
    pending = asyncio.run(fn(ctx, purpose='publish'))
    assert not pending['defaultPath'] and not ctx.prompts
    with pytest.raises(SquareError, match='프로젝트가 바뀌었습니다'):
        asyncio.run(fn(ctx, purpose='publish', request_id=pending['requestId'],
                       selection='current', path=str(setup.project), confirmed=True))
    assert setup.config.read_bytes() == before
    fresh = asyncio.run(fn(ctx, purpose='publish'))
    selected = asyncio.run(fn(ctx, purpose='publish', request_id=fresh['requestId'],
                              selection='other', path=str(setup.project), confirmed=True))
    assert selected['selected'] and setup.project in Settings(setup.config).roots


def test_changed_host_roots_reject_current_without_grant(setup, monkeypatch):
    fn = chat_tool(setup, monkeypatch)
    ctx = ChatContext([setup.project])
    pending = asyncio.run(fn(ctx, purpose='publish'))
    before = setup.config.read_bytes()
    ctx.roots.clear()
    with pytest.raises(SquareError, match='프로젝트가 바뀌었습니다'):
        asyncio.run(fn(ctx, purpose='publish', request_id=pending['requestId'],
                       selection='current', path=str(setup.project), confirmed=True))
    assert setup.config.read_bytes() == before


def test_connection_change_between_chat_calls_cancels_without_grant(setup, monkeypatch):
    fn = chat_tool(setup, monkeypatch)
    ctx = ChatContext([setup.project])
    pending = asyncio.run(fn(ctx, purpose='publish'))
    data = read_json(setup.config)
    data['baseUrl'] = 'https://changed.example'
    atomic_json(setup.config, data)
    result = asyncio.run(fn(ctx, purpose='publish', request_id=pending['requestId'],
                            selection='current', path=str(setup.project), confirmed=True))
    assert result['status'] == 'cancelled'
    assert Settings(setup.config).url == 'https://changed.example'
    assert setup.project not in Settings(setup.config).roots


def test_server_connection_changed_during_root_discovery_cannot_create_selection(setup, monkeypatch):
    fn = chat_tool(setup, monkeypatch)
    ctx = ChatContext([setup.project])
    original = ctx.session.list_roots
    async def changing_roots():
        data = read_json(setup.config)
        data['baseUrl'] = 'https://new-origin.example'
        atomic_json(setup.config, data)
        return await original()
    ctx.session.list_roots = changing_roots
    with pytest.raises(SquareError, match='연결 설정이 바뀌었습니다'):
        asyncio.run(fn(ctx, purpose='publish'))
    assert Settings(setup.config).url == 'https://new-origin.example'
    assert Settings(setup.config).roots == [setup.downloads]
    assert not ctx.prompts
    assert not (Settings(setup.config).state / 'workspace-selections' / 'publish.json').exists()


def test_explicit_cancel_remains_cancelled_and_cannot_be_reused(setup, monkeypatch):
    fn = chat_tool(setup, monkeypatch)
    ctx = ChatContext([setup.project], action='cancel')
    before = setup.config.read_bytes()
    pending = asyncio.run(fn(ctx, purpose='publish'))
    cancelled = jobs.cancel_selection(setup.config, pending['requestId'])
    assert cancelled['status'] == 'cancelled'
    result = asyncio.run(fn(ctx, purpose='publish', request_id=pending['requestId'],
                            selection='current', path=str(setup.project), confirmed=True))
    assert result['status'] == 'cancelled' and setup.config.read_bytes() == before
    assert 'request_id 없이' in result['guidance']
    fresh = asyncio.run(fn(ctx, purpose='publish'))
    assert fresh['status'] == 'pending' and fresh['requestId'] != pending['requestId']


STDIO_CHAT_FOLDER = '''import subprocess, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from pt_square_mcp.server import make_server
config_path, home = map(Path, sys.argv[2:4])
Path.home = classmethod(lambda cls: home)
def no_native(*args, **kwargs):
    raise AssertionError('Chat folder selection must not start a native process')
subprocess.Popen = no_native
make_server(config_path).run(transport='stdio')
'''


@pytest.mark.parametrize('action', ['accept', 'cancel'])
def test_actual_sdk_stdio_ignores_host_elicitation_and_uses_explicit_chat(tmp_path, monkeypatch, action):
    pytest.importorskip('mcp')
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import ElicitResult, ListRootsResult, Root
    home = tmp_path / 'isolated-home'
    downloads = home / 'AI_SQUARE' / 'downloads'
    downloads.mkdir(parents=True)
    project = tmp_path / 'host project'
    project.mkdir()
    config_path = tmp_path / 'private' / 'config.json'
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    save_config(config_path, 'https://fixture-square.example.test', [downloads], download_directory=downloads)
    before = config_path.read_bytes()
    script = tmp_path / 'stdio_chat_folder.py'
    script.write_text(STDIO_CHAT_FOLDER, encoding='utf-8')
    prompts = []
    async def roots(_ctx):
        return ListRootsResult(roots=[Root(uri=project.as_uri(), name='Current project')])
    async def confirm(_ctx, request):
        prompts.append(request)
        return ElicitResult(action=action)
    async def scenario():
        environment = {k: v for k, v in os.environ.items() if k != 'PTAI_API_TOKEN'}
        params = StdioServerParameters(command=sys.executable,
            args=['-X', 'utf8', '-B', str(script), str(PACKAGE), str(config_path), str(home)],
            cwd=str(tmp_path), env=environment)
        with (tmp_path / 'stdio-errors.txt').open('w', encoding='utf-8') as errors:
            async with stdio_client(params, errlog=errors) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=15),
                                         list_roots_callback=roots, elicitation_callback=confirm) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    tool = next(row for row in listing.tools if row.name == 'select_workspace')
                    assert set(tool.inputSchema['properties']) == {'purpose', 'request_id', 'selection', 'path', 'confirmed'}
                    response = await session.call_tool('select_workspace', {'purpose': 'publish'})
                    assert not response.isError, response.content
                    pending = json.loads(response.content[0].text)
                    assert pending['status'] == 'pending' and not pending['selected']
                    assert pending['defaultPath'] == str(project)
                    assert config_path.read_bytes() == before
                    result = await session.call_tool('select_workspace', {
                        'purpose': 'publish', 'request_id': pending['requestId'],
                        'selection': 'current', 'path': str(project), 'confirmed': True})
                    assert not result.isError, result.content
                    assert json.loads(result.content[0].text)['selected']
    asyncio.run(scenario())
    assert not prompts
    assert Settings(config_path).roots == [downloads, project]
    assert not (project / '.claude').exists()
