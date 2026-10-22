"""Employee-bound API credentials with explicit read/publish permissions."""
import hashlib
import re
import secrets
import time
from flask import Blueprint, g, jsonify, render_template, request, session
from werkzeug.exceptions import BadRequest, Conflict, Forbidden, Unauthorized
from .storage import db, public_user, audit

local_access = Blueprint('local_access', __name__)
READ_ENDPOINTS = {
    'local_access.search', 'api.details', 'api.manifest', 'api.version_check',
    'api.deployment_info', 'api.download', 'local_access.options', 'local_access.publish_targets',
}


def current_connection_key(uid):
    """Resolve one authoritative key per employee, including pre-upgrade keys.

    The user document is the atomic authority. Historical token rows remain for
    usage attribution but can never authorize unless this pointer matches.
    A missing pointer migrates once to the latest valid legacy key using CAS.
    An explicit null pointer means revoked/no key and must never revive history.
    """
    user = db().users.find_one({'_id': uid})
    if not user:
        return None
    if 'activeConnectionKeyId' not in user:
        candidate = db().local_tokens.find_one(
            {'user': uid, 'revoked': False, 'expires': {'$gt': time.time()}},
            sort=[('created', -1), ('id', -1)])
        db().users.update_one({'_id': uid, 'activeConnectionKeyId': {'$exists': False}},
                              {'$set': {'activeConnectionKeyId': candidate['id'] if candidate else None,
                                        'connectionKeyUpdatedAt': time.time()}})
        user = db().users.find_one({'_id': uid})
    return user.get('activeConnectionKeyId') if user else None


def token_user():
    """Never fall back to cookies/mock identity when a bearer header is supplied."""
    value = request.headers.get('Authorization', '')
    if not re.fullmatch(r'Bearer ptsq_[A-Za-z0-9_-]{43}', value):
        raise Unauthorized('API 인증키가 올바르지 않습니다.')
    digest = hashlib.sha256(value[7:].encode()).hexdigest()
    row = db().local_tokens.find_one({'_id': digest, 'revoked': False, 'expires': {'$gt': time.time()}})
    user = db().users.find_one({'_id': row['user']}) if row else None
    if (not user or not user.get('enabled', True)
            or current_connection_key(row['user']) != row['id']):
        raise Unauthorized('인증키가 만료·취소되었거나 사용자가 비활성 상태입니다.')
    read = request.method in {'GET', 'HEAD'} and request.endpoint in READ_ENDPOINTS
    publish = (row.get('scope', 'read') == 'publish' and request.method == 'POST'
               and request.endpoint in {'api.publish', 'api.inspect_package'})
    if not (read or publish):
        raise Forbidden('이 인증키에 허용되지 않은 작업입니다.')
    g.api_token_id = row['id']
    return public_user(user)


@local_access.get('/local-access')
def page():
    return render_template('local_access.html')


