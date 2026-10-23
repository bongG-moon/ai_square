"""Cleanup preserves referenced/unknown bytes and never masks the real failure."""
import io
from pathlib import Path

import pytest
from pymongo.collection import Collection
from pymongo.errors import OperationFailure
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import BadRequest

from pt_ai_square.backend import request_files
from pt_ai_square.backend.storage import db
from .conftest import ready
from .test_request_files import body


def stored_attachment(app, key):
    with app.app_context():
        path = request_files.attachment_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'preserved reference')
    return {'path': key}, path


def test_cleanup_deletes_only_confirmed_unreferenced_bytes(app):
    loose, loose_path = stored_attachment(app, 'loose.txt')
    referenced, referenced_path = stored_attachment(app, 'linked.txt')
    with app.app_context():
        db().ideas.insert_one({'_id': 100, 'attachments': [referenced]})
        request_files.cleanup_unreferenced_attachments([loose, referenced])
    assert not loose_path.exists()
    assert referenced_path.read_bytes() == b'preserved reference'


def test_cleanup_keeps_unknown_files_and_continues_known_files(app, monkeypatch, caplog):
    unknown, unknown_path = stored_attachment(app, 'unknown.txt')
    loose, loose_path = stored_attachment(app, 'loose.txt')
    original = Collection.find_one

    def find(collection, query, *args, **kwargs):
        if collection.name == 'ideas' and query.get('attachments.path') == 'unknown.txt':
            raise OperationFailure('private-address-and-credentials', 225)
        return original(collection, query, *args, **kwargs)

    monkeypatch.setattr(Collection, 'find_one', find)
    with app.app_context():
        request_files.cleanup_unreferenced_attachments([unknown, loose])
    assert unknown_path.exists() and not loose_path.exists()
    assert 'reason=database' in caplog.text and 'private-address' not in caplog.text


def test_cleanup_unlink_error_preserves_file_and_does_not_raise(app, monkeypatch, caplog):
    row, path = stored_attachment(app, 'busy.txt')
    original = Path.unlink

    def unlink(value, *args, **kwargs):
        if value == path:
            raise PermissionError('private-file-path')
        return original(value, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', unlink)
    with app.app_context():
        request_files.cleanup_unreferenced_attachments([row])
    assert path.exists()
    assert 'reason=filesystem' in caplog.text and 'private-file-path' not in caplog.text


def test_cleanup_rejects_path_outside_attachment_directory(app, caplog):
    path = Path(app.config['DATA_DIR']) / 'outside.txt'
    path.write_text('keep', encoding='utf-8')
    with app.app_context():
        request_files.cleanup_unreferenced_attachments([{'path': '../outside.txt'}])
    assert path.read_text(encoding='utf-8') == 'keep'
    assert 'reason=invalid-path' in caplog.text


def test_staging_unlink_failure_preserves_original_validation_error(app, monkeypatch, caplog):
    uploads = [FileStorage(io.BytesIO(b'valid'), filename='first.txt'),
               FileStorage(io.BytesIO(b'invalid'), filename='second.exe')]
    original = Path.unlink

    def unlink(path, *args, **kwargs):
        if path.parent.name == 'request_attachments':
            raise PermissionError('private-file-path')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', unlink)
    with app.app_context(), pytest.raises(BadRequest, match='첨부는 PNG'):
        request_files.stage_attachments(uploads)
    assert 'reason=filesystem' in caplog.text and 'private-file-path' not in caplog.text


@pytest.mark.parametrize('committed', [False, True])
def test_request_insert_failure_cleans_only_unreferenced_files(app, monkeypatch, committed):
    client, headers = ready(app)
    original = Collection.insert_one

    def insert(collection, row, *args, **kwargs):
        if collection.name == 'ideas':
            if committed:
                original(collection, row, *args, **kwargs)
            raise OperationFailure('primary save error', 225)
        return original(collection, row, *args, **kwargs)

    monkeypatch.setattr(Collection, 'insert_one', insert)
    response = client.post('/api/ideas', headers=headers, data=body([('example.txt', b'content')]))
    assert response.status_code == 503 and response.json['diagnostic']['mongo_code'] == 225
    files = list((Path(app.config['DATA_DIR']) / 'request_attachments').glob('*'))
    assert len(files) == (1 if committed else 0)
    with app.app_context():
        assert db().ideas.count_documents({}) == (1 if committed else 0)


def test_request_cleanup_failure_preserves_original_database_error(app, monkeypatch):
    client, headers = ready(app)
    original_insert = Collection.insert_one
    original_unlink = Path.unlink

    def insert(collection, row, *args, **kwargs):
        if collection.name == 'ideas':
            raise OperationFailure('primary save error', 225)
        return original_insert(collection, row, *args, **kwargs)

    def unlink(path, *args, **kwargs):
        if path.parent.name == 'request_attachments':
            raise PermissionError('secondary cleanup failure')
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Collection, 'insert_one', insert)
    monkeypatch.setattr(Path, 'unlink', unlink)
    response = client.post('/api/ideas', headers=headers, data=body([('example.txt', b'content')]))
    assert response.status_code == 503 and response.json['diagnostic']['mongo_code'] == 225
    assert len(list((Path(app.config['DATA_DIR']) / 'request_attachments').glob('*'))) == 1
