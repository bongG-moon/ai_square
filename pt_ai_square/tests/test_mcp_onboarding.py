"""First connection uses only a private KEY and a website-bound origin."""
import json
import os
from pathlib import Path
import sys

import pytest

PACKAGE = Path(__file__).parents[1] / 'integrations' / 'pt-square-mcp'
sys.path.insert(0, str(PACKAGE))
from pt_square_mcp import config, onboarding
from pt_square_mcp import __main__ as cli
from pt_square_mcp.config import Settings, SquareError, read_json, save_config

KEY = 'ptsq_' + 'a' * 43
NEW_KEY = 'ptsq_' + 'b' * 43
ORIGIN = 'https://square.example.test'


@pytest.fixture
def local(tmp_path, monkeypatch):
    home = tmp_path / '사용자 계정'
    home.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    # The runtime still uses actual DPAPI on Windows. Other OS unit runs use a
    # test-only reversible envelope; no real user home or credentials are used.
    if os.name != 'nt':
        monkeypatch.setattr(config, 'protect', lambda data, decrypt=False: data[::-1])
    manifest = tmp_path / 'package' / 'connection.json'
    manifest.parent.mkdir()
    manifest.write_text(json.dumps({'schemaVersion': 1, 'baseUrl': ORIGIN}), encoding='utf-8')
    monkeypatch.setattr(onboarding, 'PACKAGE_MANIFEST', manifest)
    return home, home / '.pt-ai-square' / 'mcp' / 'config.json', manifest


class VerifiedClient:
    calls = []
    def __init__(self, settings):
        self.settings = settings
    def json(self, path):
        assert path == '/api/integration/me'
        assert self.settings.token() in {KEY, NEW_KEY}
        self.calls.append(self.settings.url)
        return {'user': {'id': 'E123', 'name': '홍길동', 'dept': '융합기술', 'dept_cd': 'D123'},
                'key': {'id': 'key-id', 'scope': 'publish'}, 'irrelevant': KEY}


def connect(path, url=ORIGIN, token=KEY, **kwargs):
    return onboarding.connect(path, url, token, client_factory=VerifiedClient, **kwargs)


def old_connection(path, home, origin=ORIGIN):
    folder = home / '기존 프로젝트'
    folder.mkdir(exist_ok=True)
    save_config(path, origin, [folder], KEY)
    return folder, path.read_bytes(), (path.parent / 'credential.dpapi.json').read_bytes()


def test_packaged_origin_avoids_both_manual_arguments(local):
    home, path, manifest = local
    assert onboarding.resolve_connection(path) == ORIGIN
    result = connect(path)
    downloads = home / 'AI_SQUARE' / 'downloads'
    assert result['connected'] is True and result['configured'] is True
    assert result['user']['id'] == 'E123'
    assert result['user']['name'] == '홍길동'
    assert result['downloadDirectory'] == str(downloads)
    assert downloads.is_dir()
    settings = Settings(path)
    assert settings.downloads == downloads
    assert settings.roots == [downloads]
    assert settings.token() == KEY
    assert KEY not in json.dumps(result)
    for file in path.parent.glob('*.json'):
        assert KEY not in file.read_text(encoding='utf-8')


def test_package_origin_wins_over_saved_site_and_explicit_override_is_supported(local):
    home, path, manifest = local
    old_connection(path, home, 'https://older.example.test')
    assert onboarding.resolve_connection(path) == ORIGIN
    assert onboarding.resolve_connection(path, 'https://explicit.example.test/') == 'https://explicit.example.test'
    manifest.unlink()
    assert onboarding.resolve_connection(path) == 'https://older.example.test'


def test_generic_zip_without_prior_config_requests_site_download(local):
    home, path, manifest = local
    manifest.unlink()
    with pytest.raises(SquareError, match='웹의 로컬 MCP 받기'):
        onboarding.resolve_connection(path)
    assert not path.exists()


