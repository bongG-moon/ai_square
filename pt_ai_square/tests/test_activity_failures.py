"""Acknowledged state and durable activity delivery have separate outcomes."""
import pytest
from pymongo.collection import Collection
from pymongo.errors import OperationFailure

from pt_ai_square.backend import mongo_activity as activity, post_commit
from pt_ai_square.backend.storage import db
from .test_outbox_delivery import fail_updates


def test_like_count_failure_does_not_hide_saved_state(app, monkeypatch):
    original = Collection.count_documents

    def count(collection, *args, **kwargs):
        if collection.name == 'activity_state':
            raise OperationFailure('private error', 225)
        return original(collection, *args, **kwargs)

    with app.app_context(), monkeypatch.context() as fault:
        fault.setattr(Collection, 'count_documents', count)
        assert activity.set_like(1, 'member', True) is None
        row = db().activity_state.find_one({'_id': 'like:1:member'})
        assert row['liked'] is True and len(row['outbox']) == 1


def test_like_primary_failure_still_raises(app, monkeypatch):
    with app.app_context():
        fail_updates(monkeypatch, lambda name, query, change: name == 'activity_state')
        with pytest.raises(OperationFailure):
            activity.set_like(1, 'member', True)
        assert db().activity_state.find_one({'_id': 'like:1:member'}) is None


@pytest.mark.parametrize('failure', ['activity', 'subscriptions', 'completion'])
def test_download_delivery_failure_keeps_event_and_continues(app, monkeypatch, failure):
    with app.app_context():
        activity.record_download(1, 'member', 1)
        activity.record_download(2, 'other', 1)
        first = db().activity_state.find_one({'_id': 'download:1:member'})['outbox'][0]['_id']

        def predicate(name, query, change):
            if failure == 'completion':
                return name == 'activity_state' and query.get('_id') == 'download:1:member' and '$pull' in change
            return name == failure and (query.get('_id') == first or query.get('tool') == 1)

        with monkeypatch.context() as fault:
            fail_updates(fault, predicate)
            assert activity.flush(limit=50) == post_commit.DeliveryResult(1, True)
        assert len(db().activity_state.find_one({'_id': 'download:1:member'})['outbox']) == 1
        assert db().activity_state.find_one({'_id': 'download:2:other'})['outbox'] == []
        db().subscriptions.update_one({'tool': 1, 'user': 'member'}, {'$set': {'enabled': False}}, upsert=True)
        assert activity.flush(1, 'member', 50) == post_commit.DeliveryResult(1, False)
        assert db().activity.count_documents({'kind': 'download'}) == 2
        assert db().subscriptions.find_one({'tool': 1, 'user': 'member'})['enabled'] is False


def test_flush_scopes_tool_and_user(app):
    with app.app_context():
        for tool, user in [(1, 'member'), (1, 'other'), (2, 'member')]:
            activity.set_like(tool, user, True)
        assert activity.flush(1, 'member', 50) == post_commit.DeliveryResult(1, False)
        assert db().activity.count_documents({}) == 1
        assert db().activity_state.count_documents({'outbox.0': {'$exists': True}}) == 2


def test_flush_bounds_documents_and_events(app):
    with app.app_context():
        for n in range(51):
            activity.set_like(1, str(n), True)
        assert activity.flush(limit=50) == post_commit.DeliveryResult(50, True)
        assert activity.flush(limit=50) == post_commit.DeliveryResult(1, False)
        for n in range(51):
            activity.set_like(2, 'member', n % 2 == 0)
        assert activity.flush(2, 'member', 50) == post_commit.DeliveryResult(50, True)
        assert activity.flush(2, 'member', 50) == post_commit.DeliveryResult(1, False)


def test_history_best_effort_bounded_flush_and_primary_read_failure(app, monkeypatch):
    calls = []

    def deferred(*args):
        calls.append(args)
        raise OperationFailure('private error', 225)

    with app.app_context():
        monkeypatch.setattr(activity, 'flush', deferred)
        assert activity.history() == ([], None)
        assert calls == [(None, None, 50)]
        original = Collection.find

        def read(collection, *args, **kwargs):
            if collection.name == 'activity':
                raise OperationFailure('primary read', 225)
            return original(collection, *args, **kwargs)

        monkeypatch.setattr(Collection, 'find', read)
        with pytest.raises(OperationFailure):
            activity.history()


def test_non_mongo_activity_defect_is_not_hidden(app, monkeypatch):
    with app.app_context():
        activity.set_like(1, 'member', True)
        original = Collection.update_one

        def bug(collection, *args, **kwargs):
            if collection.name == 'activity':
                raise ValueError('programming defect')
            return original(collection, *args, **kwargs)

        monkeypatch.setattr(Collection, 'update_one', bug)
        with pytest.raises(ValueError, match='programming defect'):
            activity.flush(limit=50)
