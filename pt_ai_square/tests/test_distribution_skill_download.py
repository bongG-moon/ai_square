"""Distribution guides remain public without expanding personal KEY access."""
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile

from flask import Flask, jsonify
import pytest
from werkzeug.exceptions import HTTPException
from werkzeug.http import parse_options_header

from pt_ai_square import create_app
from pt_ai_square.backend import auth
from pt_ai_square.backend.distribution_skill import (
    DOWNLOAD_NAME, SOURCE_NAMES, distribution_skill,
)
from .conftest import ready
from .test_personal_api_usage import issue


URL = '/resources/distribution-skill.zip'


def archive_bytes(message):
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr('pt-file-distribution/SKILL.md', message)
    return output.getvalue()


@pytest.fixture
def download_app(tmp_path, monkeypatch):
    guides = tmp_path / 'static' / 'guides'
    guides.mkdir(parents=True)
    app = Flask(__name__, static_folder=str(guides.parent))
    app.config.update(TESTING=True, AUTH_MODE='sso', SECRET_KEY='test-session-key')
    app.register_blueprint(distribution_skill)
    auth.install_auth(app)
    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code
    def forbidden_database():
        pytest.fail('The public guide must not require SSO identity/database lookup')
    monkeypatch.setattr(auth, 'db', forbidden_database)
    return app, guides


def test_ascii_source_is_preferred_and_original_bytes_are_sent(download_app):
    app, guides = download_app
    preferred = archive_bytes('# current')
    legacy = archive_bytes('# legacy')
    (guides / SOURCE_NAMES[0]).write_bytes(preferred)
    (guides / SOURCE_NAMES[1]).write_bytes(legacy)
    response = app.test_client().get(URL)
    assert response.status_code == 200
    assert response.data == preferred
    assert response.mimetype == 'application/zip'
    assert response.headers['Cache-Control'] == 'public, no-cache'
    assert 'attachment;' in response.headers['Content-Disposition']
    assert DOWNLOAD_NAME == 'pt-file-distribution.zip'
    assert parse_options_header(response.headers['Content-Disposition'])[1]['filename'] == DOWNLOAD_NAME
    assert response.headers['Content-Disposition'].isascii()
    assert (guides / SOURCE_NAMES[0]).read_bytes() == preferred
    assert (guides / SOURCE_NAMES[1]).read_bytes() == legacy


def test_legacy_filename_alone_remains_downloadable(download_app):
    app, guides = download_app
    data = archive_bytes('# compatible')
    (guides / SOURCE_NAMES[1]).write_bytes(data)
    response = app.test_client().get(URL)
    assert response.status_code == 200 and response.data == data
    assert parse_options_header(response.headers['Content-Disposition'])[1]['filename'] == 'pt-file-distribution.zip'
    assert not (guides / SOURCE_NAMES[0]).exists()


def test_missing_files_give_deployment_guidance_without_config_or_paths(download_app):
    app, guides = download_app
    response = app.test_client().get(URL)
    assert response.status_code == 503
    assert '파일 배포 Skill' in response.json['error']
    assert 'static/guides' in response.json['error']
    assert 'config' not in response.json['error']
    assert str(guides) not in response.json['error']
    assert list(guides.iterdir()) == []


def test_head_and_conditional_download_have_no_body(download_app):
    app, guides = download_app
    data = archive_bytes('# download')
    (guides / SOURCE_NAMES[0]).write_bytes(data)
    client = app.test_client()
    response = client.head(URL)
    assert response.status_code == 200 and response.data == b''
    assert response.content_length == len(data)
    assert 'attachment;' in response.headers['Content-Disposition']
    unchanged = client.get(URL, headers={'If-None-Match': response.headers['ETag']})
    assert unchanged.status_code == 304 and unchanged.data == b''


def test_public_download_does_not_issue_a_session_or_follow_query_paths(download_app):
    app, guides = download_app
    data = archive_bytes('# fixed')
    (guides / SOURCE_NAMES[0]).write_bytes(data)
    response = app.test_client().get(URL + '?file=../../runtime_config.py&path=/etc/passwd',
                                   environ_overrides={'REMOTE_ADDR': '192.0.2.10'})
    assert response.status_code == 200 and response.data == data
    assert 'Set-Cookie' not in response.headers