@pytest.mark.parametrize('value', [
    {'schemaVersion': True, 'baseUrl': ORIGIN},
    {'schemaVersion': 2, 'baseUrl': ORIGIN},
    {'schemaVersion': 1, 'baseUrl': ORIGIN, 'token': KEY},
    {'schemaVersion': 1, 'baseUrl': 'https://user:password@example.test'},
    {'schemaVersion': 1, 'baseUrl': ORIGIN + '/local-access'},
    {'schemaVersion': 1, 'baseUrl': 'file:///C:/data'},
])
def test_invalid_present_manifest_cannot_silently_use_old_configuration(local, value):
    home, path, manifest = local
    old_connection(path, home)
    manifest.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(SquareError):
        onboarding.resolve_connection(path)


@pytest.mark.parametrize('failure', ['unauthorized', 'offline', 'unrelated-200', 'missing-key'])
def test_failed_authentication_keeps_working_configuration_and_credentials(local, failure):
    home, path, manifest = local
    folder, original_config, original_credential = old_connection(path, home)
    class FailedClient:
        def __init__(self, settings): pass
        def json(self, route):
            if failure in {'unauthorized', 'offline'}:
                raise SquareError('KEY 또는 서버 연결을 확인하세요.')
            return {} if failure == 'unrelated-200' else {'user': {'id':'E123','name':'홍길동'}}
    with pytest.raises(SquareError):
        onboarding.connect(path, ORIGIN, NEW_KEY, client_factory=FailedClient)
    assert path.read_bytes() == original_config
    assert (path.parent / 'credential.dpapi.json').read_bytes() == original_credential
    assert Settings(path).token() == KEY
    assert not (home / 'AI_SQUARE').exists()


@pytest.mark.parametrize('token', [None, '', 'invalid', 'ptsq_short'])
def test_malformed_key_is_rejected_before_network_or_folder_writes(local, token):
    home, path, manifest = local
    def forbidden(settings): pytest.fail('Do not send an invalid KEY')
    with pytest.raises(SquareError, match='KEY 형식'):
        onboarding.connect(path, ORIGIN, token, client_factory=forbidden)
    assert not path.exists() and not (home / 'AI_SQUARE').exists()


def test_http_requires_one_explicit_acknowledgement_before_any_key_transfer(local):
    home, path, manifest = local
    def forbidden(settings): pytest.fail('HTTP consent precedes network')
    with pytest.raises(SquareError, match='암호화'):
        onboarding.connect(path, 'http://intranet.example', KEY, client_factory=forbidden)
    result = connect(path, 'http://intranet.example', allow_http=True)
    assert result['encryptedTransport'] is False
    assert read_json(path)['acceptedHttpOrigin'] == 'http://intranet.example'


def test_same_site_reconnect_keeps_explicit_roots_and_adds_only_managed_downloads(local):
    home, path, manifest = local
    existing, _, _ = old_connection(path, home)
    additional = home / '새 프로젝트'
    additional.mkdir()
    connect(path, token=NEW_KEY, roots=[additional, existing])
    settings = Settings(path)
    assert settings.token() == NEW_KEY
    assert settings.roots == [existing, additional, home / 'AI_SQUARE' / 'downloads']
    assert read_json(path)['credentialRef'].startswith('windows-dpapi:credential.')


def test_another_site_does_not_inherit_explicit_source_folder_access(local):
    home, path, manifest = local
    existing, _, _ = old_connection(path, home)
    connect(path, 'https://different.example.test', NEW_KEY)
    assert Settings(path).roots == [home / 'AI_SQUARE' / 'downloads']
    assert existing.exists()


def test_reconnect_recreates_a_removed_automatic_download_folder(local):
    home, path, manifest = local
    connect(path)
    downloads = home / 'AI_SQUARE' / 'downloads'
    downloads.rmdir()
    connect(path, token=NEW_KEY)
    assert downloads.is_dir()
    assert Settings(path).roots == [downloads]
    assert Settings(path).token() == NEW_KEY


