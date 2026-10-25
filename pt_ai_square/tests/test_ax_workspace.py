"""Real isolated MongoDB coverage for administrator Workspace file publishing."""
import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from pymongo.collection import Collection
from pymongo.errors import AutoReconnect, OperationFailure

from pt_ai_square.backend.artifacts import used_bytes
from pt_ai_square.backend.storage import db, deliver_notifications
from .conftest import ready


def archive(name='README.md'):
    value = io.BytesIO()
    with zipfile.ZipFile(value, 'w') as output:
        output.writestr(name, '# AX Workspace\n')
    return value.getvalue()


def upload(client, headers, *, file_name='ax_workspace.zip', content=None, **metadata):
    data = dict(name='AX Workspace', description='사내 업무 환경 설치 파일입니다.',
                category='workspace', version='1.0.0')
    data.update(metadata)
    return client.post('/api/ax-workspace', headers=headers,
                       data={'metadata': json.dumps(data),
                             'file': (io.BytesIO(archive() if content is None else content), file_name)})


def files(app):
    return list((Path(app.config['DATA_DIR']) / 'artifacts').glob('*'))


def test_session_admin_csrf_and_member_download(app):
    admin, headers = ready(app, 'admin')
    member, mh = ready(app, 'member')
    assert app.test_client().get('/api/ax-workspace').status_code == 401
    maximum = app.config['MAX_CONTENT_LENGTH'] - 65536
    assert member.get('/api/ax-workspace').json == {'files': [], 'canManage': False, 'maxFileBytes': maximum}
    assert admin.get('/api/ax-workspace').json == {'files': [], 'canManage': True, 'maxFileBytes': maximum}
    assert upload(member, mh).status_code == 403
    assert upload(admin, {}).status_code == 403
    assert not files(app)

    content = archive()
    response = upload(admin, headers, content=content)
    assert response.status_code == 201, response.json
    public = response.json['file']
    assert response.json['followupsPending'] is False
    assert public['author'] == 'admin'
    assert public['fileName'] == 'ax_workspace.zip'
    assert public['sha256'] == hashlib.sha256(content).hexdigest()
    assert public['size'] == len(content)
    assert 'path' not in public and 'outbox' not in public and 'owner' not in public
    assert member.get('/api/ax-workspace').json['files'] == [public]
    downloaded = member.get(public['downloadUrl'])
    assert downloaded.status_code == 200 and downloaded.data == content
    assert 'attachment;' in downloaded.headers['Content-Disposition']
    assert downloaded.headers['Cache-Control'] == 'private, no-store'
    assert app.test_client().get(public['downloadUrl']).status_code == 401
    downloaded.close()
    with app.app_context():
        stored = db().workspace_files.find_one({'_id': public['id']})
        assert stored['owner'] == 'admin' and stored['outbox'] == []
        assert used_bytes() == len(content)
        assert db().audit.count_documents({'action': 'AX Workspace 파일 등록: AX Workspace'}) == 1
        assert db().tools.count_documents({}) == 0
        assert db().activity.count_documents({}) == 0
        assert db().activity_state.count_documents({}) == 0


