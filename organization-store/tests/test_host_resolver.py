"""Read-only managed-runtime selection and one-shot isolated process handoff."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

HERE = Path(__file__).resolve().parents[1]
SCRIPT = HERE / 'installer/ResolveWorkspace.ps1'
POWERSHELL = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
CSC = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows launcher contract')


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_ps(script, directory):
    path = directory / 'probe.ps1'
    path.write_text("$ErrorActionPreference='Stop'\n. " + quote(SCRIPT) + '\n' + script, encoding='utf-8-sig')
    return subprocess.run([str(POWERSHELL), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(path)],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)


@pytest.fixture(scope='module')
def hosts(tmp_path_factory):
    root = tmp_path_factory.mktemp('host-versions')
    result = {}
    for version, supported in [('0.23.31', False), ('0.23.32', True), ('0.23.35', True)]:
        directory = root / version
        directory.mkdir()
        source = directory / 'host.cs'
        source.write_text('''using System; using System.IO; using System.Reflection;
[assembly: AssemblyFileVersion("''' + version + '''.0")]
class Fixture {
static int Main(string[] args) {
string marker="''' + ('--import-extension' if supported else '--unsupported') + '''";
File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"called.txt"), marker);
return 0;
}}''', encoding='utf-8')
        target = directory / 'AX-Workspace.exe'
        built = subprocess.run([str(CSC), '/nologo', '/target:exe', '/out:' + str(target), str(source)],
                               capture_output=True, timeout=30)
        assert built.returncode == 0, built.stdout + built.stderr
        (directory / 'AX-Workspace.install-id').write_text('AX.Workspace.Desktop', encoding='utf-8')
        result[version] = target
    return result


def managed(state, version='0.23.34', exit_code=0):
    application = state / f'updates/versions/{version}/Company-Workspace'
    files = {
        'deploy/Start-CompanyWorkspace.ps1': ('''param([string]$StateRoot, [string]$ExtensionPackage)
$ErrorActionPreference='Stop'
$record=@{state=$StateRoot;package=$ExtensionPackage;exists=(Test-Path -LiteralPath $ExtensionPackage)} | ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $StateRoot 'received.json'), $record)
exit ''' + str(exit_code) + '\n').encode('utf-8-sig'),
        'local_app/server.py': f'WORKSPACE_VERSION = "{version}"\n'.encode(),
        'local_app/extension_open_client.py': b'# isolated fixture\n',
    }
    for name, data in files.items():
        path = application / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    pointer = state / 'updates/current.json'
    value = {'schema': 1, 'version': version, 'root': f'versions/{version}/Company-Workspace',
             'sha256': 'a' * 64, 'files': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    pointer.write_text(json.dumps(value), encoding='utf-8')
    return application, pointer, value


def select(tmp_path, state, host):
    return run_ps("try { $v=Resolve-WorkspaceTarget " + quote(state) + ' ' + quote(host) + "; @{kind=$v.kind; version=$v.version.ToString()} | ConvertTo-Json } catch { Write-Output $_.Exception.Message; exit 1 }", tmp_path)


def test_updated_runtime_is_selected_before_unsupported_installed_exe(tmp_path, hosts):
    state = tmp_path / 'state'
    managed(state)
    result = select(tmp_path, state, hosts['0.23.31'])
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout) == {'kind': 'managed', 'version': '0.23.34'}
    assert not (hosts['0.23.31'].parent / 'called.txt').exists()


def test_same_number_runtime_fix_is_preferred(tmp_path, hosts):
    state = tmp_path / 'state'
    managed(state, '0.23.32')
    result = select(tmp_path, state, hosts['0.23.32'])
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)['kind'] == 'managed'


def test_newer_installed_app_is_not_downgraded(tmp_path, hosts):
    state = tmp_path / 'state'
    managed(state)
    result = select(tmp_path, state, hosts['0.23.35'])
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)['kind'] == 'installed'


def test_no_update_uses_supported_owned_install(tmp_path, hosts):
    result = select(tmp_path, tmp_path / 'state', hosts['0.23.32'])
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)['kind'] == 'installed'


def test_pending_update_is_never_selected(tmp_path, hosts):
    state = tmp_path / 'state'
    _, pointer, _ = managed(state)
    pointer.rename(pointer.with_name('pending.json'))
    result = select(tmp_path, state, hosts['0.23.31'])
    assert result.returncode == 1 and 'AX_RESOLVE:73' in result.stdout
    assert not (state / 'received.json').exists()


@pytest.mark.parametrize('defect', ['tamper', 'missing', 'outside-root', 'extra-file', 'duplicate-json', 'oversize-json'])
def test_invalid_update_never_executes_or_falls_back(tmp_path, hosts, defect):
    state = tmp_path / 'state'
    application, pointer, value = managed(state)
    if defect == 'tamper':
        (application / 'local_app/server.py').write_text('changed')
    elif defect == 'missing':
        (application / 'local_app/server.py').unlink()
    elif defect == 'outside-root':
        value['root'] = '../../elsewhere'
        pointer.write_text(json.dumps(value))
    elif defect == 'extra-file':
        (application / 'unexpected.py').write_text('unlisted')
    elif defect == 'duplicate-json':
        pointer.write_text(pointer.read_text().replace('{', '{"schema":1,', 1))
    elif defect == 'oversize-json':
        pointer.write_text(' ' * 262145)
    result = select(tmp_path, state, hosts['0.23.32'])
    assert result.returncode == 1 and 'AX_RESOLVE:71' in result.stdout, result.stderr + result.stdout
    assert not (state / 'received.json').exists()


def test_literal_package_handoff_preserves_state_and_does_not_invoke_old_host(tmp_path, hosts):
    state = tmp_path / 'state 한글 & quote'
    managed(state)
    package = tmp_path / "설치 & key's $(name); 자료.axextension"
    package.write_bytes(b'PK fixture')
    sentinel = state / 'existing-conversation.json'
    sentinel.write_text('keep conversation and key fixture')
    result = subprocess.run([str(POWERSHELL), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(SCRIPT),
                             '-HostExe', str(hosts['0.23.31']), '-Package', str(package), '-StateRoot', str(state)],
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads((state / 'received.json').read_text(encoding='utf-8-sig'))
    assert record == {'state': str(state), 'package': str(package), 'exists': True}
    assert sentinel.read_text() == 'keep conversation and key fixture'
    assert package.read_bytes() == b'PK fixture'
    assert not (hosts['0.23.31'].parent / 'called.txt').exists()


def test_started_handoff_failure_never_falls_back_or_replays(tmp_path, hosts):
    state = tmp_path / 'state'
    managed(state, exit_code=55)
    package = tmp_path / 'package.zip'
    package.write_bytes(b'fixture')
    result = subprocess.run([str(POWERSHELL), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(SCRIPT),
                             '-HostExe', str(hosts['0.23.32']), '-Package', str(package), '-StateRoot', str(state)],
                            capture_output=True, timeout=20)
    assert result.returncode == 55, result.stdout + result.stderr
    assert (state / 'received.json').exists()
    assert not (hosts['0.23.32'].parent / 'called.txt').exists()


def test_missing_package_is_rejected_before_host_lookup(tmp_path):
    result = subprocess.run([str(POWERSHELL), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(SCRIPT),
                             '-HostExe', str(tmp_path / 'none.exe'), '-Package', str(tmp_path / 'missing.zip'),
                             '-StateRoot', str(tmp_path / 'state')], capture_output=True, timeout=20)
    assert result.returncode == 70


def test_package_size_uses_common_app_sixteen_mib_limit(tmp_path):
    package = tmp_path / 'oversize.axextension'
    with package.open('wb') as stream:
        stream.truncate(16 * 1024 * 1024 + 1)
    result = subprocess.run([str(POWERSHELL), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(SCRIPT),
                             '-HostExe', str(tmp_path / 'none.exe'), '-Package', str(package),
                             '-StateRoot', str(tmp_path / 'state')], capture_output=True, timeout=20)
    assert result.returncode == 70


def test_managed_selection_does_not_scan_installed_exe_capability(tmp_path, hosts):
    state = tmp_path / 'state'
    managed(state)
    result = run_ps("function Test-WorkspaceImportCapability { throw 'must not scan selected managed runtime' }; " +
                    "$v=Resolve-WorkspaceTarget " + quote(state) + ' ' + quote(hosts['0.23.31']) + '; Write-Output $v.kind', tmp_path)
    assert result.returncode == 0 and result.stdout.strip() == 'managed', result.stderr + result.stdout


def test_capability_marker_can_cross_read_boundary_without_loading_assembly(tmp_path):
    executable = tmp_path / 'marker.exe'
    executable.write_bytes(b'MZ' + b'\0' * 65529 + '--import-extension'.encode('utf-16-le'))
    result = run_ps('Test-WorkspaceImportCapability ' + quote(executable), tmp_path)
    assert result.returncode == 0 and result.stdout.strip() == 'True', result.stderr + result.stdout


def test_absent_owned_host_is_distinct_from_old_host(tmp_path, hosts):
    absent = select(tmp_path, tmp_path / 'state', tmp_path / 'absent.exe')
    assert absent.returncode == 1 and 'AX_RESOLVE:72' in absent.stdout
    unsupported = select(tmp_path, tmp_path / 'state', hosts['0.23.31'])
    assert unsupported.returncode == 1 and 'AX_RESOLVE:73' in unsupported.stdout
