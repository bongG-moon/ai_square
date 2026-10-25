import time
import uuid
from flask import current_app
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from .storage import db

def init_activity(app):
    with app.app_context():
        db().activity_state.create_index([('tool', 1), ('kind', 1)])
        db().activity_state.create_index([('tool', 1), ('user', 1), ('kind', 1), ('created', 1)])

def is_mongo(): return True

def flush(tool_id=None, user_id=None, limit=0):
    """Deliver scoped activity events; callers bound maintenance with limit=50."""
    from .post_commit import DeliveryResult, log_deferred
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError('Activity delivery limit must be a nonnegative integer')
    query = {'outbox.0': {'$exists': True}}
    if tool_id is not None:
        query['tool'] = tool_id
    if user_id is not None:
        query['user'] = user_id
    count, pending = 0, False
    try:
        rows = db().activity_state.find(query)
        if limit:
            rows = rows.limit(limit + 1)
        for index, row in enumerate(rows):
            if limit and index >= limit:
                pending = True
                break
            from .permanent_delete import deletion_started, cleanup_if_deleted
            if deletion_started('tool', row['tool']):
                # No notification-poll retry may resurrect a purged tool's
                # history/subscription from a stale activity-state snapshot.
                cleanup_if_deleted('tool', row['tool'])
                continue
            events = row['outbox']
            pending = len(events) > 50 or pending
            for e in events[:50]:
                try:
                    db().activity.update_one({'_id': e['_id']}, {'$setOnInsert': e}, upsert=True)
                    if e['kind'] == 'download':
                        # The state write durably records this intent. Delayed
                        # delivery never overrides an explicit later opt-out.
                        db().subscriptions.update_one(
                            {'tool': e['tool'], 'user': e['user']},
                            {'$setOnInsert': {'enabled': True}}, upsert=True)
                    from .permanent_delete import cleanup_if_deleted
                    cleanup_if_deleted('tool', row['tool'])
                    db().activity_state.update_one(
                        {'_id': row['_id']}, {'$pull': {'outbox': {'_id': e['_id']}}})
                    count += 1
                except PyMongoError as error:
                    log_deferred('activity-event', error)
                    pending = True
    except PyMongoError as error:
        log_deferred('activity-scan', error)
        pending = True
    return DeliveryResult(count, pending)

def set_like(tid, uid, liked):
    key = f'like:{tid}:{uid}'
    try: db().activity_state.update_one({'_id': key}, {'$setOnInsert': {'tool': tid, 'user': uid, 'kind': 'like', 'liked': False}}, upsert=True)
    except DuplicateKeyError: pass
    now = time.time()
    e = {'_id': uuid.uuid4().hex, 'tool': tid, 'user': uid, 'kind': 'like' if liked else 'unlike', 'created': now, 'version': None, 'counted': liked}
    # Keep the first known like date when cancelling/re-liking, so toggling
    # cannot move an old recommendation into the recent seven-day window.
    db().activity_state.update_one({'_id': key, 'liked': {'$ne': liked}}, [{'$set': {
        'liked': liked, 'created': now,
        'firstLikedAt': {'$ifNull': ['$firstLikedAt', {'$ifNull': ['$created', now]}]},
        'outbox': {'$concatArrays': [{'$ifNull': ['$outbox', []]}, [e]]}
    }}])
    try:
        return db().activity_state.count_documents({'tool': tid, 'kind': 'like', 'liked': True})
    except PyMongoError as error:
        # Both primary writes above succeeded. A stale/unavailable count must
        # not turn an acknowledged selection into a reported save failure.
        from .post_commit import log_deferred
        log_deferred('like-count', error)
        return None

