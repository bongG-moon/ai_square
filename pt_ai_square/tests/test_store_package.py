"""Server-bound optional-extension downloads without profile or Mongo writes."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
import time
from types import SimpleNamespace
from zipfile import ZipFile

from flask import Flask, url_for
import pytest

from pt_ai_square.backend.local_access import local_access
from pt_ai_square.backend.store_package import (
    INSTALLER_NAME, MANIFEST, MAX_INSTALLER_BYTES, SOURCE_NAME,
    connection_origin, package_for_origin,
)


@pytest.fixture
def package_app(tmp_path):
    guides = tmp_path / 'static' / 'guides'
    guides.mkdir(parents=True)
    source = guides / SOURCE_NAME
    source.write_bytes(b'MZ\x00fixture-prebuilt-installer\x00unchanged')
    templates = Path(__file__).resolve().parents[1] / 'templates'
    app = Flask(__name__, static_folder=str(guides.parent), template_folder=str(templates))
    app.config.update(TESTING=True, PUBLIC_URL='', SECRET_KEY='test-only-session')
    app.register_blueprint(local_access)
    app.add_url_rule('/', 'index', lambda: 'Index')
    return app, source


def unpack(response):
    assert response.status_code == 200
    with ZipFile(BytesIO(response.data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_download_binds_each_server_without_modifying_installer(package_app):
    app, source = package_app
    original = source.read_bytes()
    client = app.test_client()
    for origin in ['http://pntaisquare.company.example', 'https://other.example:8443']:
        response = client.get('/local-access/workspace-extension.zip', base_url=origin,
                              headers={'Authorization': 'test-secret-not-a-key', 'Cookie': 'private=never-copy'})
        files = unpack(response)
        assert set(files) == {INSTALLER_NAME, MANIFEST, 'README.txt'}
        assert files[INSTALLER_NAME] == original
        assert json.loads(files[MANIFEST]) == {'schemaVersion': 1, 'baseUrl': origin}
        assert b'test-secret' not in b'\n'.join(files.values())
        assert b'never-copy' not in b'\n'.join(files.values())
        assert response.headers['Cache-Control'] == 'private, no-store'
        assert response.headers['Vary'] == 'Cookie'
        assert 'ETag' not in response.headers
        assert response.headers['Content-Type'] == 'application/zip'
        assert 'PNT-AI-Square-AX-Extension.zip' in response.headers['Content-Disposition']
    assert source.read_bytes() == original


def test_public_url_wins_behind_reverse_proxy(package_app):
    app, _ = package_app
    app.config['PUBLIC_URL'] = 'http://PntAiSquare.company.example:80/'
    response = app.test_client().get('/local-access/workspace-extension.zip?url=https://untrusted.example',
                                    base_url='http://0.0.0.0:5000', headers={
                                        'X-Forwarded-Host': 'untrusted.example',
                                        'X-Forwarded-Proto': 'https',
                                    })
    assert json.loads(unpack(response)[MANIFEST])['baseUrl'] == 'http://pntaisquare.company.example'


def test_untrusted_forwarded_headers_and_query_do_not_choose_destination(package_app):
    app, _ = package_app
    response = app.test_client().get('/local-access/workspace-extension.zip?baseUrl=https://untrusted.example',
                                    base_url='http://company.example', headers={
                                        'X-Forwarded-Host': 'untrusted.example',
                                        'Forwarded': 'host=untrusted.example;proto=https',
                                    })
    assert json.loads(unpack(response)[MANIFEST])['baseUrl'] == 'http://company.example'


@pytest.mark.parametrize('origin', [
    'http://0.0.0.0', 'http://[::]:5000', 'http://user:secret@example.com',
    'https://example.com/path', 'https://example.com?key=secret',
    'https://example.com/#secret', 'https://example.com\\redirect',
])
def test_invalid_or_listening_origin_cannot_be_embedded(origin, package_app):
    with pytest.raises(ValueError):
        connection_origin(origin)
    app, _ = package_app
    app.config['PUBLIC_URL'] = origin
    response = app.test_client().get('/local-access/workspace-extension.zip')
    assert response.status_code == 503
    assert b'secret' not in response.data


def test_missing_or_invalid_installer_fails_without_empty_download(package_app):
    app, source = package_app
    client = app.test_client()
    for content in [b'', b'<html>not an installer</html>', b'MZ']:
        source.write_bytes(content)
        assert client.get('/local-access/workspace-extension.zip').status_code == 503
    source.unlink()
    assert client.get('/local-access/workspace-extension.zip').status_code == 503


def test_oversized_installer_is_rejected(package_app):
    _, source = package_app
    with source.open('wb') as stream:
        stream.write(b'MZ')
        stream.truncate(MAX_INSTALLER_BYTES + 1)
    from werkzeug.exceptions import ServiceUnavailable
    with pytest.raises(ServiceUnavailable):
        package_for_origin(source, 'https://company.example')


def test_static_source_url_returns_origin_aware_zip_too(package_app):
    app, source = package_app
    with app.test_request_context('/'):
        assert url_for('local_access.workspace_extension_download') == '/local-access/workspace-extension.zip'
    files = unpack(app.test_client().get('/static/guides/' + SOURCE_NAME, base_url='http://company.example'))
    assert files[INSTALLER_NAME] == source.read_bytes()
    assert json.loads(files[MANIFEST])['baseUrl'] == 'http://company.example'


def test_both_download_paths_use_real_browser_auth_guard(package_app, monkeypatch):
    from pt_ai_square.backend import auth
    from pt_ai_square.backend import local_access as access_module

    app, _ = package_app
    app.config.update(AUTH_MODE='sso', SESSION_COOKIE_SECURE=False)
    token = 'ptsq_' + 'A' * 43
    user = {'_id': 'employee', 'name': 'Employee', 'enabled': True, 'activeConnectionKeyId': 'key-1'}
    token_row = {'_id': hashlib.sha256(token.encode()).hexdigest(), 'id': 'key-1',
                 'user': 'employee', 'revoked': False, 'expires': None, 'scope': 'read'}

    class ReadOnlyRows:
        def __init__(self, row): self.row = row
        def find_one(self, query):
            return self.row if all(self.row.get(key) == value for key, value in query.items()) else None

    store = SimpleNamespace(users=ReadOnlyRows(user), local_tokens=ReadOnlyRows(token_row))
    for module in (auth, access_module):
        monkeypatch.setattr(module, 'db', lambda: store)
        monkeypatch.setattr(module, 'public_user', lambda row: dict(id=row['_id'], enabled=row['enabled']))
    auth.install_auth(app)
    anonymous = app.test_client()
    signed = app.test_client()
    with signed.session_transaction() as session:
        session.update({key: '' for key in auth.IDENTITY_FIELDS})
        session.update(emp_no='employee', logFlag=True,
                       _hcp_login={'employee': 'employee', 'at': time.time()})
    for path in ('/local-access/workspace-extension.zip', '/static/guides/' + SOURCE_NAME):
        assert anonymous.get(path).status_code == 302
        assert anonymous.get(path, headers={'Authorization': 'Bearer ' + token}).status_code == 403
        files = unpack(signed.get(path))
        assert token.encode() not in b'\n'.join(files.values())


def test_key_page_explains_optional_extension_and_keeps_mcp_link(package_app):
    app, _ = package_app
    response = app.test_client().get('/local-access')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '/local-access/workspace-extension.zip' in html
    assert '/local-access/mcp.zip' in html
    assert 'P&T AI Square 확장 받기' in html
    assert 'connection.json' in html
    assert '개인 KEY만 입력' in html
