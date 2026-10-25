"""Legacy connection preset ZIP -> native install helper -> packaged worker.

The synthetic ZIP here tests compatibility with an already-prepared installer
and connection.json; it does not prescribe the current publisher package format.
The web no longer assembles this package. Administrator upload and original-byte
member download are covered by pt_ai_square/tests/test_ax_workspace.py, and the
current publisher format has test_upload_package.py. This test uses isolated
local state and loopback, and never executes the interactive NSIS setup.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import pytest

from test_http_worker import service, TOKEN
from test_package import builder, CSC


@pytest.mark.skipif(os.name != 'nt' or not CSC.is_file(), reason='Windows installer and DPAPI')
@pytest.mark.skipif(not builder.host_source_available(),
                    reason='Actual AX integration: set AX_WORKSPACE_SOURCE to a compatible common-app source checkout')
@pytest.mark.skipif(not builder.nsis_compiler().is_file(),
                    reason='Actual NSIS EXE integration: set NSIS_MAKENSIS to an existing NSIS 3.12 makensis.exe')
def test_legacy_preset_zip_installs_and_authenticates_with_only_key(service, tmp_path):
    origin, _ = service
    build = builder.build(tmp_path / 'build')
    source = Path(build['installerExe'])
    installer = source.read_bytes()
    prepared = tmp_path / 'publisher' / 'PNT-AI-Square-AX-Extension.zip'
    prepared.parent.mkdir()
    with ZipFile(prepared, 'w') as archive:
        archive.writestr('PNT-AI-Square-Setup.exe', installer)
        archive.writestr('connection.json', json.dumps({'schemaVersion': 1, 'baseUrl': origin}))
    download = tmp_path / 'download'
    download.mkdir()
    with ZipFile(prepared) as archive:
        assert archive.read('PNT-AI-Square-Setup.exe') == installer
        preset = archive.read('connection.json')
        assert json.loads(preset) == {'schemaVersion': 1, 'baseUrl': origin}
        assert all(TOKEN.encode() not in archive.read(name) for name in archive.namelist())
    (download / 'connection.json').write_bytes(preset)
    root = tmp_path / 'isolated-state'
    result = subprocess.run([str(build['supportExe']), 'install', str(root), str(build['package']),
                             str(builder.HOST), str(download / 'connection.json')],
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr.decode('utf-8', 'replace')
    extension = root / 'extensions' / 'pt-ai-square.store'
    data = root / 'extension-data' / 'pt-ai-square.store'
    manifest = json.loads((extension / 'extension.json').read_text(encoding='utf-8'))
    script = extension / manifest['entrypoint']
    assert hashlib.sha256(script.read_bytes()).hexdigest() == manifest['files'][manifest['entrypoint']]

    def call(action, payload=None):
        request = {'protocol': 1, 'action': action, 'payload': payload or {},
                   'dataDirectory': str(data), 'context': {}}
        env = {k: v for k, v in os.environ.items() if k not in {'PTAI_API_TOKEN', 'CLAUDE_CONFIG_DIR'}}
        process = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(script)],
                                 input=json.dumps(request).encode(), capture_output=True,
                                 env=env, timeout=15)
        assert process.returncode == 0 and not process.stderr
        assert TOKEN.encode() not in process.stdout
        return json.loads(process.stdout)

    status = call('status')['result']
    assert status['presetBaseUrl'] == origin and not status['configured']
    assert not call('connect', {'key': TOKEN})['ok']  # HTTP consent stays explicit.
    assert call('connect', {'key': TOKEN, 'allowHttp': True})['ok']
    assert call('status')['result']['baseUrl'] == origin
    # A later installer preset does not redirect an authenticated user's KEY.
    (data / 'connection.json').write_text(json.dumps({'schemaVersion': 1, 'baseUrl': 'https://other.example'}))
    assert call('status')['result']['baseUrl'] == origin
    assert all(TOKEN.encode() not in path.read_bytes() for path in data.rglob('*') if path.is_file())
    remove = subprocess.run([str(build['supportExe']), 'uninstall', str(root)], capture_output=True, timeout=20)
    assert remove.returncode == 0, remove.stderr.decode('utf-8', 'replace')
    assert (data / 'connection.json').exists()
    assert (data / 'connection' / 'config.json').exists()
    assert source.read_bytes() == installer
