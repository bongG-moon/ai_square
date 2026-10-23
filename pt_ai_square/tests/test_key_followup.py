"""Key authority is the user pointer; secondary audit/row annotations may defer."""
import importlib
import json

import pytest
from pymongo.collection import Collection
from pymongo.errors import OperationFailure

from pt_ai_square.backend.storage import db, deliver_notifications
from .conftest import ready
from .test_connection_key import accepted, issue


key_module = importlib.import_module('pt_ai_square.backend.local_access')
PRIVATE = 'mongodb://employee:private-password@private-host/private-db'


def failure():
    return OperationFailure(PRIVATE, 225, {'errmsg': PRIVATE, 'code': 225})


def fail_update(monkeypatch, name):
    original = Collection.update_one

    def update(collection, query, change, *args, **kwargs):
        if collection.name == name:
            raise failure()
        return original(collection, query, change, *args, **kwargs)

    monkeypatch.setattr(Collection, 'update_one', update)


@pytest.mark.parametrize('target', ['local_tokens', 'audit'])
def test_key_rotation_survives_secondary_failure_and_replays_once(app, monkeypatch, caplog, target):
    original = issue(app).json
    with monkeypatch.context() as fault:
        fail_update(fault, target)
        response = issue(app)
    assert response.status_code == 201, response.json
    rotated = response.json
    assert rotated['followupsPending'] is True and rotated['replaced'] is True
    assert accepted(app, original['token']) == 401
    assert accepted(app, rotated['token']) == 200
    assert PRIVATE not in response.text + caplog.text
    with app.app_context():
        user = db().users.find_one({'_id': 'owner'})
        assert user['activeConnectionKeyId'] == rotated['id']
        assert len(user['outbox']) == 1
        event = user['outbox'][0]
        assert event['tokenUpdate']['id'] == original['id']
        assert original['token'] not in json.dumps(user)
        assert rotated['token'] not in json.dumps(user)
        deliver_notifications('users', 'owner')
        deliver_notifications('users', 'owner')
        assert db().users.find_one({'_id': 'owner'})['outbox'] == []
        assert db().audit.count_documents({'_id': event['id']}) == 1
        old = db().local_tokens.find_one({'id': original['id']})
        assert old['revoked'] is True and old['replacedBy'] == rotated['id']


def test_key_revoke_commits_authority_even_when_row_annotation_fails(app, monkeypatch):
    key = issue(app).json
    client, headers = ready(app)
    with monkeypatch.context() as fault:
        fail_update(fault, 'local_tokens')
        response = client.delete('/api/local-tokens/' + key['id'], headers=headers)
    assert response.status_code == 200 and response.json['followupsPending'] is True
    assert accepted(app, key['token']) == 401
    with app.app_context():
        user = db().users.find_one({'_id': 'owner'})
        assert user['activeConnectionKeyId'] is None
        assert user['outbox'][0]['tokenUpdate']['id'] == key['id']
        assert db().local_tokens.find_one({'id': key['id']})['revoked'] is False
        deliver_notifications('users', 'owner')
        assert db().local_tokens.find_one({'id': key['id']})['revoked'] is True


def test_cancelling_old_key_keeps_current_pointer_when_annotations_defer(app, monkeypatch):
    old = issue(app).json
    current = issue(app).json
    client, headers = ready(app)
    with monkeypatch.context() as fault:
        fail_update(fault, 'local_tokens')
        response = client.delete('/api/local-tokens/' + old['id'], headers=headers)
    assert response.status_code == 200 and response.json['followupsPending'] is True
    assert accepted(app, current['token']) == 200
    with app.app_context():
        assert db().users.find_one({'_id': 'owner'})['activeConnectionKeyId'] == current['id']


@pytest.mark.parametrize('applied_before_error', [False, True])
def test_key_pointer_failure_is_not_swallowed_or_replayed(app, monkeypatch, applied_before_error):
    old = issue(app).json
    calls = []
    original = Collection.find_one_and_update

    def update(collection, query, change, *args, **kwargs):
        if collection.name == 'users' and 'outbox' in change.get('$push', {}):
            calls.append(query)
            if applied_before_error:
                original(collection, query, change, *args, **kwargs)
            raise failure()
        return original(collection, query, change, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Collection, 'find_one_and_update', update)
        response = issue(app)
    assert response.status_code == 503 and response.json['diagnostic']['mongo_code'] == 225
    assert len(calls) == 1
    assert accepted(app, old['token']) == (401 if applied_before_error else 200)
    with app.app_context():
        user = db().users.find_one({'_id': 'owner'})
        assert bool(user.get('outbox')) == applied_before_error


def test_revoke_primary_failure_does_not_succeed_or_cancel_key(app, monkeypatch):
    key = issue(app).json
    client, headers = ready(app)
    original = Collection.update_one
    calls = []

    def update(collection, query, change, *args, **kwargs):
        if collection.name == 'users' and 'outbox' in change.get('$push', {}):
            calls.append(query)
            raise failure()
        return original(collection, query, change, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Collection, 'update_one', update)
        response = client.delete('/api/local-tokens/' + key['id'], headers=headers)
    assert response.status_code == 503 and len(calls) == 1
    assert accepted(app, key['token']) == 200


def test_confirmed_key_issue_does_not_require_second_authority_read(app, monkeypatch):
    original = key_module.current_connection_key
    calls = []

    def once(uid):
        calls.append(uid)
        if len(calls) > 1:
            raise failure()
        return original(uid)

    monkeypatch.setattr(key_module, 'current_connection_key', once)
    response = issue(app)
    assert response.status_code == 201 and calls == ['owner']


def test_key_list_activity_replay_is_user_scoped_bounded_and_best_effort(app, monkeypatch):
    issue(app)
    client, _ = ready(app)
    activity = importlib.import_module('pt_ai_square.backend.activity')
    calls = []

    def flush(*args, **kwargs):
        calls.append((args, kwargs))
        raise failure()

    monkeypatch.setattr(activity, 'flush', flush)
    response = client.get('/api/local-tokens')
    assert response.status_code == 200 and response.json['historyPending'] is True
    assert calls == [((), {'user_id': 'owner', 'limit': 50})]
    assert response.json['connectionKey'] is not None


def test_non_mongo_key_followup_bug_is_not_hidden(app, monkeypatch):
    def broken(*args):
        raise ValueError('programming defect')

    monkeypatch.setattr(key_module, 'deliver_notifications', broken)
    response = issue(app)
    assert response.status_code == 500
