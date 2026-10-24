"""Administrator removal uses isolated Mongo databases and temporary files."""
import io
import json
from pathlib import Path

import pytest
from pymongo.collection import Collection
from pymongo.errors import OperationFailure

from pt_ai_square.backend import mongo_activity, mongo_store, mongo_api, post_commit, permanent_delete
from pt_ai_square.backend.storage import db
from .conftest import ready, publish


def make_tool(app):
    owner, headers = ready(app)
    assert publish(owner, headers).status_code == 201
    return owner, headers


def trash(app):
    owner, headers = make_tool(app)
    assert owner.delete('/api/tools/1', headers=headers, json={'expectedRevision': 1}).status_code == 200
    admin, ah = ready(app, 'admin')
    with app.app_context():
        row = db().tools.find_one({'_id': 1})
        path = Path(app.config['DATA_DIR']) / 'artifacts' / row['versions'][0]['path']
    return admin, ah, path


def make_idea(app, attachment=False):
    c, h = ready(app, 'member')
    data = {'name': '새 기능 요청', 'desc': '업무 요약이 필요해요.', 'category': '공통 업무'}
    if attachment:
        r = c.post('/api/ideas', headers=h, data={
            'metadata': json.dumps(data), 'attachments': (io.BytesIO(b'request detail'), 'sample.txt')})
    else:
        r = c.post('/api/ideas', headers=h, json=data)
    assert r.status_code == 201, r.json
    return c, h


@pytest.mark.parametrize('uid', ['owner', 'member'])
def test_only_administrator_can_purge_or_delete_requests(app, uid):
    _, _, artifact = trash(app)
    make_idea(app, attachment=True)
    c, h = ready(app, uid)
    assert c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2}).status_code == 403
    assert c.delete('/api/ideas/1', headers=h, json={'expectedRevision': 0}).status_code == 403
    assert artifact.is_file()


def test_tool_must_be_trashed_and_revision_current(app):
    make_tool(app)
    c, h = ready(app, 'admin')
    assert c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 1}).status_code == 409
    assert c.delete('/api/tools/1', headers=h, json={'expectedRevision': 1}).status_code == 200
    for rev in [1, 99, None, True]:
        assert c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': rev}).status_code == 409
    with app.app_context():
        assert db().tools.find_one({'_id': 1}).get('purge') is None


def test_permanent_delete_removes_files_relations_and_links_but_keeps_others(app):
    c, h, artifact = trash(app)
    make_idea(app)
    with app.app_context():
        db().ideas.update_one({'_id': 1}, {'$set': {'tool': 1, 'status': '구현 완료'}})
        for name in ('access', 'feedback', 'subscriptions', 'activity', 'activity_state'):
            db()[name].insert_one({'_id': 'remove', 'tool': 1, 'user': 'member'})
            db()[name].insert_one({'_id': 'keep', 'tool': 987, 'user': 'member'})
        db().notifications.insert_one({'_id': 'tool-notice', 'target': {'type': 'tool', 'id': 1}, 'user': 'member'})
        db().notifications.insert_one({'_id': 'other-notice', 'target': {'type': 'tool', 'id': 987}, 'user': 'member'})
    result = c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2})
    assert result.status_code == 200, result.json
    assert result.json['deleted'] and not result.json['pending']
    assert not artifact.exists()
    with app.app_context():
        assert db().tools.find_one({'_id': 1}) is None
        for name in ('access', 'feedback', 'subscriptions', 'activity', 'activity_state'):
            assert db()[name].count_documents({'tool': 1}) == 0
            assert db()[name].count_documents({'tool': 987}) == 1
        idea = db().ideas.find_one({'_id': 1})
        assert idea['tool'] is None and idea['revision'] == 1 and idea['status'] == '구현 완료'
        assert idea['removedTool']['id'] == 1
        assert db().notifications.find_one({'_id': 'tool-notice'}) is None
        assert db().notifications.find_one({'_id': 'other-notice'})
        assert db().audit.count_documents({'action': '도구 1 영구 삭제'}) == 1
        assert db().deletion_jobs.find_one({'_id': 'tool:1'})['state'] == 'complete'
        assert mongo_activity.statistics([1], 'member', 0)[1]['totalRankScore'] == 0
    # Response loss is recoverable, without duplicate audit or a second object.
    again = c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2})
    assert again.status_code == 200 and again.json['deleted']


