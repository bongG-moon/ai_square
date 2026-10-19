"""Request attachment bytes live on disk; metadata lives with the MongoDB idea."""
import hashlib
import uuid
from pathlib import Path
from flask import current_app
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

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
            digest = hashlib.sha256()
            with path.open('xb') as output:
                while chunk := upload.stream.read(64 * 1024):
                    row['size'] += len(chunk)
                    if row['size'] > MAX_FILE:
                        raise RequestEntityTooLarge('첨부파일 하나당 최대 20MB입니다.')
                    output.write(chunk)
                    digest.update(chunk)
            if not row['size']:
                raise BadRequest('빈 첨부파일은 등록할 수 없습니다.')
            row['sha256'] = digest.hexdigest()
        from .artifacts import used_bytes
        if used_bytes() > current_app.config['STORAGE_QUOTA']:
            raise RequestEntityTooLarge('서버 저장 공간 한도를 초과했습니다.')
        return saved
    except Exception:
        for row in saved:
            attachment_path(row['path']).unlink(missing_ok=True)
        raise


def public_attachments(idea):
    return [dict(id=a['id'], name=a['name'], size=a['size'],
                 url=f"/api/ideas/{idea['_id']}/attachments/{a['id']}")
            for a in idea.get('attachments', [])]
