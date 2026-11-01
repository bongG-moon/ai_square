"""Browser cookies and MCP use the same search, facets and public summaries."""
import json

from pt_ai_square.backend import catalog_search
from pt_ai_square.backend.storage import db
from .conftest import ready
from .test_catalog_recommendations import seed, vote
from .test_organization_store import worker


def ids(result):
    return [row['id'] for row in result['items']]


def test_browser_and_mcp_natural_request_return_identical_candidates_and_order(app):
    seed(app, 1, 'HTML 보고서 만들기', data={'type': 'Skill', 'desc': '분기 실적을 부서별로 분석해 보고서를 작성합니다.', 'workTags': ['보고서', '실적'], 'approval': True})
    seed(app, 2, '업무 기록 모아 보기', data={'type': 'Skill', 'desc': '지난 업무를 보고서로 정리합니다.', 'workTags': ['보고서']})
    seed(app, 3, '엑셀 비교', data={'type': 'Skill', 'desc': '두 표의 차이를 찾습니다.', 'workTags': ['엑셀']})
    browser, headers = ready(app, 'member')
    issued = browser.post('/api/local-tokens', headers=headers, json={'name': 'same-account'})
    auth = {'Authorization': 'Bearer ' + issued.json['token']}
    api = app.test_client()

    class Adapter:
        def json(self, path):
            response = api.get(path, headers=auth)
            assert response.status_code == 200
            return response.json

    runtime = worker.Runtime.__new__(worker.Runtime)
    runtime.client = Adapter()
    query = '분기 실적을 부서별로 분석해서 보고서를 만들고 싶어요'
    web = browser.get('/api/catalog', query_string={'q': query, 'sort': 'recommended', 'limit': 12, 'facets': 'organizations'})
    mcp = runtime.search_items(query, limit=12)
    assert web.status_code == 200 and web.headers['Cache-Control'] == 'no-store'
    assert ids(web.json) == ids(mcp) == [1, 2]
    assert web.json['queryInterpretation'] == mcp['queryInterpretation']
    assert web.json['items'][0]['access'] == 'permission_required'
    for text in ('PRIVATE GUIDE', 'PRIVATE FLOW', 'PRIVATE PATH', 'SECRET PACKAGE'):
        assert text not in json.dumps(web.json)
    assert browser.get('/api/tools/1').status_code == api.get('/api/tools/1', headers=auth).status_code == 403


def test_organization_facets_keep_query_type_category_but_ignore_selected_organization(app):
    with app.app_context():
        db().taxonomy.insert_one({'_id': 'org-b', 'kind': 'organization', 'name': '운영팀', 'enabled': True})
    seed(app, 1, '보고서 A', data={'type': 'Skill'})
    seed(app, 2, '보고서 B', data={'type': 'Skill', 'orgId': 'org-b', 'org': '예전 부서'})
    seed(app, 3, '보고서 C', data={'type': 'Skill', 'orgId': 'org-b', 'categoryId': 'cat-other'})
    seed(app, 4, '보고서 D', data={'type': 'MCP/Tool', 'orgId': 'org-b'})
    seed(app, 5, '메일', data={'type': 'Skill'})
    seed(app, 6, '보고서 삭제', data={'type': 'Skill'}, deleted=True)
    seed(app, 7, '보고서 삭제중', data={'type': 'Skill'}, purge={'requested': True})
    browser, _ = ready(app, 'member')
    result = browser.get('/api/catalog', query_string={'q': '보고서', 'type': 'Skill', 'categoryId': 'category-0', 'orgId': 'organization-0', 'facets': 'organizations'}).json
    assert ids(result) == [1]
    assert result['total'] == 1 and result['facets']['total'] == 2
    facets = {row['id']: row for row in result['facets']['organizations']}
    assert facets['organization-0']['count'] == facets['org-b']['count'] == 1
    assert facets['org-b']['name'] == '운영팀'
    assert browser.get('/api/catalog?q=보고서').json['facets'] is None


def test_category_filters_before_candidate_cap_facets_count_full_matches(app, monkeypatch):
    seed(app, 1, '보고서', data={'categoryId': 'cat-other'})
    for tid in (2, 3, 4):
        seed(app, tid, f'보고서 {tid}')
    monkeypatch.setattr(catalog_search, 'CANDIDATE_LIMIT', 1)
    browser, _ = ready(app, 'member')
    result = browser.get('/api/catalog?q=보고서&categoryId=category-0&facets=organizations').json
    assert ids(result) == [2]
    assert result['total'] == result['facets']['total'] == 3
    assert result['evaluatedCount'] == 1 and result['complete'] is False
    assert result['nextOffset'] is None and result['warning']


def test_web_sorts_and_pagination_do_not_relabel_download_count_as_score(app):
    seed(app, 1, 'Beta', data={'desc': '보고서', 'workTags': []})
    seed(app, 2, 'Alpha', data={'desc': '보고서', 'workTags': []})
    vote(app, 1, 'down-one')
    for i in range(5):
        vote(app, 1, 'like-' + str(i), kind='like')
    vote(app, 2, 'down-two')
    vote(app, 2, 'down-three')
    browser, _ = ready(app, 'member')
    assert ids(browser.get('/api/catalog?q=보고서&sort=cumulative').json) == [1, 2]
    assert ids(browser.get('/api/catalog?q=보고서&sort=downloads').json) == [2, 1]
    first = browser.get('/api/catalog?q=보고서&sort=name&limit=1').json
    assert ids(first) == [2] and first['nextOffset'] == 1
    last = browser.get('/api/catalog?q=보고서&sort=name&limit=1&offset=1').json
    assert ids(last) == [1] and last['nextOffset'] is None


def test_shared_search_preserves_space_insensitive_names_and_literal_regex(app):
    seed(app, 1, '주간 보고서', data={'owner': '지원 담당'})
    seed(app, 2, '회의 정리', owner='other', data={'owner': '김하늘'})
    with app.app_context():
        db().users.update_one({'_id': 'owner'}, {'$set': {'name': '김 하늘'}})
    browser, _ = ready(app, 'member')
    assert set(ids(browser.get('/api/catalog?q=김하늘').json)) == {1, 2}
    assert ids(browser.get('/api/catalog?q=주간보고서').json)[0] == 1
    assert ids(browser.get('/api/catalog?q=.*').json) == []
    assert ids(browser.get('/api/catalog?q=지원담당').json) == [1]


def test_search_does_not_accept_a_client_asserted_department_for_recommendations(app):
    seed(app, 1)
    browser, _ = ready(app, 'member')
    with app.app_context():
        db().users.update_one({'_id': 'member'}, {'$set': {'dept_cd': '', 'dept': '공통'}})
    result = browser.get('/api/catalog?q=메일&dept_cd=other&orgId=organization-0').json
    assert result['recommendation']['status'] == 'department_unknown'
    assert result['recommendation']['identitySource'] is None
