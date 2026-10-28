"""Contribution totals survive deletion without retaining files or identities."""
from pathlib import Path

import pytest
from pymongo.collection import Collection
from pymongo.errors import OperationFailure

from pt_ai_square.backend import mongo_activity, people, permanent_delete
from pt_ai_square.backend.storage import db
from .conftest import ready, publish


def credited_tool(app):
    owner, headers = ready(app)
    assert publish(owner, headers, approval=True).status_code == 201
    with app.app_context():
        mongo_activity.set_like(1, 'member', True)
        mongo_activity.record_download(1, 'member', 1)
        tool = db().tools.find_one({'_id': 1})
        artifact = Path(app.config['DATA_DIR']) / 'artifacts' / tool['versions'][0]['path']
    return owner, headers, artifact


def details(client, **query):
    response = client.get('/api/me/contributions', query_string=query)
    assert response.status_code == 200, response.json
    assert 'no-store' in response.headers['Cache-Control']
    return response.json


def test_personal_breakdown_privacy_counts_and_active_unlike(app):
    owner, headers, _ = credited_tool(app)
    assert publish(owner, headers, tid=1, revision=1).status_code == 201
    other, oh = ready(app, 'other')
    assert publish(other, oh, name='OTHER PRIVATE TOOL', approval=True).status_code == 201
    with app.app_context():
        mongo_activity.set_like(1, 'owner', True)
        mongo_activity.record_download(1, 'owner', 1)
        mongo_activity.record_download(1, 'member', 2)
        mongo_activity.record_download(1, 'other', 2, update=True)
        for n in range(2):
            db().activity_state.insert_one(dict(_id=f'legacy-{n}', tool=1, user='legacy',
                                                 kind='download', count=4, created=100 + n))
    data = details(owner, owner='other', user='other')
    assert data['summary'] == dict(registered=1, likes=1, downloads=2, score=9)
    assert data['weights'] == dict(registered=5, likes=2, downloads=1)
    assert data['items'][0]['status'] == 'active'
    assert data['items'][0]['name'] == '장비 점검'
    assert data['items'][0]['score'] == 9
    assert 'OTHER PRIVATE TOOL' not in str(data) and 'SECRET INSTALL GUIDE' not in str(data)
    assert 'owner' not in data['items'][0] and 'user' not in data['items'][0]
    admin, _ = ready(app, 'admin')
    assert details(admin, owner='owner')['totalItems'] == 0
    with app.app_context():
        mongo_activity.set_like(1, 'member', False)
    assert details(owner)['summary']['score'] == 7
    assert owner.get('/api/people/ranking').json['me']['score'] == 7


def test_trash_restore_and_permanent_delete_preserve_one_credit(app):
    owner, headers, artifact = credited_tool(app)
    assert owner.delete('/api/tools/1', headers=headers, json={'expectedRevision': 1}).status_code == 200
    assert details(owner)['items'][0]['status'] == 'trash'
    assert details(owner)['summary']['score'] == 8
    assert owner.post('/api/tools/1/restore', headers=headers, json={'expectedRevision': 2}).status_code == 200
    assert details(owner)['summary']['score'] == 8
    assert owner.delete('/api/tools/1', headers=headers, json={'expectedRevision': 3}).status_code == 200
    admin, ah = ready(app, 'admin')
    for _ in range(2):
        response = admin.post('/api/tools/1/purge', headers=ah, json={'expectedRevision': 4})
        assert response.status_code == 200, response.json
        data = details(owner)
        assert data['summary'] == dict(registered=1, likes=1, downloads=1, score=8)
        assert data['totalItems'] == 1 and data['items'][0]['status'] == 'deleted'
        assert data['items'][0]['name'] == '장비 점검' and data['items'][0]['retainedAt']
        assert owner.get('/api/people/ranking').json['me']['score'] == 8
    assert not artifact.exists()
    with app.app_context():
        assert db().tools.find_one({'_id': 1}) is None
        assert db().activity_state.count_documents({'tool': 1}) == 0
        record = db().deletion_jobs.find_one({'_id': 'tool:1'})['contribution']
        assert set(record) == {'schemaVersion', 'tool', 'owner', 'name', 'created',
                               'retainedAt', 'registered', 'likes', 'downloads', 'score'}
        assert 'member' not in str(record) and 'SECRET INSTALL GUIDE' not in str(record)


