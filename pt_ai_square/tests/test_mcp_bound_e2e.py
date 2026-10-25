"""Run the actual website-downloaded ZIP against isolated Flask/Mongo fixtures."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import pytest
from .conftest import ready, publish
from .test_personal_api_usage import issue
from .test_receiver import server
from pt_ai_square.backend.storage import db

PACKAGE = Path(__file__).parents[1] / 'integrations' / 'pt-square-mcp'
sys.path.insert(0, str(PACKAGE))

@pytest.mark.skipif(os.name != 'nt', reason='The beginner connection stores Windows DPAPI credentials')
def test_downloaded_zip_connects_with_key_only_and_downloads_versions(app, server, tmp_path):
    owner, headers = ready(app)
    published = publish(owner, headers)
    assert published.status_code == 201
    tid = published.json['id']
    issued, _ = issue(owner, headers)
    app.config['PUBLIC_URL'] = server
    response = owner.get('/local-access/mcp.zip')
    assert response.status_code == 200
    extracted = tmp_path / 'unpacked'
    with ZipFile(io.BytesIO(response.data)) as archive:
        manifest = json.loads(archive.read('pt-square-mcp/connection.json'))
        assert manifest == {'schemaVersion': 1, 'baseUrl': server}
        assert 'pt-square-mcp/Connect.cmd' in archive.namelist()
        assert issued['token'].encode() not in b'\n'.join(archive.read(n) for n in archive.namelist())
        # This archive is generated from our reviewed source allowlist.
        archive.extractall(extracted)
    package = extracted / 'pt-square-mcp'
    home = tmp_path / 'fake-home'; home.mkdir()
    config = tmp_path / 'private' / 'config.json'
    env = dict(os.environ, USERPROFILE=str(home), HOME=str(home), PYTHONIOENCODING='utf-8',
               PYTHONPATH=str(package), SQUARE_TEST_KEY=issued['token'])
    env.pop('PTAI_API_TOKEN', None)
    script = '''
import json, os, sys
from pathlib import Path
from pt_square_mcp.onboarding import resolve_connection, connect
from pt_square_mcp.config import Settings, SquareError
from pt_square_mcp.runtime import Runtime
config = Path(sys.argv[1])
try:
    # No URL or workspace is passed. Only the test KEY is supplied privately.
    result = connect(config, resolve_connection(config), os.environ['SQUARE_TEST_KEY'], allow_http=True)
    runtime = Runtime(Settings(config))
    result['status'] = runtime.connection_status()
    result['download'] = runtime.download_item(int(sys.argv[2]), update=sys.argv[3] == 'update')
    print(json.dumps(result))
except SquareError as error:
    print(str(error), file=sys.stderr)
    sys.exit(1)
'''
    def run(mode='initial'):
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', script, str(config), str(tid), mode],
                                cwd=package, env=env, capture_output=True, text=True, encoding='utf-8', timeout=40)
        assert issued['token'] not in result.stdout + result.stderr
        return result
    first = run()
    assert first.returncode == 0, first.stderr
    result = json.loads(first.stdout)
    assert result['connected'] is True and result['user']['id'] == 'owner'
    assert result['status']['connected'] is True
    assert result['credentialStored'] == 'windows-dpapi'
    automatic = home / 'AI_SQUARE' / 'downloads'
    assert Path(result['downloadDirectory']) == automatic
    folder = automatic / ('server-' + hashlib.sha256(server.encode()).hexdigest()[:12]) / f'tool-{tid}'
    assert Path(result['download']['file']).parent == folder / 'v1'
    stored = config.read_bytes()
    assert issued['token'].encode() not in stored
    for credential in config.parent.glob('credential.*.dpapi.json'):
        assert issued['token'].encode() not in credential.read_bytes()
    # Invalid authentication cannot overwrite a working connection or its file.
    env['SQUARE_TEST_KEY'] = 'ptsq_' + 'x' * 43
    rejected = run()
    assert rejected.returncode == 1 and 'ptsq_' not in rejected.stderr
    assert config.read_bytes() == stored
    env['SQUARE_TEST_KEY'] = issued['token']
    assert run().returncode == 0  # verified cached download
    assert owner.get(f'/api/tools/{tid}').json['downloads'] == 1
    version = publish(owner, headers, tid=tid, revision=1, changes='Version two')
    assert version.status_code == 201, version.json
    updated = run('update')
    assert updated.returncode == 0, updated.stderr
    result = json.loads(updated.stdout)
    assert Path(result['download']['file']).parent == folder / 'v2'
    assert list((folder / 'v1').iterdir())
    assert owner.get(f'/api/tools/{tid}').json['downloads'] == 1


@pytest.mark.skipif(os.name != 'nt', reason='The packaged connection stores Windows DPAPI credentials')
def test_downloaded_zip_chat_publishes_new_and_owned_update_without_web_approval(app, server, tmp_path, monkeypatch):
    owner, headers = ready(app)
    issued, _ = issue(owner, headers)
    # Existing valid web KEYs use the same flow without requiring rotation.
    with app.app_context():
        db().local_tokens.update_one({'id': issued['id']}, {'$set': {'scope': 'read'}})
    def forbidden():
        pytest.fail('No browser approval endpoint is needed for confirmed MCP publishing')
    monkeypatch.setitem(app.view_functions, 'publish_drafts.approve', forbidden)
    app.config['PUBLIC_URL'] = server
    response = owner.get('/local-access/mcp.zip')
    assert response.status_code == 200
    extracted = tmp_path / 'unpacked'
    with ZipFile(io.BytesIO(response.data)) as archive:
        assert json.loads(archive.read('pt-square-mcp/connection.json'))['baseUrl'] == server
        archive.extractall(extracted)
    package = extracted / 'pt-square-mcp'
    home = tmp_path / 'fake-home'; home.mkdir()
    source = tmp_path / 'explicit-chat-project'; source.mkdir()
    (source / 'SKILL.md').write_text('# Original memo summary\n', encoding='utf-8')
    config = tmp_path / 'private' / 'config.json'
    env = dict(os.environ, USERPROFILE=str(home), HOME=str(home), PYTHONIOENCODING='utf-8',
               PYTHONPATH=str(package), SQUARE_TEST_KEY=issued['token'])
    env.pop('PTAI_API_TOKEN', None)
    script = '''
import json, os, sys
from pathlib import Path
from pt_square_mcp.onboarding import resolve_connection, connect
from pt_square_mcp.config import Settings, SquareError
from pt_square_mcp.runtime import Runtime
from pt_square_mcp.workspace_selection import start_selection, submit_selection
config, source = map(Path, sys.argv[1:3])
connected = connect(config, resolve_connection(config), os.environ['SQUARE_TEST_KEY'], allow_http=True)
candidate = {'path': str(source), 'source': 'mcp-roots', 'name': 'Explicit test project'}
selection = start_selection(config, 'publish', {'currentProject': candidate, 'projectCandidates': [candidate]})
assert submit_selection(config, selection['requestId'], 'current', confirmed=True)['selected']
runtime = Runtime(Settings(config))
values = dict(name='Packaged MCP memo', desc='Summarize fixture notes', platform='Claude', type='Skill',
              guide='Use the package in the chosen project', orgId='organization-0', categoryId='category-0',
              approval=False, changes='First version', workTags=['memo'],
              packageId='fixture.packaged-memo', entryPoint='SKILL.md')
first = runtime.prepare_publish(values, str(source), target='new')
assert first['approvalMethod'] == 'chat' and not first['serverReviewRequired']
assert first['requiresConfirmation']
blocked = False
try:
    runtime.publish_item(first['id'])
except SquareError:
    blocked = True
created = runtime.publish_item(first['id'], review_digest=first['reviewDigest'], confirmed=True)
replayed = runtime.publish_item(first['id'])
first_file = runtime.download_item(created['id'])
(source / 'SKILL.md').write_text('# Updated memo and action items\\n', encoding='utf-8')
values['changes'] = 'Add action items'
second = runtime.prepare_publish(values, str(source), target='update', tool_id=created['id'])
updated = runtime.publish_item(second['id'], review_digest=second['reviewDigest'], confirmed=True)
second_file = runtime.download_item(created['id'], update=True)
print(json.dumps({'blockedWithoutConfirmation': blocked, 'created': created, 'replayed': replayed,
                 'updated': updated, 'firstFile': first_file, 'secondFile': second_file,
                 'connection': runtime.connection_status(), 'downloads': str(runtime.settings.downloads)}))
'''
    completed = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', script, str(config), str(source)],
                               cwd=package, env=env, capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert issued['token'] not in completed.stdout + completed.stderr
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result['blockedWithoutConfirmation']
    tid = result['created']['id']
    assert result['created']['version'] == result['replayed']['version'] == 1
    assert result['updated']['id'] == tid and result['updated']['version'] == 2
    assert result['connection']['user']['id'] == 'owner'
    assert Path(result['downloads']) == home / 'AI_SQUARE' / 'downloads'
    assert Path(result['firstFile']['file']).is_file() and Path(result['secondFile']['file']).is_file()
    assert issued['token'].encode() not in config.read_bytes()
    assert owner.get('/api/local-tokens').json['usage'] == {'uploads': 2, 'downloads': 1}
    with app.app_context():
        assert db().tools.count_documents({}) == 1
        tool = db().tools.find_one({'_id': tid})
        assert tool['owner'] == 'owner' and len(tool['versions']) == 2
        assert all(version['apiUsage']['tokenId'] == issued['id'] for version in tool['versions'])
        assert db().publish_drafts.count_documents({'status': 'committed'}) == 2
        assert db().local_tokens.find_one({'id': issued['id']})['scope'] == 'read'


@pytest.mark.parametrize('suffix', ['', '.new'])
def test_encrypted_generation_files_cannot_be_packaged(tmp_path, suffix):
    from pt_square_mcp.files import source_files, validate_publish_archive
    from pt_square_mcp.config import SquareError
    name = 'credential.' + 'a' * 32 + '.dpapi.json' + suffix
    source = tmp_path / 'source'; source.mkdir()
    (source / name).write_text('{"encrypted":"private encrypted content"}')
    with pytest.raises(SquareError):
        source_files(source, [tmp_path])
    data = io.BytesIO()
    with ZipFile(data, 'w') as archive:
        archive.writestr('nested/' + name, '{}')
    data.seek(0)
    with ZipFile(data) as archive, pytest.raises(SquareError):
        validate_publish_archive(archive)