def test_file_failure_is_pending_blocks_restore_and_retry_finishes(app, monkeypatch):
    c, h, artifact = trash(app)
    unlink = Path.unlink
    with monkeypatch.context() as fault:
        def blocked(path, *args, **kwargs):
            if path == artifact:
                raise PermissionError('locked')
            return unlink(path, *args, **kwargs)
        fault.setattr(Path, 'unlink', blocked)
        r = c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2})
    assert r.status_code == 202 and r.json['pending'] and not r.json['deleted']
    assert artifact.exists() and r.json['revision'] == 3
    assert c.post('/api/tools/1/restore', headers=h, json={'expectedRevision': 3}).status_code == 409
    assert publish(c, h, tid=1, revision=3).status_code in {404, 409}
    row = c.get('/api/bootstrap').json['items'][0]
    assert row['purgePending'] and row['revision'] == 3
    r = c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 3})
    assert r.status_code == 200 and r.json['deleted'] and not artifact.exists()


@pytest.mark.parametrize('failing_collection', ['deletion_jobs', 'subscriptions', 'audit'])
def test_db_cleanup_failure_keeps_retry_intent(app, monkeypatch, failing_collection):
    c, h, artifact = trash(app)
    update = Collection.update_one
    delete = Collection.delete_many
    with monkeypatch.context() as fault:
        def fail_update(coll, *args, **kwargs):
            if coll.name == failing_collection:
                raise OperationFailure('private diagnostic', 225)
            return update(coll, *args, **kwargs)
        def fail_delete(coll, *args, **kwargs):
            if coll.name == failing_collection:
                raise OperationFailure('private diagnostic', 225)
            return delete(coll, *args, **kwargs)
        fault.setattr(Collection, 'update_one', fail_update)
        fault.setattr(Collection, 'delete_many', fail_delete)
        r = c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2})
    assert r.status_code == 202 and r.json['pending']
    assert 'private diagnostic' not in r.get_data(as_text=True)
    r = c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2})
    assert r.status_code == 200 and r.json['deleted'] and not artifact.exists()
    with app.app_context():
        assert db().audit.count_documents({'action': '도구 1 영구 삭제'}) == 1


def test_primary_lock_failure_does_not_claim_success_or_remove_file(app, monkeypatch):
    c, h, artifact = trash(app)
    original = Collection.update_one
    with monkeypatch.context() as fault:
        def fail(coll, *args, **kwargs):
            if coll.name == 'tools':
                raise OperationFailure('private diagnostic', 225)
            return original(coll, *args, **kwargs)
        fault.setattr(Collection, 'update_one', fail)
        r = c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2})
    assert r.status_code == 503 and artifact.exists()
    with app.app_context():
        assert db().tools.find_one({'_id': 1}).get('purge') is None
        assert not db().deletion_jobs.count_documents({})


def test_completion_failure_after_source_removal_is_discoverable_and_retryable(app, monkeypatch):
    c, h, artifact = trash(app)
    original = Collection.update_one
    with monkeypatch.context() as fault:
        def fail(coll, query, change, *args, **kwargs):
            if coll.name == 'deletion_jobs' and change.get('$set', {}).get('state') == 'complete':
                raise OperationFailure('private diagnostic', 225)
            return original(coll, query, change, *args, **kwargs)
        fault.setattr(Collection, 'update_one', fail)
        r = c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2})
    assert r.status_code == 202 and not artifact.exists()
    with app.app_context():
        assert db().tools.find_one({'_id': 1}) is None
    jobs = c.get('/api/deletions').json['jobs']
    assert len(jobs) == 1 and jobs[0]['kind'] == 'tool' and jobs[0]['entityId'] == 1
    member, _ = ready(app, 'member')
    assert member.get('/api/deletions').status_code == 403
    assert c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': jobs[0]['revision']}).status_code == 200
    assert c.get('/api/deletions').json['jobs'] == []


@pytest.mark.parametrize('reference', ['tool', 'workspace'])
def test_shared_artifact_is_preserved(app, reference):
    c, h, artifact = trash(app)
    with app.app_context():
        if reference == 'tool':
            db().tools.insert_one({'_id': 999, 'versions': [{'path': artifact.name}]})
        else:
            db().workspace_files.insert_one({'_id': 'workspace', 'path': artifact.name})
    r = c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2})
    assert r.status_code == 200 and artifact.exists()


def test_unsafe_stored_path_is_never_deleted(app):
    c, h, artifact = trash(app)
    outside = Path(app.config['DATA_DIR']) / 'do-not-delete.txt'
    outside.write_text('keep')
    with app.app_context():
        db().tools.update_one({'_id': 1}, {'$set': {'versions.0.path': '../do-not-delete.txt'}})
    r = c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2})
    assert r.status_code == 202 and r.json['reason'] == 'invalid-path'
    assert outside.read_text() == 'keep' and artifact.exists()


