"""MongoDB is the sole application database; artifacts stay on disk."""
import secrets
import os
import threading
import time
import uuid
from os import getpid
from flask import current_app, g
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from .artifacts import stage_upload, artifact_path, used_bytes

# A company WSGI runner may import web_main before forking its workers. Each
# process must own its own client/session pool; threads in that process share it.
_CLIENT_LOCK = threading.RLock()


def _after_fork():
    global _CLIENT_LOCK
    # A lock copied while held by a vanished parent thread must not be acquired.
    _CLIENT_LOCK = threading.RLock()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


def mongo_client(config):
    """Use identical explicit connection options in serving and diagnostics."""
    return MongoClient(config['MONGODB_URI'],
                       serverSelectionTimeoutMS=config['MONGODB_TIMEOUT_MS'],
                       retryWrites=config.get('MONGODB_RETRY_WRITES', False),
                       connect=False)


def _connect(app):
    client = mongo_client(app.config)
    try:
        database = client[app.config['MONGODB_DATABASE']]
        client.admin.command('ping')
    except Exception:
        client.close()
        raise
    app.extensions['square_mongo_client'] = client
    app.extensions['square_mongo'] = database
    app.extensions['square_mongo_pid'] = getpid()
    return client


def db():
    if current_app.extensions.get('square_mongo_pid') != getpid():
        with _CLIENT_LOCK:
            if current_app.extensions.get('square_mongo_pid') != getpid():
                inherited = current_app.extensions.get('square_mongo_client')
                _connect(current_app)
                if inherited is not None:
                    # Never use or close an inherited client: ending its copied
                    # sessions could interfere with the still-running parent.
                    current_app.extensions.setdefault('square_mongo_inherited_clients', []).append(inherited)
                current_app.logger.info('MongoDB client initialized for current worker process')
    return current_app.extensions['square_mongo']

def next_id(name):
    return db().counters.find_one_and_update({'_id': name}, {'$inc': {'value': 1}}, upsert=True, return_document=ReturnDocument.AFTER)['value']

def init_db(app):
    with _CLIENT_LOCK:
        _connect(app)
    with app.app_context():
        for collection, keys in [('taxonomy', [('kind', 1), ('name', 1)]), ('access', [('tool', 1), ('user', 1)]), ('subscriptions', [('tool', 1), ('user', 1)])]:
            db()[collection].create_index(keys, unique=True)
        db().notifications.create_index([('user', 1), ('created', -1)])
        db().local_tokens.create_index([('user', 1), ('expires', -1)])
        db().activity.create_index([('user', 1), ('kind', 1), ('created', -1)])
        db().tools.create_index('versions.apiUsage.user')
        db().tools.create_index('versions.publishRequest.key', unique=True, sparse=True)
        db().tools.create_index([('owner', 1), ('deleted', 1)])
        db().ideas.create_index([('status', 1), ('created', -1)])
        db().activity.create_index([('tool', 1), ('created', -1)])
        for kind, names in [('organization', ['공통', '제조팀', '장비팀', '기술팀']), ('category', ['공통 업무', '제조', '장비', '기술'])]:
            for order, name in enumerate(names):
                # A renamed seed must not be recreated on restart.
                key = f'{kind}-{order}'
                if not db().taxonomy.find_one({'_id': key}):
                    db().taxonomy.update_one({'kind': kind, 'name': name}, {'$setOnInsert': {'_id': key, 'enabled': True, 'order': order, 'owner': '플랫폼 운영자'}}, upsert=True)
        db().settings.update_one({'_id': 'retention'}, {'$setOnInsert': {'keep': 3, 'days': 90}}, upsert=True)
        db().settings.update_one({'_id': 'session'}, {'$setOnInsert': {'secret': secrets.token_hex(32)}}, upsert=True)
        if not app.config.get('SECRET_KEY'):
            app.config['SECRET_KEY'] = db().settings.find_one({'_id': 'session'})['secret']

def audit(message):
    db().audit.insert_one({'user': g.user['id'], 'action': message, 'created': time.time()})

def admin_ids():
    ids = {x.strip() for x in current_app.config['ADMIN_IDS'].split(',') if x.strip()}
    if current_app.config['AUTH_MODE'] == 'mock' and current_app.config['MOCK_ADMIN']:
        ids.add(current_app.config['MOCK_USER'])
    return ids

def all_admin_ids():
    return admin_ids() | {x['_id'] for x in db().administrators.find({'active': True})}

def event(recipients, title, target, kind='update'):
    return {'id': uuid.uuid4().hex, 'recipients': sorted(set(recipients) - {g.user['id']}), 'title': title, 'target': target, 'kind': kind, 'created': time.time()}

def audit_event(message, subscription=None):
    """Create an event for the same atomic document write as its mutation."""
    eid, created = uuid.uuid4().hex, time.time()
    value = {'id': eid, 'created': created,
             'audit': {'_id': eid, 'user': g.user['id'], 'action': message, 'created': created}}
    if subscription is not None:
        value['subscription'] = subscription
    return value


def best_effort(operation, callback, *args):
    """Run secondary work only; primary writes must propagate their failures."""
    from .post_commit import followup_pending
    return not followup_pending(operation, callback, *args)


