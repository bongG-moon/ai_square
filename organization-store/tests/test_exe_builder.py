"""Real standard-NSIS builds and isolated handoff executables, never live AX."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import build
import configure_server
import exe_builder
import package_for_upload

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows NSIS executable integration')


@pytest.fixture(scope='module')
def payload(tmp_path_factory):
    directory = tmp_path_factory.mktemp('exe-payload')
    report = package_for_upload.create_upload(directory, 'https://square.example', file_extension='.zip')
    return (directory / report['archive']).read_bytes()


def _fake_host(directory, code=0):
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / 'fixture.cs'
    # The fixture only captures the forwarded bytes and exits; no registry/API.
    source.write_text('''using System; using System.IO; class Fixture {
static int Main(string[] args) {
if (args.Length != 2 || args[0] != "--import-extension") return 99;
string root=AppDomain.CurrentDomain.BaseDirectory;
string id=Guid.NewGuid().ToString("N");
File.WriteAllText(Path.Combine(root,id+".path"),args[1]);
File.Copy(args[1],Path.Combine(root,id+".zip"));
return ''' + str(code) + '''; }}''', encoding='utf-8')
    host = directory / 'AX-Workspace.exe'
    compiler = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    result = subprocess.run([str(compiler), '/nologo', '/target:exe', '/out:' + str(host), str(source)],
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return host


def _setup(target, payload, host):
    return exe_builder.compile_installer(target, payload, '0.1.0', compiler=build.nsis_compiler(),
                                         host_exe_override=host)


def test_actual_exe_forwards_verified_package_without_file_association_and_cleans_temp(tmp_path, payload):
    host = _fake_host(tmp_path / '한글 $ 사용자 폴더')
    target = tmp_path / '설치 $ 프로그램.exe'
    report = _setup(target, payload, host)
    assert report['nativeHelperIncluded'] is False and report['fileAssociationRequired'] is False
    result = subprocess.run([str(target), '/S'], capture_output=True, timeout=30)
    assert result.returncode == 0
    received = list(host.parent.glob('*.zip'))
    assert len(received) == 1 and received[0].read_bytes() == payload
    source = Path(next(host.parent.glob('*.path')).read_text())
    assert not source.exists(), 'NSIS source must be cleaned after host copies it'
    with zipfile.ZipFile(received[0]) as package:
        assert json.loads(package.read('connection.json'))['baseUrl'] == 'https://square.example'


def test_actual_exe_handles_missing_and_rejecting_host_without_success(tmp_path, payload):
    missing = tmp_path / 'missing.exe'
    _setup(missing, payload, tmp_path / 'not-installed/AX-Workspace.exe')
    assert subprocess.run([str(missing), '/S'], timeout=30).returncode == 2
    host = _fake_host(tmp_path / 'old-host', code=20)
    old = tmp_path / 'old.exe'
    _setup(old, payload, host)
    assert subprocess.run([str(old), '/S'], timeout=30).returncode == 4


def test_concurrent_exe_handoffs_have_distinct_temp_packages(tmp_path, payload):
    host = _fake_host(tmp_path / 'host')
    target = tmp_path / 'setup.exe'
    _setup(target, payload, host)
    runs = [subprocess.Popen([str(target), '/S']) for _ in range(2)]
    assert [run.wait(timeout=30) for run in runs] == [0, 0]
    paths = [path.read_text() for path in host.parent.glob('*.path')]
    assert len(paths) == 2 and len(set(paths)) == 2
    assert all(not Path(path).exists() for path in paths)
    assert all(path.read_bytes() == payload for path in host.parent.glob('*.zip'))


def test_output_collision_preserves_original_before_compiler_lookup(tmp_path, payload):
    target = tmp_path / 'existing.exe'
    target.write_bytes(b'original')
    with pytest.raises(ValueError, match='이미'):
        exe_builder.compile_installer(target, payload, '0.1.0', compiler=tmp_path / 'missing.exe')
    assert target.read_bytes() == b'original'


def test_compiler_tampering_and_unsafe_archives_are_rejected_before_execution(tmp_path, monkeypatch, payload):
    report = package_for_upload.create_distribution(tmp_path / 'public')
    with zipfile.ZipFile(tmp_path / 'public' / report['archive']) as archive:
        archive.extractall(tmp_path / 'operator')
    operator = tmp_path / 'operator'
    compiler_zip = operator / 'nsis-toolchain.zip'
    original = compiler_zip.read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('Unverified compiler must never execute')
    monkeypatch.setattr(exe_builder.subprocess, 'run', forbidden)
    compiler_zip.write_bytes(original + b'tampered')
    with pytest.raises(ValueError, match='SHA256'):
        exe_builder.compile_installer(tmp_path / 'bad.exe', payload, '0.1.0', bundle_root=operator)
    data = io.BytesIO(original)
    with zipfile.ZipFile(data, 'a') as archive:
        archive.writestr('../escape.exe', b'bad')
    compiler_zip.write_bytes(data.getvalue())
    compiler_zip.with_suffix('.zip.sha256').write_text(hashlib.sha256(data.getvalue()).hexdigest())
    with pytest.raises(ValueError, match='경로'):
        exe_builder.compile_installer(tmp_path / 'bad.exe', payload, '0.1.0', bundle_root=operator)
    assert not (tmp_path / 'bad.exe').exists() and not (tmp_path / 'escape.exe').exists()


def test_default_source_packager_creates_exe(tmp_path):
    report = package_for_upload.create_upload(tmp_path, 'https://square.example')
    assert report['archive'] == 'PNT-AI-Square-0.1.0-Setup.exe'
    assert (tmp_path / report['archive']).read_bytes().startswith(b'MZ')
    assert report['installerExecutableIncluded'] is True
    assert report['nativeHelperIncluded'] is False
