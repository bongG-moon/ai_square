"""Workspace release subscriptions, atomic versions, and deferred delivery."""
import importlib
import pytest
from pymongo.collection import Collection
from pymongo.errors import AutoReconnect, OperationFailure

from pt_ai_square.backend.artifacts import artifact_path, used_bytes
from pt_ai_square.backend.storage import db, deliver_notifications
from .conftest import ready
from .test_ax_workspace import files, upload


def toggle(client, headers, file_id, enabled):
    return client.put(f'/api/ax-workspace/{file_id}/subscription',
                      headers=headers, json={'enabled': enabled})


def update(client, headers, file_id, **metadata):
    data = dict(expectedRevision=1)
    data.update(metadata)
    return upload(client, headers, file_id=file_id, **data)


def test_get_download_subscribes_once_and_explicit_off_survives_download(app):
    admin, ah = ready(app, 'admin')
    member, mh = ready(app, 'member')
    file = upload(admin, ah).json['file']
    assert file['revision'] == file['release'] == 1 and file['subscribed'] is False
    assert member.head(file['downloadUrl']).status_code == 200
    with app.app_context():
        assert db().workspace_subscriptions.count_documents({}) == 0
    for _ in range(2):
        response = member.get(file['downloadUrl'])
        assert response.status_code == 200
        response.close()
    assert member.get('/api/ax-workspace').json['files'][0]['subscribed'] is True
    assert toggle(member, mh, file['id'], False).json == {
        'ok': True, 'subscribed': False, 'followupsPending': False}
    member.get(file['downloadUrl']).close()
    assert member.get('/api/ax-workspace').json['files'][0]['subscribed'] is False
    assert toggle(member, mh, file['id'], True).json['subscribed'] is True
    with app.app_context():
        assert db().workspace_subscriptions.count_documents({}) == 1
        assert db().subscriptions.count_documents({}) == 0
        assert db().activity.count_documents({}) == 0
        assert db().activity_state.count_documents({}) == 0
        assert db().audit.count_documents({'action': 'AX Workspace 업데이트 알림 자동 구독'}) == 1


def test_partial_download_subscribes_but_not_cache_probe_or_invalid_range(app):
    admin, ah = ready(app, 'admin')
    member, _ = ready(app, 'member')
    file = upload(admin, ah, file_name='guide.md', content=b'1234567890').json['file']
    head = member.head(file['downloadUrl'])
    assert member.get(file['downloadUrl'], headers={'If-None-Match': head.headers['ETag']}).status_code == 304
    assert member.get(file['downloadUrl'], headers={'Range': 'bytes=100-200'}).status_code == 416
    with app.app_context():
        assert db().workspace_subscriptions.count_documents({}) == 0
    response = member.get(file['downloadUrl'], headers={'Range': 'bytes=0-3'})
    assert response.status_code == 206 and response.data == b'1234'
    response.close()
    with app.app_context():
        assert db().workspace_subscriptions.find_one({'file': file['id'], 'user': 'member'})['enabled'] is True


def test_missing_file_does_not_subscribe(app):
    admin, ah = ready(app, 'admin')
    file = upload(admin, ah).json['file']
    for path in files(app):
        path.unlink()
    assert admin.get(file['downloadUrl']).status_code == 404
    with app.app_context():
        assert db().workspace_subscriptions.count_documents({}) == 0


