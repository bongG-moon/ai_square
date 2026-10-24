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


def test_cli_setup_asks_only_for_key_and_verifies_the_actual_account(local, monkeypatch, capsys):
    home, path, manifest = local
    monkeypatch.setattr(cli.sys.stdin, 'isatty', lambda: True)
    prompts = []
    monkeypatch.setattr(cli.getpass, 'getpass', lambda prompt: prompts.append(prompt) or KEY)
    monkeypatch.setattr(onboarding, 'Client', VerifiedClient)
    assert cli.main(['--config', str(path), 'setup']) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert result['connected'] is True and result['user']['name'] == '홍길동'
    assert len(prompts) == 1 and 'KEY' in prompts[0]
    assert KEY not in output.out + output.err


def test_cli_http_confirmation_is_yes_no_not_manual_origin_entry(local, monkeypatch, capsys):
    home, path, manifest = local
    manifest.write_text(json.dumps({'schemaVersion':1,'baseUrl':'http://intranet.example'}), encoding='utf-8')
    monkeypatch.setattr(cli.sys.stdin, 'isatty', lambda: True)
    prompts = []
    monkeypatch.setattr('builtins.input', lambda prompt: prompts.append(prompt) or 'y')
    monkeypatch.setattr(cli.getpass, 'getpass', lambda prompt: KEY)
    monkeypatch.setattr(onboarding, 'Client', VerifiedClient)
    assert cli.main(['--config', str(path), 'setup']) == 0
    assert len(prompts) == 1 and '[y/N]' in prompts[0]
    assert json.loads(capsys.readouterr().out)['connected'] is True


def test_cli_no_key_opens_the_preconfigured_issuance_page_without_claiming_connection(local, monkeypatch, capsys):
    home, path, manifest = local
    monkeypatch.setattr(cli.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(cli.getpass, 'getpass', lambda prompt: '')
    opened = []
    monkeypatch.setattr(cli.webbrowser, 'open', lambda url: opened.append(url))
    assert cli.main(['--config', str(path), 'setup']) == 0
    assert opened == [ORIGIN + '/local-access']
    assert not path.exists() and 'connected' not in capsys.readouterr().out


def test_gui_command_delegates_to_the_key_window(local, monkeypatch):
    home, path, manifest = local
    from types import SimpleNamespace
    seen = []
    monkeypatch.setitem(sys.modules, 'pt_square_mcp.connection_ui',
                        SimpleNamespace(open_connection=lambda target: seen.append(target) or 0))
    assert cli.main(['--config', str(path), 'connect']) == 0
    assert seen == [path]