def test_administrator_can_change_waiting_directly_to_complete(app):
    make_idea(app)
    make_tool(app)
    c, h = ready(app, 'admin')
    assert c.patch('/api/ideas/1', headers=h, json={'status': '구현 완료', 'expectedRevision': 0}).status_code == 400
    assert c.patch('/api/ideas/1', headers=h, json={'status': '구현 완료', 'tool': True, 'expectedRevision': 0}).status_code == 400
    r = c.patch('/api/ideas/1', headers=h, json={'status': '구현 완료', 'tool': 1, 'expectedRevision': 0})
    assert r.status_code == 200, r.json
    with app.app_context():
        assert db().ideas.find_one({'_id': 1})['assignee'] is None
    r = c.patch('/api/ideas/1', headers=h, json={'status': '접수 대기', 'expectedRevision': 1})
    assert r.status_code == 200
    with app.app_context():
        assert db().ideas.find_one({'_id': 1})['tool'] is None
    assert c.patch('/api/ideas/1', headers=h, json={'status': 'unknown', 'expectedRevision': 2}).status_code == 400
    assert c.patch('/api/ideas/1', headers=h, json={'status': [], 'expectedRevision': 2}).status_code == 400


def test_admin_status_skips_claim_but_member_rules_remain(app):
    c, h = make_idea(app)
    assert c.patch('/api/ideas/1', headers=h, json={'status': '개발 중', 'expectedRevision': 0}).status_code == 403
    a, ah = ready(app, 'admin')
    assert a.patch('/api/ideas/1', headers=ah, json={'status': '개발 중', 'expectedRevision': 0}).status_code == 200
    assert a.patch('/api/ideas/1', headers=ah, json={'status': '보류', 'expectedRevision': 0}).status_code == 409
    with app.app_context():
        assert db().ideas.find_one({'_id': 1})['assignee'] == 'admin'


def test_idea_delete_removes_attachments_replies_and_notifications(app):
    make_idea(app, attachment=True)
    c, h = ready(app, 'admin')
    assert c.delete('/api/ideas/1', headers=h, json={'expectedRevision': 1}).status_code == 409
    with app.app_context():
        idea = db().ideas.find_one({'_id': 1})
        path = Path(app.config['DATA_DIR']) / 'request_attachments' / idea['attachments'][0]['path']
        db().ideas.update_one({'_id': 1}, {'$set': {'replies': [{'user': 'member', 'text': 'reply', 'created': 0}]}})
    assert path.exists()
    r = c.delete('/api/ideas/1', headers=h, json={'expectedRevision': 0})
    assert r.status_code == 200 and not path.exists()
    assert c.get('/api/ideas').json['ideas'] == []
    assert c.get('/api/ideas/1/attachments/'+idea['attachments'][0]['id']).status_code == 404
    with app.app_context():
        assert db().ideas.find_one({'_id': 1}) is None
        assert db().notifications.count_documents({'target.type': 'idea', 'target.id': 1}) == 0
        assert db().audit.count_documents({'action': '기능 요청 1 영구 삭제'}) == 1


def test_pending_idea_delete_is_admin_visible_and_cannot_be_changed(app, monkeypatch):
    member, mh = make_idea(app, attachment=True)
    c, h = ready(app, 'admin')
    with monkeypatch.context() as fault:
        fault.setattr(Path, 'unlink', lambda *a, **k: (_ for _ in ()).throw(PermissionError()))
        r = c.delete('/api/ideas/1', headers=h, json={'expectedRevision': 0})
    assert r.status_code == 202
    assert member.get('/api/ideas').json['ideas'] == []
    pending = c.get('/api/ideas').json['ideas'][0]
    assert pending['deletionPending'] and 'purge' not in pending
    assert c.patch('/api/ideas/1', headers=h, json={'text': 'reply', 'expectedRevision': 1}).status_code == 409
    assert c.delete('/api/ideas/1', headers=h, json={'expectedRevision': 1}).status_code == 200