@local_access.get('/api/local-tokens')
def tokens():
    from . import activity
    activity.flush()
    uid = g.user['id']
    current_id = current_connection_key(uid)
    rows = list(db().local_tokens.find({'user': uid}, {'_id': 0, 'id': 1, 'name': 1, 'created': 1, 'expires': 1, 'revoked': 1, 'scope': 1, 'replacedBy': 1}).sort('created', -1))
    # Upload provenance is committed atomically with the release. Download
    # provenance uses the existing durable activity outbox, so retries of flush
    # cannot inflate counts.
    upload_match = {'versions.apiUsage.user': uid}
    groups = list(db().tools.aggregate([
        {'$match': upload_match}, {'$unwind': '$versions'}, {'$match': upload_match},
        {'$group': {'_id': '$versions.apiUsage.tokenId', 'count': {'$sum': 1}}},
    ]))
    downloads = list(db().activity.aggregate([
        {'$match': {'user': uid, 'kind': 'download', 'counted': True}},
        {'$sort': {'created': 1, '_id': 1}},
        {'$group': {'_id': '$tool', 'tokenId': {'$first': '$tokenId'}}},
        {'$match': {'tokenId': {'$ne': None}}},
        {'$group': {'_id': '$tokenId', 'count': {'$sum': 1}}},
    ]))
    upload_counts = {x['_id']: x['count'] for x in groups}
    download_counts = {x['_id']: x['count'] for x in downloads}
    for row in rows:
        row.update(scope=row.get('scope', 'read'),
                   status=('replaced' if row.get('replacedBy') else 'revoked' if row.get('revoked')
                           else 'expired' if row['expires'] <= time.time() else 'active' if row['id'] == current_id else 'replaced'),
                   uploads=upload_counts.get(row['id'], 0), downloads=download_counts.get(row['id'], 0))
        row.pop('replacedBy', None)
    uploads = list(db().tools.aggregate([
        {'$match': upload_match}, {'$unwind': '$versions'}, {'$match': upload_match},
        {'$sort': {'versions.created': -1}}, {'$limit': 20},
        {'$project': {'_id': 0, 'tool': '$_id', 'version': '$versions.n', 'created': '$versions.created',
                      'tokenId': '$versions.apiUsage.tokenId', 'action': {'$literal': 'upload'}}},
    ]))
    recent = list(db().activity.find({'user': uid, 'kind': 'download', 'tokenId': {'$exists': True}},
                  {'_id': 0, 'tool': 1, 'version': 1, 'created': 1, 'tokenId': 1, 'counted': 1, 'purpose': 1}).sort('created', -1).limit(20))
    for row in recent:
        row['action'] = 'download'
    history = sorted(uploads + recent, key=lambda x: x['created'], reverse=True)[:20]
    return jsonify(tokens=rows, currentKeyId=current_id,
                   connectionKey=next((r for r in rows if r['id'] == current_id), None),
                   csrf=session['csrf'], employee=dict(id=uid, name=g.user['name']),
                   usage=dict(uploads=sum(upload_counts.values()), downloads=sum(download_counts.values())), history=history)


@local_access.post('/api/local-tokens')
def issue():
    raw = request.get_json(silent=True)
    if not isinstance(raw, dict):
        raise BadRequest('이름과 유효기간을 확인하세요.')
    name = raw.get('name', '내 연결 KEY')
    days = raw.get('days', 7)
    scope = raw.get('scope', 'read')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or type(days) is not int or days not in {1, 7, 30}:
        raise BadRequest('이름은 1~60자, 유효기간은 1·7·30일입니다.')
    if not isinstance(scope, str) or scope not in {'read', 'publish'}:
        raise BadRequest('조회·다운로드 또는 업로드 포함 권한을 선택하세요.')
    current_connection_key(g.user['id'])
    token = 'ptsq_' + secrets.token_urlsafe(32)
    now = time.time()
    row = dict(_id=hashlib.sha256(token.encode()).hexdigest(), id=secrets.token_hex(16),
               user=g.user['id'], name=name.strip(), created=now, expires=now + days * 86400, revoked=False, scope=scope)
    db().local_tokens.insert_one(row)
    # A single document update is the cutover point. Never revoke all other rows
    # here: a concurrent reissue may already have created the next valid key.
    previous = db().users.find_one_and_update(
        {'_id': row['user'], 'enabled': {'$ne': False}},
        {'$set': {'activeConnectionKeyId': row['id'], 'connectionKeyUpdatedAt': now}})
    if not previous:
        db().local_tokens.update_one({'_id': row['_id']}, {'$set': {'revoked': True}})
        raise Unauthorized('현재 사용자 상태를 확인하세요.')
    previous_id = previous.get('activeConnectionKeyId')
    if previous_id:
        db().local_tokens.update_one({'user': row['user'], 'id': previous_id},
                                    {'$set': {'revoked': True, 'revokedAt': now, 'replacedBy': row['id']}})
    audit('개인 연결 KEY 발급·교체: ' + ('업로드 포함' if scope == 'publish' else '조회·다운로드'))
    if current_connection_key(row['user']) != row['id']:
        raise Conflict('다른 화면에서 KEY가 다시 발급되었습니다. 현재 화면을 새로고침하세요.')
    return jsonify(token=token, id=row['id'], expires=row['expires'], scope=scope,
                   replaced=bool(previous_id)), 201


