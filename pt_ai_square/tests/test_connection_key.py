"""One employee/active key contract across rotation, legacy data and races."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import secrets
import threading
import time

from pt_ai_square.backend.storage import db
from .conftest import ready


def issue(app, uid='owner', **overrides):
    client, headers = ready(app, uid)
    data = dict(name='업무 연결', days=7, scope='read')
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
    assert accepted(app, first['token']) == 200
    second = issue(app).json
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


def test_legacy_latest_key_selected_once_without_escalating_scope(app):
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
    assert data['connectionKey']['scope'] == 'read'
    assert data['connectionKey']['status'] == 'active'
    assert next(r for r in data['tokens'] if r['id'] == old['id'])['status'] == 'replaced'
    assert app.test_client().post('/api/tools', headers={'Authorization': 'Bearer '+new_token}).status_code == 403
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
                               json={'name':'동시 발급', 'days':7, 'scope':'read'})
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
    assert '각 서비스의 실제 연결 기능은 해당 연동이 추가된 뒤' in text
    assert 'autocomplete="off"' in text
