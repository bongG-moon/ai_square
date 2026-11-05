"""MCP preserves server ranking and exposes the recommendation evidence contract."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

PACKAGE = Path(__file__).parents[1] / 'integrations' / 'pt-square-mcp'
sys.path.insert(0, str(PACKAGE))
from pt_square_mcp.runtime import Runtime


@pytest.mark.parametrize('sort', ['recommended', 'realtime', 'cumulative', 'newest'])
def test_search_preserves_badges_peer_metadata_server_order_and_explicit_sort(sort):
    # The first result is deliberately unbadged: text relevance and explicit
    # sorts must not be replaced by a client-side badge-only ranking.
    response = {'items': [
        {'id': 10, 'recommendationBadge': {'active': False, 'status': 'none'}},
        {'id': 20, 'recommendationBadge': {'active': True, 'status': 'active',
                                         'reason': '회의에서 나온 할 일을 정리합니다.', 'reviewedVersion': 2}},
        {'id': 30, 'access': 'required', 'recommendationBadge': {'active': True, 'status': 'active'}},
    ], 'recommendation': {'basis': 'sso_department'}, 'total': 3}
    calls = []
    def query(path):
        calls.append(path)
        return response
    runtime = Runtime.__new__(Runtime)
    runtime.client = SimpleNamespace(json=query)
    result = runtime.search_items('회의에서 나온 할 일 정리', sort=sort, offset=0, limit=10)
    assert result is response
    assert [item['id'] for item in result['items']] == [10, 20, 30]
    assert 'reason' not in result['items'][2]['recommendationBadge']
    assert result['recommendation']['basis'] == 'sso_department'
    parsed = urlsplit(calls[0])
    assert parsed.path == '/api/catalog'
    assert parse_qs(parsed.query)['sort'] == [sort]
    assert parse_qs(parsed.query)['q'] == ['회의에서 나온 할 일 정리']


def test_advertised_search_guidance_preserves_evidence_and_read_only_boundary(tmp_path):
    pytest.importorskip('mcp')
    from pt_square_mcp.server import make_server
    server = make_server(tmp_path / 'absent-config.json')
    tool = next(tool for tool in asyncio.run(server.list_tools()) if tool.name == 'search_items')
    assert tool.annotations.readOnlyHint is True
    assert tool.inputSchema['properties']['sort']['default'] == 'recommended'
    assert 'recommendationBadge.active=true' in tool.description
    assert 'reason과 reviewedVersion' in tool.description
    assert '명시한 정렬은 유지' in tool.description
    assert '보안 인증이나 모든 버전의 품질 보증이 아닙니다' in tool.description
    assert '관련 없는 도구를 추천 배지만 보고 앞으로 옮기지 마세요' in server.instructions
    assert 'needs_review' in server.instructions
    assert list(tmp_path.iterdir()) == []