def test_subscription_session_csrf_key_and_own_identity_boundary(app):
    admin, ah = ready(app, 'admin')
    member, mh = ready(app, 'member')
    file = upload(admin, ah).json['file']
    endpoint = f"/api/ax-workspace/{file['id']}/subscription"
    assert toggle(app.test_client(), {}, file['id'], True).status_code == 401
    assert toggle(member, {}, file['id'], True).status_code == 403
    for body in ({}, [], {'enabled': 1}, {'enabled': 'true'}, {'enabled': None}):
        assert member.put(endpoint, headers=mh, json=body).status_code == 400
    assert member.put(endpoint, headers=mh, json={'enabled': True, 'user': 'other'}).status_code == 200
    token = admin.post('/api/local-tokens', headers=ah, json={'name': 'test', 'scope': 'publish'}).json['token']
    bearer = {'Authorization': 'Bearer ' + token, **ah}
    assert toggle(admin, bearer, file['id'], True).status_code == 403
    assert update(admin, bearer, file['id']).status_code == 403
    assert update(member, mh, file['id']).status_code == 403
    assert update(admin, {}, file['id']).status_code == 403
    with app.app_context():
        assert db().workspace_subscriptions.count_documents({'user': 'member'}) == 1
        assert db().workspace_subscriptions.count_documents({'user': 'other'}) == 0


def test_new_version_keeps_card_and_old_bytes_and_notifies_subscribed_active_users(app):
    admin, ah = ready(app, 'admin')
    member, mh = ready(app, 'member')
    other, oh = ready(app, 'other')
    owner, _ = ready(app, 'owner')
    file = upload(admin, ah, file_name='guide.md', content=b'# original').json['file']
    for client in (admin, member, other, owner):
        client.get(file['downloadUrl']).close()
    toggle(other, oh, file['id'], False)
    with app.app_context():
        db().users.update_one({'_id': 'owner'}, {'$set': {'enabled': False}})
    response = update(admin, ah, file['id'], file_name='guide.md', content=b'# newest')
    assert response.status_code == 201 and response.json['followupsPending'] is False
    latest = response.json['file']
    assert latest['id'] == file['id'] and latest['revision'] == latest['release'] == 2
    assert latest['version'] == '2'
    assert latest['created'] == file['created'] and latest['updated'] >= file['created']
    assert latest['subscribed'] is True
    assert len(member.get('/api/ax-workspace').json['files']) == 1
    downloaded = member.get(file['downloadUrl'])
    assert downloaded.data == b'# newest'
    downloaded.close()
    with app.app_context():
        stored = db().workspace_files.find_one({'_id': file['id']})
        assert [v['version'] for v in stored['versions']] == ['1', '2']
        assert [artifact_path(v['path']).read_bytes() for v in stored['versions']] == [b'# original', b'# newest']
        assert used_bytes() == len(b'# original# newest')
        notices = list(db().notifications.find({'target.type': 'workspace'}))
        assert len(notices) == 1 and notices[0]['user'] == 'member'
        assert notices[0]['title'].endswith('새 버전 v2')
        assert notices[0]['kind'] == 'release' and notices[0]['target'] == {'type': 'workspace', 'id': file['id']}
        assert stored['outbox'] == []
    # An intentional new item stays independent despite matching its name.
    assert upload(admin, ah).status_code == 201
    assert len(member.get('/api/ax-workspace').json['files']) == 2


@pytest.mark.parametrize('has_history', [False, True])
def test_legacy_file_upgrades_atomically_without_losing_first_release(app, has_history):
    admin, ah = ready(app, 'admin')
    file = upload(admin, ah).json['file']
    with app.app_context():
        legacy = {'version': '0.23.32', 'category': 'other'}
        missing = {'revision': '', 'release': '', 'updated': ''}
        if has_history:
            legacy.update({'versions.0.version': '0.23.32', 'versions.0.category': 'other'})
        else:
            missing['versions'] = ''
        db().workspace_files.update_one({'_id': file['id']}, {
            '$set': legacy, '$unset': missing})
    listed = admin.get('/api/ax-workspace').json['files'][0]
    assert listed['revision'] == listed['release'] == 1
    assert listed['version'] == '1' and listed['category'] == 'integration'
    assert update(admin, ah, file['id'], category='other').status_code == 201
    with app.app_context():
        row = db().workspace_files.find_one({'_id': file['id']})
        assert len(row['versions']) == 2
        assert row['versions'][0]['version'] == '0.23.32' and row['versions'][0]['category'] == 'other'
        assert row['versions'][1]['version'] == row['version'] == '2'
        assert row['versions'][1]['category'] == row['category'] == 'integration'


