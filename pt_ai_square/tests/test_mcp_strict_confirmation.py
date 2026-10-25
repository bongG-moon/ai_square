"""Official SDK validation must not coerce strings/numbers into user consent."""
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sys

import pytest

pytest.importorskip('mcp')
PACKAGE = Path(__file__).parents[1] / 'integrations' / 'pt-square-mcp'
sys.path.insert(0, str(PACKAGE))
from pt_square_mcp.server import make_server


ARGUMENTS = {
    'select_workspace': {'purpose': 'publish', 'request_id': 'a' * 32,
                         'selection': 'other', 'path': 'C:/isolated-fixture'},
    'install_item': {'plan_id': 'fixture-plan', 'approval_digest': 'a' * 64},
    'rollback_install': {'installation_id': 'fixture-installation'},
    'publish_item': {'draft_id': '12345678-1234-1234-1234-123456789abc', 'review_digest': 'a' * 64},
}


def replace_handlers(server, calls):
    """Keep generated SDK argument models; replace only side-effect handlers."""
    for name in ARGUMENTS:
        tool = server._tool_manager.get_tool(name)
        def handler(_name=name, **kwargs):
            calls.append((_name, kwargs['confirmed']))
            return {'tool': _name, 'confirmed': kwargs['confirmed']}
        async def async_handler(_handler=handler, **kwargs):
            return _handler(**kwargs)
        tool.fn = async_handler if tool.is_async else handler


@pytest.mark.parametrize('name', ARGUMENTS)
@pytest.mark.parametrize('invalid', [1, 0, 'true', 'false', 'yes', None, []])
def test_fastmcp_rejects_non_boolean_confirmation_before_handler(tmp_path, name, invalid):
    server = make_server(tmp_path / 'absent-config.json')
    calls = []
    replace_handlers(server, calls)
    with pytest.raises(Exception, match='(?i)(boolean|bool_type)'):
        asyncio.run(server.call_tool(name, dict(ARGUMENTS[name], confirmed=invalid)))
    assert calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('name', ARGUMENTS)
@pytest.mark.parametrize('confirmed', [False, True])
def test_fastmcp_preserves_real_boolean_confirmation(tmp_path, name, confirmed):
    server = make_server(tmp_path / 'absent-config.json')
    calls = []
    replace_handlers(server, calls)
    asyncio.run(server.call_tool(name, dict(ARGUMENTS[name], confirmed=confirmed)))
    assert calls == [(name, confirmed)]
    assert type(calls[0][1]) is bool
    assert list(tmp_path.iterdir()) == []


STDIO_FIXTURE = '''import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from pt_square_mcp.server import make_server
server = make_server(Path(sys.argv[2]) / 'absent-config.json')
trace = Path(sys.argv[2]) / 'handler-calls.jsonl'
for name in ('select_workspace', 'install_item', 'rollback_install', 'publish_item'):
    tool = server._tool_manager.get_tool(name)
    def handler(_name=name, **kwargs):
        result = {'tool': _name, 'confirmed': kwargs['confirmed']}
        with trace.open('a', encoding='utf-8') as output:
            output.write(json.dumps(result) + '\\n')
        return result
    async def async_handler(_handler=handler, **kwargs):
        return _handler(**kwargs)
    tool.fn = async_handler if tool.is_async else handler
server.run(transport='stdio')
'''


def test_actual_stdio_rejects_coercion_and_preserves_boolean_values(tmp_path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    script = tmp_path / 'strict_confirmation_host.py'
    script.write_text(STDIO_FIXTURE, encoding='utf-8')
    expected = []
    async def scenario():
        params = StdioServerParameters(command=sys.executable,
            args=['-X', 'utf8', '-B', str(script), str(PACKAGE), str(tmp_path)],
            cwd=str(tmp_path), env={k: v for k, v in os.environ.items() if k != 'PTAI_API_TOKEN'})
        with (tmp_path / 'stdio-stderr.txt').open('w', encoding='utf-8') as errors:
            async with stdio_client(params, errlog=errors) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=15)) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    for name, arguments in ARGUMENTS.items():
                        schema = next(tool for tool in listing.tools if tool.name == name).inputSchema
                        assert schema['properties']['confirmed']['type'] == 'boolean'
                        assert schema['properties']['confirmed']['default'] is False
                        for invalid in (1, 'true', 'yes'):
                            result = await session.call_tool(name, dict(arguments, confirmed=invalid))
                            assert result.isError, (name, invalid, result.content)
                        for confirmed in (False, True):
                            result = await session.call_tool(name, dict(arguments, confirmed=confirmed))
                            assert not result.isError, result.content
                            value = json.loads(result.content[0].text)
                            assert value == {'tool': name, 'confirmed': confirmed}
                            assert type(value['confirmed']) is bool
                            expected.append(value)
    asyncio.run(scenario())
    actual = [json.loads(line) for line in (tmp_path / 'handler-calls.jsonl').read_text().splitlines()]
    assert actual == expected
    assert len(actual) == 8
    assert not (tmp_path / 'absent-config.json').exists()
