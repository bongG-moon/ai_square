"""Administrator taxonomy removal with explicit transfer and durable retry state.

Taxonomy rows remain as hidden tombstones so seed initialization and SSO cannot
recreate deleted labels. Reference writers share a short database lease with
taxonomy changes; this works with standalone MongoDB without transactions.
"""
from contextlib import contextmanager
from functools import wraps
import time
import uuid

from flask import g
from pymongo import ReturnDocument, timeout
from pymongo.errors import DuplicateKeyError, PyMongoError
from werkzeug.exceptions import BadRequest, Conflict, NotFound

from .storage import db, audit_event, deliver_notifications
from .post_commit import log_deferred


@contextmanager
def change_lock():
    """Serialize mutations only, with a shorter operation deadline than lease.

CSOT prevents a paused worker from writing after its lease could be reclaimed.
Read-only requests and ordinary authenticated requests never acquire this lock.
"""
    if getattr(g, '_taxonomy_change_lock', None):
        yield
        return
    collection = db().settings
    token = uuid.uuid4().hex
    try:
        collection.update_one({'_id': 'taxonomy-change-lock'},
                              {'$setOnInsert': {'owner': '', 'until': 0}}, upsert=True)
    except DuplicateKeyError:
        pass
    deadline = time.monotonic() + 2
    while True:
        now = time.time()
        held = collection.find_one_and_update(
            {'_id': 'taxonomy-change-lock', 'until': {'$lte': now}},
            {'$set': {'owner': token, 'until': now + 90}}, return_document=ReturnDocument.AFTER)
        if held:
            break
        if time.monotonic() >= deadline:
            raise Conflict('다른 조직 또는 업무 변경을 처리하고 있습니다. 잠시 후 다시 시도해 주세요.')
        time.sleep(.05)
    g._taxonomy_change_lock = token
    try:
        with timeout(30):
            yield
    finally:
        g.pop('_taxonomy_change_lock', None)
        try:
            collection.update_one({'_id': 'taxonomy-change-lock', 'owner': token},
                                  {'$set': {'owner': '', 'until': 0}})
        except PyMongoError as error:
            log_deferred('taxonomy-unlock', error)


def serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with change_lock():
            return function(*args, **kwargs)
    return wrapped


def resolve_alias(row):
    """Resolve an SSO/catalog alias without altering original department data."""
    visited = set()
    while row and (row.get('deleted') or row.get('deletion')):
        if row['_id'] in visited:
            raise Conflict('조직 이관 정보를 확인해 주세요.')
        visited.add(row['_id'])
        key = (row.get('deletion') or {}).get('targetId')
        if not key and row['kind'] == 'organization':
            key = 'organization-0'
        row = db().taxonomy.find_one({'_id': key, 'kind': row['kind']}) if key else None
    return row


def _source(key):
    row = db().taxonomy.find_one({'_id': key})
    if not row or row.get('kind') not in {'organization', 'category'}:
        raise NotFound('조직 또는 업무 분류를 찾을 수 없습니다.')
    return row


def _reference_query(source, prefix, field):
    return {'$or': [{prefix + field + 'Id': source['_id']},
                    {prefix + field + 'Id': {'$in': [None, '']}, prefix + field: source['name']}]}


def usage(source):
    field = 'org' if source['kind'] == 'organization' else 'category'
    counts = {'tools': db().tools.count_documents(_reference_query(source, 'data.', field)),
              'ideas': 0, 'users': 0}
    if source['kind'] == 'organization':
        counts['users'] = db().users.count_documents({'orgId': source['_id']})
    else:
        counts['ideas'] = db().ideas.count_documents(_reference_query(source, '', 'category'))
    counts['total'] = sum(counts.values())
    return counts


def preview(key):
    source = _source(key)
    marker = source.get('deletion') or {}
    protected = key == 'organization-0'
    targets = list(db().taxonomy.find({'kind': source['kind'], '_id': {'$ne': key},
        'enabled': True, 'deleted': {'$ne': True}, 'deletion': {'$exists': False}}).sort([('order', 1), ('name', 1)]))
    return dict(item=dict(id=key, name=source['name'], kind=source['kind']),
                usage=usage(source), targets=[dict(id=r['_id'], name=r['name']) for r in targets],
                protected=protected, reason='공통 조직은 기본 항목이므로 삭제할 수 없습니다.' if protected else '',
                pending=marker.get('state') == 'pending', deleted=bool(source.get('deleted')),
                lockedTargetId=marker.get('targetId'))


