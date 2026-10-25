"""Personal API credentials: catalog use and confirmed, owner-only publishing."""
import hashlib
import math
import re
import secrets
import time
from flask import Blueprint, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import BadRequest, Conflict, Forbidden, Unauthorized
from .storage import db, public_user, audit_event, deliver_notifications
from .post_commit import followup_pending
from .package_identity import fixed_package_id, identity_fields

local_access = Blueprint('local_access', __name__)
READ_ENDPOINTS = {
    'local_access.search', 'api.details', 'api.manifest', 'api.version_check',
    'api.deployment_info', 'api.download', 'local_access.options', 'local_access.publish_targets',
    'local_access.integration_me', 'publish_drafts.details',
}


def effective_connection_scope(row):
    """One personal KEY supports publishing; known legacy scopes need no rotation.

    Missing scopes were historically read-only keys. Keep that legacy format,
    but never interpret an unknown or malformed explicit scope as a permission.
    Stored rows remain intact for audit and existing KEY attribution.
    """
    scope = row.get('scope', 'read')
    return 'publish' if isinstance(scope, str) and scope in {'read', 'publish'} else None


def expiry_status(row, now=None):
    """Only explicit BSON null means no expiry; legacy timestamps still apply."""
    if 'expires' not in row:
        return 'invalid'
    expires = row['expires']
    if expires is None:
        return 'active'
    if isinstance(expires, bool) or not isinstance(expires, (int, float)) or not math.isfinite(expires):
        return 'invalid'
    return 'active' if expires > (time.time() if now is None else now) else 'expired'


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
        now = time.time()
        # Explicit scalar validation avoids Mongo's null/missing equivalence and
        # array matching. Malformed recent records must not hide a valid legacy key.
        candidates = db().local_tokens.find({'user': uid, 'revoked': False}).sort([('created', -1), ('id', -1)])
        candidate = next((row for row in candidates if expiry_status(row, now) == 'active'
                          and effective_connection_scope(row)), None)
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
    row = db().local_tokens.find_one({'_id': digest, 'revoked': False})
    if row and (expiry_status(row) != 'active' or not effective_connection_scope(row)):
        row = None
    user = db().users.find_one({'_id': row['user']}) if row else None
    if (not user or not user.get('enabled', True)
            or current_connection_key(row['user']) != row['id']):
        raise Unauthorized('인증키가 만료·취소되었거나 사용자가 비활성 상태입니다.')
    read = request.method in {'GET', 'HEAD'} and request.endpoint in READ_ENDPOINTS
    scope = effective_connection_scope(row)
    publish = (scope == 'publish' and request.method == 'POST'
               and request.endpoint in {'api.publish', 'api.inspect_package', 'publish_drafts.create', 'publish_drafts.commit'})
    # Desired-state PUT reuses the web's idempotent per-employee like accounting.
    # Explicit detail views use the same bounded employee/tool counter. No
    # other browser mutation is made available to a personal connection KEY.
    like = request.method == 'PUT' and request.endpoint == 'api.like'
    view = request.method == 'POST' and request.endpoint == 'api.record_view'
    if not (read or publish or like or view):
        raise Forbidden('이 인증키에 허용되지 않은 작업입니다.')
    g.api_token_id = row['id']
    g.api_token_scope = scope
    return public_user(user)


@local_access.get('/local-access')
def page():
    return render_template('local_access.html')


@local_access.get('/static/guides/pt-square-mcp.zip')
@local_access.get('/local-access/mcp.zip')
def mcp_download():
    # This exact legacy static URL must also pass the normal browser auth guard.
    # Personal KEY callers are not added to the API allowlist above.
    from .mcp_package import download_package
    return download_package()


@local_access.get('/static/guides/ax-workspace-extension-setup.exe')
@local_access.get('/local-access/workspace-extension.zip')
def workspace_extension_download():
    # Old bookmarks now lead to administrator-published Workspace files. Keep
    # the browser auth guard on both URLs; never serve an obsolete bundled EXE.
    response = redirect(url_for('index', view='ax'))
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Cookie'
    return response


