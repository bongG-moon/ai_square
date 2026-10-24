"""Administrator-published Workspace installers; metadata in Mongo, bytes on disk."""
import json
import re
import time
import uuid

from flask import Blueprint, current_app, g, jsonify, request, send_file, url_for
from pymongo.errors import PyMongoError
from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from .artifacts import artifact_path, stage_upload
from .post_commit import followup_pending
from .storage import audit_event, db, deliver_notifications


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


def _metadata():
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
    return dict(name=_text(raw, 'name', 100),
                description=_text(raw, 'description', 2000, required=False),
                category=category, version=_text(raw, 'version', 40))


def _public(row):
    # A saved response never needs a second database read or reveals a server path.
    return dict(id=row['_id'], name=row['name'], description=row['description'],
                category=row['category'], version=row['version'],
                fileName=row['fileName'], size=row['size'], sha256=row['sha256'],
                created=row['created'], author=row['author'],
                downloadUrl=url_for('ax_workspace.download', file_id=row['_id']))


@ax_workspace.get('/api/ax-workspace')
def catalog():
    # Authentication/CSRF are the same app-wide session rules as other web APIs.
    # These endpoints are deliberately absent from the personal KEY allowlist.
    rows = db().workspace_files.find({}, {'path': 0, 'outbox': 0}).sort(
        [('created', -1), ('_id', -1)])
    # Reserve room for multipart boundaries and metadata inside the request cap.
    maximum = max(0, int(current_app.config['MAX_CONTENT_LENGTH']) - 65536)
    return jsonify(files=[_public(row) for row in rows],
                   canManage=g.user['role'] == 'admin', maxFileBytes=maximum)


@ax_workspace.post('/api/ax-workspace')
def publish():
    if g.user['role'] != 'admin':
        raise Forbidden('관리자만 AX Workspace 파일을 등록할 수 있습니다.')
    metadata = _metadata()
    uploads = request.files.getlist('file')
    if len(uploads) != 1 or any(key != 'file' for key in request.files):
        raise BadRequest('등록할 파일을 하나 선택해 주세요.')
    artifact = stage_upload(uploads[0])
    file_id = uuid.uuid4().hex
    row = dict(_id=file_id, **metadata, path=artifact['path'],
               fileName=artifact['name'], size=artifact['size'], sha256=artifact['sha'],
               created=time.time(), author=g.user['name'], owner=g.user['id'],
               outbox=[audit_event('AX Workspace 파일 등록: ' + metadata['name'])])
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


@ax_workspace.get('/api/ax-workspace/<file_id>/download')
def download(file_id):
    if not re.fullmatch(r'[0-9a-f]{32}', file_id):
        raise NotFound('등록된 파일을 찾을 수 없습니다.')
    row = db().workspace_files.find_one({'_id': file_id})
    if row is None:
        raise NotFound('등록된 파일을 찾을 수 없습니다.')
    path = artifact_path(row['path'])
    if not path.is_file():
        raise NotFound('서버에서 파일을 찾을 수 없습니다. 관리자에게 알려주세요.')
    # Dedicated downloads do not affect tool/contributor ranking or activity.
    response = send_file(path, as_attachment=True, download_name=row['fileName'],
                         mimetype='application/octet-stream', max_age=0)
    response.headers['Cache-Control'] = 'private, no-store'
    return response
