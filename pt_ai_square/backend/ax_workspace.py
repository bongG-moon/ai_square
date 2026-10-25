"""Administrator-published Workspace installers; metadata in Mongo, bytes on disk."""
import json
import re
import time
import uuid

from flask import Blueprint, current_app, g, jsonify, request, send_file, url_for
from pymongo.errors import DuplicateKeyError, PyMongoError
from werkzeug.exceptions import BadRequest, Conflict, Forbidden, NotFound

from .artifacts import artifact_path, stage_upload
from .post_commit import followup_pending
from .storage import audit_event, db, deliver_notifications, event


ax_workspace = Blueprint('ax_workspace', __name__)
CATEGORIES = {'workspace', 'plugin', 'integration', 'other'}


def _text(raw, field, maximum, *, required=True):
    value = raw.get(field, '')
    if not isinstance(value, str):
        raise BadRequest('파일 이름·설명·버전 정보를 확인해 주세요.')
    value = value.strip()
    if len(value) > maximum or (required and not value) or '\x00' in value:
        raise BadRequest(f'{field} 항목은 {"1~" if required else "최대 "}{maximum}자로 입력해 주세요.')
    return value


def _metadata(*, updating=False):
    text = request.form.get('metadata', '')
    if len(text) > 16000:
        raise BadRequest('등록 정보가 너무 깁니다.')
    try:
        raw = json.loads(text)
    except (TypeError, ValueError):
        raise BadRequest('등록 정보를 확인해 주세요.') from None
    if not isinstance(raw, dict):
        raise BadRequest('등록 정보를 확인해 주세요.')
    category = raw.get('category', 'workspace')
    if not isinstance(category, str) or category not in CATEGORIES:
        raise BadRequest('Workspace·플러그인·연동·기타 중 구분을 선택해 주세요.')
    metadata = dict(name=_text(raw, 'name', 100),
                    description=_text(raw, 'description', 2000, required=False),
                    category=category, version=_text(raw, 'version', 40))
    if updating:
        revision = raw.get('expectedRevision')
        if type(revision) is not int or revision < 1:
            raise BadRequest('현재 버전 정보를 확인한 뒤 다시 등록해 주세요.')
        metadata['expectedRevision'] = revision
    return metadata


def _public(row, *, subscribed=False):
    # A saved response never needs a second database read or reveals a server path.
    return dict(id=row['_id'], name=row['name'], description=row['description'],
                category=row['category'], version=row['version'],
                fileName=row['fileName'], size=row['size'], sha256=row['sha256'],
                created=row['created'], author=row['author'],
                updated=row.get('updated', row['created']),
                revision=row.get('revision', 1), release=row.get('release', 1),
                subscribed=subscribed,
                downloadUrl=url_for('ax_workspace.download', file_id=row['_id']))


def _file(file_id):
    if not re.fullmatch(r'[0-9a-f]{32}', file_id):
        raise NotFound('등록된 파일을 찾을 수 없습니다.')
    row = db().workspace_files.find_one({'_id': file_id})
    if row is None:
        raise NotFound('등록된 파일을 찾을 수 없습니다.')
    return row


def _upload():
    uploads = request.files.getlist('file')
    if len(uploads) != 1 or any(key != 'file' for key in request.files):
        raise BadRequest('등록할 파일을 하나 선택해 주세요.')
    return stage_upload(uploads[0])


def _version(row):
    """Retain the exact bytes and metadata of every committed release."""
    fields = ('name', 'description', 'category', 'version', 'path', 'fileName',
              'size', 'sha256', 'author', 'owner')
    return {**{field: row[field] for field in fields},
            'release': row.get('release', 1),
            'created': row.get('updated', row['created'])}


def _subscription_write(file_id, *, enabled=None):
    """None auto-follows only once; an explicit False must survive downloads."""
    key = file_id + ':' + g.user['id']
    identity = {'_id': key, 'file': file_id, 'user': g.user['id']}
    now = time.time()
    audit = audit_event('AX Workspace 업데이트 알림 ' +
                        ('자동 구독' if enabled is None else ('켜기' if enabled else '끄기')))
    if enabled is None:
        update = {'$setOnInsert': {'enabled': True, 'created': now,
                                   'updated': now, 'outbox': [audit]}}
    else:
        update = {'$set': {'enabled': enabled, 'updated': now},
                  '$setOnInsert': {'created': now}, '$push': {'outbox': audit}}
    try:
        db().workspace_subscriptions.update_one(identity, update, upsert=True)
    except DuplicateKeyError:
        # Two simultaneous first downloads/toggles can race on the unique key.
        # Reapply only to that exact existing identity, preserving explicit OFF.
        result = db().workspace_subscriptions.update_one(identity, update)
        if result.matched_count != 1:
            raise
    return followup_pending('ax-workspace-subscription', deliver_notifications,
                            'workspace_subscriptions', key)


@ax_workspace.get('/api/ax-workspace')
def catalog():
    # Authentication/CSRF are the same app-wide session rules as other web APIs.
    # These endpoints are deliberately absent from the personal KEY allowlist.
    rows = list(db().workspace_files.find({}, {'path': 0, 'outbox': 0, 'versions': 0}).sort(
        [('created', -1), ('_id', -1)]))
    subscribed = {row['file'] for row in db().workspace_subscriptions.find(
        {'user': g.user['id'], 'enabled': True, 'file': {'$in': [row['_id'] for row in rows]}},
        {'file': 1})}
    # Reserve room for multipart boundaries and metadata inside the request cap.
    maximum = max(0, int(current_app.config['MAX_CONTENT_LENGTH']) - 65536)
    return jsonify(files=[_public(row, subscribed=row['_id'] in subscribed) for row in rows],
                   canManage=g.user['role'] == 'admin', maxFileBytes=maximum)