def test_reconnect_drops_only_missing_previous_sources(local):
    home, path, _ = local
    missing = home / '삭제한 원본'; missing.mkdir()
    existing = home / '남아 있는 원본'; existing.mkdir()
    connect(path, roots=[missing, existing])
    missing.rmdir()
    downloads = home / 'AI_SQUARE' / 'downloads'
    downloads.rmdir()
    result = connect(path, token=NEW_KEY)
    assert result['removedWorkspaceCount'] == 1
    assert Settings(path).roots == [existing, downloads]
    assert Settings(path).token() == NEW_KEY
    assert downloads.is_dir() and not missing.exists()


def test_reconnect_still_rejects_explicit_missing_source(local):
    home, path, _ = local
    connect(path)
    original = path.read_bytes()
    with pytest.raises(SquareError, match='작업 폴더'):
        connect(path, token=NEW_KEY, roots=[home / '없는 원본'])
    assert path.read_bytes() == original and Settings(path).token() == KEY


def test_environment_mode_references_the_environment_without_persisting_token(local, monkeypatch):
    home, path, manifest = local
    monkeypatch.setenv('PTAI_API_TOKEN', KEY)
    result = connect(path, token=None, token_from_env=True)
    assert result['credentialStored'] == 'environment'
    assert read_json(path)['credentialRef'] == 'environment:PTAI_API_TOKEN'
    assert Settings(path).token() == KEY
    assert not list(path.parent.glob('credential*.json'))
    monkeypatch.delenv('PTAI_API_TOKEN')
    with pytest.raises(SquareError, match='KEY가 없습니다'):
        Settings(path).token()


def test_atomic_config_failure_cannot_replace_old_encrypted_key(local, monkeypatch):
    home, path, manifest = local
    existing, old_config, old_secret = old_connection(path, home)
    original = config.atomic_json
    def fail_config(target, value):
        if target == path:
            raise OSError('Simulated disk failure')
        return original(target, value)
    monkeypatch.setattr(config, 'atomic_json', fail_config)
    with pytest.raises(OSError):
        connect(path, token=NEW_KEY)
    assert path.read_bytes() == old_config
    assert (path.parent / 'credential.dpapi.json').read_bytes() == old_secret
    assert list(path.parent.glob('credential.*.dpapi.json')) == []
    assert Settings(path).token() == KEY


@pytest.mark.parametrize('command', ['connect', 'setup'])
def test_cli_standard_routes_only_explain_chat_without_prompt_window_or_network(local, monkeypatch, capsys, command):
    import getpass
    import webbrowser
    home, path, manifest = local
    def forbidden(*args, **kwargs):
        pytest.fail('Standard launchers must not prompt, open windows, or authenticate')
    monkeypatch.setattr('builtins.input', forbidden)
    monkeypatch.setattr(getpass, 'getpass', forbidden)
    monkeypatch.setattr(webbrowser, 'open', forbidden)
    monkeypatch.setattr(cli, 'connect', forbidden)
    monkeypatch.setitem(sys.modules, 'tkinter', None)
    assert cli.main(['--config', str(path), command]) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result['chatRequired'] is True and result['keyRequired'] is True
    assert result['connected'] is False and result['connectTool'] == 'connect_account'
    assert result['baseUrl'] == ORIGIN and result['authUrl'] == ORIGIN + '/local-access'
    assert KEY not in output.out + output.err
    assert not path.exists()


def test_cli_auth_only_prints_current_saved_origin_without_opening_browser(local, monkeypatch, capsys):
    import webbrowser
    home, path, manifest = local
    current = 'https://already-connected.example.test'
    old_connection(path, home, current)
    before = path.read_bytes()
    monkeypatch.setattr(webbrowser, 'open', lambda *a: pytest.fail('No browser window'))
    assert cli.main(['--config', str(path), 'auth']) == 0
    assert capsys.readouterr().out.strip() == current + '/local-access'
    assert path.read_bytes() == before


