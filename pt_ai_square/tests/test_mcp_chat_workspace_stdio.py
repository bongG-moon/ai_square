"""Real MCP stdio chat choices with isolated config and forbidden native windows."""
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sys

import pytest

from .test_local_mcp import PACKAGE, KEY, Settings, settings


RUNNER = '''import builtins, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from pt_square_mcp.server import make_server
import subprocess
original_import = builtins.__import__
def checked_import(name, *args, **kwargs):
    if name == 'tkinter' or name.startswith('tkinter.'):
        raise AssertionError('Native UI must not be imported')
    return original_import(name, *args, **kwargs)
builtins.__import__ = checked_import
def no_process(*args, **kwargs): raise AssertionError('Native picker must not be launched')
subprocess.Popen = no_process
Path.home = classmethod(lambda cls: Path(sys.argv[3]))
make_server(Path(sys.argv[2])).run(transport='stdio')
'''


def decoded(result):
    assert not result.isError, result.content
    return json.loads(result.content[0].text)


@pytest.mark.parametrize('purpose,mode', [
    ('publish','current'), ('install','current'), ('install','user'),
    ('publish','other'), ('publish','cancel'), ('publish','changed'),
    ('publish','fallback'),
])
def test_real_stdio_choices_no_native_window(settings,tmp_path,purpose,mode):
    pytest.importorskip('mcp')
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import ElicitResult, ListRootsResult, Root
    project = tmp_path/'current project'
    other = tmp_path/'other project'
    project.mkdir(); other.mkdir()
    roots = [project]
    before = settings.path.read_bytes()
    requests = []
    runner = tmp_path/'chat_runner.py'
    runner.write_text(RUNNER,encoding='utf-8')

    async def host_roots(_context):
        return ListRootsResult(roots=[Root(uri=path.as_uri(),name=path.name) for path in roots])

    async def choose(_context,request):
        document = request.model_dump(mode='json')
        requests.append(document)
        schema = document['requestedSchema']['properties']
        assert set(schema) == {'selection','path'}
        assert KEY not in json.dumps(document)
        current = schema['selection']['default']
        assert current.endswith(str(project))
        if mode == 'cancel':
            return ElicitResult(action='cancel')
        if mode == 'changed':
            roots[:] = [other]
        selected = '기타 경로' if mode == 'other' else '공통 (내 계정)' if mode == 'user' else current
        return ElicitResult(action='accept',content={'selection':selected,'path':str(other) if mode == 'other' else ''})

    async def scenario():
        params = StdioServerParameters(command=sys.executable,
            args=['-X','utf8','-B',str(runner),str(PACKAGE),str(settings.path),str(Path.home())],
            env=dict(os.environ,PTAI_API_TOKEN=KEY))
        with (tmp_path/'stdio-errors.txt').open('w',encoding='utf-8') as log:
            async with stdio_client(params,errlog=log) as (reader,writer):
                async with ClientSession(reader,writer,read_timeout_seconds=timedelta(seconds=15),
                        list_roots_callback=host_roots,
                        elicitation_callback=None if mode=='fallback' else choose) as session:
                    await session.initialize()
                    result = await session.call_tool('select_workspace',{'purpose':purpose})
                    if mode=='changed':
                        assert result.isError and '프로젝트가 바뀌었' in result.content[0].text
                        return
                    state = decoded(result)
                    if mode=='fallback':
                        assert state['status']=='pending' and state['defaultPath']==str(project)
                        assert requests==[] and settings.path.read_bytes()==before
                        state = decoded(await session.call_tool('select_workspace',{
                            'purpose':purpose,'request_id':state['requestId'],
                            'selection':'current','confirmed':True}))
                    if mode=='cancel':
                        assert state['status']=='cancelled' and not state['selected']
                    else:
                        assert state['selected'] and state['selectionMethod']=='chat'
                        expected = Path.home() if mode=='user' else other if mode=='other' else project
                        assert state['path']==str(expected)
    asyncio.run(scenario())
    assert not (project/'.claude').exists() and not (other/'.claude').exists()
    expected_grant = purpose=='publish' and mode not in {'cancel','changed'}
    if expected_grant:
        assert (other if mode=='other' else project) in Settings(settings.path).roots
    else:
        assert settings.path.read_bytes()==before
    assert Settings(settings.path).downloads==settings.downloads
    assert len(requests)==(0 if mode=='fallback' else 1)
    assert KEY not in (tmp_path/'stdio-errors.txt').read_text(encoding='utf-8')