def test_purge_pending_and_cleaned_activity_use_frozen_snapshot_once(app, monkeypatch):
    owner, headers, artifact = credited_tool(app)
    owner.delete('/api/tools/1', headers=headers, json={'expectedRevision': 1})
    admin, ah = ready(app, 'admin')
    original = Collection.delete_one
    with monkeypatch.context() as fault:
        def fail_source(coll, *args, **kwargs):
            if coll.name == 'tools':
                raise OperationFailure('private', 225)
            return original(coll, *args, **kwargs)
        fault.setattr(Collection, 'delete_one', fail_source)
        response = admin.post('/api/tools/1/purge', headers=ah, json={'expectedRevision': 2})
    assert response.status_code == 202 and not artifact.exists()
    with app.app_context():
        assert db().tools.find_one({'_id': 1})
        assert db().activity_state.count_documents({'tool': 1}) == 0
    assert details(owner)['summary']['score'] == 8
    assert owner.get('/api/people/ranking').json['me']['registered'] == 1
    assert admin.post('/api/tools/1/purge', headers=ah, json={'expectedRevision': 2}).status_code == 200
    assert details(owner)['summary']['score'] == 8


def test_snapshot_read_failure_never_deletes_or_claims_saved(app, monkeypatch):
    owner, headers, artifact = credited_tool(app)
    owner.delete('/api/tools/1', headers=headers, json={'expectedRevision': 1})
    admin, ah = ready(app, 'admin')
    original = Collection.aggregate
    with monkeypatch.context() as fault:
        def fail(coll, *args, **kwargs):
            if coll.name == 'activity_state':
                raise OperationFailure('private', 225)
            return original(coll, *args, **kwargs)
        fault.setattr(Collection, 'aggregate', fail)
        response = admin.post('/api/tools/1/purge', headers=ah, json={'expectedRevision': 2})
    assert response.status_code == 503 and artifact.exists()
    with app.app_context():
        assert db().tools.find_one({'_id': 1}).get('purge') is None
        assert db().activity_state.count_documents({'tool': 1}) == 2
    assert details(owner)['summary']['score'] == 8


def test_failed_job_copy_keeps_credit_on_source_and_retry_preserves_it(app, monkeypatch):
    owner, headers, artifact = credited_tool(app)
    owner.delete('/api/tools/1', headers=headers, json={'expectedRevision': 1})
    admin, ah = ready(app, 'admin')
    original = Collection.update_one
    with monkeypatch.context() as fault:
        def fail(coll, *args, **kwargs):
            if coll.name == 'deletion_jobs':
                raise OperationFailure('private', 225)
            return original(coll, *args, **kwargs)
        fault.setattr(Collection, 'update_one', fail)
        response = admin.post('/api/tools/1/purge', headers=ah, json={'expectedRevision': 2})
    assert response.status_code == 202 and artifact.exists()
    assert details(owner)['summary']['score'] == 8
    assert admin.post('/api/tools/1/purge', headers=ah, json={'expectedRevision': 2}).status_code == 200
    assert details(owner)['summary']['score'] == 8