def _move_references(source, target):
    field = 'org' if source['kind'] == 'organization' else 'category'
    moved = {'tools': 0, 'ideas': 0, 'users': 0}
    moved['tools'] = db().tools.update_many(_reference_query(source, 'data.', field),
        {'$set': {'data.' + field + 'Id': target['_id'], 'data.' + field: target['name']},
         '$inc': {'revision': 1}}).modified_count
    if source['kind'] == 'organization':
        moved['users'] = db().users.update_many({'orgId': source['_id']},
            {'$set': {'orgId': target['_id']}}).modified_count
    else:
        moved['ideas'] = db().ideas.update_many(_reference_query(source, '', 'category'),
            {'$set': {'categoryId': target['_id'], 'category': target['name']},
             '$inc': {'revision': 1}}).modified_count
    return moved


@serialized
def remove(key, raw):
    if raw.get('confirmed') is not True:
        raise BadRequest('삭제 여부를 확인해 주세요.')
    source = _source(key)
    if key == 'organization-0':
        raise BadRequest('공통 조직은 기본 항목이므로 삭제할 수 없습니다.')
    target_id = raw.get('targetId')
    if target_id is not None and (not isinstance(target_id, str) or len(target_id) > 200):
        raise BadRequest('이관할 항목을 확인해 주세요.')
    target_id = target_id or None
    marker = source.get('deletion')
    if marker:
        if target_id != marker.get('targetId'):
            raise Conflict('이미 시작한 삭제는 같은 이관 대상으로 다시 시도해 주세요.')
        if marker.get('state') == 'complete':
            return dict(ok=True, deleted=True, id=key, targetId=target_id,
                        moved=marker.get('usage', {}), replayed=True)
    if db().taxonomy.find_one({'deletion.state': 'pending', 'deletion.targetId': key}, {'_id': 1}):
        raise Conflict('다른 항목의 이관 대상으로 사용 중입니다. 해당 이관을 먼저 완료해 주세요.')
    target = None
    if target_id:
        target = db().taxonomy.find_one({'_id': target_id, 'kind': source['kind'],
            'enabled': True, 'deleted': {'$ne': True}, 'deletion': {'$exists': False}})
        if target_id == key or not target:
            raise BadRequest('사용 가능한 다른 항목을 이관 대상으로 선택해 주세요.')
    counts = usage(source)
    if counts['total'] and not target:
        raise Conflict('등록된 항목이 있습니다. 이관할 항목을 선택해 주세요.')
    if not marker:
        marker = dict(state='pending', targetId=target_id, actor=g.user['id'],
                      started=time.time(), usage=counts, originalEnabled=source.get('enabled', True))
        db().taxonomy.update_one({'_id': key, 'deletion': {'$exists': False}},
            {'$set': {'deletion': marker, 'enabled': False}})
    if target:
        _move_references(source, target)
    if usage(source)['total']:
        raise Conflict('이관이 아직 완료되지 않았습니다. 같은 대상으로 다시 시도해 주세요.')
    label = '조직' if source['kind'] == 'organization' else '업무 분류'
    job = audit_event(f'{label} {source["name"]} 삭제' + (f' / {target["name"]}으로 이관' if target else ''))
    db().taxonomy.update_one({'_id': key, 'deletion.state': 'pending'},
        {'$set': {'deleted': True, 'enabled': False, 'deletion.state': 'complete',
                  'deletion.completed': time.time()}, '$push': {'outbox': job}})
    pending = False
    try:
        pending = deliver_notifications('taxonomy', key).pending
    except PyMongoError as error:
        log_deferred('taxonomy-delete-audit', error)
        pending = True
    return dict(ok=True, deleted=True, id=key, targetId=target_id,
                moved=marker['usage'], pending=pending)
