"""Extension searches use the authenticated server catalog, before pagination."""
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from pymongo.collection import Collection

from pt_ai_square.backend import catalog_search
from pt_ai_square.backend.storage import db
from .conftest import ready
from .test_catalog_recommendations import seed
from .test_organization_store import worker
from .test_personal_api_usage import issue
from .test_receiver import server


@pytest.fixture
def store_search(app, server, tmp_path, monkeypatch):
    member, headers = ready(app, 'member')
    token, _ = issue(member, headers, 'read')
    monkeypatch.setenv('PTAI_API_TOKEN', token['token'])
    data, workspace = tmp_path / 'extension', tmp_path / 'workspace'
    data.mkdir()
    workspace.mkdir()
    config = tmp_path / 'config.json'
    worker.save_config(config, server, [data, workspace], allow_http=True, download_directory=data)
    requests = []

    class CountedClient(worker.StoreClient):
        def json(self, path, *args, **kwargs):
            requests.append(path)
            return super().json(path, *args, **kwargs)

    store = worker.Store(data, {'workspace': str(workspace)}, home=tmp_path,
                         existing_config=config, client_factory=CountedClient)
    store.dispatch('connect', {'reuseExisting': True})
    requests.clear()
    return store, requests


def registrar(app, uid='owner', name='김테스트'):
    with app.app_context():
        db().users.update_one({'_id': uid}, {'$set': {'name': name}})


def catalog_item(app, tid, **changes):
    data = dict(type='Skill', desc='자료 정리', workTags=[], owner='운영 부서')
    data.update(changes.pop('data', {}))
    return seed(app, tid, f'기능 {tid}', data=data, **changes)


def test_extension_registrant_search_pages_full_filtered_server_results(app, store_search):
    store, requests = store_search
    registrar(app)
    for tid in range(1, 28):
        catalog_item(app, tid, data={'approval': tid == 5})
    catalog_item(app, 28, deleted=True)
    catalog_item(app, 29, purge={'requested': True})
    catalog_item(app, 30, data={'type': 'MCP/Tool'})
    catalog_item(app, 31, data={'platform': 'ChatGPT'})
    catalog_item(app, 32, data={'orgId': 'organization-other'})
    catalog_item(app, 33, owner='other')
    payload = dict(q='김테', type='Skill', orgId='organization-0', platform='Claude',
                   sort='newest', limit=10, offset=0)
    pages = []
    while True:
        result = store.dispatch('catalog', payload)
        assert result['total'] == 27 and result['complete'] is True
        pages.extend(result['items'])
        if result['nextOffset'] is None:
            break
        payload['offset'] = result['nextOffset']
    assert [row['id'] for row in pages] == list(range(27, 0, -1))
    assert all(row['registrantName'] == '김테스트' for row in pages)
    assert next(row for row in pages if row['id'] == 5)['access'] == 'permission_required'
    assert 'PRIVATE GUIDE' not in json.dumps(pages)
    assert 'PRIVATE PATH' not in json.dumps(pages)
    calls = [url for url in requests if urlsplit(url).path == '/api/catalog']
    assert len(calls) == 3
    assert [parse_qs(urlsplit(url).query)['offset'][0] for url in calls] == ['0', '10', '20']
    assert all(parse_qs(urlsplit(url).query)['q'] == ['김테'] for url in calls)
    assert not any('/api/users' in url for url in requests)


def test_extension_registrant_search_is_partial_case_insensitive_and_literal(app, store_search):
    store, requests = store_search
    registrar(app, name='Arin Lee')
    catalog_item(app, 1)
    registrar(app, 'other', 'NobodySecretName')
    for query in ['arin', 'ARIN', 'Lee']:
        result = store.dispatch('catalog', {'q': query})
        assert [row['id'] for row in result['items']] == [1]
        assert any('등록자 이름' in reason for reason in result['items'][0]['reasons'])
    for query in ['.*', 'NobodySecretName']:
        result = store.dispatch('catalog', {'q': query})
        assert result['total'] == 0 and result['items'] == []
        assert 'NobodySecretName' not in json.dumps(result)


def test_registrant_matches_enter_candidate_cap_before_weak_description_matches(app, store_search, monkeypatch):
    store, _ = store_search
    registrar(app, name='김테스트')
    for tid in range(1, 6):
        catalog_item(app, tid, owner='other', data={'desc': '김테스트 사용 예시'})
    catalog_item(app, 99)
    monkeypatch.setattr(catalog_search, 'CANDIDATE_LIMIT', 2)
    result = store.dispatch('catalog', {'q': '김테스트'})
    assert result['total'] == 6 and result['complete'] is False
    assert result['items'][0]['id'] == 99
    assert result['warning'] and result['evaluatedCount'] == 2


@pytest.mark.parametrize('count', [1, 30])
def test_registrant_search_keeps_one_server_request_and_bulk_account_lookups(app, store_search, monkeypatch, count):
    store, requests = store_search
    registrar(app)
    for tid in range(1, count + 1):
        catalog_item(app, tid)
    calls = []
    find = Collection.find

    def observed(collection, *args, **kwargs):
        calls.append(collection.name)
        return find(collection, *args, **kwargs)

    monkeypatch.setattr(Collection, 'find', observed)
    result = store.dispatch('catalog', {'q': '김테스트', 'sort': 'newest', 'limit': 100})
    assert len(result['items']) == count
    assert len(requests) == 1 and requests[0].startswith('/api/catalog?')
    # Personal-KEY auth makes two account reads, followed by one name search
    # and one registrar display batch. This stays constant for 1 or 30 cards.
    assert calls.count('users') <= 4