def test_legacy_pending_cleanup_cannot_remove_activity_before_snapshot_write(app, monkeypatch):
    owner, headers, artifact = credited_tool(app)
    owner.delete('/api/tools/1', headers=headers, json={'expectedRevision': 1})
    with app.app_context():
        marker = dict(id='legacy-purge', created=123, requestRevision=2,
                      audit={'id': 'legacy-audit', 'audit': {'_id': 'legacy-audit', 'user': 'admin', 'created': 123, 'action': 'delete'}})
        db().tools.update_one({'_id': 1}, {'$set': {'purge': marker}, '$inc': {'revision': 1}})
        job = permanent_delete._job_from_source('tool', db().tools.find_one({'_id': 1}))
        db().deletion_jobs.insert_one(job)
        original = Collection.update_one
        with monkeypatch.context() as fault:
            def fail(coll, query, change, *args, **kwargs):
                if coll.name == 'deletion_jobs' and 'contribution' in change.get('$set', {}):
                    raise OperationFailure('private', 225)
                return original(coll, query, change, *args, **kwargs)
            fault.setattr(Collection, 'update_one', fail)
            with pytest.raises(OperationFailure):
                permanent_delete.cleanup_if_deleted('tool', 1)
        assert db().activity_state.count_documents({'tool': 1}) == 2
        assert artifact.exists()
        assert permanent_delete.cleanup_if_deleted('tool', 1)
        assert db().activity_state.count_documents({'tool': 1}) == 0
    assert details(owner)['summary']['score'] == 8
    admin, ah = ready(app, 'admin')
    assert admin.post('/api/tools/1/purge', headers=ah, json={'expectedRevision': 2}).status_code == 200
    assert details(owner)['summary']['score'] == 8


def test_legacy_removed_without_retained_data_is_not_fabricated(app):
    owner, _ = ready(app)
    with app.app_context():
        db().deletion_jobs.insert_one(dict(_id='tool:100', kind='tool', entityId=100, state='complete'))
        db().tools.insert_one(dict(_id=101, owner='owner', deleted=True))
    data = details(owner)
    assert data['summary']['score'] == 5 and data['totalItems'] == 1
    assert data['items'][0]['name'] == '도구 #101' and data['items'][0]['created'] is None


def test_owner_pagination_and_authentication_boundary(app):
    owner, headers = ready(app)
    with app.app_context():
        db().tools.insert_many([dict(_id=n, owner='owner', deleted=False) for n in range(1, 24)])
    first = details(owner)
    second = details(owner, page=2)
    assert first['totalItems'] == 23 and first['totalPages'] == 2
    assert len(first['items']) == 20 and [r['id'] for r in second['items']] == [21, 22, 23]
    assert first['summary'] == second['summary'] == dict(registered=23, likes=0, downloads=0, score=115)
    assert details(owner, page=3)['items'] == []
    assert app.test_client().get('/api/me/contributions').status_code == 401
    token = owner.post('/api/local-tokens', headers=headers, json={}).json['token']
    assert app.test_client().get('/api/me/contributions', headers={'Authorization': 'Bearer ' + token}).status_code == 403
    for query in [{'page': '0'}, {'page': '-1'}, {'page': 'true'}, {'page': '1000001'},
                  {'pageSize': '0'}, {'pageSize': '101'}, {'pageSize': '3.5'}]:
        assert owner.get('/api/me/contributions', query_string=query).status_code == 400


def test_retained_contributor_portrait_remains_eligible_but_disabled_is_hidden(app, monkeypatch):
    owner, headers, _ = credited_tool(app)
    owner.delete('/api/tools/1', headers=headers, json={'expectedRevision': 1})
    admin, ah = ready(app, 'admin')
    assert admin.post('/api/tools/1/purge', headers=ah, json={'expectedRevision': 2}).status_code == 200
    monkeypatch.setattr(people, '_photo_enabled', lambda employee: True)
    monkeypatch.setattr(people, '_photo_response', lambda employee: ('portrait', 200))
    member, _ = ready(app, 'member')
    assert member.get('/api/people/owner/photo').status_code == 200
    with app.app_context():
        db().users.update_one({'_id': 'owner'}, {'$set': {'enabled': False}})
    assert member.get('/api/people/owner/photo').status_code == 404
    assert member.get('/api/people/ranking').json['totalUsers'] == 0