@pytest.mark.parametrize('revision', [None, True, '1', 0, -1, [], {}])
def test_version_requires_valid_revision_before_staging(app, revision):
    admin, ah = ready(app, 'admin')
    file = upload(admin, ah).json['file']
    assert update(admin, ah, file['id'], expectedRevision=revision).status_code == 400
    assert len(files(app)) == 1


def test_auto_versions_ignore_client_numbers_and_reject_stale_replays_before_staging(app):
    admin, ah = ready(app, 'admin')
    file = upload(admin, ah).json['file']
    assert update(admin, ah, file['id'], expectedRevision=2).status_code == 409
    assert len(files(app)) == 1
    second = update(admin, ah, file['id'], version='1.0.0', release=9999)
    assert second.status_code == 201 and second.json['file']['version'] == '2'
    assert update(admin, ah, file['id']).status_code == 409
    assert len(files(app)) == 2
    third = update(admin, ah, file['id'], expectedRevision=2, version='1.0.0', release=-1)
    assert third.status_code == 201
    assert third.json['file']['version'] == '3' and third.json['file']['release'] == 3
    assert update(admin, ah, file['id'], expectedRevision=2).status_code == 409
    assert len(files(app)) == 3
    with app.app_context():
        row = db().workspace_files.find_one({'_id': file['id']})
        assert [version['version'] for version in row['versions']] == ['1', '2', '3']


def test_concurrent_version_cas_preserves_winner_and_cleans_unreferenced_loser(app, monkeypatch):
    module = importlib.import_module('pt_ai_square.backend.ax_workspace')
    admin, ah = ready(app, 'admin')
    file = upload(admin, ah).json['file']
    original = module.stage_upload

    def concurrent_save(uploaded):
        artifact = original(uploaded)
        db().workspace_files.update_one({'_id': file['id']}, {'$inc': {'revision': 1}})
        return artifact

    with monkeypatch.context() as fault:
        fault.setattr(module, 'stage_upload', concurrent_save)
        assert update(admin, ah, file['id']).status_code == 409
    assert len(files(app)) == 1
    with app.app_context():
        row = db().workspace_files.find_one({'_id': file['id']})
        assert row['revision'] == 2 and row['release'] == 1 and len(row['versions']) == 1


@pytest.mark.parametrize('committed', [False, True])
def test_uncertain_version_write_keeps_bytes_without_false_success(app, monkeypatch, committed):
    admin, ah = ready(app, 'admin')
    file = upload(admin, ah).json['file']
    original = Collection.update_one

    def lose_reply(collection, query, operation, *args, **kwargs):
        if collection.name == 'workspace_files' and '$set' in operation:
            if committed:
                original(collection, query, operation, *args, **kwargs)
            raise AutoReconnect('simulated ambiguous version write')
        return original(collection, query, operation, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Collection, 'update_one', lose_reply)
        assert update(admin, ah, file['id']).status_code == 503
    assert len(files(app)) == 2
    with app.app_context():
        row = db().workspace_files.find_one({'_id': file['id']})
        assert row['revision'] == 1 + int(committed)
        assert len(row['versions']) == 1 + int(committed)
        if committed:
            assert row['outbox']
    if committed:
        assert update(admin, ah, file['id']).status_code == 409


def test_subscription_and_download_audit_failures_preserve_primary_success(app, monkeypatch):
    admin, ah = ready(app, 'admin')
    member, mh = ready(app, 'member')
    file = upload(admin, ah).json['file']
    original = Collection.update_one

    def fail_audit(collection, *args, **kwargs):
        if collection.name == 'audit':
            raise OperationFailure('secondary audit unavailable', 225)
        return original(collection, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Collection, 'update_one', fail_audit)
        response = member.get(file['downloadUrl'])
        assert response.status_code == 200
        response.close()
        assert toggle(member, mh, file['id'], False).json == {
            'ok': True, 'subscribed': False, 'followupsPending': True}
    with app.app_context():
        row = db().workspace_subscriptions.find_one({'file': file['id'], 'user': 'member'})
        assert row['enabled'] is False and len(row['outbox']) == 2
        assert deliver_notifications('workspace_subscriptions', row['_id']).pending is False
        assert db().workspace_subscriptions.find_one({'_id': row['_id']})['outbox'] == []


