"""One employee/active key contract across rotation, legacy data and races."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import json
import secrets
import threading
import time
from types import SimpleNamespace

import pytest

from pt_ai_square.backend.storage import db
from .conftest import ready


def issue(app, uid='owner', **overrides):
    client, headers = ready(app, uid)
    data = dict(name='업무 연결', scope='read')
    data.update(overrides)
    return client.post('/api/local-tokens', headers=headers, json=data)


def accepted(app, token):
    return app.test_client().get('/api/catalog', headers={'Authorization': 'Bearer ' + token}).status_code


def legacy(app, uid, created, **overrides):
    token = 'ptsq_' + secrets.token_urlsafe(32)
    row = dict(_id=hashlib.sha256(token.encode()).hexdigest(), id=secrets.token_hex(16),
               user=uid, name='이전 PC', created=created, expires=time.time() + 86400, revoked=False)
    row.update(overrides)
    with app.app_context():
        db().local_tokens.insert_one(row)
    return row, token


def test_rotation_invalidates_previous_key_and_keeps_employee_history(app):
    first = issue(app).json
    assert first['expires'] is None
    assert accepted(app, first['token']) == 200
    second = issue(app).json
    assert second['expires'] is None
    assert second['replaced'] is True
    assert accepted(app, first['token']) == 401
    assert accepted(app, second['token']) == 200
    owner, headers = ready(app)
    summary = owner.get('/api/local-tokens').json
    assert summary['currentKeyId'] == second['id']
    assert summary['connectionKey']['id'] == second['id']
    assert [r['status'] for r in summary['tokens']].count('active') == 1
    assert len(summary['tokens']) == 2
    assert 'token' not in summary['connectionKey']
    with app.app_context():
        user = db().users.find_one({'_id': 'owner'})
        records = list(db().local_tokens.find({'user': 'owner'}))
    assert user['activeConnectionKeyId'] == second['id']
    assert first['token'] not in json.dumps(records)
    assert second['token'] not in json.dumps(user)
    # An old key's cancellation must not clear the new pointer.
    owner.delete('/api/local-tokens/' + first['id'], headers=headers)
    assert accepted(app, second['token']) == 200
    owner.delete('/api/local-tokens/' + second['id'], headers=headers)
    assert accepted(app, second['token']) == 401
    assert owner.get('/api/local-tokens').json['currentKeyId'] is None
    assert accepted(app, first['token']) == 401


def test_legacy_latest_key_selected_once_with_personal_publish_capability(app):
    now = time.time()
    old, old_token = legacy(app, 'owner', now-30)
    latest, new_token = legacy(app, 'owner', now-10)
    legacy(app, 'owner', now, revoked=True)
    legacy(app, 'owner', now+1, expires=now-1)
    assert accepted(app, old_token) == 401
    assert accepted(app, new_token) == 200
    owner, headers = ready(app)
    data = owner.get('/api/local-tokens').json
    assert data['currentKeyId'] == latest['id']
    assert data['connectionKey']['scope'] == 'publish'
    assert data['connectionKey']['status'] == 'active'
    assert next(r for r in data['tokens'] if r['id'] == old['id'])['status'] == 'replaced'
    assert app.test_client().post('/api/tools', headers={'Authorization': 'Bearer '+new_token}).status_code == 409
    owner.delete('/api/local-tokens/' + latest['id'], headers=headers)
    assert accepted(app, new_token) == 401
    assert accepted(app, old_token) == 401
    assert owner.get('/api/local-tokens').json['currentKeyId'] is None


def test_expired_pointer_does_not_fall_back_to_older_legacy_key(app):
    old, old_token = legacy(app, 'owner', time.time()-100)
    current = issue(app).json
    with app.app_context():
        db().local_tokens.update_one({'id': current['id']}, {'$set': {'expires': time.time()-1}})
    assert accepted(app, current['token']) == 401
    assert accepted(app, old_token) == 401
    owner, _ = ready(app)
    assert owner.get('/api/local-tokens').json['connectionKey']['status'] == 'expired'


def test_concurrent_reissues_leave_exactly_one_usable_key(app):
    original = issue(app).json
    gate = threading.Barrier(5)
    def rotate(_):
        client, headers = ready(app)
        gate.wait(timeout=10)
        response = client.post('/api/local-tokens', headers=headers,
                               json={'name':'동시 발급', 'scope':'read'})
        return response.status_code, response.json
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(rotate, range(5)))
    assert all(code in {201, 409} for code, _ in results)
    successful = [row for code, row in results if code == 201]
    assert successful
    valid = [row for row in successful if accepted(app, row['token']) == 200]
    assert len(valid) == 1
    assert accepted(app, original['token']) == 401
    owner, _ = ready(app)
    data = owner.get('/api/local-tokens').json
    assert data['currentKeyId'] == valid[0]['id']
    assert len([row for row in data['tokens'] if row['status'] == 'active']) == 1


def test_another_employee_key_and_csrf_are_independent(app):
    first = issue(app).json
    other = issue(app, 'member').json
    rotated = issue(app).json
    assert accepted(app, other['token']) == 200
    assert accepted(app, first['token']) == 401
    assert accepted(app, rotated['token']) == 200
    owner, _ = ready(app)
    assert owner.post('/api/local-tokens', json={}).status_code == 403
    assert owner.get('/api/local-tokens', headers={'Authorization':'Bearer '+rotated['token']}).status_code == 403


def test_key_page_explains_rotation_without_promising_future_integrations(app):
    owner, _ = ready(app)
    response = owner.get('/local-access')
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '연결 KEY 발급' in text and '한 개의 KEY' in text
    assert '로컬 MCP 받기' in text
    assert '신규 등록·내 도구 업데이트' in text
    assert 'id="token-scope"' not in text
    assert 'autocomplete="off"' in text


def test_permanent_key_serializes_and_remains_valid_far_in_future(app, monkeypatch):
    response = issue(app)
    assert response.status_code == 201
    issued = response.json
    assert 'expires' in issued and issued['expires'] is None
    with app.app_context():
        row = db().local_tokens.find_one({'id': issued['id']})
        assert 'expires' in row and row['expires'] is None
        assert row['user'] == 'owner'
        assert row['_id'] == hashlib.sha256(issued['token'].encode()).hexdigest()
    key_module = importlib.import_module('pt_ai_square.backend.local_access')
    monkeypatch.setattr(key_module, 'time', SimpleNamespace(time=lambda: time.time() + 80 * 365 * 86400))
    assert accepted(app, issued['token']) == 200
    owner, _ = ready(app)
    summary = owner.get('/api/local-tokens').json
    assert summary['connectionKey']['status'] == 'active'
    assert summary['connectionKey']['expires'] is None
    assert summary['tokens'][0]['expires'] is None


def test_legacy_numeric_expiry_keeps_original_deadline_until_reissue(app, monkeypatch):
    deadline = time.time() + 3600
    row, token = legacy(app, 'owner', time.time(), expires=deadline)
    assert accepted(app, token) == 200
    owner, _ = ready(app)
    assert owner.get('/api/local-tokens').json['connectionKey']['expires'] == deadline
    key_module = importlib.import_module('pt_ai_square.backend.local_access')
    monkeypatch.setattr(key_module, 'time', SimpleNamespace(time=lambda: deadline))
    assert accepted(app, token) == 401
    assert owner.get('/api/local-tokens').json['connectionKey']['status'] == 'expired'
    with app.app_context():
        assert db().local_tokens.find_one({'id': row['id']})['expires'] == deadline
    replacement = issue(app).json
    assert replacement['expires'] is None
    assert accepted(app, token) == 401
    assert accepted(app, replacement['token']) == 200


@pytest.mark.parametrize('expires', ['missing', '2099-01-01', True, float('nan'), float('inf'),
                                     float('-inf'), [], [None], [4102444800], {}])
def test_missing_or_malformed_expiration_fails_closed_and_lists_safely(app, expires):
    issued = issue(app).json
    update = {'$unset': {'expires': ''}} if expires == 'missing' else {'$set': {'expires': expires}}
    with app.app_context():
        db().local_tokens.update_one({'id': issued['id']}, update)
    assert accepted(app, issued['token']) == 401
    owner, _ = ready(app)
    response = owner.get('/api/local-tokens')
    assert response.status_code == 200
    current = response.json['connectionKey']
    assert current['status'] == 'invalid'
    assert current['expires'] is None


def test_legacy_selection_skips_invalid_records_and_accepts_explicit_null(app):
    now = time.time()
    permanent, token = legacy(app, 'owner', now, expires=None)
    legacy(app, 'owner', now + 1, expires=[None])
    malformed, malformed_token = legacy(app, 'owner', now + 2)
    with app.app_context():
        db().local_tokens.update_one({'id': malformed['id']}, {'$unset': {'expires': ''}})
    assert accepted(app, malformed_token) == 401
    assert accepted(app, token) == 200
    owner, _ = ready(app)
    assert owner.get('/api/local-tokens').json['currentKeyId'] == permanent['id']


@pytest.mark.parametrize('request_scope', ['missing', 'read', 'publish'])
def test_new_personal_key_has_uniform_publish_capability(app, request_scope):
    owner, csrf = ready(app)
    payload = {'name': '내 연결 KEY'}
    if request_scope != 'missing':
        payload['scope'] = request_scope
    response = owner.post('/api/local-tokens', headers=csrf, json=payload)
    assert response.status_code == 201
    issued = response.json
    assert issued['scope'] == 'publish'
    with app.app_context():
        assert db().local_tokens.find_one({'id': issued['id']})['scope'] == 'publish'
    info = app.test_client().get('/api/integration/me', headers={
        'Authorization': 'Bearer ' + issued['token']}).json
    assert info['key'] == {'id': issued['id'], 'scope': 'publish'}
    assert info['capabilities']['publishDraft'] is True
    assert info['capabilities']['approvalRequired'] is True
    assert owner.get('/api/local-tokens').json['connectionKey']['scope'] == 'publish'


@pytest.mark.parametrize('scope', [None, '', 'admin', 'READ', ['read'], ['publish'], {}, True])
def test_unknown_explicit_key_scope_fails_closed_and_lists_safely(app, scope):
    issued = issue(app).json
    with app.app_context():
        db().local_tokens.update_one({'id': issued['id']}, {'$set': {'scope': scope}})
    assert accepted(app, issued['token']) == 401
    owner, _ = ready(app)
    current = owner.get('/api/local-tokens').json['connectionKey']
    assert current['status'] == 'invalid' and current['scope'] is None


def test_legacy_pointer_migration_skips_unknown_scopes(app):
    now = time.time()
    valid, token = legacy(app, 'owner', now, scope='read')
    _, malformed_token = legacy(app, 'owner', now + 1, scope=['publish'])
    assert accepted(app, malformed_token) == 401
    assert accepted(app, token) == 200
    owner, _ = ready(app)
    assert owner.get('/api/local-tokens').json['currentKeyId'] == valid['id']


@pytest.mark.parametrize('days', [1, 7, 30, None])
def test_cached_duration_request_requires_refresh_without_rotating_key(app, days):
    original = issue(app).json
    response = issue(app, days=days)
    assert response.status_code == 400
    assert '새로고침' in response.json['error']
    assert accepted(app, original['token']) == 200
    with app.app_context():
        assert db().local_tokens.count_documents({'user': 'owner'}) == 1
