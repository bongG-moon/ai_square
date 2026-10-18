"""MongoDB is the sole application database; artifacts stay on disk."""
import secrets
import time
import uuid
from flask import current_app, g
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
from .artifacts import stage_upload, artifact_path, used_bytes

def db():
    return current_app.extensions['square_mongo']

def next_id(name):
    return db().counters.find_one_and_update({'_id': name}, {'$inc': {'value': 1}}, upsert=True, return_document=ReturnDocument.AFTER)['value']

def init_db(app):
    client = MongoClient(app.config['MONGODB_URI'], serverSelectionTimeoutMS=app.config['MONGODB_TIMEOUT_MS'])
    client.admin.command('ping')
    app.extensions['square_mongo_client'] = client
    app.extensions['square_mongo'] = client[app.config['MONGODB_DATABASE']]
    with app.app_context():
        for collection, keys in [('taxonomy', [('kind', 1), ('name', 1)]), ('access', [('tool', 1), ('user', 1)]), ('subscriptions', [('tool', 1), ('user', 1)])]:
            db()[collection].create_index(keys, unique=True)
        db().notifications.create_index([('user', 1), ('created', -1)])
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

def deliver_notifications():
    # The source mutation atomically writes its outbox. Retry delivery is idempotent.
    for collection in ['tools', 'access', 'feedback', 'ideas', 'administrators']:
        for doc in db()[collection].find({'outbox.0': {'$exists': True}}, {'outbox': 1}):
            for e in doc['outbox']:
                for uid in e['recipients']:
                    db().notifications.update_one({'_id': e['id'] + ':' + uid}, {'$setOnInsert': {'user': uid, 'title': e['title'], 'target': e['target'], 'kind': e['kind'], 'created': e['created'], 'read': False}}, upsert=True)
                db()[collection].update_one({'_id': doc['_id']}, {'$pull': {'outbox': {'id': e['id']}}})

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
    values = {'name': name, 'orgId': tax['_id']}
    db().users.update_one({'_id': uid}, {'$set': values, '$setOnInsert': {'enabled': True, 'created': time.time()}}, upsert=True)

def public_user(row):
    org = db().taxonomy.find_one({'_id': row.get('orgId')})
    uid = row['_id']
    return {'id': uid, 'name': row['name'], 'org': org['name'] if org else '공통', 'orgId': row.get('orgId'), 'role': 'admin' if uid in all_admin_ids() else 'member', 'baseAdmin': uid in admin_ids(), 'enabled': row.get('enabled', True)}