@local_access.get('/api/local-tokens')
def tokens():
    from . import activity
    uid = g.user['id']
    history_pending = followup_pending(
        'key-activity', lambda: activity.flush(user_id=uid, limit=50))
    followups_pending = followup_pending('key-maintenance', deliver_notifications, 'users', uid)
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
        expiration = expiry_status(row)
        scope = effective_connection_scope(row)
        row.update(scope=scope,
                   status=('replaced' if row.get('replacedBy') else 'revoked' if row.get('revoked')
                           else 'invalid' if scope is None
                           else expiration if expiration != 'active'
                           else 'active' if row['id'] == current_id else 'replaced'),
                   uploads=upload_counts.get(row['id'], 0), downloads=download_counts.get(row['id'], 0))
        if expiration == 'invalid':
            # Do not emit non-JSON values such as NaN; status still requires reissue.
            row['expires'] = None
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
                   usage=dict(uploads=sum(upload_counts.values()), downloads=sum(download_counts.values())), history=history,
                   historyPending=history_pending, followupsPending=followups_pending)


@local_access.post('/api/local-tokens')
def issue():
    raw = request.get_json(silent=True)
    if not isinstance(raw, dict):
        raise BadRequest('KEY 이름을 확인하세요.')
    if 'days' in raw:
        raise BadRequest('KEY는 유효기간 없이 발급됩니다. 화면을 새로고침하고 유효기간 항목 없이 다시 발급하세요.')
    name = raw.get('name', '내 연결 KEY')
    requested_scope = raw.get('scope', 'publish')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60:
        raise BadRequest('KEY 이름은 1~60자입니다.')
    if not isinstance(requested_scope, str) or requested_scope not in {'read', 'publish'}:
        raise BadRequest('개인 KEY 요청 형식이 올바르지 않습니다. 화면을 새로고침하고 다시 발급하세요.')
    # Cached clients may still submit the old read option. Every new personal
    # KEY now has the same owner-bound API capabilities, including draft upload.
    scope = 'publish'
    previous_id = current_connection_key(g.user['id'])
    token = 'ptsq_' + secrets.token_urlsafe(32)
    now = time.time()
    row = dict(_id=hashlib.sha256(token.encode()).hexdigest(), id=secrets.token_hex(16),
               user=g.user['id'], name=name.strip(), created=now, expires=None, revoked=False, scope=scope)
    db().local_tokens.insert_one(row)
    # The pointer and follow-up event share one atomic cutover. Compare the
    # previous pointer so a simultaneous rotation cannot annotate the wrong key.
    # A failed write is never blindly replayed; only an acknowledged CAS miss is.
    for _ in range(5):
        event = audit_event('개인 연결 KEY 발급·교체: 조회·다운로드·좋아요·본인 도구 등록 및 업데이트')
        if previous_id:
            event['tokenUpdate'] = {'user': row['user'], 'id': previous_id,
                                    'fields': {'revoked': True, 'revokedAt': now, 'replacedBy': row['id']}}
        previous = db().users.find_one_and_update(
            {'_id': row['user'], 'enabled': {'$ne': False}, 'activeConnectionKeyId': previous_id},
            {'$set': {'activeConnectionKeyId': row['id'], 'connectionKeyUpdatedAt': now},
             '$push': {'outbox': event}})
        if previous is not None:
            break
        current = db().users.find_one({'_id': row['user']}, {'enabled': 1, 'activeConnectionKeyId': 1})
        if not current or not current.get('enabled', True):
            raise Unauthorized('현재 사용자 상태를 확인하세요.')
        previous_id = current.get('activeConnectionKeyId')
    else:
        raise Conflict('다른 화면에서 KEY가 다시 발급되었습니다. 현재 화면을 새로고침하세요.')
    pending = followup_pending('key-maintenance', deliver_notifications, 'users', row['user'])
    # Do not turn a confirmed cutover into failure because a later read failed.
    # A subsequent concurrent rotation may naturally supersede this issued key.
    return jsonify(token=token, id=row['id'], expires=row['expires'], scope=scope,
                   replaced=bool(previous_id), followupsPending=pending), 201


