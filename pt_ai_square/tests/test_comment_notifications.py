"""Feedback inbox delivery, using private UUID Mongo databases and fault injection."""
from pymongo.collection import Collection
from pymongo.errors import OperationFailure

from pt_ai_square.backend.storage import db, deliver_notifications
from .conftest import publish, ready


def create_tool(app, *, restricted=False):
    owner, headers = ready(app, 'owner')
    response = publish(owner, headers, owner='다른 표시 이름', approval=restricted)
    assert response.status_code == 201
    return owner, headers, response.json['id']


def add_comment(client, headers, tid, text='설치 안내를 조금 더 자세히 적어 주세요.'):
    return client.post(f'/api/tools/{tid}/comments', headers=headers,
                       json={'kind': '개선 의견', 'text': text})


def feedback_notices(client):
    response = client.get('/api/notifications')
    assert response.status_code == 200
    return [row for row in response.json['notifications'] if row['kind'] == 'feedback']


def test_other_member_comment_notifies_actual_owner_even_when_update_notifications_are_off(app):
    owner, headers, tid = create_tool(app)
    member, member_headers = ready(app, 'member')
    admin, _ = ready(app, 'admin')
    for client, csrf in [(owner, headers), (member, member_headers)]:
        assert client.put(f'/api/tools/{tid}/subscription', headers=csrf,
                          json={'enabled': False}).status_code == 200
    saved = add_comment(member, member_headers, tid)
    assert saved.status_code == 201 and saved.json['pending'] is False
    notice = feedback_notices(owner)
    assert len(notice) == 1 and notice[0]['user'] == 'owner'
    assert notice[0]['target'] == {'type': 'feedback', 'id': tid, 'feedbackId': saved.json['id']}
    assert 'member' in notice[0]['title'] and notice[0]['read'] is False
    assert len(feedback_notices(admin)) == 1
    assert feedback_notices(member) == []
    with app.app_context():
        assert db().tools.find_one({'_id': tid})['owner'] == 'owner'
        assert db().subscriptions.find_one({'tool': tid, 'user': 'owner'})['enabled'] is False
        assert db().subscriptions.find_one({'tool': tid, 'user': 'member'})['enabled'] is False


def test_own_comment_has_no_self_notice_but_a_reply_notifies_the_comment_author(app):
    owner, headers, tid = create_tool(app)
    member, mh = ready(app, 'member')
    own = add_comment(owner, headers, tid)
    assert own.status_code == 201 and feedback_notices(owner) == []
    saved = add_comment(member, mh, tid)
    assert saved.status_code == 201
    assert owner.post(f'/api/feedback/{saved.json["id"]}/reply', headers=headers,
                      json={'text': '안내를 보완하겠습니다.', 'status': '반영 중'}).status_code == 200
    notices = feedback_notices(member)
    assert len(notices) == 1 and notices[0]['target']['feedbackId'] == saved.json['id']
    assert len(feedback_notices(owner)) == 1  # The member's comment, never the owner's own reply.


def test_comment_subscription_failure_does_not_hold_back_owner_inbox(app, monkeypatch):
    owner, _, tid = create_tool(app)
    member, mh = ready(app, 'member')
    original = Collection.update_one
    def fail_subscription(collection, *args, **kwargs):
        if collection.name == 'subscriptions':
            raise OperationFailure('fixture secondary subscription failure', 225)
        return original(collection, *args, **kwargs)
    with monkeypatch.context() as fault:
        fault.setattr(Collection, 'update_one', fail_subscription)
        saved = add_comment(member, mh, tid)
        assert saved.status_code == 201 and saved.json['pending'] is True
        with app.app_context():
            row = db().feedback.find_one({'_id': saved.json['id']})
            assert row['outbox'] and row['body']
            # The author's subscription is secondary to notifying the owner.
            assert db().notifications.count_documents({'user': 'owner', 'kind': 'feedback'}) == 1
        assert len(feedback_notices(owner)) == 1
    assert len(feedback_notices(owner)) == 1
    assert len(feedback_notices(owner)) == 1
    with app.app_context():
        assert db().feedback.find_one({'_id': saved.json['id']})['outbox'] == []
        assert db().subscriptions.find_one({'tool': tid, 'user': 'member'})['enabled'] is True
        assert db().notifications.count_documents({'kind': 'feedback'}) == 2


