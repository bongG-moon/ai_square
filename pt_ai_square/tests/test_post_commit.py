"""Committed writes stay successful while durable secondary effects are pending."""
import uuid

import pytest
from pymongo.collection import Collection
from pymongo.errors import OperationFailure

from pt_ai_square.backend import mongo_api, post_commit, storage_capacity
from pt_ai_square.backend.storage import db
from .conftest import ready, publish
from .test_storage_capacity import limits


PRIVATE = 'mongodb://private-user:private-password@private-host/employee-data'


def unavailable():
    return OperationFailure(PRIVATE, 225, {'errmsg': PRIVATE, 'code': 225})


def fail_update(monkeypatch, predicate):
    original = Collection.update_one

    def update(collection, query, change, *args, **kwargs):
        if predicate(collection.name, query, change):
            raise unavailable()
        return original(collection, query, change, *args, **kwargs)

    monkeypatch.setattr(Collection, 'update_one', update)


@pytest.mark.parametrize('updating', [False, True])
@pytest.mark.parametrize('failure', ['subscription', 'audit', 'completion'])
def test_publish_replays_durable_effects_without_duplicate_version(
        app, monkeypatch, caplog, updating, failure):
    client, headers = ready(app)
    if updating:
        assert publish(client, headers).status_code == 201
    number = 2 if updating else 1
    request_id = str(uuid.uuid4())
    arguments = dict(mode='url', url='https://example.test/tool', clientRequestId=request_id)
    if updating:
        arguments.update(tid=1, revision=1)
    predicates = {
        'subscription': lambda name, query, change: name == 'subscriptions',
        'audit': lambda name, query, change: name == 'audit',
        'completion': lambda name, query, change: name == 'tools' and 'outbox' in change.get('$pull', {}),
    }
    with monkeypatch.context() as fault:
        fail_update(fault, predicates[failure])
        result = publish(client, headers, **arguments)
    assert result.status_code == 201, result.json
    assert result.json['version'] == number and result.json['pending'] is True
    assert PRIVATE not in result.get_data(as_text=True) + caplog.text
    assert 'DB-SESSION-ORDER' in caplog.text and 'mongo_code=225' in caplog.text
    with app.app_context():
        stored = db().tools.find_one({'_id': 1})
        assert stored['active'] == number and stored['revision'] == number
        assert len(stored['versions']) == number
        jobs = [job for job in stored['outbox'] if 'audit' in job]
        assert len(jobs) == 1 and jobs[0]['audit']['user'] == 'owner'
        audit_id = jobs[0]['audit']['_id']
    # A later explicit opt-out wins even if the original subscribe never ran.
    assert client.put('/api/tools/1/subscription', headers=headers,
                      json={'enabled': False}).status_code == 200
    replay = publish(client, headers, **arguments)
    assert replay.status_code == 200 and replay.json['replayed'] is True
    assert replay.json['pending'] is False and replay.json['version'] == number
    with app.app_context():
        assert len(db().tools.find_one({'_id': 1})['versions']) == number
        assert db().tools.find_one({'_id': 1})['outbox'] == []
        assert db().audit.count_documents({'_id': audit_id}) == 1
        assert db().subscriptions.find_one({'tool': 1, 'user': 'owner'})['enabled'] is False
        assert post_commit.drain() == post_commit.DeliveryResult()


def test_publish_notification_failure_keeps_outbox_and_bootstrap_readable(app, monkeypatch):
    client, headers = ready(app)
    assert publish(client, headers).status_code == 201
    member, mh = ready(app, 'member')
    assert member.put('/api/tools/1/subscription', headers=mh,
                      json={'enabled': True}).status_code == 200
    with monkeypatch.context() as fault:
        fail_update(fault, lambda name, query, change: name == 'notifications')
        result = publish(client, headers, tid=1, revision=1)
        assert result.status_code == 201 and result.json['pending'] is True
        response = client.get('/api/bootstrap')
        assert response.status_code == 200
        assert response.json['items'][0]['active'] == 2
        with app.app_context():
            stored = db().tools.find_one({'_id': 1})
            assert len(stored['outbox']) == 1
    assert client.get('/api/notifications').json['pending'] is False
    with app.app_context():
        assert db().tools.find_one({'_id': 1})['outbox'] == []
        assert db().notifications.count_documents({'user': 'member', 'kind': 'release'}) == 1


@pytest.mark.parametrize('revision', [0, 1])
def test_capacity_commit_retains_audit_and_uses_saved_policy(app, monkeypatch, revision):
    client, headers = ready(app, 'admin')
    if revision:
        assert limits(client, headers).status_code == 200
    with monkeypatch.context() as fault:
        fail_update(fault, lambda name, query, change: name == 'audit')
        # A post-save response must not require another settings read.
        fault.setattr(storage_capacity, 'policy', lambda: pytest.fail('Unexpected policy reread'))
        result = limits(client, headers, expectedRevision=revision, quotaBytes=7 * 1024**3)
    assert result.status_code == 200 and result.json['ok'] is True
    assert result.json['pending'] is True
    assert result.json['storage']['configuredQuota'] == 7 * 1024**3
    assert result.json['storage']['limitRevision'] == revision + 1
    assert result.json['storage']['source'] == 'admin'
    with app.app_context():
        row = db().settings.find_one({'_id': 'storage_limits'})
        assert row['revision'] == revision + 1 and row['quotaBytes'] == 7 * 1024**3
        assert len(row['outbox']) == 1
        audit_id = row['outbox'][0]['audit']['_id']
    assert client.get('/api/notifications').status_code == 200
    with app.app_context():
        assert db().settings.find_one({'_id': 'storage_limits'})['outbox'] == []
        assert db().audit.count_documents({'_id': audit_id}) == 1
        assert post_commit.drain() == post_commit.DeliveryResult()