def test_catalog_lists_only_admin_uploaded_files_not_static_bundles(app, tmp_path):
    # An old deployment may retain a bundled EXE. It must not appear as a
    # synthetic catalog item or bypass the administrator's actual uploads.
    static = tmp_path / 'legacy-static'
    guides = static / 'guides'
    guides.mkdir(parents=True)
    (guides / 'ax-workspace-extension-setup.exe').write_bytes(b'MZlegacy-bundle')
    app.static_folder = str(static)
    admin, headers = ready(app, 'admin')
    member, _ = ready(app, 'member')
    assert member.get('/api/ax-workspace').json['files'] == []
    uploaded = []
    for name, category, content in [
        ('AX Workspace 설치', 'workspace', b'MZworkspace-installer'),
        ('P&T AI Square 연동', 'integration', b'MZregistered-integration'),
    ]:
        response = upload(admin, headers, name=name, category=category,
                          file_name='installer.exe', content=content)
        assert response.status_code == 201
        uploaded.append((response.json['file'], content))
    listed = member.get('/api/ax-workspace').json['files']
    assert {row['id'] for row in listed} == {row['id'] for row, _ in uploaded}
    assert len(listed) == 2
    for row, content in uploaded:
        downloaded = member.get(row['downloadUrl'])
        assert downloaded.status_code == 200 and downloaded.data == content
        downloaded.close()
    for path in ['/local-access/workspace-extension.zip',
                 '/static/guides/ax-workspace-extension-setup.exe']:
        response = member.get(path)
        assert response.status_code == 302 and response.headers['Location'] == '/?view=ax'
        assert b'MZlegacy-bundle' not in response.data
    with app.app_context():
        assert db().workspace_files.count_documents({}) == 2
        assert db().tools.count_documents({}) == 0


@pytest.mark.parametrize('scope', ['read', 'publish'])
def test_personal_key_cannot_bypass_workspace_browser_only_scope(app, scope):
    admin, headers = ready(app, 'admin')
    saved = upload(admin, headers).json['file']
    issued = admin.post('/api/local-tokens', headers=headers,
                        json={'name': 'test', 'scope': scope})
    assert issued.status_code == 201
    bearer = {'Authorization': 'Bearer ' + issued.json['token']}
    # Include the existing signed session too: a denied KEY must not fall back.
    assert admin.get('/api/ax-workspace', headers=bearer).status_code == 403
    assert admin.get(saved['downloadUrl'], headers=bearer).status_code == 403
    assert upload(admin, bearer).status_code == 403
    with app.app_context():
        assert db().workspace_files.count_documents({}) == 1


@pytest.mark.parametrize('name,content', [
    ('workspace.exe', b'MZinstaller'),
    ('workspace.msi', bytes.fromhex('d0cf11e0a1b11ae1') + b'installer'),
    ('setup.ps1', b'Write-Output "Workspace"'),
    ('guide.md', '# 안내'.encode()),
    ('cube-plugin.zip', archive()),
])
def test_supported_download_formats_preserve_original_bytes(app, name, content):
    admin, headers = ready(app, 'admin')
    response = upload(admin, headers, file_name=name, content=content, category='plugin')
    assert response.status_code == 201
    saved = response.json['file']
    assert saved['fileName'] == name and saved['category'] == 'plugin'
    downloaded = admin.get(saved['downloadUrl'])
    assert downloaded.data == content
    downloaded.close()


@pytest.mark.parametrize('name,content', [
    ('bad.html', b'<html>'), ('bad.exe', b'not an executable'),
    ('bad.msi', b'not msi'), ('bad.zip', b'not zip'), ('empty.md', b''),
    ('bad.zip', archive('../outside.md')), ('bad.zip', archive('/outside.md')),
    ('bad.zip', archive('C:/outside.md')),
])
def test_invalid_artifacts_leave_no_metadata_or_partial_file(app, name, content):
    admin, headers = ready(app, 'admin')
    assert upload(admin, headers, file_name=name, content=content).status_code == 400
    assert files(app) == []
    with app.app_context():
        assert db().workspace_files.count_documents({}) == 0


@pytest.mark.parametrize('metadata', [
    {'name': ''}, {'name': 'a' * 101}, {'name': ['bad']},
    {'description': 'a' * 2001}, {'description': None},
    {'category': 'unknown'}, {'category': ['workspace']},
    {'version': ''}, {'version': 'a' * 41},
])
def test_metadata_validation_happens_before_writing_file(app, metadata):
    admin, headers = ready(app, 'admin')
    assert upload(admin, headers, **metadata).status_code == 400
    assert files(app) == []


