"""Real MongoDB reservation conflicts, permissions, retries, and atomic release."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
import uuid

import pytest
from pymongo.collection import Collection
from pymongo.errors import OperationFailure

from pt_ai_square.backend import immersion_room
from pt_ai_square.backend.storage import db
from .conftest import ready


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(immersion_room, 'today', lambda: date(2026, 11, 1))


def payload(**changes):
    value = dict(startDate='2026-11-10', endDate='2026-11-10', slot='all',
                 title='업무 도구 개발', purpose='팀에서 사용하는 보고서 도구를 함께 개발합니다.',
                 clientRequestId=str(uuid.uuid4()))
    value.update(changes)
    return value


def create(client, headers, **changes):
    return client.post('/api/immersion-room/reservations', headers=headers, json=payload(**changes))


def transition(client, headers, row, status, **changes):
    body = dict(status=status, expectedRevision=row['revision'])
    body.update(changes)
    return client.patch('/api/immersion-room/reservations/' + row['id'], headers=headers, json=body)


def month(client):
    response = client.get('/api/immersion-room?start=2026-11-01&end=2026-11-30')
    assert response.status_code == 200, response.json
    return response.json


def test_member_request_admin_approval_and_admin_autoapproval(app):
    owner, oh = ready(app, 'owner')
    admin, ah = ready(app, 'admin')
    made = create(owner, oh)
    assert made.status_code == 201, made.json
    row = made.json['reservation']
    assert row['status'] == 'pending' and row['revision'] == 1
    assert row['owner'] == dict(id='owner', name='owner', org='공통')
    assert row['canCancel'] and not row['canApprove']
    admin_row = month(admin)['reservations'][0]
    assert admin_row['canApprove']
    approved = transition(admin, ah, row, 'approved')
    assert approved.status_code == 200 and approved.json['reservation']['status'] == 'approved'
    assert approved.json['reservation']['revision'] == 2
    direct = create(admin, ah, startDate='2026-11-11', endDate='2026-11-11')
    assert direct.status_code == 201 and direct.json['reservation']['status'] == 'approved'
    assert month(owner)['today'] == '2026-11-01'
    assert not month(owner)['canManage'] and month(admin)['canManage']


def test_pending_all_day_blocks_and_am_pm_coexist(app):
    owner, oh = ready(app)
    member, mh = ready(app, 'member')
    assert create(owner, oh, slot='am').status_code == 201
    assert create(member, mh, slot='pm').status_code == 201
    assert create(member, mh, slot='am').status_code == 409
    assert create(member, mh).status_code == 409
    with app.app_context():
        assert db().room_reservations.count_documents({}) == 2


def test_multi_day_collision_is_all_or_nothing_and_inclusive(app):
    owner, oh = ready(app)
    assert create(owner, oh, startDate='2026-11-12', endDate='2026-11-12', slot='pm').status_code == 201
    assert create(owner, oh, startDate='2026-11-10', endDate='2026-11-12').status_code == 409
    # A failed multi-day write must not leave the otherwise-free first dates held.
    assert create(owner, oh, startDate='2026-11-10', endDate='2026-11-11').status_code == 201
    assert create(owner, oh, startDate='2026-11-12', endDate='2026-11-12', slot='am').status_code == 201


def test_simultaneous_overlap_only_one_succeeds(app):
    clients = [ready(app, 'owner'), ready(app, 'member')]
    barrier = Barrier(2)
    def submit(pair):
        client, headers = pair
        barrier.wait(timeout=5)
        return create(client, headers, startDate='2026-11-10', endDate='2026-11-14').status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, clients))
    assert sorted(results) == [201, 409]
    with app.app_context():
        assert db().room_reservations.count_documents({}) == 1
        assert len(db().room_reservations.find_one()['slotKeys']) == 10


def test_simultaneous_same_request_is_idempotent(app):
    clients = [ready(app), ready(app)]
    body = payload()
    barrier = Barrier(2)
    def submit(pair):
        client, headers = pair
        barrier.wait(timeout=5)
        response = client.post('/api/immersion-room/reservations', headers=headers, json=body)
        return response.status_code, response.json['reservation']['id']
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(submit, clients))
    assert sorted(status for status, _ in results) == [200, 201]
    assert len({identifier for _, identifier in results}) == 1
    with app.app_context():
        assert db().room_reservations.count_documents({}) == 1


def test_reject_cancel_release_slots_and_history_permissions(app):
    owner, oh = ready(app)
    member, mh = ready(app, 'member')
    admin, ah = ready(app, 'admin')
    row = create(owner, oh).json['reservation']
    rejected = transition(admin, ah, row, 'rejected', reason='다른 날짜로 신청해 주세요.')
    assert rejected.status_code == 200
    assert month(owner)['reservations'][0]['reason'] == '다른 날짜로 신청해 주세요.'
    assert month(member)['reservations'] == []
    new = create(member, mh).json['reservation']
    assert transition(member, mh, new, 'cancelled').status_code == 200
    assert create(owner, oh).status_code == 201
    with app.app_context():
        assert db().room_reservations.count_documents({'slotKeys': {'$exists': True}}) == 1
        assert db().room_reservations.count_documents({}) == 3
    assert len(month(admin)['reservations']) == 3
    assert len(month(owner)['reservations']) == 2


def test_permissions_authoritative_identity_and_csrf(app):
    owner, oh = ready(app)
    member, mh = ready(app, 'member')
    admin, ah = ready(app, 'admin')
    row = create(owner, oh).json['reservation']
    assert transition(owner, oh, row, 'approved').status_code == 403
    assert transition(member, mh, row, 'cancelled').status_code == 403
    assert transition(member, mh, row, 'rejected').status_code == 403
    assert create(owner, {}, startDate='2026-11-11', endDate='2026-11-11').status_code == 403
    assert transition(admin, {}, row, 'approved').status_code == 403
    assert create(owner, oh, owner={'id': 'admin'}).status_code == 400
    assert create(owner, oh, status='approved').status_code == 400
    assert app.test_client().get('/api/immersion-room?start=2026-11-01&end=2026-11-30').status_code == 401
    assert transition(admin, ah, row, 'cancelled').status_code == 200


def test_personal_key_cannot_read_or_write_room(app):
    owner, oh = ready(app)
    token = owner.post('/api/local-tokens', headers=oh, json={}).json['token']
    headers = {'Authorization': 'Bearer ' + token}
    assert owner.get('/api/immersion-room?start=2026-11-01&end=2026-11-30', headers=headers).status_code == 403
    assert create(owner, headers).status_code == 403


def test_admin_list_pagination_and_detail_permissions(app):
    owner, oh = ready(app, 'owner')
    member, _ = ready(app, 'member')
    admin, ah = ready(app, 'admin')
    row = create(owner, oh).json['reservation']
    later = create(owner, oh, startDate='2026-12-10', endDate='2026-12-10').json['reservation']
    url = '/api/immersion-room/admin/reservations'
    assert owner.get(url).status_code == 403
    listing = admin.get(url + '?pageSize=1').json
    assert listing['total'] == 2 and listing['totalPages'] == 2
    assert listing['reservations'][0]['id'] == row['id']
    assert admin.get(url + '?pageSize=1&page=2').json['reservations'][0]['id'] == later['id']
    assert admin.get(url + '?status=bad').status_code == 400
    assert admin.get(url + '?pageSize=999').status_code == 400
    assert transition(admin, ah, row, 'rejected', reason='다른 날짜').status_code == 200
    assert admin.get(url + '?status=pending').json['total'] == 1
    assert admin.get(url + '?status=history').json['reservations'][0]['id'] == row['id']
    detail = '/api/immersion-room/reservations/' + row['id']
    assert owner.get(detail).json['reservation']['reason'] == '다른 날짜'
    assert admin.get(detail).status_code == 200
    assert member.get(detail).status_code == 404


def test_status_notifications_idempotent_and_owner_only(app):
    owner, oh = ready(app, 'owner')
    admin, ah = ready(app, 'admin')
    row = create(owner, oh).json['reservation']
    rejected = transition(admin, ah, row, 'rejected', reason='일정 변경')
    assert rejected.status_code == 200
    assert transition(admin, ah, row, 'rejected', reason='일정 변경').status_code == 200
    with app.app_context():
        messages = list(db().notifications.find({'user': 'owner', 'kind': 'room'}))
        assert len(messages) == 1
        assert '반려' in messages[0]['title']
        assert messages[0]['target'] == {'type': 'room', 'id': row['id'], 'startDate': row['startDate']}
    assert owner.get('/api/immersion-room/reservations/' + row['id']).json['reservation']['reason'] == '일정 변경'
    approved_row = create(owner, oh, startDate='2026-11-12', endDate='2026-11-12').json['reservation']
    approved = transition(admin, ah, approved_row, 'approved').json['reservation']
    assert transition(admin, ah, approved, 'cancelled').status_code == 200
    self_cancel = create(owner, oh, startDate='2026-11-13', endDate='2026-11-13').json['reservation']
    assert transition(owner, oh, self_cancel, 'cancelled').status_code == 200
    with app.app_context():
        messages = list(db().notifications.find({'user': 'owner', 'kind': 'room'}))
        assert len(messages) == 3
        assert any('승인' in message['title'] for message in messages)
        assert any('취소' in message['title'] for message in messages)


def test_rejection_outbox_retries_after_notification_failure(app, monkeypatch):
    owner, oh = ready(app, 'owner')
    admin, ah = ready(app, 'admin')
    row = create(owner, oh).json['reservation']
    original = Collection.update_one
    def failing(collection, *args, **kwargs):
        if collection.name == 'notifications':
            raise OperationFailure('injected failure', code=225)
        return original(collection, *args, **kwargs)
    monkeypatch.setattr(Collection, 'update_one', failing)
    assert transition(admin, ah, row, 'rejected', reason='사유').status_code == 200
    with app.app_context():
        saved = db().room_reservations.find_one({'_id': row['id']})
        assert saved['status'] == 'rejected' and len(saved['outbox']) == 1
    monkeypatch.setattr(Collection, 'update_one', original)
    response = owner.get('/api/notifications')
    assert response.status_code == 200
    assert any(item['target']['id'] == row['id'] and item['kind'] == 'room' for item in response.json['notifications'])
    with app.app_context():
        assert not db().room_reservations.find_one({'_id': row['id']}).get('outbox')


def test_replay_mismatch_owner_scope_and_cancelled_replay(app):
    owner, oh = ready(app)
    member, mh = ready(app, 'member')
    key = str(uuid.uuid4())
    row = create(owner, oh, clientRequestId=key).json['reservation']
    assert create(owner, oh, clientRequestId=key).status_code == 200
    assert create(owner, oh, clientRequestId=key, purpose='다른 목적').status_code == 409
    assert transition(owner, oh, row, 'cancelled').status_code == 200
    replay = create(owner, oh, clientRequestId=key)
    assert replay.status_code == 200 and replay.json['reservation']['status'] == 'cancelled'
    # Same UUID from another authenticated member is a distinct request.
    assert create(member, mh, clientRequestId=key).status_code == 201


def test_transitions_revision_and_retries_do_not_repeat_decisions(app):
    owner, oh = ready(app)
    admin, ah = ready(app, 'admin')
    row = create(owner, oh).json['reservation']
    approved = transition(admin, ah, row, 'approved').json['reservation']
    assert transition(admin, ah, row, 'approved').status_code == 200
    assert transition(admin, ah, row, 'cancelled').status_code == 409
    assert transition(admin, ah, approved, 'rejected').status_code == 409
    cancelled = transition(owner, oh, approved, 'cancelled')
    assert cancelled.status_code == 200
    assert transition(owner, oh, approved, 'cancelled').status_code == 200
    assert transition(admin, ah, cancelled.json['reservation'], 'approved').status_code == 409
    with app.app_context():
        assert len(db().room_reservations.find_one({'_id': row['id']})['decisions']) == 3


@pytest.mark.parametrize('changes', [
    {'startDate': '2026-10-31'}, {'startDate': '2026-11-11'},
    {'endDate': '2026-02-30'}, {'endDate': '2026-12-11'},
    {'slot': 'midnight'}, {'slot': []}, {'title': ''}, {'title': 'x' * 101},
    {'purpose': ''}, {'purpose': 'x' * 2001}, {'purpose': 'a\x00b'},
    {'clientRequestId': 'not-a-uuid'}, {'clientRequestId': None}, {'startDate': 20261110},
])
def test_invalid_create(app, changes):
    owner, oh = ready(app)
    assert create(owner, oh, **changes).status_code == 400
    with app.app_context():
        assert db().room_reservations.count_documents({}) == 0


def test_calendar_range_and_half_days_default_and_plain_text(app):
    owner, oh = ready(app)
    assert owner.get('/api/immersion-room').status_code == 400
    assert owner.get('/api/immersion-room?start=2026-11-02&end=2026-11-01').status_code == 400
    assert owner.get('/api/immersion-room?start=2026-11-01&end=2027-01-02').status_code == 400
    body = payload(title='  <script>name</script>  ', purpose='목적\n두 번째 줄')
    del body['slot']
    row = owner.post('/api/immersion-room/reservations', headers=oh, json=body).json['reservation']
    assert row['slot'] == 'all' and row['title'] == '<script>name</script>'
    assert row['purpose'] == '목적\n두 번째 줄'
    result = month(owner)['reservations'][0]
    assert not {'slotKeys', 'clientRequestId', 'fingerprint', 'decisions'} & set(result)
    assert owner.get('/api/immersion-room?start=2026-11-11&end=2026-11-20').json['reservations'] == []


def test_past_pending_cannot_be_approved_but_can_be_cancelled(app, monkeypatch):
    owner, oh = ready(app)
    admin, ah = ready(app, 'admin')
    row = create(owner, oh).json['reservation']
    monkeypatch.setattr(immersion_room, 'today', lambda: date(2026, 11, 11))
    assert not month(admin)['reservations'][0]['canApprove']
    assert month(admin)['reservations'][0]['canReject']
    assert transition(admin, ah, row, 'approved').status_code == 409
    assert transition(owner, oh, row, 'cancelled').status_code == 200


def test_primary_write_failure_never_returns_saved_or_leaves_partial_slots(app, monkeypatch):
    owner, oh = ready(app)
    original = Collection.insert_one
    def fail(coll, *args, **kwargs):
        if coll.name == 'room_reservations':
            raise OperationFailure('private failure', 225)
        return original(coll, *args, **kwargs)
    with monkeypatch.context() as fault:
        fault.setattr(Collection, 'insert_one', fail)
        response = create(owner, oh)
    assert response.status_code == 503 and 'private failure' not in str(response.json)
    assert month(owner)['reservations'] == []
    assert create(owner, oh).status_code == 201


def test_history_limit_never_hides_active_reservations(app):
    owner, oh = ready(app)
    row = create(owner, oh).json['reservation']
    with app.app_context():
        base = db().room_reservations.find_one({'_id': row['id']})
        history = []
        for n in range(105):
            item = dict(base, _id=str(uuid.uuid4()), clientRequestId=str(uuid.uuid4()),
                        status='cancelled', updated=base['updated'] + n)
            item.pop('slotKeys')
            history.append(item)
        db().room_reservations.insert_many(history)
    result = month(owner)
    assert result['historyTruncated'] and len(result['reservations']) == 101
    assert len([item for item in result['reservations'] if item['status'] == 'pending']) == 1
