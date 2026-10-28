"""Extension permission requests use the web identity and approval workflow."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from .conftest import ready, publish
from .test_personal_api_usage import issue
from pt_ai_square.backend import mongo_api
from pt_ai_square.backend.storage import db, ensure_user


REASON = {'reason': 'AX Workspace에서 사용 권한을 신청합니다.'}


def private_tool(app):
    owner, headers = ready(app)
    assert publish(owner, headers, approval=True).status_code == 201
    member, member_headers = ready(app, 'member')
    issued, auth = issue(member, member_headers)
    return owner, headers, issued, auth


def test_key_request_is_own_pending_access_and_duplicate_safe(app):
    owner, headers, _, auth = private_tool(app)
    api = app.test_client()
    assert api.get('/api/integration/me', headers=auth).json['capabilities']['accessRequest']
    status = api.get('/api/tools/1/access-status', headers=auth).json
    assert status['access'] == 'none' and status['canRequest'] is True
    card = api.get('/api/catalog', headers=auth).json['items'][0]
    for key in ('id', 'name', 'desc', 'platform', 'owner', 'registrantName', 'registrantId'):
        assert status['item'][key] == card[key]
    assert not {'guide', 'environment', 'versions', 'url', 'installProfile', 'commands'} & status['item'].keys()
    assert 'SECRET' not in json.dumps(status)
    for iteration in range(3):
        response = api.post('/api/tools/1/requests', headers=auth, json=REASON)
        assert response.status_code == 200
        assert response.json['access'] == 'pending'
        assert response.json['requested'] is (iteration == 0)
    assert api.get('/api/tools/1/access-status', headers=auth).json['canRequest'] is False
    with app.app_context():
        row = db().access.find_one({'_id': '1:member'})
        assert row['user'] == 'member' and not row['granted'] and row['status'] == '대기'
        assert len(row['history']) == 1
    assert owner.get('/api/notifications').json['unread'] == 1
    for path in ('/api/tools/1', '/api/tools/1/manifest', '/download/1/1'):
        assert api.get(path, headers=auth).status_code == 403
    assert owner.post('/api/requests/1:member/decision', headers=headers,
                      json={'status': '승인', 'reason': '', 'expectedRevision': response.json['requestRevision']}).status_code == 200
    assert api.get('/api/tools/1/access-status', headers=auth).json['access'] == 'approved'
    assert api.get('/api/tools/1', headers=auth).status_code == 200
    assert api.get('/download/1/1', headers=auth).status_code == 200
    repeated = api.post('/api/tools/1/requests', headers=auth, json=REASON)
    assert repeated.json['access'] == 'approved' and repeated.json['requested'] is False


def test_key_can_request_but_never_grant_approve_or_impersonate(app):
    owner, headers, _, auth = private_tool(app)
    api = app.test_client()
    for extra in ({'user': 'other'}, {'granted': True}, {'status': '승인'}):
        assert api.post('/api/tools/1/requests', headers=auth, json={**REASON, **extra}).status_code == 400
    for data in ({}, {'reason': ''}, {'reason': 123}, {'reason': 'x' * 2001}):
        assert api.post('/api/tools/1/requests', headers=auth, json=data).status_code == 400
    with app.app_context():
        assert db().access.count_documents({}) == 0
    assert api.post('/api/tools/1/requests', headers=auth, json=REASON).status_code == 200
    _, owner_auth = issue(owner, headers)
    for actor in (auth, owner_auth):
        for path, data in (
            ('/api/requests/1:member/decision', {'status': '승인', 'reason': ''}),
            ('/api/tools/1/grants', {'user': 'member'}),
            ('/api/tools/1/grants/departments', {'departments': [{'code': 'D', 'name': 'Team'}]}),
        ):
            assert api.post(path, headers=actor, json=data).status_code == 403
    with app.app_context():
        assert db().access.find_one({'_id': '1:member'})['granted'] is False
    other, other_headers = ready(app, 'other')
    _, other_auth = issue(other, other_headers)
    assert api.get('/api/tools/1/access-status', headers=other_auth).json['access'] == 'none'


def test_organization_grants_and_revoke_are_shared_with_key_access(app):
    owner, headers, _, auth = private_tool(app)
    with app.app_context():
        ensure_user('member', 'Member', 'Team A', 'TEAM-A')
    assert owner.post('/api/tools/1/grants/departments', headers=headers,
                      json={'departments': [{'code': 'TEAM-A', 'name': 'Team A'}]}).status_code == 200
    api = app.test_client()
    assert api.get('/api/tools/1/access-status', headers=auth).json['access'] == 'approved'
    assert api.post('/api/tools/1/requests', headers=auth, json=REASON).json['requested'] is False
    with app.app_context():
        assert db().access.count_documents({'tool': 1}) == 0
        ensure_user('member', 'Member', 'Team A', 'TEAM-B')
    assert api.get('/api/tools/1/access-status', headers=auth).json['access'] == 'none'
    assert api.get('/download/1/1', headers=auth).status_code == 403
    assert api.post('/api/tools/1/requests', headers=auth, json=REASON).json['requested'] is True


def test_denied_or_revoked_request_can_be_requested_again(app):
    owner, headers, _, auth = private_tool(app)
    api = app.test_client()
    for decision in ('반려', '승인'):
        submitted = api.post('/api/tools/1/requests', headers=auth, json=REASON).json
        assert submitted['requested'] is True
        assert owner.post('/api/requests/1:member/decision', headers=headers,
                          json={'status': decision, 'reason': '검토 완료', 'expectedRevision': submitted['requestRevision']}).status_code == 200
        if decision == '승인':
            assert owner.post('/api/requests/1:member/decision', headers=headers,
                              json={'status': '회수', 'reason': '사용 종료'}).status_code == 200
        state = api.get('/api/tools/1/access-status', headers=auth).json
        assert state['access'] == 'none' and state['canRequest']
        assert state['accessDecision'] == ('사용 종료' if decision == '승인' else '검토 완료')
    assert api.post('/api/tools/1/requests', headers=auth, json=REASON).json['requested'] is True


def test_concurrent_key_requests_create_one_request_and_notification(app):
    owner, _, _, auth = private_tool(app)
    def submit(_):
        return app.test_client().post('/api/tools/1/requests', headers=auth, json=REASON)
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(submit, range(16)))
    assert all(response.status_code == 200 for response in responses)
    assert sum(response.json['requested'] for response in responses) == 1
    with app.app_context():
        assert db().access.count_documents({'tool': 1, 'user': 'member'}) == 1
        assert len(db().access.find_one({'_id': '1:member'})['history']) == 1
    assert owner.get('/api/notifications').json['unread'] == 1


@pytest.mark.parametrize('scope', ['read', 'publish', 'missing'])
def test_known_legacy_keys_need_no_rotation_to_request_access(app, scope):
    _, _, issued, auth = private_tool(app)
    with app.app_context():
        change = {'$unset': {'scope': ''}} if scope == 'missing' else {'$set': {'scope': scope}}
        db().local_tokens.update_one({'id': issued['id']}, change)
    assert app.test_client().post('/api/tools/1/requests', headers=auth, json=REASON).status_code == 200


@pytest.mark.parametrize('change', [
    {'scope': 'administrator'}, {'scope': []}, {'scope': None},
    {'revoked': True}, {'expires': 1},
])
def test_invalid_credentials_cannot_request_or_read_access_state(app, change):
    _, _, issued, auth = private_tool(app)
    with app.app_context():
        db().local_tokens.update_one({'id': issued['id']}, {'$set': change})
    api = app.test_client()
    assert api.get('/api/tools/1/access-status', headers=auth).status_code == 401
    assert api.post('/api/tools/1/requests', headers=auth, json=REASON).status_code == 401
    with app.app_context():
        assert db().access.count_documents({}) == 0


def test_missing_deleted_tools_and_disabled_user_are_rejected(app):
    _, _, _, auth = private_tool(app)
    api = app.test_client()
    for tid in (999, 1):
        if tid == 1:
            with app.app_context():
                db().tools.update_one({'_id': 1}, {'$set': {'deleted': True}})
        assert api.get(f'/api/tools/{tid}/access-status', headers=auth).status_code == 404
        assert api.post(f'/api/tools/{tid}/requests', headers=auth, json=REASON).status_code == 404
    with app.app_context():
        db().users.update_one({'_id': 'member'}, {'$set': {'enabled': False}})
    assert api.get('/api/tools/1/access-status', headers=auth).status_code == 401


def test_deferred_notification_still_reports_saved_request(app, monkeypatch):
    _, _, _, auth = private_tool(app)
    monkeypatch.setattr(mongo_api, 'deliver_pending', lambda *args: True)
    response = app.test_client().post('/api/tools/1/requests', headers=auth, json=REASON)
    assert response.status_code == 200 and response.json['requested'] is True
    assert response.json['access'] == 'pending' and response.json['pending'] is True
    with app.app_context():
        row = db().access.find_one({'_id': '1:member'})
        assert row['status'] == '대기' and not row['granted'] and row['outbox']
    repeated = app.test_client().post('/api/tools/1/requests', headers=auth, json=REASON)
    assert repeated.json['requested'] is False and repeated.json['pending'] is True
