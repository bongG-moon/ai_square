"""Manual upload packages are source ZIPs and never run native installers."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import package_for_upload as uploader

spec = importlib.util.spec_from_file_location('upload_contract', HERE.parent / 'pt_ai_square/static/guides/pt-file-distribution/scripts/package_contract.py')
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


def test_package_is_directly_registerable_and_contains_no_native_installer(tmp_path, monkeypatch):
    def no_build(*args, **kwargs):
        raise AssertionError('Native installer must not be built or run')
    monkeypatch.setattr(sys.modules['build'], 'build', no_build)
    report = uploader.create_upload(tmp_path, 'https://square.example', file_extension='.axextension')
    path = tmp_path / report['archive']
    assert path.suffix == '.axextension'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == report['sha256']
    assert report['installerExecutableIncluded'] is False
    assert report['profileModified'] is False and report['antivirusCleared'] is False
    with zipfile.ZipFile(path) as archive:
        metadata = contract.read_package(archive)
        assert metadata['type'] == '플러그인/하네스'
        assert metadata['packageId'] == 'pt-ai-square.store'
        assert '확장 ZIP 가져오기' in metadata['guide']
        assert '더블클릭' in metadata['guide']
        assert json.loads(archive.read('connection.json')) == {'schemaVersion': 1, 'baseUrl': 'https://square.example'}
        manifest = json.loads(archive.read('extension.json'))
        assert set(archive.namelist()) == set(manifest['files']) | {'extension.json', 'connection.json', 'README.txt', 'ai-square.json'}
        assert not any(Path(name).suffix.lower() in {'.exe', '.dll', '.ps1', '.cmd', '.bat', '.vbs', '.msi'} for name in archive.namelist())
        for name, digest in manifest['files'].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest


def test_server_binding_does_not_change_worker_payload_or_hide_http_warning(tmp_path):
    first = uploader.create_upload(tmp_path / 'first', 'http://square.company.example', file_extension='.axextension')
    second = uploader.create_upload(tmp_path / 'second', 'http://127.0.0.1:5080', file_extension='.axextension')
    assert first['build'] == second['build']
    assert first['sha256'] != second['sha256']
    with zipfile.ZipFile(tmp_path / 'first' / first['archive']) as archive:
        assert '암호화되지 않은' in archive.read('README.txt').decode('utf-8')
        assert b'apiToken' not in archive.read('connection.json')


@pytest.mark.parametrize('value', [
    'http://0.0.0.0', 'http://[::]', 'https://user:password@square.example',
    'https://square.example/subpath', 'https://square.example?token=secret',
    'https://square.example/#secret', 'file:///private', 'https://square.example:99999',
    'https://square.example\n', 'https://square.example\\other', '',
])
def test_invalid_origin_writes_no_package(tmp_path, value):
    target = tmp_path / 'new'
    with pytest.raises(ValueError):
        uploader.create_upload(target, value)
    assert not target.exists()


def test_existing_output_is_not_overwritten(tmp_path):
    result = uploader.create_upload(tmp_path, 'https://square.example', file_extension='.axextension')
    original = (tmp_path / result['archive']).read_bytes()
    with pytest.raises(ValueError, match='이미'):
        uploader.create_upload(tmp_path, 'https://changed.example', file_extension='.axextension')
    assert (tmp_path / result['archive']).read_bytes() == original
