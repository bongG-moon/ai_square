"""The website binds only its origin to MCP downloads; credentials stay local."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

from flask import Flask, url_for
import pytest
from pymongo.collection import Collection

from pt_ai_square.backend.local_access import local_access
from pt_ai_square.backend.mcp_package import MANIFEST, normalize_origin, package_for_origin
from .conftest import ready
from .test_personal_api_usage import issue


@pytest.fixture
def package_app(tmp_path):
    static = tmp_path / 'static'
    guides = static / 'guides'
    guides.mkdir(parents=True)
    source = guides / 'pt-square-mcp.zip'
    with ZipFile(source, 'w') as archive:
        archive.writestr('pt-square-mcp/README.md', '# MCP instructions')
        archive.writestr('pt-square-mcp/run_mcp.py', 'print("entry")')
        archive.writestr('pt-square-mcp/pt_square_mcp/runtime.py', '# reviewed source')
    app = Flask(__name__, static_folder=str(static))
    app.config.update(TESTING=True, PUBLIC_URL='')
    # Route/package unit tests do not require MongoDB. Real authentication is
    # exercised below using the existing full-app fixture and its signed session.
    app.register_blueprint(local_access)
    return app, source


def unpack(response):
    assert response.status_code == 200
    with ZipFile(BytesIO(response.data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


@pytest.mark.parametrize('url,expected', [
    ('http://COMPANY.example:80/', 'http://company.example'),
    ('https://COMPANY.example:443/', 'https://company.example'),
    ('http://127.0.0.1:5000/', 'http://127.0.0.1:5000'),
    ('https://company.example:9443', 'https://company.example:9443'),
    ('http://[::1]:5000/', 'http://[::1]:5000'),
])
def test_normalized_origin_matches_mcp_contract(url, expected):
    assert normalize_origin(url) == expected


@pytest.mark.parametrize('url', [
    'ftp://company.example', 'https://user:pass@company.example',
    'https://company.example/local-access', 'https://company.example/?key=secret',
    'https://company.example/#secret', 'https://company.example\\other',
    'https://company.example:bad', '//company.example', ' https://company.example',
])
def test_invalid_origin_is_rejected(url):
    with pytest.raises(ValueError):
        normalize_origin(url)


def test_each_download_binds_current_origin_without_modifying_source(package_app):
    app, source = package_app
    before = source.read_bytes()
    with ZipFile(source) as archive:
        expected = {name: archive.read(name) for name in archive.namelist()}
    client = app.test_client()
    for origin in ['http://first.example:5000', 'https://second.example']:
        response = client.get('/local-access/mcp.zip', base_url=origin,
                              headers={'Cookie': 'secret-cookie=never-in-package'})
        entries = unpack(response)
        assert json.loads(entries.pop(MANIFEST)) == {'schemaVersion': 1, 'baseUrl': origin}
        assert entries == expected
        assert b'never-in-package' not in response.data
        assert response.headers['Cache-Control'] == 'private, no-store'
        assert 'attachment' in response.headers['Content-Disposition']
        assert 'pt-square-mcp.zip' in response.headers['Content-Disposition']
        assert 'ETag' not in response.headers
        assert 'Cookie' in response.headers['Vary']
    assert source.read_bytes() == before


def test_forwarded_headers_and_query_cannot_replace_the_download_origin(package_app):
    app, _ = package_app
    response = app.test_client().get(
        '/local-access/mcp.zip?url=https://query.example&baseUrl=https://query.example',
        base_url='http://real.example', headers={
            'X-Forwarded-Host': 'attacker.example',
            'X-Forwarded-Proto': 'https',
            'Forwarded': 'host=attacker.example;proto=https',
        })
    manifest = json.loads(unpack(response)[MANIFEST])
    assert manifest['baseUrl'] == 'http://real.example'


def test_operator_canonical_url_is_used_behind_a_proxy(package_app):
    app, _ = package_app
    app.config['PUBLIC_URL'] = 'https://Public.Example:443/'
    response = app.test_client().get('/local-access/mcp.zip', base_url='http://internal:5000')
    assert json.loads(unpack(response)[MANIFEST])['baseUrl'] == 'https://public.example'


def test_invalid_operator_url_does_not_silently_fall_back(package_app):
    app, _ = package_app
    app.config['PUBLIC_URL'] = 'http://user:private@wrong.example/path'
    response = app.test_client().get('/local-access/mcp.zip')
    assert response.status_code == 503
    assert b'private' not in response.data


def test_old_web_link_is_bound_and_new_route_is_canonical(package_app):
    app, _ = package_app
    with app.test_request_context('/'):
        assert url_for('local_access.mcp_download') == '/local-access/mcp.zip'
    result = unpack(app.test_client().get('/static/guides/pt-square-mcp.zip',
                                         base_url='http://company.example'))
    assert json.loads(result[MANIFEST])['baseUrl'] == 'http://company.example'


def test_stale_embedded_connection_is_replaced_not_accumulated(package_app):
    _, source = package_app
    with ZipFile(source, 'a') as archive:
        archive.writestr(MANIFEST, json.dumps({'baseUrl': 'https://old.example', 'token': 'old-secret'}))
    output = package_for_origin(source, 'http://new.example')
    with ZipFile(output) as archive:
        assert archive.namelist().count(MANIFEST) == 1
        assert json.loads(archive.read(MANIFEST)) == {'schemaVersion': 1, 'baseUrl': 'http://new.example'}


def test_package_downloads_require_browser_session_including_legacy_static_path(app):
    owner, headers = ready(app)
    token, bearer = issue(owner, headers)
    anonymous = app.test_client()
    for path in ('/local-access/mcp.zip', '/static/guides/pt-square-mcp.zip'):
        assert anonymous.get(path).status_code == 302
        assert anonymous.get(path, headers=bearer).status_code == 403
        entries = unpack(owner.get(path))
        manifest = json.loads(entries[MANIFEST])
        assert manifest == {'schemaVersion': 1, 'baseUrl': 'http://localhost'}
        assert token['token'].encode() not in b'\n'.join(entries.values())


def test_authenticated_package_generation_does_not_mutate_database_or_disk(app, monkeypatch):
    owner, _ = ready(app)
    source = Path(app.static_folder) / 'guides' / 'pt-square-mcp.zip'
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    def forbidden(*args, **kwargs):
        pytest.fail('MCP package download must not write to MongoDB')
    for method in ('insert_one', 'update_one', 'update_many', 'find_one_and_update', 'delete_one', 'delete_many'):
        monkeypatch.setattr(Collection, method, forbidden)
    response = owner.get('/local-access/mcp.zip')
    assert response.status_code == 200
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_public_url_is_optional_and_environment_owned(monkeypatch, tmp_path):
    from pt_ai_square import config
    monkeypatch.setattr(config, 'BASE', tmp_path)
    monkeypatch.delenv('PTAI_PUBLIC_URL', raising=False)
    assert config.settings()['PUBLIC_URL'] == ''
    (tmp_path / 'runtime_config.py').write_text("PTAI_PUBLIC_URL = 'http://file.example'\n", encoding='utf-8')
    assert config.settings()['PUBLIC_URL'] == 'http://file.example'
    monkeypatch.setenv('PTAI_PUBLIC_URL', 'https://environment.example')
    assert config.settings()['PUBLIC_URL'] == 'https://environment.example'