def _deliver_event(e):
    entry = e.get('audit')
    if entry:
        # Operational builds used the enclosing event ID as the audit key and
        # may omit a duplicated _id inside the optional audit payload.
        entry = dict(entry)
        entry.setdefault('_id', e['id'])
        db().audit.update_one({'_id': entry['_id']}, {'$setOnInsert': entry}, upsert=True)
    subscription = e.get('subscription')
    if subscription:
        # Preserve an explicit unsubscribe even when delivery was delayed.
        db().subscriptions.update_one(subscription, {'$setOnInsert': {'enabled': True}}, upsert=True)
    token_update = e.get('tokenUpdate')
    if token_update:
        fields = token_update['fields']
        if set(fields) - {'revoked', 'revokedAt', 'replacedBy'}:
            raise ValueError('Unsupported deferred token fields')
        db().local_tokens.update_one({'id': token_update['id'], 'user': token_update['user']},
                                     {'$set': fields})
    for uid in e.get('recipients', []):
        db().notifications.update_one(
            {'_id': e['id'] + ':' + uid},
            {'$setOnInsert': {'user': uid, 'title': e['title'], 'target': e['target'],
                              'kind': e['kind'], 'created': e['created'], 'read': False}}, upsert=True)


def deliver_notifications(collection_name=None, document_id=None):
    """Deliver bounded, idempotent outbox work; leave failed events durable."""
    from .post_commit import DeliveryResult, deliver_job, log_deferred
    supported = ('tools', 'access', 'feedback', 'ideas', 'administrators', 'settings', 'taxonomy', 'users')
    collections = supported if collection_name is None else (collection_name,)
    if any(name not in supported for name in collections):
        raise ValueError('Unsupported outbox collection')
    count, pending = 0, False
    for name in collections:
        collection = db()[name]
        query = {'outbox.0': {'$exists': True}}
        if name in {'tools', 'settings'}:
            query = {'$or': [query, {'postCommit.0': {'$exists': True}}]}
        if document_id is not None:
            query['_id'] = document_id
        try:
            rows = list(collection.find(query, {'outbox': 1, 'postCommit': 1}).limit(51))
        except PyMongoError as error:
            log_deferred('outbox-scan', error)
            pending = True
            continue
        pending = len(rows) > 50 or pending
        for doc in rows[:50]:
            events = [('outbox', e) for e in doc.get('outbox', [])]
            # Pre-upgrade jobs share the same per-document delivery budget, so
            # an upgrade cannot double the work done in one maintenance call.
            if name in {'tools', 'settings'}:
                events += [('postCommit', e) for e in doc.get('postCommit', [])]
            pending = len(events) > 50 or pending
            for queue, e in events[:50]:
                try:
                    if queue == 'postCommit':
                        deliver_job(collection, doc['_id'], e)
                    else:
                        _deliver_event(e)
                        collection.update_one({'_id': doc['_id']}, {'$pull': {'outbox': {'id': e['id']}}})
                    count += 1
                except PyMongoError as error:
                    log_deferred('outbox-event', error)
                    pending = True
    return DeliveryResult(count, pending)

def purge_deleted():
    for t in db().tools.find({'versions': {'$elemMatch': {'deleted': True, 'path': {'$ne': None}}}}):
        for v in t.get('versions', []):
            if not v.get('deleted') or not v.get('path'): continue
            try: artifact_path(v['path']).unlink(missing_ok=True)
            except OSError: continue
            db().tools.update_one({'_id': t['_id']}, {'$set': {'versions.$[v].path': None}}, array_filters=[{'v.n': v['n'], 'v.deleted': True}])

def ensure_user(uid, name, org='공통', org_code=None):
    tax = db().taxonomy.find_one({'kind': 'organization', 'ssoCode': org_code}) if org_code else None
    if not tax: tax = db().taxonomy.find_one({'kind': 'organization', 'name': org})
    if not tax:
        try: db().taxonomy.insert_one({'_id': uuid.uuid4().hex, 'kind': 'organization', 'name': org, 'enabled': True, 'order': 99, 'owner': '플랫폼 운영자'})
        except DuplicateKeyError: pass
        tax = db().taxonomy.find_one({'kind': 'organization', 'name': org})
    if org_code: db().taxonomy.update_one({'_id': tax['_id']}, {'$set': {'ssoCode': org_code}})
    # The employee number remains the primary key: existing tool ownership,
    # grants and connection-key pointers must survive an SSO profile refresh.
    # Keep the four company SSO fields explicitly as well as the existing UI
    # aliases. Department display names may change while the SSO code stays.
    values = {'name': name, 'orgId': tax['_id'], 'emp_no': uid,
              'emp_name': name, 'dept': org, 'dept_cd': str(org_code or '')}
    db().users.update_one({'_id': uid}, {'$set': values, '$setOnInsert': {'enabled': True, 'created': time.time()}}, upsert=True)

def public_user(row):
    org = db().taxonomy.find_one({'_id': row.get('orgId')})
    uid = row['_id']
    department = row.get('dept') or (org['name'] if org else '공통')
    # Preserve the administrator-managed catalog organization alias while
    # exposing the exact SSO department separately for the personal profile.
    return {'id': uid, 'name': row['name'], 'org': org['name'] if org else department, 'orgId': row.get('orgId'),
            'emp_no': uid, 'emp_name': row.get('emp_name', row['name']),
            'dept': department, 'dept_cd': row.get('dept_cd', (org or {}).get('ssoCode', '')),
            'photoUrl': '/api/me/photo',
            'role': 'admin' if uid in all_admin_ids() else 'member', 'baseAdmin': uid in admin_ids(), 'enabled': row.get('enabled', True)}