@local_access.delete('/api/local-tokens/<token_id>')
def revoke(token_id):
    uid = g.user['id']
    current_connection_key(uid)
    # CAS preserves a newer key if revoke races with reissue.
    db().users.update_one({'_id': uid, 'activeConnectionKeyId': token_id},
                          {'$set': {'activeConnectionKeyId': None, 'connectionKeyUpdatedAt': time.time()}})
    db().local_tokens.update_one({'id': token_id, 'user': uid}, {'$set': {'revoked': True, 'revokedAt': time.time()}})
    audit('개인 API 인증키 취소')
    return jsonify(ok=True)


@local_access.get('/api/catalog/options')
def options():
    rows = list(db().taxonomy.find({'enabled': True}, {'_id': 1, 'kind': 1, 'name': 1}).sort('order', 1))
    return jsonify(employee=dict(id=g.user['id'], name=g.user['name']),
                   organizations=[dict(id=r['_id'], name=r['name']) for r in rows if r['kind'] == 'organization'],
                   categories=[dict(id=r['_id'], name=r['name']) for r in rows if r['kind'] == 'category'])


@local_access.get('/api/publish-targets')
def publish_targets():
    from .mongo_api import manager
    package_id = request.args.get('packageId', '')
    if not re.fullmatch(r'[a-z][a-z0-9.-]{2,79}', package_id):
        raise BadRequest('packageId를 확인하세요.')
    rows = db().tools.find({'deleted': {'$ne': True}, 'versions.package.packageId': package_id})
    return jsonify(items=[dict(id=t['_id'], name=t['data']['name'], revision=t['revision'])
                          for t in rows if manager(t)])


@local_access.get('/api/catalog')
def search():
    from .mongo_api import allowed, resolved, TYPE_ALIASES
    q = request.args.get('q', '').strip()
    kind = request.args.get('type', '')
    if len(q) > 200:
        raise BadRequest('검색어는 200자 이내로 입력하세요.')
    try:
        limit = int(request.args.get('limit', '20'))
        offset = int(request.args.get('offset', '0'))
    except ValueError:
        raise BadRequest('limit와 offset은 정수입니다.')
    if not 1 <= limit <= 100 or not 0 <= offset <= 100000:
        raise BadRequest('limit는 1~100, offset은 0~100000입니다.')
    query = {'deleted': {'$ne': True}}
    if q:
        query['$or'] = [{'data.' + key: {'$regex': re.escape(q), '$options': 'i'}} for key in ['name', 'desc', 'workTags', 'category']]
    if kind:
        kind = TYPE_ALIASES.get(kind, kind)
        if kind not in {'MCP/Tool', 'Skill', '플러그인/하네스'}:
            raise BadRequest('도구 유형을 확인하세요.')
        query['data.type'] = {'$in': [kind] + [k for k, v in TYPE_ALIASES.items() if v == kind]}
    if request.args.get('orgId'):
        query['data.orgId'] = request.args['orgId']
    rows = list(db().tools.find(query).sort('_id', 1).skip(offset).limit(limit + 1))
    items = []
    for row in rows[:limit]:
        data = resolved(row)
        items.append(dict(id=row['_id'], **{k: data[k] for k in ['name', 'desc', 'type', 'platform', 'org', 'orgId', 'category', 'workTags']},
                          access='approved' if allowed(row) else 'permission_required'))
    return jsonify(items=items, total=db().tools.count_documents(query),
                   nextOffset=offset + limit if len(rows) > limit else None)