def test_cli_env_setup_verifies_account_without_prompt_or_permanent_key(local, monkeypatch, capsys):
    import getpass
    home, path, manifest = local
    monkeypatch.setenv('PTAI_API_TOKEN', KEY)
    monkeypatch.setattr(getpass, 'getpass', lambda *a: pytest.fail('No hidden prompt'))
    monkeypatch.setattr('builtins.input', lambda *a: pytest.fail('No interactive prompt'))
    monkeypatch.setattr(onboarding, 'Client', VerifiedClient)
    assert cli.main(['--config', str(path), 'setup', '--token-from-env']) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result['connected'] is True and result['user']['name'] == '홍길동'
    assert KEY not in output.out + output.err
    assert Settings(path).token() == KEY
    assert not list(path.parent.glob('credential*.json'))


@pytest.mark.parametrize('ack', ['', 'http://other.example'])
def test_cli_env_http_requires_exact_origin_without_prompt_or_network(local, monkeypatch, capsys, ack):
    home, path, manifest = local
    manifest.write_text(json.dumps({'schemaVersion': 1, 'baseUrl': 'http://intranet.example'}), encoding='utf-8')
    monkeypatch.setenv('PTAI_API_TOKEN', KEY)
    monkeypatch.setattr('builtins.input', lambda *a: pytest.fail('No interactive prompt'))
    monkeypatch.setattr(cli, 'connect', lambda *a, **k: pytest.fail('No unacknowledged HTTP request'))
    argv = ['--config', str(path), 'setup', '--token-from-env']
    if ack:
        argv += ['--accept-http-origin', ack]
    assert cli.main(argv) == 1
    output = capsys.readouterr()
    assert KEY not in output.out + output.err and not path.exists()


def test_cli_env_http_exact_origin_and_explicit_extra_workspace(local, monkeypatch, capsys):
    home, path, manifest = local
    source = home / 'source'
    source.mkdir()
    monkeypatch.setenv('PTAI_API_TOKEN', KEY)
    monkeypatch.setattr(onboarding, 'Client', VerifiedClient)
    assert cli.main(['--config', str(path), 'setup', '--token-from-env',
                     '--url', 'http://intranet.example', '--accept-http-origin', 'http://intranet.example',
                     '--workspace', str(source)]) == 0
    assert json.loads(capsys.readouterr().out)['connected'] is True
    settings = Settings(path)
    assert settings.url == 'http://intranet.example' and source in settings.roots


def test_cli_env_setup_preserves_saved_origin_without_explicit_override(local, monkeypatch, capsys):
    home, path, manifest = local
    origin = 'https://existing.example.test'
    old_connection(path, home, origin)
    monkeypatch.setenv('PTAI_API_TOKEN', NEW_KEY)
    monkeypatch.setattr(onboarding, 'Client', VerifiedClient)
    assert cli.main(['--config', str(path), 'setup', '--token-from-env']) == 0
    assert json.loads(capsys.readouterr().out)['connected'] is True
    assert Settings(path).url == origin


def test_cli_env_setup_cannot_overwrite_concurrent_connection(local, monkeypatch, capsys):
    home, path, manifest = local
    monkeypatch.setenv('PTAI_API_TOKEN', KEY)
    class ConcurrentClient(VerifiedClient):
        def json(self, url):
            response = super().json(url)
            old_connection(path, home, 'https://new-connection.example.test')
            return response
    monkeypatch.setattr(onboarding, 'Client', ConcurrentClient)
    assert cli.main(['--config', str(path), 'setup', '--token-from-env']) == 1
    output = capsys.readouterr()
    assert KEY not in output.out + output.err
    assert Settings(path).url == 'https://new-connection.example.test'
