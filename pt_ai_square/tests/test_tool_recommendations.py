"""Admin-only recommendation, reviewed-release lifecycle, and shared catalog order."""
import json
import time

import pytest

from pt_ai_square.backend import catalog_search
from pt_ai_square.backend.storage import db
from .conftest import ready, publish
from .test_catalog_recommendations import seed, vote, department


def recommend(client, headers, tid=1, revision=1, enabled=True, reason='반복적인 자료 취합에 추천합니다.', **extra):
    return client.put(f'/api/tools/{tid}/recommendation', headers=headers, json={
        'enabled': enabled, 'reason': reason, 'expectedRevision': revision, **extra})


def seed_reviewed(app, tid, **changes):
    return seed(app, tid, active=1, versions=[{'n': 1}], recommendationBadge={
        'enabled': True, 'reason': '추천 이유', 'reviewedVersion': 1,
        'reviewedBy': 'admin', 'updatedAt': time.time()}, **changes)


def test_only_web_administrator_can_recommend_and_owner_cannot_forge_metadata(app):
    owner, headers = ready(app)
    admin, admin_headers = ready(app, 'admin')
    assert publish(owner, headers, recommendationBadge={'enabled': True, 'reviewedVersion': 1}).status_code == 201
    assert owner.get('/api/tools/1').json['recommendationBadge']['status'] == 'none'
    assert recommend(owner, headers).status_code == 403
    assert recommend(admin, {}).status_code == 403
    token = admin.post('/api/local-tokens', headers=admin_headers, json={}).json['token']
    assert recommend(app.test_client(), {'Authorization': 'Bearer ' + token}).status_code == 403
    response = recommend(admin, admin_headers)
    assert response.status_code == 200 and response.json['revision'] == 2
    assert response.json['recommendationBadge']['active'] is True
    assert response.json['recommendationBadge']['reviewedVersion'] == 1
    assert owner.patch('/api/tools/1', headers=headers, json={
        'expectedRevision': 2, 'recommendationBadge': {'enabled': False}}).status_code == 200
    with app.app_context():
        record = db().tools.find_one({'_id': 1})
        assert record['recommendationBadge']['enabled'] is True
        assert 'recommendationBadge' not in record['data']
        assert db().audit.count_documents({'action': '도구 1 추천 설정 (v1)'}) == 1


@pytest.mark.parametrize('changes', [
    {'enabled': 'true'}, {'enabled': 1}, {'expectedRevision': True}, {'reason': ''},
    {'reason': ' '}, {'reason': 'x' * 301}, {'reviewedVersion': 999},
])
def test_invalid_recommendation_does_not_write(app, changes):
    owner, headers = ready(app)
    admin, ah = ready(app, 'admin')
    assert publish(owner, headers).status_code == 201
    body = dict(enabled=True, reason='자료 취합에 추천합니다.', expectedRevision=1)
    body.update(changes)
    response = admin.put('/api/tools/1/recommendation', json=body, headers=ah)
    assert response.status_code == 400
    with app.app_context():
        assert 'recommendationBadge' not in db().tools.find_one({'_id': 1})


@pytest.mark.parametrize('state', ['withdrawn', 'deleted', 'missing_file', 'no_active', 'purging'])
def test_unavailable_release_cannot_be_recommended(app, state):
    owner, headers = ready(app)
    admin, ah = ready(app, 'admin')
    assert publish(owner, headers).status_code == 201
    update = {
        'withdrawn': {'versions.0.withdrawn': True},
        'deleted': {'versions.0.deleted': True},
        'missing_file': {'versions.0.path': 'missing-release.zip'},
        'no_active': {'active': None},
        'purging': {'purge': {'requested': True}},
    }[state]
    with app.app_context():
        db().tools.update_one({'_id': 1}, {'$set': update})
    assert recommend(admin, ah).status_code == 409
    with app.app_context():
        assert 'recommendationBadge' not in db().tools.find_one({'_id': 1})


def test_stale_admin_action_conflicts_and_disable_does_not_resurrect(app):
    owner, headers = ready(app)
    admin, ah = ready(app, 'admin')
    assert publish(owner, headers).status_code == 201
    assert recommend(admin, ah).status_code == 200
    assert recommend(admin, ah, enabled=False).status_code == 409
    assert recommend(admin, ah, revision=2, enabled=False).status_code == 200
    assert publish(owner, headers, tid=1, revision=3).status_code == 201
    assert owner.post('/api/tools/1/rollback', headers=headers,
                      json={'expectedRevision': 4, 'version': 1}).status_code == 200
    assert owner.get('/api/tools/1').json['recommendationBadge']['status'] == 'none'


def test_new_release_requires_review_and_reconfirm_binds_to_that_release(app):
    owner, headers = ready(app)
    admin, ah = ready(app, 'admin')
    member, _ = ready(app, 'member')
    assert publish(owner, headers).status_code == 201
    assert recommend(admin, ah).status_code == 200
    assert publish(owner, headers, tid=1, revision=2).status_code == 201
    pending = admin.get('/api/bootstrap').json['items'][0]['recommendationBadge']
    assert pending['status'] == 'needs_review' and not pending['active']
    assert pending['reviewedVersion'] == 1 and pending['reason']
    assert member.get('/api/tools/1').json['recommendationBadge']['status'] == 'none'
    assert member.get('/api/catalog').json['items'][0]['recommendationBadge']['status'] == 'none'
    assert recommend(admin, ah, revision=3, reason='새 버전의 취합 기능을 확인했습니다.').status_code == 200
    current = member.get('/api/tools/1').json['recommendationBadge']
    assert current['active'] and current['reviewedVersion'] == 2
    assert current['reason'] == '새 버전의 취합 기능을 확인했습니다.'
    assert 'reviewedBy' not in current


