"""Downloaded public origin is a preset, never a credential or permission grant."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from test_worker import worker, FakeClient


@pytest.fixture
def store(tmp_path):
    package = tmp_path / 'package'; package.mkdir()
    return worker.Store(tmp_path / 'data', home=tmp_path, existing_config=tmp_path / 'unused.json',
                        package_directory=package, client_factory=FakeClient)


def preset(store, url='https://square.example.test', **extra):
    worker.atomic_json(store.directory / 'connection.json', dict(schemaVersion=1, baseUrl=url, **extra))


def test_downloaded_origin_is_shown_without_authentication_or_network(store):
    preset(store, 'http://PnTAISquare.example.test:80/')
    store.client_factory = lambda _: pytest.fail('status must not contact server')
    status = store.status()
    assert status['presetBaseUrl'] == 'http://pntaisquare.example.test'
    assert status['configured'] is False and status['baseUrl'] == ''
    assert not store.config_path.exists()


def test_key_only_connection_uses_preset_and_stores_only_dpapi(store):
    preset(store)
    seen = []
    class Client(FakeClient):
        def json(self, path, **kwargs):
            seen.append((self.settings.url, path, self.settings.token()))
            return super().json(path, **kwargs)
    store.client_factory = Client
    key = 'ptsq_' + 'Q' * 43
    result = store.connect({'key': key})
    assert result['configured'] and result['baseUrl'] == 'https://square.example.test'
    assert seen == [('https://square.example.test', '/api/integration/me', key)]
    assert store.settings().token() == key
    assert key not in json.dumps(result)
    assert all(key not in f.read_text(encoding='utf-8') for f in store.directory.rglob('*.json'))


def test_http_preset_requires_explicit_consent_before_probe(store):
    preset(store, 'http://square.example.test')
    store.client_factory = lambda _: pytest.fail('unconfirmed HTTP request')
    with pytest.raises(worker.SquareError, match='HTTP'):
        store.connect({'key': 'ptsq_' + 'R' * 43})
    assert not store.config_path.exists()
    store.client_factory = FakeClient
    assert store.connect({'key': 'ptsq_' + 'R' * 43, 'allowHttp': True})['configured']


def test_new_package_origin_does_not_rebind_existing_connection(store):
    preset(store)
    key = 'ptsq_' + 'S' * 43
    store.connect({'key': key})
    before = store.config_path.read_bytes()
    preset(store, 'https://other.example.test')
    status = store.status()
    assert status['baseUrl'] == 'https://square.example.test'
    assert status['presetBaseUrl'] == 'https://other.example.test'
    assert store.config_path.read_bytes() == before
    seen = []
    def client(settings):
        seen.append(settings.url)
        return FakeClient(settings)
    store.client_factory = client
    store.connect({'key': key})
    assert seen == ['https://square.example.test']
    # A new explicit address plus newly supplied KEY can switch the connection.
    store.connect({'url': 'https://chosen.example.test', 'key': 'ptsq_' + 'T' * 43})
    assert store.settings().url == 'https://chosen.example.test'


@pytest.mark.parametrize('value', [
    {'schemaVersion': 1, 'baseUrl': 'https://square.test', 'key': 'ptsq_' + 'U' * 43},
    {'schemaVersion': 1, 'baseUrl': 'http://square.test', 'allowHttp': True},
    {'schemaVersion': True, 'baseUrl': 'https://square.test'},
    {'schemaVersion': 2, 'baseUrl': 'https://square.test'},
    {'schemaVersion': 1, 'baseUrl': 'https://user:pass@square.test'},
    {'schemaVersion': 1, 'baseUrl': 'https://square.test/api'},
    {'schemaVersion': 1, 'baseUrl': 'https://square.test?key=x'},
    {'schemaVersion': 1, 'baseUrl': 'javascript:alert(1)'},
])
def test_invalid_preset_fails_closed_and_never_loads_bundled_key(store, value):
    worker.atomic_json(store.directory / 'connection.json', value)
    status = store.status()
    assert not status['presetBaseUrl'] and status['presetMessage']
    assert 'ptsq_' not in json.dumps(status)
    store.client_factory = lambda _: pytest.fail('invalid preset reached network')
    with pytest.raises(worker.SquareError):
        store.connect({'key': 'ptsq_' + 'V' * 43})
    assert not store.config_path.exists()


@pytest.mark.parametrize('raw', ['not-json', ' ' * 4097, '[]'])
def test_malformed_or_large_primary_does_not_fallback(store, raw):
    worker.atomic_json(store.package_directory / 'connection.json', {'schemaVersion': 1, 'baseUrl': 'https://fallback.test'})
    (store.directory / 'connection.json').write_text(raw)
    assert not store.status()['presetBaseUrl']
    with pytest.raises(worker.SquareError):
        store.preset_url()


def test_missing_preset_keeps_manual_connection_and_package_fallback(store):
    assert store.status()['presetBaseUrl'] == ''
    with pytest.raises(worker.SquareError):
        store.connect({'key': 'ptsq_' + 'W' * 43})
    worker.atomic_json(store.package_directory / 'connection.json', {'schemaVersion': 1, 'baseUrl': 'https://fallback.test'})
    assert store.status()['presetBaseUrl'] == 'https://fallback.test'
    preset(store, 'https://installed.test')
    assert store.status()['presetBaseUrl'] == 'https://installed.test'
    assert store.connect({'url': 'https://manual.test', 'key': 'ptsq_' + 'W' * 43})['baseUrl'] == 'https://manual.test'


@pytest.mark.skipif(os.name != 'nt', reason='Windows MAX_PATH import regression')
def test_packaged_worker_imports_vendor_beyond_legacy_windows_path_limit(tmp_path):
    # Keep the entrypoint below MAX_PATH while a nested vendor module crosses
    # it, matching the native installer's version-directory layout.
    installed = tmp_path / ('p' * max(1, 230 - len(str(tmp_path))))
    native = Path('\\\\?\\' + str(installed))
    native.mkdir(parents=True)
    script = installed / 'worker.py'
    shutil.copyfile(Path(worker.__file__), script)
    shutil.copytree(worker.PACKAGE_ROOT / 'pt_square_mcp', native / 'vendor' / 'pt_square_mcp',
                    ignore=shutil.ignore_patterns('__pycache__'))
    nested = native / 'vendor' / 'pt_square_mcp' / '_vendor' / 'package_contract.py'
    assert nested.is_file() and len(str(nested)) > 260
    request = {'protocol': 1, 'action': 'status', 'payload': {},
               'dataDirectory': str(tmp_path / 'data'), 'context': {}}
    result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(script)],
                            input=json.dumps(request).encode(), capture_output=True, timeout=15)
    assert result.returncode == 0 and not result.stderr, result.stderr.decode('utf-8', 'replace')
    assert json.loads(result.stdout)['result']['configured'] is False