def test_like_flush_failure_returns_saved_state_and_recovers_once(app, monkeypatch):
    client, headers = ready(app)
    assert publish(client, headers).status_code == 201
    calls = []
    set_like = mongo_api.activity.set_like

    def tracked_like(*args):
        calls.append(args)
        return set_like(*args)

    monkeypatch.setattr(mongo_api.activity, 'set_like', tracked_like)
    with monkeypatch.context() as fault:
        fail_update(fault, lambda name, query, change: name == 'activity')
        result = client.put('/api/tools/1/like', headers=headers, json={'liked': True})
        assert result.status_code == 200
        assert result.json == {'liked': True, 'count': 1, 'pending': True,
                               'historyPending': True, 'countsPending': False}
        response = client.get('/api/bootstrap')
        assert response.status_code == 200
        assert response.json['items'][0]['liked'] is True
        assert response.json['items'][0]['likes'] == 1
        with app.app_context():
            row = db().activity_state.find_one({'_id': 'like:1:owner'})
            assert row['liked'] is True and len(row['outbox']) == 1
    assert calls == [(1, 'owner', True)]
    assert client.get('/api/notifications').json['pending'] is False
    with app.app_context():
        assert db().activity.count_documents({'tool': 1, 'kind': 'like'}) == 1
        assert db().activity_state.find_one({'_id': 'like:1:owner'})['outbox'] == []


def test_bootstrap_skips_all_followups_and_preserves_primary_read_failure(app, monkeypatch):
    client, headers = ready(app)
    assert publish(client, headers).status_code == 201
    calls = []

    def failed(name):
        def run(*args):
            calls.append(name)
            raise unavailable()
        return run

    monkeypatch.setattr(post_commit, 'drain', failed('maintenance'))
    monkeypatch.setattr(mongo_api.activity, 'flush', failed('activity'))
    monkeypatch.setattr(mongo_api, 'deliver_notifications', failed('notifications'))
    response = client.get('/api/bootstrap')
    assert response.status_code == 200
    assert response.json['items'][0]['id'] == 1
    assert calls == []
    monkeypatch.setattr(mongo_api.activity, 'statistics', failed('primary-statistics'))
    response = client.get('/api/bootstrap')
    assert response.status_code == 503
    assert response.json['diagnostic']['mongo_code'] == 225


@pytest.mark.parametrize('operation', ['publish-new', 'publish-update', 'capacity-new', 'capacity-update', 'like'])
def test_primary_failure_still_fails_without_mutation_retry(app, monkeypatch, operation):
    client, headers = ready(app, 'admin')
    if operation in {'publish-update', 'like'}:
        assert publish(client, headers).status_code == 201
    if operation == 'capacity-update':
        assert limits(client, headers).status_code == 200
    calls = []
    original_insert, original_update = Collection.insert_one, Collection.update_one

    def inserted(collection, value, *args, **kwargs):
        if ((operation == 'publish-new' and collection.name == 'tools') or
                (operation == 'capacity-new' and collection.name == 'settings' and value['_id'] == 'storage_limits')):
            calls.append(operation)
            raise unavailable()
        return original_insert(collection, value, *args, **kwargs)

    def updated(collection, query, change, *args, **kwargs):
        if ((operation == 'publish-update' and collection.name == 'tools' and 'revision' in query) or
                (operation == 'capacity-update' and collection.name == 'settings' and query.get('_id') == 'storage_limits') or
                (operation == 'like' and collection.name == 'activity_state')):
            calls.append(operation)
            raise unavailable()
        return original_update(collection, query, change, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Collection, 'insert_one', inserted)
        fault.setattr(Collection, 'update_one', updated)
        if operation.startswith('publish'):
            arguments = {'tid': 1, 'revision': 1} if operation.endswith('update') else {}
            result = publish(client, headers, mode='url', url='https://example.test/tool', **arguments)
        elif operation.startswith('capacity'):
            result = limits(client, headers, expectedRevision=1 if operation.endswith('update') else 0)
        else:
            result = client.put('/api/tools/1/like', headers=headers, json={'liked': True})
    assert result.status_code == 503 and result.json['diagnostic']['mongo_code'] == 225
    assert calls == [operation]
    with app.app_context():
        if operation == 'publish-new':
            assert db().tools.count_documents({}) == 0
        elif operation == 'publish-update':
            assert len(db().tools.find_one({'_id': 1})['versions']) == 1
        elif operation == 'capacity-new':
            assert db().settings.find_one({'_id': 'storage_limits'}) is None
        elif operation == 'capacity-update':
            assert db().settings.find_one({'_id': 'storage_limits'})['revision'] == 1
        else:
            assert db().activity_state.count_documents({'liked': True}) == 0


def test_non_mongo_followup_errors_are_not_hidden(app):
    def defect():
        raise ValueError('programming error')

    with app.app_context(), pytest.raises(ValueError, match='programming error'):
        post_commit.followup_pending('test', defect)
