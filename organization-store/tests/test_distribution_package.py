"""Public bundles configure offline without source checkout or native helpers."""
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import configure_server as binder
import package_for_upload as uploader


@pytest.fixture
def distribution(tmp_path):
    report = uploader.create_distribution(tmp_path / 'public')
    target = tmp_path / report['archive']
    target.write_bytes((tmp_path / 'public' / report['archive']).read_bytes())
    with zipfile.ZipFile(target) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    return report, files


def test_public_bundle_is_neutral_and_only_has_offline_material(distribution):
    report, files = distribution
    assert report['serverPresetIncluded'] is False
    assert report['installerExecutableIncluded'] is False
    assert set(files) == {'extension-template.zip', 'extension-template.zip.sha256', 'configure_server.py', 'README.txt', 'exe_builder.py', 'installer/ImportExtension.nsi', 'installer/ResolveWorkspace.ps1', 'nsis-toolchain.zip', 'nsis-toolchain.zip.sha256', 'licenses/NSIS-COPYING.txt', 'licenses/NSIS-Modern-UI-2.txt'}
    assert report['standardCompilerIncluded'] is True
    assert report['nativeHelperIncluded'] is False
    assert hashlib.sha256(files['extension-template.zip']).hexdigest() == report['templateSha256']
    assert files['extension-template.zip.sha256'].decode().strip() == report['templateSha256']
    with zipfile.ZipFile(io.BytesIO(files['extension-template.zip'])) as archive:
        manifest = json.loads(archive.read('extension.json'))
        assert set(archive.namelist()) == set(manifest['files']) | {'extension.json'}
    assert b'from build import' not in files['configure_server.py']


def test_operator_cli_works_without_checkout_and_output_matches_source_packager(tmp_path, distribution):
    report, files = distribution
    isolated = tmp_path / 'isolated'
    isolated.mkdir()
    for name, data in files.items():
        (isolated / name).parent.mkdir(parents=True, exist_ok=True)
        (isolated / name).write_bytes(data)
    result = subprocess.run([
        sys.executable, '-I', '-B', '-X', 'utf8', str(isolated / 'configure_server.py'),
        '--server-url', 'http://SQUARE.company.example:80/', '--output', 'ready.zip',
    ], cwd=isolated, capture_output=True, text=True, encoding='utf-8', timeout=120)
    assert result.returncode == 0, result.stderr
    assert '암호화되지 않은' in result.stdout
    ready = isolated / 'ready.zip'
    source = uploader.create_upload(tmp_path / 'source', 'http://square.company.example', file_extension='.zip')
    assert ready.read_bytes() == (tmp_path / 'source' / source['archive']).read_bytes()
    assert source['build'] == report['build']
    assert sorted(p.relative_to(isolated).as_posix() for p in isolated.rglob('*') if p.is_file()) == sorted([*files, 'ready.zip'])
    with zipfile.ZipFile(ready) as archive:
        assert '암호화되지 않은' in archive.read('README.txt').decode()
        assert json.loads(archive.read('connection.json')) == {'schemaVersion': 1, 'baseUrl': 'http://square.company.example'}


def _operator_copy(directory, files, *, server=None, output=None):
    directory.mkdir()
    for name, data in files.items():
        if name == 'configure_server.py':
            source = data.decode('utf-8')
            for constant, value in [('SERVER_URL', server), ('OUTPUT_ZIP', output)]:
                if value is not None:
                    source, count = re.subn(
                        rf'^{constant}\s*=.*$',
                        lambda _match: constant + ' = ' + json.dumps(value),
                        source, flags=re.M)
                    assert count == 1, 'The operator-editable setting must be available.'
            data = source.encode('utf-8')
        (directory / name).parent.mkdir(parents=True, exist_ok=True)
        (directory / name).write_bytes(data)
    return directory / 'configure_server.py'


