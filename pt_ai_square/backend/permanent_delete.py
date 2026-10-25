"""Explicit administrator deletion, with durable intent and retryable disk cleanup.

The source is locked first. Files/relations are removed before its final removal;
the minimal job/audit tombstone survives so retries cannot resurrect the object.
"""
import time
import uuid
from pathlib import Path

from flask import current_app, g
from pymongo.errors import PyMongoError
from werkzeug.exceptions import BadRequest, Conflict, NotFound

from .storage import db, audit_event, deliver_notifications
from .post_commit import log_deferred, DeliveryResult


KINDS = {'tool': 'tools', 'idea': 'ideas'}


def deletion_started(kind, entity_id):
    """Also covers a committed source lock whose job copy is still deferred."""
    if db().deletion_jobs.find_one({'_id': f'{kind}:{entity_id}'}, {'_id': 1}):
        return True
    return bool(db()[KINDS[kind]].find_one(
        {'_id': entity_id, 'purge': {'$exists': True}}, {'_id': 1}))


def _file_path(folder, key):
    if not isinstance(key, str) or not key or Path(key).name != key or '\\' in key:
        raise BadRequest('삭제할 파일 경로를 확인해 주세요.')
    root = Path(current_app.config['DATA_DIR']).resolve()
    directory = (root / folder).resolve()
    path = (directory / key).resolve()
    # Reject a symlink/junction redirecting either the folder or file outside
    # DATA_DIR, even if the pre-existing artifact helper accepted that folder.
    if directory.parent != root or path.parent != directory:
        raise BadRequest('삭제할 파일 경로를 확인해 주세요.')
    return path


def _referenced(job, key):
    if job['kind'] == 'idea':
        return bool(db().ideas.find_one(
            {'_id': {'$ne': job['entityId']}, 'attachments.path': key}, {'_id': 1}))
    return bool(db().tools.find_one(
        {'_id': {'$ne': job['entityId']}, 'versions.path': key}, {'_id': 1})
        or db().workspace_files.find_one({'$or': [{'path': key}, {'versions.path': key}]}, {'_id': 1}))


def _job_from_source(kind, source):
    marker = source['purge']
    rows = source.get('versions' if kind == 'tool' else 'attachments', [])
    # Audits are preserved, but obsolete subscriptions/notifications must not
    # be delivered after the source itself has been removed.
    audits = [{'id': e['id'], 'audit': e['audit']} for e in source.get('outbox', []) if e.get('audit')]
    audits += [{'id': e['_id'], 'audit': e['audit']} for e in source.get('postCommit', []) if e.get('audit')]
    audits.append(marker['audit'])
    completed_id = marker['id'] + ':complete'
    completed = {'id': completed_id, 'audit': {'_id': completed_id,
                 'user': marker['audit']['audit']['user'], 'created': marker['created'],
                 'action': f'{"도구" if kind == "tool" else "기능 요청"} {source["_id"]} 영구 삭제'}}
    return {'_id': f'{kind}:{source["_id"]}', 'kind': kind, 'entityId': source['_id'],
            'operationId': marker['id'], 'state': 'pending', 'created': marker['created'],
            'revision': source['revision'], 'requestRevision': marker['requestRevision'],
            'files': sorted({r['path'] for r in rows if r.get('path')}), 'outbox': audits,
            'completionAudit': completed}


def _remove_relations(job):
    entity_id = job['entityId']
    if job['kind'] == 'tool':
        # Keep the request and its discussion; retain a readable snapshot but
        # remove the live foreign key and bump its optimistic revision.
        db().ideas.update_many({'tool': entity_id}, {
            '$set': {'tool': None, 'removedTool': {'id': entity_id, 'removedAt': job['created']}},
            '$inc': {'revision': 1}})
        for name in ('access', 'feedback'):
            # Never drop committed deferred audits with the deleted relation.
            # Compare its exact queues when removing: a concurrent append is
            # retried rather than discarded after our audit snapshot.
            collection = db()[name]
            for _ in range(3):
                for row in collection.find({'tool': entity_id}):
                    audits = [{'id': e['id'], 'audit': e['audit']} for e in row.get('outbox', []) if e.get('audit')]
                    audits += [{'id': e['_id'], 'audit': e['audit']} for e in row.get('postCommit', []) if e.get('audit')]
                    if audits:
                        db().deletion_jobs.update_one({'_id': job['_id']}, {'$addToSet': {'outbox': {'$each': audits}}})
                    query = {'_id': row['_id'], 'tool': entity_id}
                    for field in ('outbox', 'postCommit'):
                        query[field] = row[field] if field in row else {'$exists': False}
                    collection.delete_one(query)
                if not collection.find_one({'tool': entity_id}, {'_id': 1}):
                    break
            else:
                return False
        for collection in ('activity_state', 'subscriptions', 'activity'):
            db()[collection].delete_many({'tool': entity_id})
        db().notifications.delete_many({'target.type': {'$in': ['tool', 'access', 'feedback']},
                                        'target.id': entity_id})
    else:
        db().notifications.delete_many({'target.type': 'idea', 'target.id': entity_id})
    return True


def cleanup_if_deleted(kind, entity_id):
    """Post-write guard: closes the check-before-purge/write-after-purge race.

If deletion starts after this check its cleanup sees the completed write. If
deletion has already started, this writer cleans its own late side effects.
"""
    job = db().deletion_jobs.find_one({'_id': f'{kind}:{entity_id}'})
    if not job:
        source = db()[KINDS[kind]].find_one({'_id': entity_id, 'purge': {'$exists': True}})
        if not source:
            return False
        job = _job_from_source(kind, source)
        db().deletion_jobs.update_one({'_id': job['_id']}, {'$setOnInsert': job}, upsert=True)
    was_complete = job.get('state') == 'complete'
    if was_complete:
        db().deletion_jobs.update_one({'_id': job['_id']}, {'$set': {'state': 'pending'}})
    if not _remove_relations(job):
        # Leave a discoverable retry even if this was a very late writer after
        # the original source was already removed successfully.
        db().deletion_jobs.update_one({'_id': job['_id']}, {'$set': {'state': 'pending'}})
    elif was_complete:
        db().deletion_jobs.update_one({'_id': job['_id']}, {'$set': {'state': 'complete'}})
    return True