def test_late_outbox_and_legacy_jobs_do_not_resurrect_subscriptions(app):
    c, h, _ = trash(app)
    assert c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2}).status_code == 200
    with app.app_context():
        mongo_store._deliver_event({'id': 'late', 'subscription': {'tool': 1, 'user': 'member'},
                                    'recipients': ['member'], 'title': 'old', 'target': {'type': 'tool', 'id': 1},
                                    'kind': 'release', 'created': 0})
        db().activity_state.insert_one({'_id': 'late-state', 'tool': 1, 'user': 'member',
                                       'outbox': [{'_id': 'late-activity', 'tool': 1, 'user': 'member', 'kind': 'download'}]})
        mongo_activity.flush(tool_id=1)
        job = post_commit.audit_job('legacy-late', 'member', 'old audit', subscription={'tool': 1, 'user': 'member'})
        post_commit.deliver_job(db().tools, 1, job)
        assert db().subscriptions.count_documents({'tool': 1}) == 0
        assert db().activity.count_documents({'tool': 1}) == 0
        assert db().activity_state.count_documents({'tool': 1}) == 0
        assert db().notifications.count_documents({'target.type': 'tool', 'target.id': 1}) == 0


@pytest.mark.parametrize('worker', ['subscription', 'notification', 'activity', 'legacy'])
def test_worker_resuming_after_purge_cleans_its_late_writes(app, monkeypatch, worker):
    c, h, _ = trash(app)
    original = permanent_delete.deletion_started
    paused = False
    def pause_after_check(kind, entity_id):
        nonlocal paused
        value = original(kind, entity_id)
        if not paused:
            paused = True
            r = c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2})
            assert r.status_code == 200, r.json
        return value
    with app.app_context():
        if worker == 'activity':
            db().activity_state.insert_one({'_id': 'paused', 'tool': 1, 'user': 'member', 'outbox': [
                {'_id': 'paused-event', 'tool': 1, 'user': 'member', 'kind': 'download', 'created': 0}]})
        monkeypatch.setattr(permanent_delete, 'deletion_started', pause_after_check)
        if worker == 'activity':
            mongo_activity.flush(tool_id=1)
        elif worker == 'legacy':
            post_commit.deliver_job(db().tools, 1, post_commit.audit_job(
                'paused-legacy', 'member', 'audit kept', subscription={'tool': 1, 'user': 'member'}))
        elif worker == 'subscription':
            mongo_store._deliver_event({'id': 'paused-sub', 'subscription': {'tool': 1, 'user': 'member'}})
        else:
            mongo_store._deliver_event({'id': 'paused-notice', 'recipients': ['member'], 'title': 'old',
                'target': {'type': 'tool', 'id': 1}, 'kind': 'release', 'created': 0})
        assert paused
        for name in ('subscriptions', 'activity', 'activity_state'):
            assert db()[name].count_documents({'tool': 1}) == 0
        assert db().notifications.count_documents({'target.type': 'tool', 'target.id': 1}) == 0


@pytest.mark.parametrize('operation', ['subscription', 'grant', 'comment', 'link'])
def test_primary_writer_with_stale_tool_read_cannot_leave_deleted_relations(app, monkeypatch, operation):
    make_tool(app)
    if operation == 'link':
        make_idea(app)
    c, h = ready(app, 'admin')
    original = mongo_api.tool
    paused = False
    def stale_tool(*args, **kwargs):
        nonlocal paused
        value = original(*args, **kwargs)
        if not paused:
            paused = True
            db().tools.update_one({'_id': 1}, {'$set': {'deleted': True}, '$inc': {'revision': 1}})
            result = c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2})
            assert result.status_code == 200, result.json
        return value
    monkeypatch.setattr(mongo_api, 'tool', stale_tool)
    if operation == 'subscription':
        result = c.put('/api/tools/1/subscription', headers=h, json={'enabled': True})
    elif operation == 'grant':
        result = c.post('/api/tools/1/grants', headers=h, json={'user': 'member'})
    elif operation == 'comment':
        result = c.post('/api/tools/1/comments', headers=h, json={'kind': '개선 의견', 'text': 'stale'})
    else:
        result = c.patch('/api/ideas/1', headers=h, json={'status': '구현 완료', 'tool': 1, 'expectedRevision': 0})
    assert result.status_code in {200, 201}, result.json
    assert paused
    with app.app_context():
        for name in ('access', 'feedback', 'subscriptions', 'activity', 'activity_state'):
            assert db()[name].count_documents({'tool': 1}) == 0
        assert db().ideas.count_documents({'tool': 1}) == 0


