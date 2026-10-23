"""Bounded durable delivery survives secondary failures without data loss."""
import time

import pytest
from flask import g
from pymongo.collection import Collection
from pymongo.errors import OperationFailure

from pt_ai_square.backend import mongo_store, post_commit
from pt_ai_square.backend.storage import db


def event(eid, **extra):
    now = time.time()
    return dict(id=eid, created=now,
                audit=dict(_id=eid, user='owner', action='Saved', created=now), **extra)


def fail_updates(monkeypatch, predicate):
    original = Collection.update_one

    def update(collection, query, change, *args, **kwargs):
        if predicate(collection.name, query, change):
            raise OperationFailure('mongodb://secret-user:secret-pass@private-host', 225)
        return original(collection, query, change, *args, **kwargs)

    monkeypatch.setattr(Collection, 'update_one', update)


def test_audit_event_has_stable_identity_and_no_side_effect(app):
    with app.app_context():
        g.user = {'id': 'owner'}
        value = mongo_store.audit_event('Saved', {'tool': 1, 'user': 'owner'})
        assert value['id'] == value['audit']['_id']
        assert value['audit']['user'] == 'owner'
        assert value['subscription'] == {'tool': 1, 'user': 'owner'}
        assert db().audit.count_documents({}) == 0
        assert mongo_store.audit_event('Saved')['id'] != value['id']


def test_operational_audit_payload_can_use_enclosing_event_id(app, monkeypatch):
    with app.app_context():
        value = event('operational-event')
        value['audit'].pop('_id')
        db().ideas.insert_one({'_id': 1, 'outbox': [value]})
        with monkeypatch.context() as fault:
            fail_updates(fault, lambda name, query, change: name == 'ideas' and '$pull' in change)
            assert mongo_store.deliver_notifications('ideas', 1) == post_commit.DeliveryResult(0, True)
        assert mongo_store.deliver_notifications('ideas', 1) == post_commit.DeliveryResult(1, False)
        assert db().audit.count_documents({'_id': 'operational-event'}) == 1


@pytest.mark.parametrize('failure', ['audit', 'subscriptions', 'notifications', 'completion'])
def test_delivery_partial_failure_preserves_event_and_continues(app, monkeypatch, caplog, failure):
    with app.app_context():
        first = event('first', subscription={'tool': 1, 'user': 'member'},
                      recipients=['member'], title='Ready', target={'tool': 1}, kind='release')
        db().tools.insert_many([{'_id': 1, 'outbox': [first]},
                                {'_id': 2, 'outbox': [event('second')]}])

        def predicate(name, query, change):
            if failure == 'completion':
                return name == 'tools' and query.get('_id') == 1 and '$pull' in change
            if name != failure:
                return False
            return (query.get('_id') in {'first', 'first:member'} or query.get('tool') == 1)

        with monkeypatch.context() as fault:
            fail_updates(fault, predicate)
            result = mongo_store.deliver_notifications('tools')
        assert result == post_commit.DeliveryResult(1, True)
        assert db().tools.find_one({'_id': 1})['outbox'] == [first]
        assert db().tools.find_one({'_id': 2})['outbox'] == []
        assert 'secret-user' not in caplog.text and 'mongo_code=225' in caplog.text
        # A later explicit unsubscribe must survive replay of the original event.
        db().subscriptions.update_one({'tool': 1, 'user': 'member'}, {'$set': {'enabled': False}}, upsert=True)
        assert mongo_store.deliver_notifications('tools') == post_commit.DeliveryResult(1, False)
        assert mongo_store.deliver_notifications('tools') == post_commit.DeliveryResult()
        assert db().audit.count_documents({'_id': 'first'}) == 1
        assert db().notifications.count_documents({'_id': 'first:member'}) == 1
        assert db().subscriptions.find_one({'tool': 1, 'user': 'member'})['enabled'] is False


def test_delivery_continues_later_event_in_same_document(app, monkeypatch):
    with app.app_context():
        db().ideas.insert_one({'_id': 1, 'outbox': [event('bad'), event('good')]})
        with monkeypatch.context() as fault:
            fail_updates(fault, lambda name, query, change: name == 'audit' and query.get('_id') == 'bad')
            result = mongo_store.deliver_notifications('ideas', 1)
        assert result == post_commit.DeliveryResult(1, True)
        assert [e['id'] for e in db().ideas.find_one({'_id': 1})['outbox']] == ['bad']


