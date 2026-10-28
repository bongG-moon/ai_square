"""Sharing credit, including a minimal durable record for removed tools.

Tool popularity still uses live tools. Sharing credit uses current reactions
until permanent deletion, then keeps its acknowledged snapshot in the existing
deletion job. No download identities, file paths or tool contents are retained.
"""
import time

from .storage import db

WEIGHTS = dict(registered=5, likes=2, downloads=1)


def activity_totals_pipeline():
    # Legacy daily download rows collapse to one employee/tool. An explicit
    # null firstDownloadedAt is update-only and must not fall back to created.
    first = {'$cond': [
        {'$eq': [{'$type': '$firstDownloadedAt'}, 'missing']}, '$created', '$firstDownloadedAt',
    ]}
    return [
        {'$group': {'_id': {'user': '$user', 'kind': '$kind'},
            'liked': {'$max': {'$cond': [{'$and': [
                {'$eq': ['$kind', 'like']}, {'$eq': ['$liked', True]},
            ]}, 1, 0]}},
            'downloaded': {'$max': {'$cond': [{'$and': [
                {'$eq': ['$kind', 'download']}, {'$gt': [{'$ifNull': ['$count', 0]}, 0]},
                {'$ne': [{'$ifNull': [first, None]}, None]},
            ]}, 1, 0]}},
        }},
        {'$group': {'_id': None, 'likes': {'$sum': '$liked'}, 'downloads': {'$sum': '$downloaded'}}},
    ]


def snapshot_tool(tool, retained_at=None):
    """Read before destructive cleanup; a read error must abort that cleanup."""
    existing = tool.get('purge', {}).get('contribution')
    if existing:
        return existing
    rows = list(db().activity_state.aggregate([
        {'$match': {'tool': tool['_id'], 'user': {'$ne': tool['owner']},
                    'kind': {'$in': ['like', 'download']}}},
        *activity_totals_pipeline(),
    ]))
    totals = rows[0] if rows else {}
    likes, downloads = totals.get('likes', 0), totals.get('downloads', 0)
    return dict(schemaVersion=1, tool=tool['_id'], owner=tool['owner'],
                name=tool.get('data', {}).get('name') or f'도구 #{tool["_id"]}',
                created=tool.get('created'), retainedAt=retained_at or time.time(),
                registered=1, likes=likes, downloads=downloads,
                score=5 + likes * 2 + downloads)


def item_pipeline(owner=None):
    """One row per numeric tool ID, shared by personal detail and ranking.

Both a locked source and its durable job can exist during cleanup. Dedupe by
tool ID after the union so a concurrent deletion never adds credit twice.
"""
    tool_match = {'owner': owner} if owner is not None else {}
    job_match = {'kind': 'tool', 'contribution.schemaVersion': 1}
    if owner is not None:
        job_match['contribution.owner'] = owner
    return [
        {'$match': tool_match},
        {'$lookup': {'from': 'activity_state', 'let': {'toolId': '$_id', 'creatorId': '$owner'}, 'pipeline': [
            {'$match': {'$expr': {'$and': [
                {'$eq': ['$tool', '$$toolId']}, {'$ne': ['$user', '$$creatorId']},
                {'$in': ['$kind', ['like', 'download']]},
            ]}}},
            *activity_totals_pipeline(),
        ], 'as': 'activity'}},
        {'$project': {
            '_id': 1, 'owner': 1,
            'name': {'$ifNull': ['$purge.contribution.name', {'$ifNull': ['$data.name', {'$concat': ['도구 #', {'$toString': '$_id'}]}]}]},
            'created': {'$ifNull': ['$created', None]},
            'retainedAt': {'$ifNull': ['$purge.contribution.retainedAt', None]},
            'status': {'$cond': [{'$ne': [{'$ifNull': ['$purge', None]}, None]}, 'deleted', {'$cond': ['$deleted', 'trash', 'active']}]},
            'registered': {'$literal': 1},
            'likes': {'$ifNull': ['$purge.contribution.likes', {'$ifNull': [{'$arrayElemAt': ['$activity.likes', 0]}, 0]}]},
            'downloads': {'$ifNull': ['$purge.contribution.downloads', {'$ifNull': [{'$arrayElemAt': ['$activity.downloads', 0]}, 0]}]},
            '_retained': {'$literal': 0},
        }},
        {'$unionWith': {'coll': 'deletion_jobs', 'pipeline': [
            {'$match': job_match},
            {'$project': {
                '_id': '$entityId', 'owner': '$contribution.owner', 'name': '$contribution.name',
                'created': '$contribution.created', 'retainedAt': '$contribution.retainedAt',
                'status': {'$literal': 'deleted'}, 'registered': {'$literal': 1},
                'likes': '$contribution.likes', 'downloads': '$contribution.downloads',
                '_retained': {'$literal': 1},
            }},
        ]}},
        {'$sort': {'_id': 1, '_retained': -1}},
        {'$group': {'_id': '$_id', 'item': {'$first': '$$ROOT'}}},
        {'$replaceRoot': {'newRoot': '$item'}},
        {'$unset': '_retained'},
        {'$set': {'score': {'$add': [5, {'$multiply': ['$likes', 2]}, '$downloads']}}},
    ]


def ranking_pipeline():
    return [
        *item_pipeline(),
        {'$group': {'_id': '$owner', 'registered': {'$sum': '$registered'},
                    'likes': {'$sum': '$likes'}, 'downloads': {'$sum': '$downloads'},
                    'score': {'$sum': '$score'}}},
        {'$lookup': {'from': 'users', 'localField': '_id', 'foreignField': '_id', 'as': 'creator'}},
        {'$unwind': '$creator'},
        {'$match': {'creator.enabled': {'$ne': False}}},
        {'$lookup': {'from': 'taxonomy', 'localField': 'creator.orgId', 'foreignField': '_id', 'as': 'organization'}},
        {'$set': {'name': '$creator.name',
                  'org': {'$ifNull': ['$creator.dept', {'$ifNull': [{'$arrayElemAt': ['$organization.name', 0]}, '공통']}]}}},
        {'$sort': {'score': -1, 'registered': -1, 'likes': -1, 'downloads': -1, '_id': 1}},
        {'$project': {'creator': 0, 'organization': 0}},
    ]


def personal_details(owner, page, page_size):
    result = next(db().tools.aggregate([
        *item_pipeline(owner),
        {'$facet': {
            'totals': [{'$group': {'_id': None, 'registered': {'$sum': '$registered'},
                                  'likes': {'$sum': '$likes'}, 'downloads': {'$sum': '$downloads'},
                                  'score': {'$sum': '$score'}}}],
            'items': [{'$sort': {'score': -1, '_id': 1}}, {'$skip': (page - 1) * page_size},
                      {'$limit': page_size}, {'$project': {'owner': 0}}],
        }},
    ], allowDiskUse=True))
    summary = result['totals'][0] if result['totals'] else dict(registered=0, likes=0, downloads=0, score=0)
    summary.pop('_id', None)
    for item in result['items']:
        item['id'] = item.pop('_id')
    total = summary['registered']
    return dict(summary=summary, items=result['items'], totalItems=total, page=page,
                pageSize=page_size, totalPages=(total + page_size - 1) // page_size,
                weights=WEIGHTS, asOf=time.time())