def reconcile_completed(limit=5):
    """Rotate a bounded repair sweep over retained tombstones.

An in-flight worker can outlive source removal, then lose DB connectivity at
its post-write guard. Its old outbox may already be gone. The tombstone is the
durable retry anchor for that case, including across process restarts.
"""
    jobs = db().deletion_jobs.find({'state': 'complete'}).sort([('checkedAt', 1), ('created', 1)]).limit(limit)
    processed = 0
    for job in jobs:
        cleanup_if_deleted(job['kind'], job['entityId'])
        db().deletion_jobs.update_one({'_id': job['_id']}, {'$set': {'checkedAt': time.time()}})
        processed += 1
    return DeliveryResult(processed, False)


def _resume(job):
    key = job['_id']
    try:
        if job.get('state') != 'complete':
            folder = 'artifacts' if job['kind'] == 'tool' else 'request_attachments'
            for filename in job.get('files', []):
                path = _file_path(folder, filename)
                if not _referenced(job, filename):
                    path.unlink(missing_ok=True)
            if not _remove_relations(job):
                return {'ok': True, 'pending': True, 'deleted': False, 'revision': job['revision'],
                        'jobId': key, 'reason': 'concurrent-change',
                        'message': '동시에 처리된 이력을 정리하고 있습니다. 삭제 재시도로 마무리해 주세요.'}
            source = db()[KINDS[job['kind']]]
            removed = source.delete_one({'_id': job['entityId'], 'purge.id': job['operationId']})
            if not removed.deleted_count and source.find_one({'_id': job['entityId']}, {'_id': 1}):
                raise Conflict('삭제 대상이 변경되었습니다. 관리자에게 문의해 주세요.')
            # A failed completion marker can be retried after source removal.
            db().deletion_jobs.update_one({'_id': key}, {'$set': {'state': 'complete', 'completed': time.time()},
                                                        '$unset': {'files': ''},
                                                        '$addToSet': {'outbox': job['completionAudit']}})
        pending = deliver_notifications('deletion_jobs', key).pending
        return {'ok': True, 'pending': pending, 'deleted': True, 'revision': job['revision'], 'jobId': key}
    except PyMongoError as error:
        log_deferred('permanent-delete', error)
        reason = 'database'
    except OSError:
        current_app.logger.warning('Permanent deletion deferred reason=filesystem')
        reason = 'filesystem'
    except BadRequest:
        current_app.logger.warning('Permanent deletion deferred reason=invalid-path')
        reason = 'invalid-path'
    return {'ok': True, 'pending': True, 'deleted': False, 'revision': job['revision'],
            'jobId': key, 'reason': reason,
            'message': '삭제 요청은 저장되었습니다. 파일·관련 정보 정리가 남아 있습니다. 삭제 재시도로 이어서 처리할 수 있습니다.'}


def remove(kind, entity_id, expected_revision):
    """Caller enforces admin. Acknowledged source lock is never reported undone."""
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
        raise Conflict('변경된 버전이 있습니다. 새로고침해 주세요.')
    collection = db()[KINDS[kind]]
    source = collection.find_one({'_id': entity_id})
    if source is None:
        job = db().deletion_jobs.find_one({'_id': f'{kind}:{entity_id}'})
        if job is None:
            raise NotFound('삭제할 항목을 찾을 수 없습니다.')
        if expected_revision not in {job['requestRevision'], job['revision']}:
            raise Conflict('변경된 버전이 있습니다. 새로고침해 주세요.')
        return _resume(job)
    if kind == 'tool' and source.get('deleted') is not True:
        raise Conflict('휴지통으로 이동한 도구만 영구 삭제할 수 있습니다.')
    marker = source.get('purge')
    permitted = {source['revision']}
    if marker:
        permitted.add(marker['requestRevision'])
    if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision not in permitted:
        raise Conflict('변경된 버전이 있습니다. 새로고침해 주세요.')
    if not marker:
        marker = {'id': uuid.uuid4().hex, 'created': time.time(), 'requestRevision': source['revision'],
                  'audit': audit_event(f'{"도구" if kind == "tool" else "기능 요청"} {entity_id} 영구 삭제 요청')}
        result = collection.update_one({'_id': entity_id, 'revision': source['revision'], 'purge': {'$exists': False}},
                                       {'$set': {'purge': marker}, '$inc': {'revision': 1}})
        if not result.modified_count:
            raise Conflict('다른 변경이 반영되었습니다. 새로고침 후 다시 시도해 주세요.')
        source = dict(source, purge=marker, revision=source['revision'] + 1)
    job = _job_from_source(kind, source)
    try:
        db().deletion_jobs.update_one({'_id': job['_id']}, {'$setOnInsert': job}, upsert=True)
        # Another retry may already have completed cleanup; reread canonical job.
        job = db().deletion_jobs.find_one({'_id': job['_id']})
    except PyMongoError as error:
        log_deferred('permanent-delete-intent', error)
        return {'ok': True, 'pending': True, 'deleted': False, 'revision': source['revision'],
                'jobId': job['_id'], 'reason': 'database',
                'message': '삭제 요청은 저장되었습니다. 삭제 재시도로 정리를 이어서 처리해 주세요.'}
    return _resume(job)
