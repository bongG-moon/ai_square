"""Request attachment bytes live on disk; metadata lives with the MongoDB idea."""
import hashlib
import uuid
from pathlib import Path
from flask import current_app
from pymongo.errors import PyMongoError
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge
from .storage_capacity import save_upload
from .storage import db

MAX_FILE = 20 * 1024 * 1024
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.pdf', '.txt', '.csv', '.xlsx', '.docx', '.zip'}


def attachment_path(key):
    root = (Path(current_app.config['DATA_DIR']) / 'request_attachments').resolve()
    path = (root / key).resolve()
    if path.parent != root:
        raise BadRequest('첨부파일 경로를 확인하세요.')
    return path


def stage_attachments(files):
    if len(files) > 5:
        raise BadRequest('첨부파일은 최대 5개입니다.')
    saved = []
    try:
        for upload in files:
            name = (upload.filename or '').replace('\\', '/').split('/')[-1]
            ext = Path(name).suffix.lower()
            if not name or len(name) > 180 or any(ord(c) < 32 for c in name) or ext not in EXTENSIONS:
                raise BadRequest('첨부는 PNG, JPG, WEBP, PDF, TXT, CSV, XLSX, DOCX, ZIP만 가능합니다.')
            key = uuid.uuid4().hex + ext
            path = attachment_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            row = {'id': uuid.uuid4().hex, 'name': name, 'path': key, 'size': 0}
            saved.append(row)
            row['size'] = save_upload(upload, path, MAX_FILE)
            if not row['size']:
                raise BadRequest('빈 첨부파일은 등록할 수 없습니다.')
            with path.open('rb') as source:
                row['sha256'] = hashlib.file_digest(source,'sha256').hexdigest()
        return saved
    except Exception:
        for row in saved:
            try:
                attachment_path(row['path']).unlink(missing_ok=True)
            except OSError:
                # Cleanup must not replace the validation/storage error that
                # explains why this upload failed.
                current_app.logger.warning('Request attachment cleanup deferred reason=filesystem')
        raise


def cleanup_unreferenced_attachments(files):
    """Remove failed-request bytes only when Mongo confirms no idea refers to them.

    A write may have committed even if its response was lost. Failed lookups
    therefore preserve bytes, as do filesystem failures during cleanup.
    """
    for row in files:
        key = row.get('path')
        try:
            path = attachment_path(key)
        except (BadRequest, TypeError):
            current_app.logger.warning('Request attachment cleanup deferred reason=invalid-path')
            continue
        try:
            if db().ideas.find_one({'attachments.path': key}, {'_id': 1}) is not None:
                continue
        except PyMongoError:
            current_app.logger.warning('Request attachment cleanup deferred reason=database')
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            current_app.logger.warning('Request attachment cleanup deferred reason=filesystem')


def public_attachments(idea):
    return [dict(id=a['id'], name=a['name'], size=a['size'],
                 url=f"/api/ideas/{idea['_id']}/attachments/{a['id']}")
            for a in idea.get('attachments', [])]
