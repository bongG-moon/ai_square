"""Own pending request withdrawal is atomic and cannot revoke a grant."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from .conftest import ready
from .test_personal_api_usage import issue
from .test_store_access_requests import private_tool, REASON
from pt_ai_square.backend import mongo_api
from pt_ai_square.backend.storage import db, ensure_user


def apply(api, auth):
    response = api.post('/api/tools/1/requests', headers=auth, json=REASON)
    assert response.status_code == 200
    return response.json


def cancel(api, auth, revision):
    return api.post('/api/tools/1/requests/cancel', headers=auth,
                    json={'expectedRevision': revision})


def test_cancel_updates_app_web_state_history_and_notifications(app):
    owner, _, _, auth = private_tool(app)
    api = app.test_client()
    applied = apply(api, auth)
    revision = applied['requestRevision']
    assert len(revision) == 32 and applied['canCancel'] and applied['requestStatus'] == 'pending'
    member, member_headers = ready(app, 'member')
    card = member.get('/api/bootstrap').json['items'][0]
    assert card['requestRevision'] == revision and card['canCancel']
    status = api.get('/api/tools/1/access-status', headers=auth).json
    assert status['item']['requestRevision'] == revision
    assert status['item']['canCancel']
    response = cancel(member, member_headers, revision)
    assert response.status_code == 200
    assert response.json['cancelled'] and response.json['access'] == 'none'
    assert response.json['requestStatus'] == 'cancelled' and not response.json['canCancel']
    status = api.get('/api/tools/1/access-status', headers=auth).json
    assert status['requestStatus'] == 'cancelled' and status['canRequest']
    repeated = cancel(api, auth, revision)
    assert repeated.status_code == 200 and repeated.json['cancelled']
    with app.app_context():
        row = db().access.find_one({'_id': '1:member'})
        assert row['status'] == '취소' and row['granted'] is False
        assert row['requestRevision'] == revision and row['cancelledBy'] == 'member'
        assert [entry['status'] for entry in row['history']] == ['대기', '취소']
        assert db().notifications.count_documents({'user': 'owner'}) == 2
        assert db().audit.count_documents({'action': {'$regex': '사용자 취소'}}) == 1
    requests = owner.get('/api/bootstrap').json['requests']
    assert len(requests) == 1 and requests[0]['status'] == '취소'
    assert api.get('/download/1/1', headers=auth).status_code == 403


def test_same_revision_does_not_cancel_a_new_application(app, monkeypatch):
    _, _, _, auth = private_tool(app)
    api = app.test_client()
    # Deliberately freeze updated timestamps: request identity still changes.
    monkeypatch.setattr(mongo_api.time, 'time', lambda: 1234567890.0)
    first = apply(api, auth)['requestRevision']
    assert cancel(api, auth, first).json['cancelled']
    second = apply(api, auth)['requestRevision']
    assert first != second
    stale = cancel(api, auth, first)
    assert stale.status_code == 409
    status = api.get('/api/tools/1/access-status', headers=auth).json
    assert status['requestRevision'] == second and status['requestStatus'] == 'pending'
    assert cancel(api, auth, second).json['cancelled']


def test_legacy_pending_request_can_be_cancelled_without_migration(app):
    _, _, _, auth = private_tool(app)
    api = app.test_client()
    apply(api, auth)
    with app.app_context():
        db().access.update_one({'_id': '1:member'}, {'$unset': {'requestRevision': ''}})
    status = api.get('/api/tools/1/access-status', headers=auth).json
    revision = status['requestRevision']
    assert len(revision) == 64
    with app.app_context():
        assert 'requestRevision' not in db().access.find_one({'_id': '1:member'})
    assert cancel(api, auth, revision).json['cancelled']
    assert cancel(api, auth, revision).json['cancelled']
    assert apply(api, auth)['requestRevision'] != revision


def test_concurrent_cancel_is_one_history_entry_and_notification(app):
    _, _, _, auth = private_tool(app)
    revision = apply(app.test_client(), auth)['requestRevision']
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: cancel(app.test_client(), auth, revision), range(16)))
    assert all(response.status_code == 200 and response.json['cancelled'] for response in responses)
    with app.app_context():
        row = db().access.find_one({'_id': '1:member'})
        assert len(row['history']) == 2 and row['status'] == '취소'
        assert db().notifications.count_documents({'user': 'owner'}) == 2
        assert db().audit.count_documents({'action': {'$regex': '사용자 취소'}}) == 1


def test_other_user_cannot_cancel_someone_elses_request(app):
    owner, owner_headers, _, auth = private_tool(app)
    api = app.test_client()
    revision = apply(api, auth)['requestRevision']
    other, other_headers = ready(app, 'other')
    _, other_auth = issue(other, other_headers)
    assert cancel(api, other_auth, revision).status_code == 409
    for client, headers in ((owner, owner_headers), ready(app, 'admin')):
        response = cancel(client, headers, revision)
        assert response.status_code == 200 and response.json['cancelled'] is False
    with app.app_context():
        assert db().access.find_one({'_id': '1:member'})['status'] == '대기'


@pytest.mark.parametrize('payload', [{}, {'expectedRevision': None}, {'expectedRevision': 1},
    {'expectedRevision': True}, {'expectedRevision': ''}, {'expectedRevision': '../other'},
    {'expectedRevision': 'a' * 33}, {'expectedRevision': 'a' * 32, 'user': 'other'},
    {'expectedRevision': 'a' * 32, 'granted': False}])
def test_cancel_requires_only_current_request_revision(app, payload):
    _, _, _, auth = private_tool(app)
    api = app.test_client()
    apply(api, auth)
    assert api.post('/api/tools/1/requests/cancel', headers=auth, json=payload).status_code == 400
    with app.app_context():
        assert db().access.find_one({'_id': '1:member'})['status'] == '대기'


def test_browser_cancel_requires_csrf_and_key_must_still_be_valid(app):
    _, _, key, auth = private_tool(app)
    api = app.test_client()
    revision = apply(api, auth)['requestRevision']
    member, _ = ready(app, 'member')
    assert cancel(member, {}, revision).status_code == 403
    with app.app_context():
        db().local_tokens.update_one({'id': key['id']}, {'$set': {'revoked': True}})
    assert cancel(api, auth, revision).status_code == 401
    with app.app_context():
        assert db().access.find_one({'_id': '1:member'})['status'] == '대기'


@pytest.mark.parametrize('grant_kind', ['decision', 'direct', 'department'])
def test_cancel_never_revokes_existing_user_or_organization_grant(app, grant_kind):
    owner, headers, _, auth = private_tool(app)
    api = app.test_client()
    revision = apply(api, auth)['requestRevision']
    if grant_kind == 'decision':
        response = owner.post('/api/requests/1:member/decision', headers=headers,
                              json={'status': '승인', 'reason': '', 'expectedRevision': revision})
    elif grant_kind == 'direct':
        response = owner.post('/api/tools/1/grants', headers=headers, json={'user': 'member'})
    else:
        with app.app_context(): ensure_user('member', 'Member', 'Team A', 'TEAM-A')
        response = owner.post('/api/tools/1/grants/departments', headers=headers,
                              json={'departments': [{'code': 'TEAM-A', 'name': 'Team A'}]})
    assert response.status_code == 200
    before = api.get('/api/tools/1/access-status', headers=auth).json
    assert not before['canCancel'] and before['access'] == 'approved'
    response = cancel(api, auth, revision)
    assert response.status_code == 200 and response.json['access'] == 'approved'
    assert response.json['cancelled'] is False
    assert api.get('/download/1/1', headers=auth).status_code == 200
    with app.app_context():
        row = db().access.find_one({'_id': '1:member'})
        assert all(entry['status'] != '취소' for entry in row['history'])


@pytest.mark.parametrize('iteration', range(6))
def test_concurrent_cancel_and_approval_has_only_one_terminal_transition(app, iteration):
    _, headers, _, auth = private_tool(app)
    revision = apply(app.test_client(), auth)['requestRevision']
    owner, _ = ready(app)
    barrier = Barrier(2)
    def approve():
        barrier.wait()
        return owner.post('/api/requests/1:member/decision', headers=headers,
                          json={'status': '승인', 'reason': '', 'expectedRevision': revision})
    def withdraw():
        barrier.wait()
        return cancel(app.test_client(), auth, revision)
    with ThreadPoolExecutor(max_workers=2) as pool:
        approval, withdrawal = pool.submit(approve), pool.submit(withdraw)
        ar, cr = approval.result(), withdrawal.result()
    assert ar.status_code in (200, 409) and cr.status_code == 200
    with app.app_context():
        row = db().access.find_one({'_id': '1:member'})
        assert row['status'] in {'승인', '취소'}
        assert len(row['history']) == 2
        assert row['granted'] is (row['status'] == '승인')
        assert cr.json['cancelled'] is (row['status'] == '취소')


def test_cancelled_request_cannot_be_approved_and_can_reapply(app):
    owner, headers, _, auth = private_tool(app)
    api = app.test_client()
    revision = apply(api, auth)['requestRevision']
    assert cancel(api, auth, revision).json['cancelled']
    assert owner.post('/api/requests/1:member/decision', headers=headers,
                      json={'status': '승인', 'reason': '', 'expectedRevision': revision}).status_code == 409
    member, member_headers = ready(app, 'member')
    again = member.post('/api/tools/1/requests', headers=member_headers, json=REASON)
    assert again.status_code == 200 and again.json['requestRevision'] != revision
    assert again.json['canCancel'] and again.json['requestStatus'] == 'pending'


def test_cancel_notification_failure_does_not_undo_saved_withdrawal(app, monkeypatch):
    _, _, _, auth = private_tool(app)
    api = app.test_client()
    revision = apply(api, auth)['requestRevision']
    monkeypatch.setattr(mongo_api, 'deliver_pending', lambda *args: True)
    first = cancel(api, auth, revision)
    repeated = cancel(api, auth, revision)
    assert first.status_code == repeated.status_code == 200
    assert first.json['cancelled'] and repeated.json['cancelled']
    assert first.json['pending'] and repeated.json['pending']
    with app.app_context():
        row = db().access.find_one({'_id': '1:member'})
        assert row['status'] == '취소' and len(row['history']) == 2 and row['outbox']


@pytest.mark.parametrize('decision', ['승인', '반려'])
def test_stale_reviewed_revision_cannot_decide_new_application(app, decision):
    owner, headers, _, auth = private_tool(app)
    api = app.test_client()
    first = apply(api, auth)['requestRevision']
    reviewed = owner.get('/api/bootstrap').json['requests'][0]
    assert reviewed['requestRevision'] == first
    assert cancel(api, auth, first).json['cancelled']
    second = apply(api, auth)['requestRevision']
    stale = owner.post('/api/requests/1:member/decision', headers=headers,
                       json={'status': decision, 'reason': '검토 결과', 'expectedRevision': first})
    assert stale.status_code == 409
    state = api.get('/api/tools/1/access-status', headers=auth).json
    assert state['requestRevision'] == second and state['requestStatus'] == 'pending'
    valid = owner.post('/api/requests/1:member/decision', headers=headers,
                       json={'status': decision, 'reason': '새 신청 검토', 'expectedRevision': second})
    assert valid.status_code == 200


@pytest.mark.parametrize('decision', ['승인', '반려'])
def test_old_admin_screen_cannot_decide_a_reapplied_request(app, decision):
    owner, headers, _, auth = private_tool(app)
    api = app.test_client()
    first = apply(api, auth)['requestRevision']
    assert cancel(api, auth, first).json['cancelled']
    second = apply(api, auth)['requestRevision']
    assert second != first
    old_client = owner.post('/api/requests/1:member/decision', headers=headers,
                            json={'status': decision, 'reason': '검토'})
    assert old_client.status_code == 409
    assert '새로고침' in old_client.json['error']
    state = api.get('/api/tools/1/access-status', headers=auth).json
    assert state['requestRevision'] == second and state['requestStatus'] == 'pending'
    reviewed = owner.get('/api/bootstrap').json['requests'][0]
    assert reviewed['requestRevision'] == second
    assert owner.post('/api/requests/1:member/decision', headers=headers,
                      json={'status': decision, 'reason': '새 신청 검토',
                            'expectedRevision': reviewed['requestRevision']}).status_code == 200


@pytest.mark.parametrize('revision', [None, '', 1, 'a' * 33, 'x' * 32])
def test_malformed_admin_revision_is_rejected_with_refresh_guidance(app, revision):
    owner, headers, _, auth = private_tool(app)
    apply(app.test_client(), auth)
    result = owner.post('/api/requests/1:member/decision', headers=headers,
                        json={'status': '승인', 'reason': '', 'expectedRevision': revision})
    assert result.status_code == 400 and '새로고침' in result.json['error']
    with app.app_context():
        assert db().access.find_one({'_id': '1:member'})['status'] == '대기'
