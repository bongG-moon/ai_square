"""Host-root discovery and temporary install permissions, using test-owned folders."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from .test_local_mcp import FakeClient, Installer, Settings, SquareError, settings
from pt_square_mcp.install_locations import (
    MAX_HOST_ROOTS, PACKAGE_DIRECTORY, discover_locations, project_path, project_roots,
)


def context(roots=(), *, supported=True, fail=False, delay=0):
    calls = []
    async def list_roots():
        calls.append(True)
        if delay:
            await asyncio.sleep(delay)
        if fail:
            raise RuntimeError('private host diagnostic not for output')
        return SimpleNamespace(roots=[SimpleNamespace(uri=value, name='Project') for value in roots])
    session = SimpleNamespace(
        client_params=SimpleNamespace(capabilities=SimpleNamespace(roots=object() if supported else None)),
        list_roots=list_roots,
    )
    return SimpleNamespace(session=session), calls


def discover(settings, ctx, **kwargs):
    return asyncio.run(discover_locations(settings, ctx, **kwargs))


def test_single_host_root_is_current_project_without_persistent_permission(settings, tmp_path):
    host = tmp_path / '호스트 현재 프로젝트'
    host.mkdir()
    before = settings.path.read_bytes()
    ctx, calls = context([host.as_uri(), host.as_uri()])
    locations = discover(settings, ctx)
    assert calls == [True]
    assert locations['rootsStatus'] == 'available'
    assert locations['currentProject'] == {'path': str(host), 'name': 'Project', 'source': 'mcp-roots'}
    assert project_path(locations) == str(host)
    assert project_roots(locations) == (host,)
    assert not locations['requiresProjectSelection']
    assert [option['scope'] for option in locations['options']] == ['user', 'project', 'other']
    assert settings.path.read_bytes() == before
    assert host not in Settings(settings.path).roots


def test_multiple_host_roots_do_not_guess_even_with_known_launch_cwd(settings, tmp_path):
    second = tmp_path / 'second-project'
    second.mkdir()
    ctx, _ = context([settings.roots[0].as_uri(), second.as_uri()])
    locations = discover(settings, ctx, launch_cwd=settings.roots[0])
    assert locations['currentProject'] is None and locations['requiresProjectSelection']
    assert len(locations['projectCandidates']) == 2
    with pytest.raises(SquareError, match='여러 개'):
        project_path(locations)
    assert project_path(locations, str(second)) == str(second)


@pytest.mark.parametrize('reason', ['unsupported', 'timeout', 'unavailable', 'empty'])
def test_roots_failure_is_bounded_and_falls_back_only_to_trusted_launch_cwd(settings, reason):
    ctx, calls = context(supported=reason != 'unsupported', fail=reason == 'unavailable',
                         delay=0.1 if reason == 'timeout' else 0)
    locations = discover(settings, ctx, launch_cwd=settings.roots[0], timeout=0.01)
    assert locations['rootsStatus'] == reason
    assert locations['currentProject']['source'] == 'launch-cwd'
    assert locations['currentProject']['path'] == str(settings.roots[0])
    assert 'private host diagnostic' not in str(locations)
    assert bool(calls) == (reason != 'unsupported')


def test_untrusted_cwd_is_not_granted_or_used_as_current_project(settings, tmp_path):
    elsewhere = tmp_path / 'not-authorized'
    elsewhere.mkdir()
    ctx, _ = context(supported=False)
    result = discover(settings, ctx, launch_cwd=elsewhere)
    assert result['currentProject'] is None
    assert result['projectCandidates'] == []
    assert result['confirmationCandidates'] == [{'path': str(elsewhere), 'name': elsewhere.name,
        'source': 'launch-cwd-unconfirmed', 'requiresUserSelection': True}]
    assert project_roots(result) == ()
    with pytest.raises(SquareError, match='시작 폴더 후보'):
        project_path(result)
    assert elsewhere not in Settings(settings.path).roots


@pytest.mark.parametrize('kind', ['home', 'drive', 'downloads', 'state', 'program', 'missing', 'file'])
def test_unsafe_or_non_project_host_roots_are_ignored(settings, tmp_path, kind):
    settings.downloads.mkdir(parents=True, exist_ok=True)
    settings.state.mkdir(parents=True, exist_ok=True)
    file = tmp_path / 'ordinary.txt'
    file.write_text('data')
    path = {'home': Path.home(), 'drive': Path(tmp_path.anchor), 'downloads': settings.downloads,
            'state': settings.state, 'program': PACKAGE_DIRECTORY, 'missing': tmp_path / 'missing',
            'file': file}[kind]
    ctx, _ = context([path.as_uri()])
    assert discover(settings, ctx)['projectCandidates'] == []


@pytest.mark.parametrize('uri', [
    'https://host.example/project', 'file://remote-server/share', 'file:////remote/share',
    'file:///path?query=x', 'file:///path#fragment', 'file:///path%00bad',
    'file:relative', 'file:///C:\\project', '',
    'file:///path%ZZbad', ' file:///path',
])
def test_malformed_or_remote_root_uris_are_not_authority(settings, uri):
    ctx, _ = context([uri])
    assert discover(settings, ctx)['projectCandidates'] == []


def test_excessive_root_response_does_not_pick_first_entry(settings):
    ctx, _ = context([settings.roots[0].as_uri()] * (MAX_HOST_ROOTS + 1))
    result = discover(settings, ctx)
    assert result['currentProject'] is None and result['rootsStatus'] == 'unavailable'


@pytest.mark.parametrize('variable', ['SystemRoot', 'WINDIR', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramData'])
def test_system_launch_directory_is_not_even_an_unconfirmed_candidate(settings, tmp_path, monkeypatch, variable):
    system = tmp_path / 'system-files'
    child = system / 'some-app'
    child.mkdir(parents=True)
    monkeypatch.setenv(variable, str(system))
    ctx, _ = context(supported=False)
    locations = discover(settings, ctx, launch_cwd=child)
    assert locations['currentProject'] is None
    assert locations['projectCandidates'] == locations['confirmationCandidates'] == []
    ctx, _ = context([child.as_uri()])
    assert discover(settings, ctx)['projectCandidates'] == []


def test_symlink_root_cannot_authorize_project(settings, tmp_path):
    link = tmp_path / 'linked-project'
    try:
        link.symlink_to(settings.roots[0], target_is_directory=True)
    except OSError:
        pytest.skip('Symlink creation requires Windows permission on this host')
    ctx, _ = context([link.as_uri()])
    assert discover(settings, ctx)['projectCandidates'] == []


def test_outer_cancellation_is_not_swallowed_as_a_root_failure(settings):
    ctx, _ = context(delay=1)
    async def cancel():
        task = asyncio.create_task(discover_locations(settings, ctx))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(cancel())


def test_host_project_is_revalidated_at_install_and_never_grants_publish_access(settings, tmp_path):
    host = tmp_path / 'host-project'
    host.mkdir()
    client = FakeClient()
    installer = Installer(settings, client, Path.home())
    before = settings.path.read_bytes()
    ctx, _ = context([host.as_uri()])
    locations = discover(settings, ctx)
    plan = installer.prepare(1, 'project', project_path(locations), project_roots=project_roots(locations))
    assert plan['scopeDir'] == str(host) and plan['requiresConfirmation']
    assert not (host / '.claude').exists()
    # A root withdrawn by the host cannot be retained by a previously prepared plan.
    with pytest.raises(SquareError, match='허용된'):
        installer.install(plan['planId'], plan['approvalDigest'], True)
    assert client.downloads == []
    result = installer.install(plan['planId'], plan['approvalDigest'], True,
                               project_roots=project_roots(locations))
    assert result['installed']
    assert (host / '.claude' / 'skills' / 'memo-summary' / 'SKILL.md').read_bytes() == client.raw
    assert settings.path.read_bytes() == before
    from pt_square_mcp.files import inspect
    with pytest.raises(SquareError, match='허용된'):
        inspect(host, Settings(settings.path).roots)


def test_arbitrary_ai_path_cannot_escape_host_and_existing_trust(settings, tmp_path):
    host = tmp_path / 'host-project'
    arbitrary = tmp_path / 'ai-requested'
    host.mkdir()
    arbitrary.mkdir()
    installer = Installer(settings, FakeClient(), Path.home())
    with pytest.raises(SquareError, match='허용된'):
        installer.prepare(1, 'project', str(arbitrary), project_roots=(host,))
    assert not (arbitrary / '.claude').exists()


def test_user_scope_keeps_existing_per_account_location(settings):
    installer = Installer(settings, FakeClient(), Path.home())
    plan = installer.prepare(1, 'user')
    assert plan['scope'] == 'user' and plan['scopeDir'] == str(Path.home())
    assert Path(plan['destination']) == Path.home() / '.claude' / 'skills' / 'memo-summary'


def test_location_discovery_uses_chat_choice_and_keeps_download_destination(settings):
    before = settings.path.read_bytes()
    ctx, _ = context([settings.roots[0].as_uri()])
    result = discover(settings, ctx)
    other = next(option for option in result['options'] if option['scope'] == 'other')
    assert not other.get('requiresPicker', False)
    assert '선택창' not in result['notice']
    assert settings.path.read_bytes() == before
    assert Settings(settings.path).downloads == settings.downloads


def test_unconfirmed_cwd_guidance_never_instructs_opening_native_picker(settings, tmp_path):
    cwd = tmp_path / 'unconfirmed project'
    cwd.mkdir()
    ctx, _ = context(supported=False)
    result = discover(settings, ctx, launch_cwd=cwd)
    assert result['currentProject'] is None
    assert '채팅' in result['notice'] and '선택창' not in result['notice']
    assert result['confirmationCandidates'][0]['path'] == str(cwd)
    assert project_roots(result) == ()