def test_one_recipient_failure_does_not_block_the_other_recipient(app, monkeypatch):
    owner, _, tid = create_tool(app)
    member, mh = ready(app, 'member')
    original = Collection.update_one
    def fail_admin_inbox(collection, query, change, *args, **kwargs):
        if collection.name == 'notifications' and change.get('$setOnInsert', {}).get('user') == 'admin':
            raise OperationFailure('fixture first recipient failure', 225)
        return original(collection, query, change, *args, **kwargs)
    with monkeypatch.context() as fault:
        fault.setattr(Collection, 'update_one', fail_admin_inbox)
        saved = add_comment(member, mh, tid)
        assert saved.status_code == 201 and saved.json['pending'] is True
        assert len(feedback_notices(owner)) == 1
        with app.app_context():
            assert db().feedback.find_one({'_id': saved.json['id']})['outbox']
            assert db().notifications.count_documents({'user': 'admin', 'kind': 'feedback'}) == 0
    admin, _ = ready(app, 'admin')
    assert len(feedback_notices(admin)) == 1
    assert len(feedback_notices(owner)) == 1
    with app.app_context():
        assert db().feedback.find_one({'_id': saved.json['id']})['outbox'] == []


def test_delivery_ack_failure_replay_never_duplicates_or_unreads_a_notice(app, monkeypatch):
    owner, headers, tid = create_tool(app)
    member, mh = ready(app, 'member')
    original = Collection.update_one
    def fail_ack(collection, query, change, *args, **kwargs):
        if collection.name == 'feedback' and '$pull' in change:
            raise OperationFailure('fixture delivery acknowledgement failure', 225)
        return original(collection, query, change, *args, **kwargs)
    with monkeypatch.context() as fault:
        fault.setattr(Collection, 'update_one', fail_ack)
        saved = add_comment(member, mh, tid)
        assert saved.status_code == 201 and saved.json['pending'] is True
        notice = feedback_notices(owner)[0]
        assert owner.put('/api/notifications/read', headers=headers,
                         json={'id': notice['id']}).status_code == 200
    notices = feedback_notices(owner)
    assert len(notices) == 1 and notices[0]['id'] == notice['id'] and notices[0]['read'] is True
    with app.app_context():
        assert deliver_notifications('feedback', saved.json['id']).pending is False
        assert db().notifications.count_documents({'kind': 'feedback'}) == 2


def test_comment_author_followup_reply_still_reaches_owner_when_admin_delivery_fails(app, monkeypatch):
    owner, _, tid = create_tool(app)
    member, mh = ready(app, 'member')
    saved = add_comment(member, mh, tid)
    assert saved.status_code == 201
    original = Collection.update_one
    def fail_admin(collection, query, change, *args, **kwargs):
        if collection.name == 'notifications' and change.get('$setOnInsert', {}).get('user') == 'admin':
            raise OperationFailure('fixture admin inbox failure', 225)
        return original(collection, query, change, *args, **kwargs)
    with monkeypatch.context() as fault:
        fault.setattr(Collection, 'update_one', fail_admin)
        response = member.post(f'/api/feedback/{saved.json["id"]}/reply', headers=mh,
                               json={'text': '재현 화면을 추가로 확인했습니다.'})
        assert response.status_code == 200 and response.json['pending'] is True
        notices = feedback_notices(owner)
        assert len(notices) == 2
        assert all(row['target'] == {'type': 'feedback', 'id': tid, 'feedbackId': saved.json['id']}
                   for row in notices)
    assert len(feedback_notices(owner)) == 2
    assert feedback_notices(member) == []


def test_unauthorized_comment_and_cross_user_read_cannot_change_the_owner_inbox(app):
    owner, _, tid = create_tool(app, restricted=True)
    member, mh = ready(app, 'member')
    assert add_comment(member, mh, tid).status_code == 403
    with app.app_context():
        assert db().feedback.count_documents({}) == 0
        assert db().notifications.count_documents({'kind': 'feedback'}) == 0
        db().access.insert_one({'tool': tid, 'user': 'member', 'granted': True, 'status': '승인'})
    saved = add_comment(member, mh, tid)
    assert saved.status_code == 201
    notice = feedback_notices(owner)[0]
    assert member.put('/api/notifications/read', headers=mh, json={'id': notice['id']}).status_code == 200
    assert feedback_notices(owner)[0]['read'] is False
    assert feedback_notices(member) == []


def test_primary_comment_insert_failure_never_claims_saved_or_sends_a_notice(app, monkeypatch):
    _, _, tid = create_tool(app)
    member, mh = ready(app, 'member')
    original = Collection.insert_one
    def fail_primary(collection, *args, **kwargs):
        if collection.name == 'feedback':
            raise OperationFailure('fixture primary write failure', 225)
        return original(collection, *args, **kwargs)
    monkeypatch.setattr(Collection, 'insert_one', fail_primary)
    response = add_comment(member, mh, tid)
    assert response.status_code == 503
    with app.app_context():
        assert db().feedback.count_documents({}) == 0
        assert db().notifications.count_documents({'kind': 'feedback'}) == 0
