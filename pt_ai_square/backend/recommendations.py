"""Administrator recommendations attach to one reviewed release, not an owner claim."""


def is_active(tool):
    record = tool.get('recommendationBadge') or {}
    version = record.get('reviewedVersion')
    return bool(record.get('enabled') is True and type(version) is int and version > 0
                and version == tool.get('active') and not tool.get('deleted')
                and 'purge' not in tool
                and any(v.get('n') == version and not v.get('deleted') and not v.get('withdrawn')
                        for v in tool.get('versions', [])))


def public_badge(tool, *, readable=False, administrator=False):
    record = tool.get('recommendationBadge') or {}
    active = is_active(tool)
    pending = record.get('enabled') is True and not active and administrator
    disclosed = (active and readable) or pending
    result = dict(active=active, status='active' if active else 'needs_review' if pending else 'none',
                  reason=record.get('reason', '') if disclosed else '',
                  reviewedVersion=record.get('reviewedVersion') if disclosed else None,
                  updatedAt=record.get('updatedAt') if disclosed else None)
    if administrator and record:
        result['reviewedBy'] = record.get('reviewedBy', '')
    return result


def active_expression():
    """Mongo equivalent of is_active, used before candidate truncation."""
    reviewed = {'$ifNull': ['$recommendationBadge.reviewedVersion', 0]}
    return {'$and': [
        {'$eq': [{'$ifNull': ['$recommendationBadge.enabled', False]}, True]},
        {'$gt': [reviewed, 0]},
        {'$eq': [reviewed, {'$ifNull': ['$active', 0]}]},
        {'$ne': [{'$ifNull': ['$deleted', False]}, True]},
        {'$eq': [{'$type': '$purge'}, 'missing']},
        {'$gt': [{'$size': {'$filter': {
            'input': {'$ifNull': ['$versions', []]}, 'as': 'release',
            'cond': {'$and': [
                {'$eq': [{'$ifNull': ['$$release.n', 0]}, reviewed]},
                {'$ne': [{'$ifNull': ['$$release.deleted', False]}, True]},
                {'$ne': [{'$ifNull': ['$$release.withdrawn', False]}, True]},
            ]},
        }}}, 0]},
    ]}