def test_upload_quota_includes_workspace_files(app):
    admin, headers = ready(app, 'admin')
    with app.app_context():
        db().settings.insert_one({'_id': 'storage_limits', 'mode': 'manual',
                                  'quotaBytes': 5, 'reserveBytes': 0})
    assert upload(admin, headers, file_name='guide.md', content=b'abcdef').status_code == 409
    assert files(app) == []
    with app.app_context():
        assert db().workspace_files.count_documents({}) == 0


@pytest.mark.parametrize('committed', [False, True])
def test_uncertain_insert_keeps_bytes_and_never_claims_success(app, monkeypatch, committed):
    admin, headers = ready(app, 'admin')
    original = Collection.insert_one

    def lose_reply(collection, document, *args, **kwargs):
        if collection.name == 'workspace_files':
            if committed:
                original(collection, document, *args, **kwargs)
            raise AutoReconnect('simulated lost acknowledgement')
        return original(collection, document, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Collection, 'insert_one', lose_reply)
        response = upload(admin, headers, file_name='guide.md', content=b'keep bytes')
    assert response.status_code == 503
    assert len(files(app)) == 1 and files(app)[0].read_bytes() == b'keep bytes'
    with app.app_context():
        assert db().workspace_files.count_documents({}) == int(committed)
        if committed:
            stored = db().workspace_files.find_one()
            assert stored['outbox'] and stored['path'] == files(app)[0].name


def test_failed_audit_does_not_fail_saved_file_and_is_replayable(app, monkeypatch):
    admin, headers = ready(app, 'admin')
    original = Collection.update_one

    def fail_audit(collection, *args, **kwargs):
        if collection.name == 'audit':
            raise OperationFailure('simulated secondary write', 225)
        return original(collection, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(Collection, 'update_one', fail_audit)
        response = upload(admin, headers)
    assert response.status_code == 201 and response.json['followupsPending'] is True
    with app.app_context():
        saved = db().workspace_files.find_one()
        assert saved['outbox']
        assert deliver_notifications('workspace_files', saved['_id']).pending is False
        assert db().workspace_files.find_one()['outbox'] == []
        assert db().audit.count_documents({'action': 'AX Workspace 파일 등록: AX Workspace'}) == 1


def test_download_rejects_missing_file_or_unsafe_stored_path(app, tmp_path):
    admin, headers = ready(app, 'admin')
    saved = upload(admin, headers).json['file']
    assert admin.get('/api/ax-workspace/not-an-id/download').status_code == 404
    assert admin.get('/api/ax-workspace/' + '0' * 32 + '/download').status_code == 404
    with app.app_context():
        db().workspace_files.update_one({'_id': saved['id']}, {'$set': {'path': '../outside.md'}})
    (tmp_path / 'outside.md').write_text('private')
    assert admin.get(saved['downloadUrl']).status_code == 400
    with app.app_context():
        db().workspace_files.update_one({'_id': saved['id']}, {'$set': {'path': 'missing.md'}})
    assert admin.get(saved['downloadUrl']).status_code == 404


def test_only_one_file_per_publish(app):
    admin, headers = ready(app, 'admin')
    data = {'metadata': json.dumps(dict(name='Workspace', version='1')),
            'file': [(io.BytesIO(b'# one'), 'a.md'), (io.BytesIO(b'# two'), 'b.md')]}
    assert admin.post('/api/ax-workspace', headers=headers, data=data).status_code == 400
    assert files(app) == []


@pytest.mark.parametrize('request_limit,maximum', [(256 * 1048576, 256 * 1048576 - 65536), (1024, 0)])
def test_catalog_exposes_configured_upload_limit_with_metadata_headroom(app, request_limit, maximum):
    member, _ = ready(app, 'member')
    app.config['MAX_CONTENT_LENGTH'] = request_limit
    response = member.get('/api/ax-workspace')
    assert response.status_code == 200
    assert response.json['maxFileBytes'] == maximum