def test_explicit_invalid_key_is_not_silently_treated_as_public(download_app):
    app, guides = download_app
    (guides / SOURCE_NAMES[0]).write_bytes(archive_bytes('# fixed'))
    response = app.test_client().get(URL, headers={'Authorization': 'Bearer invalid'})
    assert response.status_code == 401


def test_full_dummy_app_registers_resource_without_enabling_dummy_artifact_downloads(tmp_path):
    app = create_app({'TESTING': True, 'DATA_MODE': 'dummy', 'AUTH_MODE': 'mock',
                      'SECRET_KEY': 'test-session-key'})
    app.static_folder = str(tmp_path / 'static')
    guides = Path(app.static_folder) / 'guides'
    guides.mkdir(parents=True)
    data = archive_bytes('# dummy preview guide')
    (guides / SOURCE_NAMES[0]).write_bytes(data)
    client = app.test_client()
    response = client.get(URL)
    assert response.status_code == 200 and response.data == data
    assert client.get('/download/1/1').status_code == 409


def test_full_mongodb_app_allows_anonymous_but_keeps_key_api_allowlist(app, tmp_path):
    app.static_folder = str(tmp_path / 'download-static')
    guides = Path(app.static_folder) / 'guides'
    guides.mkdir(parents=True)
    data = archive_bytes('# public guide')
    (guides / SOURCE_NAMES[0]).write_bytes(data)
    anonymous = app.test_client()
    response = anonymous.get(URL)
    assert response.status_code == 200 and response.data == data
    assert 'Set-Cookie' not in response.headers
    owner, headers = ready(app)
    _, bearer = issue(owner, headers)
    assert owner.get(URL).status_code == 200
    assert anonymous.get(URL, headers=bearer).status_code == 403


def test_builder_writes_identical_ascii_and_legacy_archives(tmp_path):
    source = Path(__file__).resolve().parents[1]
    script = tmp_path / 'scripts' / 'build_guides.py'
    script.parent.mkdir()
    shutil.copyfile(source / 'scripts' / 'build_guides.py', script)
    for relative, content in {
        'backend/package_contract.py': '# package contract',
        'receiver/pt-square-receiver/scripts/square_client.py': '# client',
        'static/guides/pt-file-distribution/SKILL.md': '# distribution skill',
        'static/guides/pt-file-distribution/scripts/local.py': '# helper',
        'static/guides/pt-file-distribution/scripts/publish_client.py': '# legacy upload',
        'static/guides/pt-file-distribution/scripts/square_client.py': '# legacy network',
        'static/guides/pt-file-distribution/scripts/__pycache__/local.pyc': 'exclude',
    }.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
    completed = subprocess.run([sys.executable, '-B', str(script)], capture_output=True,
                               text=True, encoding='utf-8', timeout=20)
    assert completed.returncode == 0, completed.stderr
    guides = tmp_path / 'static' / 'guides'
    assert (guides / SOURCE_NAMES[0]).read_bytes() == (guides / SOURCE_NAMES[1]).read_bytes()
    with ZipFile(guides / SOURCE_NAMES[0]) as archive:
        assert archive.testzip() is None
        assert 'pt-file-distribution/SKILL.md' in archive.namelist()
        assert 'pt-file-distribution/scripts/package_contract.py' in archive.namelist()
        assert 'pt-file-distribution/scripts/local.py' in archive.namelist()
        assert not any(name.endswith(('/publish_client.py', '/square_client.py'))
                       for name in archive.namelist())
        assert not any('__pycache__' in name or name.endswith('.pyc') for name in archive.namelist())
    # Building the local-only Skill must neither remove compatibility source
    # files nor replace them with a different receiver version.
    scripts = guides / 'pt-file-distribution' / 'scripts'
    assert (scripts / 'square_client.py').read_text() == '# legacy network'
    assert (scripts / 'publish_client.py').read_text() == '# legacy upload'
