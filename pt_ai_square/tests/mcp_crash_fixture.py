"""Subprocess-only deterministic hard exits, confined to a caller's temp root."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'integrations/pt-square-mcp'))
from pt_square_mcp.config import Settings, save_config
from pt_square_mcp.install import Installer
from pt_square_mcp import install as engine
from pt_square_mcp import transactions


class FixtureClient:
    def __init__(self, kind, directory):
        self.kind, self.directory, self.release = kind, directory, 1
    def json(self, path):
        assert path == '/api/integration/me'
        return {'user': {'id': 'crash-fixture-user'}}
    def content(self):
        raw = ('# version ' + str(self.release) + '\n').encode()
        if self.kind == 'skill':
            return raw
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr(zipfile.ZipInfo('server.py', (2020, 1, 1, 0, 0, 0)), raw)
        return output.getvalue()
    def manifest(self, tool_id):
        profile = dict(schemaVersion=1, kind=self.kind, host='claude', slug='crash-fixture',
                       scopes=['project', 'user'], entrypoint='SKILL.md' if self.kind == 'skill' else 'server.py')
        if self.kind == 'mcp':
            profile['command'] = {'executable': 'python', 'args': ['{entrypoint}', '--version=' + str(self.release)]}
        return dict(toolId=1, release=self.release, filename='fixture.md' if self.kind == 'skill' else 'fixture.zip',
                    bytes=len(self.content()), sha256=hashlib.sha256(self.content()).hexdigest(),
                    downloadUrl=f'/download/1/{self.release}', installProfile=profile)
    def download(self, manifest, directory, *, update=False):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory/manifest['filename']; path.write_bytes(self.content())
        with (self.directory/'network-calls').open('a') as trace:
            trace.write('download\n')
        return path


def setup(directory, kind):
    data, project, home = [directory/name for name in ('data', 'project', 'home')]
    for path in (data, project, home):
        path.mkdir(parents=True, exist_ok=True)
    config = data/'config.json'
    if not config.exists():
        save_config(config, 'https://crash-fixture.example.test', [data, project], download_directory=data)
    return Installer(Settings(config), FixtureClient(kind, directory), home=home), project


def main():
    directory, kind, mode, crash_point = Path(sys.argv[1]), *sys.argv[2:]
    installer, project = setup(directory, kind)
    config_path = project/'.mcp.json'
    if kind == 'mcp':
        engine.atomic_json(config_path, {'mcpServers': {'unrelated': {'command': 'keep'}}, 'preference': True})
    installed = None
    if mode != 'first':
        plan = installer.prepare(1, 'project', str(project))
        installed = installer.install(plan['planId'], plan['approvalDigest'], True)
    if mode == 'rollback_update':
        installer.client.release = 2
        plan = installer.prepare(1, 'project', str(project))
        installed = installer.install(plan['planId'], plan['approvalDigest'], True)
    elif mode == 'update':
        installer.client.release = 2
    plan = None if mode.startswith('rollback') else installer.prepare(1, 'project', str(project))
    target = (project/'.claude/skills/crash-fixture' if kind == 'skill'
              else project/'.pt-ai-square/tools/crash-fixture')
    old_json, old_move, old_rename, old_begin = engine.atomic_json, engine.shutil.move, Path.rename, transactions.begin
    def hard_exit(point):
        if crash_point == point:
            os._exit(93)
    def atomic(path, value):
        if Path(path) == installer.record_path:
            hard_exit('record_before')
        result = old_json(path, value)
        if Path(path) == installer.record_path:
            hard_exit('record_after')
        if Path(path) == config_path:
            hard_exit('config_after')
        return result
    def move(source, destination, *args, **kwargs):
        result = old_move(source, destination, *args, **kwargs)
        if Path(source) == target:
            hard_exit('old_moved')
        if Path(destination) == target:
            hard_exit('new_moved')
        return result
    def rename(source, destination):
        result = old_rename(source, destination)
        if source == target:
            hard_exit('old_moved')
        return result
    def begin(*args, **kwargs):
        result = old_begin(*args, **kwargs)
        hard_exit('journal')
        return result
    engine.atomic_json, engine.shutil.move, Path.rename, transactions.begin = atomic, move, rename, begin
    if mode.startswith('rollback'):
        installer.rollback(installed['installationId'], True)
    else:
        installer.install(plan['planId'], plan['approvalDigest'], True)
    raise AssertionError('Crash injection was not reached: ' + crash_point)


if __name__ == '__main__':
    main()