def test_exact_reviewed_release_rollback_and_deleted_tool_visibility(app):
    owner, headers = ready(app)
    admin, ah = ready(app, 'admin')
    assert publish(owner, headers).status_code == 201
    assert recommend(admin, ah).status_code == 200
    assert publish(owner, headers, tid=1, revision=2).status_code == 201
    assert owner.post('/api/tools/1/rollback', headers=headers,
                      json={'expectedRevision': 3, 'version': 1}).status_code == 200
    assert owner.get('/api/tools/1').json['recommendationBadge']['active']
    assert owner.delete('/api/tools/1', headers=headers, json={'expectedRevision': 4}).status_code == 200
    assert not admin.get('/api/bootstrap').json['items'][0]['recommendationBadge']['active']
    assert admin.get('/api/catalog').json['items'] == []
    assert recommend(admin, ah, revision=5).status_code == 409
    assert owner.post('/api/tools/1/restore', headers=headers, json={'expectedRevision': 5}).status_code == 200
    assert owner.get('/api/tools/1').json['recommendationBadge']['active']


def test_restricted_recommendation_reason_is_not_a_new_detail_disclosure(app):
    owner, headers = ready(app)
    admin, ah = ready(app, 'admin')
    member, _ = ready(app, 'member')
    assert publish(owner, headers, approval=True).status_code == 201
    assert recommend(admin, ah, reason='PRIVATE RECOMMENDATION DETAILS').status_code == 200
    for route in ['/api/bootstrap', '/api/catalog']:
        payload = member.get(route).json
        badge = payload['items'][0]['recommendationBadge']
        assert badge['active'] and badge['reason'] == '' and badge['reviewedVersion'] is None
        assert 'PRIVATE RECOMMENDATION' not in json.dumps(payload)
    assert member.get('/api/tools/1').status_code == 403
    assert owner.get('/api/tools/1').json['recommendationBadge']['reason'] == 'PRIVATE RECOMMENDATION DETAILS'


def test_default_catalog_curation_is_below_relevance_but_above_department_and_popularity(app):
    seed_reviewed(app, 1)
    seed(app, 2)
    seed(app, 3, name='메일', data={'workTags': [], 'desc': ''})
    seed_reviewed(app, 4, name='엑셀 취합', data={'workTags': ['엑셀'], 'desc': '엑셀 자료 취합'})
    department(app, 2, count=5)
    client, _ = ready(app, 'member')
    with app.app_context():
        db().users.update_one({'_id': 'member'}, {'$set': {'dept_cd': 'D001'}})
    data = client.get('/api/catalog?q=메일').json
    assert [row['id'] for row in data['items']] == [3, 1, 2]
    assert '추천 도구입니다. 추천 이유' in data['items'][1]['reasons']
    assert data['items'][2]['departmentPreference']['status'] == 'applied'
    first = client.get('/api/catalog').json['items'][:2]
    assert {row['id'] for row in first} == {1, 4}


@pytest.mark.parametrize('query', ['', '?q=메일'])
def test_recommendation_enters_candidate_cap_before_pagination(app, monkeypatch, query):
    seed(app, 1)
    seed(app, 2)
    seed_reviewed(app, 99)
    monkeypatch.setattr(catalog_search, 'CANDIDATE_LIMIT', 2)
    client, _ = ready(app, 'member')
    result = client.get('/api/catalog' + query).json
    assert result['items'][0]['id'] == 99
    assert result['complete'] is False and result['evaluatedCount'] == 2
    url = '/api/catalog' + (query + '&' if query else '?') + 'limit=1'
    assert client.get(url).json['nextOffset'] == 1
    assert client.get(url + '&offset=1').json['items'][0]['id'] != 99


def test_explicit_sorts_and_expired_review_do_not_receive_recommendation_boost(app):
    seed_reviewed(app, 1)
    seed(app, 2, name='가나다 조회')
    vote(app, 2, 'other')
    client, _ = ready(app, 'member')
    for sort in ['newest', 'name', 'downloads', 'cumulative', 'realtime']:
        result = client.get('/api/catalog?sort=' + sort).json
        assert result['items'][0]['id'] == 2
        assert result['items'][1]['recommendationBadge']['active']
    with app.app_context():
        db().tools.update_one({'_id': 1}, {'$set': {'active': 2, 'versions': [{'n': 1}, {'n': 2}]}})
    assert client.get('/api/catalog').json['items'][0]['id'] == 2
    with app.app_context():
        db().tools.update_one({'_id': 1}, {'$set': {'active': 1, 'versions': [{'n': 1, 'withdrawn': True}]}})
    row = next(row for row in client.get('/api/catalog').json['items'] if row['id'] == 1)
    assert row['recommendationBadge']['active'] is False
