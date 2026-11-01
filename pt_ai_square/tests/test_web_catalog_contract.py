"""Web session and extension KEY search share one permission-aware contract."""
import json

import pytest

from .conftest import ready
from .test_catalog_recommendations import seed
from .test_personal_api_usage import issue
from pt_ai_square.backend.storage import db


@pytest.mark.parametrize('query', [
    '분기 실적을 부서별로 분석해서 보고서를 만들고 싶어요',
    '부서별 보고서', 'html-report', '김등록',
])
def test_web_and_key_have_same_search_order_and_private_boundary(app, query):
    for tid, name in [(1, 'HTML 보고서 html-report'), (2, '업무 기록 정리'), (3, '설비 검색')]:
        seed(app, tid, name, data={'desc': '부서별 분기 실적을 분석하는 보고서' if tid == 1 else name,
                                 'workTags': ['보고서'] if tid < 3 else [], 'approval': tid == 1})
    seed(app, 4, '삭제된 보고서', deleted=True)
    with app.app_context():
        db().users.update_one({'_id': 'owner'}, {'$set': {'name': '김등록'}})
    browser, headers = ready(app, 'member')
    _, authorization = issue(browser, headers)
    extension = app.test_client()
    web = browser.get('/api/catalog', query_string={'q': query, 'limit': 12}).json
    key = extension.get('/api/catalog', query_string={'q': query, 'limit': 12}, headers=authorization).json
    assert [row['id'] for row in web['items']] == [row['id'] for row in key['items']]
    assert web['total'] == key['total'] and web['items']
    assert 4 not in [row['id'] for row in web['items']]
    assert 'PRIVATE' not in json.dumps(web) and 'SECRET' not in json.dumps(web)
    if query != 'html-report':
        assert web['items'][0]['id'] == 1 or query == '김등록'


def test_web_filters_and_pagination_apply_before_result_limit(app):
    for tid in range(1, 27):
        seed(app, tid, f'보고서 {tid:02d}', data={'category': '제조', 'categoryId': 'category-1'})
    seed(app, 30, '보고서 다른 분류', data={'category': '기술', 'categoryId': 'category-3'})
    c, _ = ready(app, 'member')
    params={'q': '보고서', 'category': '제조', 'org': '공통', 'limit': 12, 'sort': 'name'}
    first=c.get('/api/catalog', query_string=params).json
    second=c.get('/api/catalog', query_string={**params, 'offset': first['nextOffset']}).json
    third=c.get('/api/catalog', query_string={**params, 'offset': second['nextOffset']}).json
    assert first['total'] == 26
    assert [row['id'] for result in [first, second, third] for row in result['items']] == list(range(1, 27))
    assert third['nextOffset'] is None
    assert c.get('/api/catalog', query_string={**params, 'sort': 'downloads'}).status_code == 200