def test_collection_and_document_scope_and_all_supported_sources(app):
    supported = ['tools', 'access', 'feedback', 'ideas', 'administrators', 'settings', 'taxonomy', 'users']
    with app.app_context():
        for name in supported:
            db()[name].insert_one({'_id': 'scope-' + name, 'outbox': [event(name)]})
        assert mongo_store.deliver_notifications('settings', 'scope-settings') == post_commit.DeliveryResult(1, False)
        assert db().audit.count_documents({}) == 1
        assert mongo_store.deliver_notifications() == post_commit.DeliveryResult(7, False)


def test_combined_legacy_and_current_work_shares_event_cap(app):
    with app.app_context():
        jobs = [post_commit.audit_job('legacy:' + str(n), 'owner', 'Saved') for n in range(2)]
        db().tools.insert_one({'_id': 1, 'outbox': [event('new:' + str(n)) for n in range(49)],
                              'postCommit': jobs})
        assert mongo_store.deliver_notifications('tools') == post_commit.DeliveryResult(50, True)
        row = db().tools.find_one({'_id': 1})
        assert row['outbox'] == [] and len(row['postCommit']) == 1
        assert mongo_store.deliver_notifications('tools') == post_commit.DeliveryResult(1, False)
        assert db().audit.count_documents({}) == 51


def test_collection_document_cap_includes_legacy_only_documents(app):
    with app.app_context():
        for n in range(51):
            db().tools.insert_one({'_id': n, 'postCommit': [post_commit.audit_job(str(n), 'owner', 'Saved')]})
        assert mongo_store.deliver_notifications('tools') == post_commit.DeliveryResult(50, True)
        assert mongo_store.deliver_notifications('tools') == post_commit.DeliveryResult(1, False)
        assert db().audit.count_documents({}) == 51


def test_legacy_queue_failure_isolated_and_direct_drain_bounded(app, monkeypatch):
    with app.app_context():
        jobs = [post_commit.audit_job(str(n), 'owner', 'Saved') for n in range(52)]
        db().settings.insert_one({'_id': 'legacy-settings', 'postCommit': jobs})
        with monkeypatch.context() as fault:
            fail_updates(fault, lambda name, query, change: name == 'audit' and query.get('_id') == 'post-commit:0')
            result = post_commit.drain('settings', 'legacy-settings')
        assert result == post_commit.DeliveryResult(49, True)
        assert post_commit.drain('settings', 'legacy-settings') == post_commit.DeliveryResult(3, False)
        assert db().audit.count_documents({}) == 52


def test_token_annotation_has_user_scope_and_deferred_retry(app, monkeypatch):
    with app.app_context():
        db().local_tokens.insert_many([{'_id': 'mine', 'id': 'old', 'user': 'owner', 'revoked': False},
                                      {'_id': 'other', 'id': 'old', 'user': 'other', 'revoked': False}])
        annotation = dict(user='owner', id='old', fields=dict(revoked=True, revokedAt=123, replacedBy='new'))
        db().users.update_one({'_id': 'owner'}, {'$push': {'outbox': event('key', tokenUpdate=annotation)}})
        with monkeypatch.context() as fault:
            fail_updates(fault, lambda name, query, change: name == 'local_tokens')
            assert mongo_store.deliver_notifications('users', 'owner') == post_commit.DeliveryResult(0, True)
        assert mongo_store.deliver_notifications('users', 'owner') == post_commit.DeliveryResult(1, False)
        assert db().local_tokens.find_one({'_id': 'mine'})['revoked'] is True
        assert db().local_tokens.find_one({'_id': 'other'})['revoked'] is False
        assert db().audit.count_documents({'_id': 'key'}) == 1


def test_followup_pending_uses_explicit_result_and_propagates_programming_error(app):
    with app.app_context():
        assert post_commit.followup_pending('done', lambda: post_commit.DeliveryResult(2, False)) is False
        assert post_commit.followup_pending('queued', lambda: post_commit.DeliveryResult(2, True)) is True
        assert post_commit.followup_pending('old-counter', lambda: 7) is False
        with pytest.raises(ValueError):
            mongo_store.deliver_notifications('bad-collection')
