"""Real host selection -> Store -> canonical ZIP installer, isolated profiles.

The download client and worker transport are local test adapters. Host HTTP,
capability validation, plans, installation and files are real. No production
platform, real Claude profile, install command or child server is used.
"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import zipfile

import pytest

HERE = Path(__file__).resolve().parents[1]
HOST = Path(os.environ.get('AX_WORKSPACE_SOURCE', HERE.parent/'build/workspace-local-repository'))
if not (HOST/'local_app/extensions.py').is_file():
    pytest.skip('AX_WORKSPACE_SOURCE is required for cross-app integration checks', allow_module_level=True)
sys.path.insert(0, str(HOST))
from local_app.server import LocalApp, Server

spec = importlib.util.spec_from_file_location('organization_store_install_integration', HERE/'worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class DownloadClient:
    origin = 'https://store.example.test'
    skill = b'---\nname: fixture-store\ndescription: Integration fixture\n---\n# Fixture\n'

    def __init__(self):
        content = io.BytesIO()
        with zipfile.ZipFile(content, 'w') as archive:
            archive.writestr('SKILL.md', self.skill)
            archive.writestr('references/example.txt', 'Packaged reference')
        self.content = content.getvalue()
        self.downloads = 0

    def manifest(self, tool_id):
        return dict(toolId=tool_id, release=1, name='Fixture', filename='fixture.zip',
                    downloadUrl='/download/1/1', bytes=len(self.content),
                    sha256=hashlib.sha256(self.content).hexdigest(),
                    installProfile=dict(schemaVersion=1, kind='skill', host='claude',
                                        slug='fixture-store', scopes=['project', 'user'], entrypoint='SKILL.md'))

    def download(self, manifest, directory, *, update=False):
        self.downloads += 1
        directory.mkdir(parents=True, exist_ok=True)
        path = directory/manifest['filename']
        path.write_bytes(self.content)
        return path


@pytest.fixture
def integration(tmp_path):
    current, target, home = (tmp_path/name for name in ('current', 'target', 'home'))
    for path in (current, target, home):
        path.mkdir()
    package = tmp_path/'extensions/example.store'
    package.mkdir(parents=True)
    contents = {'worker.py': '# runner adapter; never executed', 'ui.html': '<!doctype html><title>Fixture</title>'}
    for name, text in contents.items():
        (package/name).write_text(text, encoding='utf-8')
    manifest = dict(schemaVersion=1, id='example.store', name='Fixture', version='1.0.0', hostApi=1,
                    entrypoint='worker.py', ui='ui.html', actions=['prepareInstall', 'install', 'verify'],
                    files={name: hashlib.sha256((package/name).read_bytes()).hexdigest() for name in contents})
    (package/'extension.json').write_text(json.dumps(manifest), encoding='utf-8')
    app = LocalApp(tmp_path/'state', command=['never-start'], managed_workspace_root=tmp_path/'managed')
    server = Server(app, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        current_id = app.create(str(current), True)['id']
        target_id = app.create(str(target), True)['id']
        app.sessions[target_id]['trusted'] = False
        app.drafts.update({'id': current_id, 'revision': 0,
                           'draft': {'text': '작성 중인 내용 유지', 'attachments': []},
                           'stash': None, 'selectedId': current_id})
        draft_before = app.drafts.snapshot()
        client = DownloadClient()

        def runner(*args, **kwargs):
            request = json.loads(kwargs['input'])
            data = Path(request['dataDirectory'])
            store = worker.Store(data, request['context'], home=home, existing_config=tmp_path/'unused.json')
            if not store.config_path.exists():
                (data/'downloads').mkdir()
                worker.save_config(store.config_path, client.origin, [data], download_directory=data/'downloads')
                worker.atomic_json(store.selection_path, {'mode': 'local'})
            store.client_factory = lambda settings: client
            result = store.dispatch(request['action'], request['payload'])
            return subprocess.CompletedProcess([], 0, json.dumps({'ok': True, 'result': result}).encode(), b'')

        app.extensions.runner = runner

        def post(operation, data):
            headers = {'Authorization': 'Bearer '+app.token, 'Origin': server.origin, 'Content-Type': 'application/json'}
            request = Request(server.origin+'/api/extensions/example.store/'+operation, json.dumps(data).encode(), headers)
            with urlopen(request, timeout=10) as response:
                return json.load(response)

        def action(name, payload, token=None):
            data = {'action': name, 'payload': payload, 'sessionId': current_id}
            if token:
                data['directoryToken'] = token
            return post('action', data)['result']

        yield SimpleNamespace(app=app, current=current, target=target, home=home, current_id=current_id,
                              target_id=target_id, client=client, draft_before=draft_before, post=post, action=action)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
        app.close()


@pytest.mark.parametrize('scope', ['directory', 'user'])
def test_real_zip_installs_to_selected_work_or_common_without_switching_task(integration, scope):
    ctx = integration
    listed = ctx.post('workspaces', {})
    assert {row['id'] for row in listed['items']} == {ctx.current_id, ctx.target_id}
    selected = ctx.post('workspace', {'sessionId': ctx.target_id})
    token = selected['directoryToken'] if scope == 'directory' else None
    plan = ctx.action('prepareInstall', {'toolId': 1, 'scope': scope}, token)
    installed = ctx.action('install', dict(plan, confirmed=True), token)
    destination = ctx.target if scope == 'directory' else ctx.home
    assert installed['installed']
    assert (destination/'.claude/skills/fixture-store/SKILL.md').read_bytes() == ctx.client.skill
    assert (destination/'.claude/skills/fixture-store/references/example.txt').read_text() == 'Packaged reference'
    assert ctx.action('verify', {'installationId': installed['installationId']})['filesIntact']
    assert not (ctx.current/'.claude').exists()
    assert not ((ctx.home if scope == 'directory' else ctx.target)/'.claude').exists()
    assert ctx.app.drafts.snapshot() == ctx.draft_before
    assert ctx.app.sessions[ctx.target_id]['trusted'] is False
    assert ctx.client.downloads == 1


@pytest.mark.parametrize('change', ['archive', 'folder'])
def test_prepared_work_install_rejects_changed_task_before_writing(integration, tmp_path, change):
    ctx = integration
    selected = ctx.post('workspace', {'sessionId': ctx.target_id})
    token = selected['directoryToken']
    plan = ctx.action('prepareInstall', {'toolId': 1, 'scope': 'directory'}, token)
    other = tmp_path/'changed'; other.mkdir()
    if change == 'archive':
        ctx.app.session_visibility.set_hidden(ctx.target_id, True)
    else:
        ctx.app.sessions[ctx.target_id]['workspace'] = str(other)
    with pytest.raises(HTTPError) as caught:
        ctx.action('install', dict(plan, confirmed=True), token)
    assert caught.value.code in {400, 403}
    assert not (ctx.target/'.claude').exists() and not (other/'.claude').exists()
    assert not (ctx.current/'.claude').exists() and not (ctx.home/'.claude').exists()
    assert ctx.app.drafts.snapshot() == ctx.draft_before
    assert ctx.app.sessions[ctx.target_id]['trusted'] is False
