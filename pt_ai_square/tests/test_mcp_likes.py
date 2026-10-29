"""Actual MCP stdio calls use the same per-user like API as the website."""
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sys

import pytest

from .conftest import ready, publish
from .test_personal_api_usage import issue
from .test_receiver import server
from pt_ai_square.backend.storage import db

PACKAGE = Path(__file__).resolve().parents[1] / 'integrations' / 'pt-square-mcp'
sys.path.insert(0, str(PACKAGE))
from pt_square_mcp.client import Client
from pt_square_mcp.config import Settings, SquareError, save_config
from pt_square_mcp.runtime import Runtime


def test_like_client_allowlist_is_limited_to_exact_desired_state_endpoint(tmp_path):
    path = tmp_path / 'config.json'
    save_config(path, 'http://127.0.0.1:1111', [tmp_path], allow_http=True)
    client = Client(Settings(path))
    for method, endpoint in [('PUT', '/api/tools/1'),
                             ('PUT', '/api/tools/1/subscription'),
                             ('PUT', '/api/tools/1/like?x=1'),
                             ('POST', '/api/tools/1/like'),
                             ('GET', '/api/tools/1/like'),
                             ('PATCH', '/api/tools/1/like')]:
        with pytest.raises(SquareError, match='허용되지 않은'):
            client.open(endpoint, method)
    with pytest.raises(SquareError, match='true 또는 false'):
        Runtime(Settings(path)).like_item(1, 'false')
    with pytest.raises(SquareError, match='양의 정수'):
        Runtime(Settings(path)).like_item(True, True)


def test_stdio_like_and_unlike_are_idempotent_and_enforce_access(app, server, tmp_path):
    pytest.importorskip('mcp')
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    owner, headers = ready(app)
    public = publish(owner, headers)
    restricted = publish(owner, headers, approval=True)
    assert public.status_code == restricted.status_code == 201
    member, member_headers = ready(app, 'member')
    key, auth = issue(member, member_headers, scope='read')
    config = tmp_path / 'config.json'
    save_config(config, server, [tmp_path], allow_http=True)
    home = tmp_path / 'home'
    home.mkdir()

    async def scenario():
        params = StdioServerParameters(
            command=sys.executable,
            args=['-X', 'utf8', '-B', str(PACKAGE/'run_mcp.py'), '--config', str(config), 'serve'],
            env=dict(os.environ, PTAI_API_TOKEN=key['token'], USERPROFILE=str(home), HOME=str(home)))
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=20)) as session:
                await session.initialize()
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                assert {'tool_id', 'liked'} <= set(tools['like_item'].inputSchema['required'])
                async def call(tid, liked):
                    response = await session.call_tool('like_item', {'tool_id': tid, 'liked': liked})
                    assert key['token'] not in str(response.content)
                    return response
                for liked, count in [(True, 1), (True, 1), (False, 0), (False, 0)]:
                    response = await call(public.json['id'], liked)
                    assert not response.isError, response.content
                    value = json.loads(response.content[0].text)
                    assert value['liked'] is liked and value['count'] == count
                denied = await call(restricted.json['id'], True)
                assert denied.isError
                invalid = await call(public.json['id'], 'false')
                assert invalid.isError

    asyncio.run(scenario())
    api = app.test_client()
    assert api.get(f"/api/tools/{public.json['id']}", headers=auth).json['liked'] is False
    with app.app_context():
        assert db().activity_state.count_documents({'user':'member', 'tool':restricted.json['id'], 'kind':'like'}) == 0
        assert db().activity_state.count_documents({'user':'member', 'tool':public.json['id'], 'kind':'like'}) == 1
