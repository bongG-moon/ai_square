import time
import uuid
from flask import current_app
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from .storage import db

def init_activity(app):
    with app.app_context():
        db().activity_state.create_index([('tool', 1), ('kind', 1)])

def is_mongo(): return True

def flush():
    count = 0
    for row in db().activity_state.find({'outbox.0': {'$exists': True}}):
        for e in row['outbox']:
            db().activity.update_one({'_id': e['_id']}, {'$setOnInsert': e}, upsert=True)
            db().activity_state.update_one({'_id': row['_id']}, {'$pull': {'outbox': {'_id': e['_id']}}})
            count += 1
    return count

def set_like(tid, uid, liked):
    key = f'like:{tid}:{uid}'
    try: db().activity_state.update_one({'_id': key}, {'$setOnInsert': {'tool': tid, 'user': uid, 'kind': 'like', 'liked': False}}, upsert=True)
    except DuplicateKeyError: pass
    now = time.time()
    e = {'_id': uuid.uuid4().hex, 'tool': tid, 'user': uid, 'kind': 'like' if liked else 'unlike', 'created': now, 'version': None, 'counted': liked}
    db().activity_state.update_one({'_id': key, 'liked': {'$ne': liked}}, {'$set': {'liked': liked, 'created': now}, '$push': {'outbox': e}})
    return db().activity_state.count_documents({'tool': tid, 'kind': 'like', 'liked': True})

def record_download(tid, uid, version):
    now = time.time(); day = int((now + 9 * 3600) // 86400)
    key = f'download:{tid}:{uid}:{day}'
    try: db().activity_state.update_one({'_id': key}, {'$setOnInsert': {'tool': tid, 'user': uid, 'kind': 'download', 'created': now, 'count': 0}}, upsert=True)
    except DuplicateKeyError: pass
    # Count and durable event are updated in one document, even on standalone MongoDB.
    eid = uuid.uuid4().hex
    db().activity_state.update_one({'_id': key}, [{'$set': {'outbox': {'$concatArrays': [{'$ifNull': ['$outbox', []]}, [{'_id': eid, 'tool': tid, 'user': uid, 'kind': 'download', 'created': now, 'version': version, 'counted': {'$eq': ['$count', 0]}}]]}, 'count': {'$add': ['$count', 1]}}}])

def statistics(ids, uid, now):
    stats = {tid: dict(liked=False, likes=0, downloads=0, rankScore=0) for tid in ids}
    for r in db().activity_state.find({'tool': {'$in': ids}}):
        s = stats[r['tool']]; age = now - r.get('created', 0)
        weight = 4 if age < 3600 else 2 if age < 21600 else 1 if age < 86400 else 0
        if r['kind'] == 'like' and r.get('liked'):
            s['likes'] += 1; s['rankScore'] += 3 * weight
            if r['user'] == uid: s['liked'] = True
        elif r['kind'] == 'download' and r.get('count', 0):
            s['downloads'] += 1; s['rankScore'] += weight
    return stats

def history(before=None):
    flush()
    query = {}
    if before:
        # Cursor is the last event ID; pair timestamp with ID to preserve ties.
        last = db().activity.find_one({'_id': before})
        if last: query = {'$or': [{'created': {'$lt': last['created']}}, {'created': last['created'], '_id': {'$lt': last['_id']}}]}
    rows = list(db().activity.find(query).sort([('created', -1), ('_id', -1)]).limit(51))
    more = len(rows) > 50; rows = rows[:50]
    for r in rows: r['id'] = str(r['_id']); r.pop('_id')
    return rows, rows[-1]['id'] if more else None