def record_download(tid, uid, version, token_id=None, update=False):
    now = time.time()
    key = f'download:{tid}:{uid}'
    # Preserve the earliest historical download without rewriting old events.
    legacy = db().activity_state.find_one(
        {'tool': tid, 'user': uid, 'kind': 'download', '_id': {'$ne': key}, 'count': {'$gt': 0}},
        sort=[('created', 1)])
    first = legacy['created'] if legacy else None
    try: db().activity_state.update_one({'_id': key}, {'$setOnInsert': {'tool': tid, 'user': uid, 'kind': 'download', 'created': now, 'count': 0, 'firstDownloadedAt': first}}, upsert=True)
    except DuplicateKeyError: pass
    # Count and durable event are updated in one document, even on standalone MongoDB.
    eid = uuid.uuid4().hex
    eligible = {'$and': [{'$eq': [{'$ifNull': ['$firstDownloadedAt', None]}, None]}, {'$literal': not update}]}
    record = {'_id': eid, 'tool': tid, 'user': uid, 'kind': 'download', 'created': now, 'version': version, 'counted': eligible, 'purpose': 'update' if update else 'download'}
    if token_id:
        record['tokenId'] = token_id
    db().activity_state.update_one({'_id': key}, [{'$set': {'outbox': {'$concatArrays': [{'$ifNull': ['$outbox', []]}, [record]]}, 'count': {'$add': ['$count', 1]}, 'firstDownloadedAt': {'$cond': [eligible, now, '$firstDownloadedAt']}}}])


VIEW_WINDOW_SECONDS = 30 * 60


def record_view(tid, uid):
    """One bounded state row per user/tool, without a per-open history outbox.

    Web and extension share the same atomic cooldown. Read APIs, preview loads,
    install plans and retries do not manufacture views or affect ranking.
    """
    now, key = time.time(), f'view:{tid}:{uid}'
    try:
        db().activity_state.update_one({'_id': key}, {'$setOnInsert': {
            'tool': tid, 'user': uid, 'kind': 'view', 'count': 0,
            'created': now, 'lastViewedAt': 0}}, upsert=True)
    except DuplicateKeyError:
        pass
    result = db().activity_state.update_one(
        {'_id': key, 'lastViewedAt': {'$lte': now - VIEW_WINDOW_SECONDS}},
        {'$inc': {'count': 1}, '$set': {'lastViewedAt': now}})
    try:
        rows = list(db().activity_state.aggregate([
            {'$match': {'tool': tid, 'kind': 'view'}},
            {'$group': {'_id': None, 'views': {'$sum': '$count'}}}], maxTimeMS=5000))
        return {'views': rows[0]['views'] if rows else 0,
                'counted': result.modified_count == 1, 'pending': False}
    except PyMongoError as error:
        from .post_commit import log_deferred
        log_deferred('view-count', error)
        return {'views': None, 'counted': result.modified_count == 1, 'pending': True}

def statistics(ids, uid, now):
    stats = {tid: dict(liked=False, likes=0, downloads=0, views=0, recentLikes=0,
                      recentDownloads=0, rankScore=0, totalRankScore=0) for tid in ids}
    cutoff = now - 7 * 86400
    first_downloads = {}
    for r in db().activity_state.find({'tool': {'$in': ids}}):
        s = stats[r['tool']]
        created = r.get('firstLikedAt', r.get('created', 0)) if r['kind'] == 'like' else r.get('created', 0)
        recent = cutoff <= created <= now
        if r['kind'] == 'like' and r.get('liked'):
            s['likes'] += 1
            if recent: s['recentLikes'] += 1
            if r['user'] == uid: s['liked'] = True
        elif r['kind'] == 'download' and r.get('count', 0):
            first = r.get('firstDownloadedAt', r.get('created', 0))
            if first is not None:
                key = (r['tool'], r['user'])
                first_downloads[key] = min(first_downloads.get(key, first), first)
        elif r['kind'] == 'view':
            s['views'] += max(0, r.get('count', 0))
    for (tid, user), first in first_downloads.items():
        stats[tid]['downloads'] += 1
        if cutoff <= first <= now: stats[tid]['recentDownloads'] += 1
    for s in stats.values():
        s['rankScore'] = 2 * s['recentLikes'] + s['recentDownloads']
        s['totalRankScore'] = 2 * s['likes'] + s['downloads']
    return stats

def history(before=None):
    from .post_commit import followup_pending
    followup_pending('activity-history', flush, None, None, 50)
    query = {}
    if before:
        # Cursor is the last event ID; pair timestamp with ID to preserve ties.
        last = db().activity.find_one({'_id': before})
        if last: query = {'$or': [{'created': {'$lt': last['created']}}, {'created': last['created'], '_id': {'$lt': last['_id']}}]}
    rows = list(db().activity.find(query).sort([('created', -1), ('_id', -1)]).limit(51))
    more = len(rows) > 50; rows = rows[:50]
    for r in rows: r['id'] = str(r['_id']); r.pop('_id')
    return rows, rows[-1]['id'] if more else None