@ax_workspace.post('/api/ax-workspace')
def publish():
    if g.user['role'] != 'admin':
        raise Forbidden('관리자만 AX Workspace 파일을 등록할 수 있습니다.')
    metadata = _metadata()
    artifact = _upload()
    file_id = uuid.uuid4().hex
    now = time.time()
    row = dict(_id=file_id, **metadata, path=artifact['path'],
               fileName=artifact['name'], size=artifact['size'], sha256=artifact['sha'],
               created=now, updated=now, revision=1, release=1,
               author=g.user['name'], owner=g.user['id'],
               outbox=[audit_event('AX Workspace 파일 등록: ' + metadata['name'])])
    row['versions'] = [_version(row)]
    try:
        db().workspace_files.insert_one(row)
    except PyMongoError:
        # The server may have committed before its acknowledgement was lost.
        # Keep bytes even if an immediate lookup cannot confirm that write.
        current_app.logger.warning('AX Workspace upload retained reason=database-write-outcome')
        raise
    pending = followup_pending('ax-workspace-audit', deliver_notifications,
                               'workspace_files', file_id)
    return jsonify(file=_public(row), followupsPending=pending), 201


@ax_workspace.post('/api/ax-workspace/<file_id>/versions')
def publish_version(file_id):
    if g.user['role'] != 'admin':
        raise Forbidden('관리자만 AX Workspace 새 버전을 등록할 수 있습니다.')
    metadata = _metadata(updating=True)
    expected = metadata.pop('expectedRevision')
    current = _file(file_id)
    if current.get('revision', 1) != expected:
        raise Conflict('다른 변경이 먼저 저장되었습니다. 목록을 새로고침해 주세요.')
    versions = list(current.get('versions') or [_version(current)])
    if any(version['version'] == metadata['version'] for version in versions):
        raise Conflict('이미 등록한 버전입니다. 새로운 버전 이름을 입력해 주세요.')
    # Resolve recipients before saving bytes; notifications remain independent
    # from the committed version and are rechecked at actual delivery time.
    subscribers = list(db().workspace_subscriptions.find({'file': file_id, 'enabled': True}))
    recipients = [row['_id'] for row in db().users.find(
        {'_id': {'$in': [row['user'] for row in subscribers]}, 'enabled': {'$ne': False}}, {'_id': 1})]
    subscribed = any(row['user'] == g.user['id'] for row in subscribers)
    artifact = _upload()
    row = {**current, **metadata, 'path': artifact['path'], 'fileName': artifact['name'],
           'size': artifact['size'], 'sha256': artifact['sha'], 'updated': time.time(),
           'author': g.user['name'], 'owner': g.user['id'], 'revision': expected + 1,
           'release': current.get('release', 1) + 1}
    row['versions'] = versions + [_version(row)]
    release_event = event(recipients, metadata['name'] + ' 새 버전 ' + metadata['version'],
                          {'type': 'workspace', 'id': file_id}, 'release')
    release_event['audit'] = audit_event('AX Workspace 새 버전 등록: ' + metadata['name'])['audit']
    query = {'_id': file_id, 'revision': expected}
    if expected == 1:
        query = {'_id': file_id, '$or': [{'revision': 1}, {'revision': {'$exists': False}}]}
    update = {key: value for key, value in row.items() if key not in {'_id', 'outbox'}}
    try:
        result = db().workspace_files.update_one(query, {'$set': update, '$push': {'outbox': release_event}})
    except PyMongoError:
        current_app.logger.warning('AX Workspace upload retained reason=database-write-outcome')
        raise
    if result.modified_count != 1:
        # A definite CAS miss did not reference these newly staged bytes.
        from .publish_drafts import remove_unreferenced
        followup_pending('ax-workspace-conflict-cleanup', remove_unreferenced, artifact)
        raise Conflict('다른 변경이 먼저 저장되었습니다. 목록을 새로고침해 주세요.')
    pending = followup_pending('ax-workspace-release', deliver_notifications, 'workspace_files', file_id)
    return jsonify(file=_public(row, subscribed=subscribed), followupsPending=pending), 201


@ax_workspace.put('/api/ax-workspace/<file_id>/subscription')
def subscription(file_id):
    _file(file_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or type(body.get('enabled')) is not bool:
        raise BadRequest('업데이트 알림을 켜거나 끄는 값을 확인해 주세요.')
    enabled = body['enabled']
    pending = _subscription_write(file_id, enabled=enabled)
    return jsonify(ok=True, subscribed=enabled, followupsPending=pending)


@ax_workspace.get('/api/ax-workspace/<file_id>/download')
def download(file_id):
    row = _file(file_id)
    path = artifact_path(row['path'])
    if not path.is_file():
        raise NotFound('서버에서 파일을 찾을 수 없습니다. 관리자에게 알려주세요.')
    # Dedicated downloads do not affect tool/contributor ranking or activity.
    response = send_file(path, as_attachment=True, download_name=row['fileName'],
                         mimetype='application/octet-stream', max_age=0)
    response.headers['Cache-Control'] = 'private, no-store'
    if request.method == 'GET' and response.status_code in {200, 206}:
        try:
            _subscription_write(file_id)
        except Exception:
            response.close()
            raise
    return response