def _run_operator(script, cwd, *arguments):
    return subprocess.run([
        sys.executable, '-I', '-B', '-X', 'utf8', str(script), *arguments,
    ], cwd=cwd, capture_output=True, text=True, encoding='utf-8', timeout=120)


def test_editable_settings_run_without_arguments_from_another_directory(tmp_path, distribution):
    _, files = distribution
    script = _operator_copy(tmp_path / 'operator', files,
                            server='https://SQUARE.company.example:443/', output='configured.zip')
    working = tmp_path / 'unrelated-working-directory'
    working.mkdir()
    result = _run_operator(script, working)
    assert result.returncode == 0, result.stderr
    ready = script.parent / 'configured.zip'
    assert ready.is_file()
    assert not list(working.iterdir())
    with zipfile.ZipFile(io.BytesIO(files['extension-template.zip'])) as before, zipfile.ZipFile(ready) as after:
        for name in before.namelist():
            assert before.read(name) == after.read(name)
        assert json.loads(after.read('connection.json'))['baseUrl'] == 'https://square.company.example'
    unchanged = ready.read_bytes()
    repeated = _run_operator(script, working)
    assert repeated.returncode == 2
    assert '이미' in repeated.stderr
    assert ready.read_bytes() == unchanged


def test_blank_editable_server_explains_setting_and_writes_nothing(tmp_path, distribution):
    _, files = distribution
    script = _operator_copy(tmp_path / 'operator', files)
    before = {path.relative_to(script.parent).as_posix(): path.read_bytes() for path in script.parent.rglob('*') if path.is_file()}
    result = _run_operator(script, tmp_path)
    assert result.returncode == 2
    assert 'SERVER_URL' in result.stderr
    assert {path.relative_to(script.parent).as_posix(): path.read_bytes() for path in script.parent.rglob('*') if path.is_file()} == before
    assert not (tmp_path / 'PNT-AI-Square-0.1.0-Setup.exe').exists()


def test_default_operator_output_is_doubleclick_package(tmp_path, distribution):
    _, files = distribution
    script = _operator_copy(tmp_path / 'operator', files, server='https://square.company.example')
    result = _run_operator(script, tmp_path)
    assert result.returncode == 0, result.stderr
    ready = script.parent / 'PNT-AI-Square-0.1.0-Setup.exe'
    assert ready.read_bytes().startswith(b'MZ')
    assert '"installerExecutableIncluded": true' in result.stdout
    assert '"installerExecuted": false' in result.stdout


def test_explicit_cli_values_override_editable_settings_and_keep_cwd_output(tmp_path, distribution):
    _, files = distribution
    script = _operator_copy(tmp_path / 'operator', files,
                            server='https://default.example', output='not-created.zip')
    working = tmp_path / 'explicit-output-directory'
    working.mkdir()
    result = _run_operator(script, working,
                           '--server-url', 'http://override.example', '--output', 'cli-ready.zip')
    assert result.returncode == 0, result.stderr
    assert '암호화되지 않은' in result.stdout
    assert not (script.parent / 'not-created.zip').exists()
    assert not (script.parent / 'cli-ready.zip').exists()
    with zipfile.ZipFile(working / 'cli-ready.zip') as ready:
        assert json.loads(ready.read('connection.json'))['baseUrl'] == 'http://override.example'


def test_rebinding_preserves_manifest_payload_and_refuses_overwrite(tmp_path):
    first = uploader.create_upload(tmp_path / 'first', 'https://first.example', file_extension='.zip')
    original = tmp_path / 'first' / first['archive']
    destination = tmp_path / 'second.zip'
    second = binder.configure(original, destination, 'https://second.example:443/')
    assert first['build'] == second['build']
    with zipfile.ZipFile(original) as before, zipfile.ZipFile(destination) as after:
        manifest = json.loads(before.read('extension.json'))
        for name in [*manifest['files'], 'extension.json']:
            assert before.read(name) == after.read(name)
        assert b'first.example' not in after.read('README.txt')
        assert json.loads(after.read('connection.json'))['baseUrl'] == 'https://second.example'
    preserved = destination.read_bytes()
    with pytest.raises(ValueError, match='이미'):
        binder.configure(original, destination, 'https://third.example')
    assert destination.read_bytes() == preserved