@local_access.delete('/api/local-tokens/<token_id>')
def revoke(token_id):
    uid = g.user['id']
    current_connection_key(uid)
    now = time.time()
    event = audit_event('개인 API 인증키 취소')
    event['tokenUpdate'] = {'user': uid, 'id': token_id, 'fields': {'revoked': True, 'revokedAt': now}}
    # CAS preserves a newer key if revoke races with reissue.
    result = db().users.update_one({'_id': uid, 'activeConnectionKeyId': token_id},
                                  {'$set': {'activeConnectionKeyId': None, 'connectionKeyUpdatedAt': now},
                                   '$push': {'outbox': event}})
    if not result.matched_count:
        # Cancelling an older key still records the request atomically without
        # disturbing a newer pointer. New issue IDs are never reused.
        result = db().users.update_one({'_id': uid, 'activeConnectionKeyId': {'$ne': token_id}},
                                      {'$push': {'outbox': event}})
        if not result.matched_count:
            raise Conflict('KEY 상태가 변경되었습니다. 현재 화면을 새로고침하세요.')
    pending = followup_pending('key-maintenance', deliver_notifications, 'users', uid)
    return jsonify(ok=True, followupsPending=pending)


@local_access.get('/api/catalog/options')
def options():
    rows = list(db().taxonomy.find({'enabled': True}, {'_id': 1, 'kind': 1, 'name': 1}).sort('order', 1))
    return jsonify(employee=dict(id=g.user['id'], name=g.user['name']),
                   organizations=[dict(id=r['_id'], name=r['name']) for r in rows if r['kind'] == 'organization'],
                   categories=[dict(id=r['_id'], name=r['name']) for r in rows if r['kind'] == 'category'])


@local_access.get('/api/publish-targets')
def publish_targets():
    package_id = request.args.get('packageId', '')
    q = request.args.get('q', '').strip()
    if package_id and not re.fullmatch(r'[a-z][a-z0-9.-]{2,79}', package_id):
        raise BadRequest('packageId를 확인하세요.')
    if len(q) > 200:
        raise BadRequest('검색어는 200자 이내로 입력하세요.')
    query = {'deleted': {'$ne': True}, 'purge': {'$exists': False}, 'owner': g.user['id']}
    if package_id:
        # A declared identity is stronger than a human-readable name, which can
        # change between releases. Only fall back to similarity without an ID.
        # MongoDB 5-compatible candidate lookup. Historic source IDs are only a
        # legacy read aid, never aliases of the stable platform identity.
        query['$or'] = [{'packageId': package_id}, {'versions.package.packageId': package_id}]
    elif q:
        query['$or'] = [{'data.' + key: {'$regex': re.escape(q), '$options': 'i'}}
                        for key in ('name', 'desc', 'workTags')]
    rows = db().tools.find(query).sort('_id', -1)
    items = []
    for t in rows:
        if package_id and fixed_package_id(t) != package_id:
            continue
        current = next((v for v in t.get('versions', []) if v['n'] == t['active']), None)
        items.append(dict(id=t['_id'], name=t['data']['name'], revision=t['revision'],
                          **identity_fields(t, current.get('package') if current else None)))
        if len(items) == 20:
            break
    return jsonify(items=items)


@local_access.get('/api/catalog')
def search():
    from .catalog_search import search_catalog
    return search_catalog()


@local_access.get('/api/integration/me')
def integration_me():
    key_id = getattr(g, 'api_token_id', None)
    scope = getattr(g, 'api_token_scope', None)
    return jsonify(user=dict(id=g.user['id'], name=g.user['name'],
                             dept=g.user.get('dept', g.user.get('org', '')),
                             dept_cd=g.user.get('dept_cd', ''), role=g.user['role']),
                   key=dict(id=key_id, scope=scope) if key_id else None,
                   capabilities=dict(search=True, download=True, like=True, view=True,
                                     publishDraft=bool(key_id and scope == 'publish'),
                                     approvalRequired=True))