def test_deferred_related_audits_survive_and_archive_failure_is_retryable(app, monkeypatch):
    c, h, _ = trash(app)
    with app.app_context():
        audit = {'id': 'saved-grant', 'audit': {'_id': 'saved-grant', 'user': 'admin', 'action': '권한 승인', 'created': 1}}
        db().access.insert_one({'_id': 'saved-access', 'tool': 1, 'user': 'member', 'outbox': [audit]})
    original = Collection.update_one
    with monkeypatch.context() as fault:
        def fail(coll, query, change, *args, **kwargs):
            if coll.name == 'deletion_jobs' and '$each' in change.get('$addToSet', {}).get('outbox', {}):
                raise OperationFailure('deferred audit failure', 225)
            return original(coll, query, change, *args, **kwargs)
        fault.setattr(Collection, 'update_one', fail)
        r = c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2})
    assert r.status_code == 202
    with app.app_context():
        assert db().access.find_one({'_id': 'saved-access'})['outbox'] == [audit]
    assert c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2}).status_code == 200
    with app.app_context():
        assert db().audit.count_documents({'_id': 'saved-grant'}) == 1
        assert db().access.find_one({'_id': 'saved-access'}) is None


def test_concurrently_appended_related_audit_is_not_dropped(app, monkeypatch):
    c, h, _ = trash(app)
    with app.app_context():
        db().access.insert_one({'_id': 'race-access', 'tool': 1, 'user': 'member', 'outbox': []})
    original = Collection.delete_one
    appended = False
    def append_before_delete(coll, query, *args, **kwargs):
        nonlocal appended
        if coll.name == 'access' and not appended:
            appended = True
            coll.update_one({'_id': 'race-access'}, {'$push': {'outbox': {'id': 'last-audit',
                'audit': {'_id': 'last-audit', 'user': 'admin', 'action': 'last permission decision', 'created': 2}}}})
        return original(coll, query, *args, **kwargs)
    monkeypatch.setattr(Collection, 'delete_one', append_before_delete)
    assert c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2}).status_code == 200
    with app.app_context():
        assert appended and db().audit.count_documents({'_id': 'last-audit'}) == 1
        assert db().access.find_one({'_id': 'race-access'}) is None


def test_late_activity_cleanup_failure_repaired_from_completed_tombstone(app, monkeypatch):
    c, h, _ = trash(app)
    original = permanent_delete.deletion_started
    paused = False
    def pause(kind, entity_id):
        nonlocal paused
        value = original(kind, entity_id)
        if not paused:
            paused = True
            assert c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2}).status_code == 200
        return value
    with app.app_context():
        db().activity_state.insert_one({'_id': 'lost-outbox', 'tool': 1, 'user': 'member', 'outbox': [
            {'_id': 'late-event', 'tool': 1, 'user': 'member', 'kind': 'download', 'created': 0}]})
        with monkeypatch.context() as fault:
            fault.setattr(permanent_delete, 'deletion_started', pause)
            fault.setattr(permanent_delete, 'cleanup_if_deleted', lambda *a: (_ for _ in ()).throw(OperationFailure('temporary DB outage', 225)))
            assert mongo_activity.flush(tool_id=1).pending
        assert db().activity.count_documents({'tool': 1}) == 1
        assert db().activity_state.count_documents({'tool': 1}) == 0
    assert c.get('/api/notifications').status_code == 200
    with app.app_context():
        assert db().activity.count_documents({'tool': 1}) == 0
        assert db().subscriptions.count_documents({'tool': 1}) == 0


def test_idea_link_cleanup_failure_remains_durable_until_delivery(app, monkeypatch):
    make_tool(app)
    make_idea(app)
    c, h = ready(app, 'admin')
    original = mongo_api.tool
    paused = False
    def stale_tool(*args, **kwargs):
        nonlocal paused
        row = original(*args, **kwargs)
        if not paused:
            paused = True
            db().tools.update_one({'_id': 1}, {'$set': {'deleted': True}, '$inc': {'revision': 1}})
            assert c.post('/api/tools/1/purge', headers=h, json={'expectedRevision': 2}).status_code == 200
        return row
    with monkeypatch.context() as fault:
        fault.setattr(mongo_api, 'tool', stale_tool)
        fault.setattr(permanent_delete, 'cleanup_if_deleted', lambda *a: (_ for _ in ()).throw(OperationFailure('temporary DB outage', 225)))
        r = c.patch('/api/ideas/1', headers=h, json={'status': '구현 완료', 'tool': 1, 'expectedRevision': 0})
    assert r.status_code == 200 and r.json['pending']
    with app.app_context():
        idea = db().ideas.find_one({'_id': 1})
        assert idea['tool'] == 1 and any(e.get('toolCheck') == 1 for e in idea['outbox'])
        # Deliberately test the saved event, independent of the periodic sweep.
        mongo_store.deliver_notifications('ideas', 1)
        assert db().ideas.find_one({'_id': 1})['tool'] is None