def test_checksum_tamper_creates_no_output(tmp_path, distribution):
    _, files = distribution
    template = tmp_path / 'template.zip'
    template.write_bytes(files['extension-template.zip'])
    with pytest.raises(ValueError, match='SHA256'):
        binder.configure(template, tmp_path / 'new' / 'ready.zip', 'https://square.example', expected_sha256='0' * 64)
    assert not (tmp_path / 'new').exists()


@pytest.mark.parametrize('extra_name', ['../escape.py', '/absolute.py', 'C:/escape.py', 'packages/../bad',
    'EXTENSION.JSON', 'unknown.txt', 'NUL.txt', 'bad\\file.py', 'bad./file.py', 'installer.exe'])
def test_unsafe_or_undeclared_paths_rejected_without_extracting(tmp_path, distribution, extra_name):
    _, files = distribution
    buffer = io.BytesIO(files['extension-template.zip'])
    with zipfile.ZipFile(buffer, 'a') as archive:
        archive.writestr(extra_name, b'not executed')
    template = tmp_path / 'bad.zip'
    template.write_bytes(buffer.getvalue())
    with pytest.raises(ValueError):
        binder.configure(template, tmp_path / 'output' / 'ready.zip', 'https://square.example')
    assert not (tmp_path / 'output').exists()
    assert not (tmp_path / 'escape.py').exists()


@pytest.mark.parametrize('mutation', ['payload', 'build', 'duplicate-json', 'link', 'reparse', 'name'])
def test_bad_payload_and_manifest_rejected(tmp_path, distribution, mutation):
    _, files = distribution
    with zipfile.ZipFile(io.BytesIO(files['extension-template.zip'])) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries['extension.json'])
    first = next(iter(manifest['files']))
    if mutation == 'payload':
        entries[first] += b'changed'
    elif mutation == 'build':
        old = first.split('/')[1]
        entries = {name.replace(old, '0' * 64): data for name, data in entries.items()}
        entries['extension.json'] = entries['extension.json'].replace(old.encode(), b'0' * 64)
    elif mutation == 'duplicate-json':
        entries['extension.json'] = b'{"schemaVersion":1,' + entries['extension.json'][1:]
    elif mutation == 'name':
        manifest['name'] = ''
        entries['extension.json'] = json.dumps(manifest).encode()
    template = tmp_path / 'bad.zip'
    with zipfile.ZipFile(template, 'w') as archive:
        for name, data in entries.items():
            entry = zipfile.ZipInfo(name)
            if mutation == 'link' and name == first:
                entry.create_system = 3
                entry.external_attr = 0o120777 << 16
            if mutation == 'reparse' and name == first:
                entry.external_attr |= 0x400
            archive.writestr(entry, data)
    with pytest.raises(ValueError):
        binder.configure(template, tmp_path / 'output' / 'ready.zip', 'https://square.example')
    assert not (tmp_path / 'output').exists()


def test_invalid_origin_and_missing_cli_checksum_write_nothing(tmp_path, distribution):
    _, files = distribution
    for name in ['extension-template.zip', 'configure_server.py']:
        (tmp_path / name).write_bytes(files[name])
    with pytest.raises(ValueError):
        binder.configure(tmp_path / 'extension-template.zip', tmp_path / 'ready.zip', 'https://square.example:0')
    result = subprocess.run([
        sys.executable, '-I', '-B', str(tmp_path / 'configure_server.py'),
        '--server-url', 'https://square.example', '--output', str(tmp_path / 'ready.zip'),
    ], capture_output=True, timeout=120)
    assert result.returncode == 2
    assert not (tmp_path / 'ready.zip').exists()