def test_subscription_primary_write_failure_is_not_hidden(app, monkeypatch):
    admin, ah = ready(app, 'admin')
    member, mh = ready(app, 'member')
    file = upload(admin, ah).json['file']
    original = Collection.update_one

    def fail_write(collection, *args, **kwargs):
        if collection.name == 'workspace_subscriptions':
            raise AutoReconnect('subscription write unavailable')
        return original(collection, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Collection, 'update_one', fail_write)
        assert member.get(file['downloadUrl']).status_code == 503
        assert toggle(member, mh, file['id'], True).status_code == 503
    with app.app_context():
        assert db().workspace_subscriptions.count_documents({}) == 0


@pytest.mark.parametrize('unsubscribe', [True, False])
def test_deferred_release_respects_later_off_or_disabled_account(app, monkeypatch, unsubscribe):
    admin, ah = ready(app, 'admin')
    member, mh = ready(app, 'member')
    other, _ = ready(app, 'other')
    file = upload(admin, ah).json['file']
    for client in (member, other):
        client.get(file['downloadUrl']).close()
    original = Collection.update_one

    def fail_member(collection, query, *args, **kwargs):
        if collection.name == 'notifications' and query['_id'].endswith(':member'):
            raise OperationFailure('secondary inbox unavailable', 225)
        return original(collection, query, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Collection, 'update_one', fail_member)
        response = update(admin, ah, file['id'])
    assert response.status_code == 201 and response.json['followupsPending'] is True
    if unsubscribe:
        assert toggle(member, mh, file['id'], False).status_code == 200
    with app.app_context():
        if not unsubscribe:
            db().users.update_one({'_id': 'member'}, {'$set': {'enabled': False}})
        row = db().workspace_files.find_one({'_id': file['id']})
        assert row['outbox'] and row['release'] == 2
        assert db().notifications.count_documents({'user': 'other'}) == 1
        assert deliver_notifications('workspace_files', file['id']).pending is False
        deliver_notifications('workspace_files', file['id'])
        assert db().notifications.count_documents({'user': 'member'}) == 0
        assert db().notifications.count_documents({'user': 'other'}) == 1
        assert db().workspace_files.find_one({'_id': file['id']})['outbox'] == []


def test_historical_workspace_file_is_protected_by_shared_file_cleanup(app):
    from pt_ai_square.backend.permanent_delete import _referenced
    from pt_ai_square.backend.publish_drafts import remove_unreferenced
    from pt_ai_square.backend.mongo_store import purge_deleted
    admin, ah = ready(app, 'admin')
    file = upload(admin, ah).json['file']
    assert update(admin, ah, file['id']).status_code == 201
    with app.app_context():
        row = db().workspace_files.find_one({'_id': file['id']})
        old_path = row['versions'][0]['path']
        assert old_path != row['path']
        assert remove_unreferenced({'path': old_path}) is True
        assert _referenced({'kind': 'tool', 'entityId': 99}, old_path) is True
        db().tools.insert_one({'_id': 99, 'versions': [{'n': 1, 'deleted': True, 'path': old_path}]})
        purge_deleted()
        assert artifact_path(old_path).is_file()
        assert db().tools.find_one({'_id': 99})['versions'][0]['path'] is None


def test_retained_versions_count_towards_upload_quota(app):
    admin, ah = ready(app, 'admin')
    file = upload(admin, ah, file_name='guide.md', content=b'12345').json['file']
    with app.app_context():
        db().settings.insert_one({'_id': 'storage_limits', 'mode': 'manual',
                                  'quotaBytes': 8, 'reserveBytes': 0})
    assert update(admin, ah, file['id'], file_name='guide.md', content=b'12345').status_code == 409
    assert len(files(app)) == 1
