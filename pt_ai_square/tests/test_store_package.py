"""Legacy extension links route to the administrator-published AX Workspace catalog."""
import hashlib
from pathlib import Path
import re
import time
from types import SimpleNamespace

from flask import Flask, url_for
import pytest

from pt_ai_square.backend.local_access import local_access
SOURCE_NAME = 'ax-workspace-extension-setup.exe'


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


@pytest.mark.parametrize('path', ['/local-access/workspace-extension.zip', '/static/guides/' + SOURCE_NAME])
def test_old_links_redirect_to_workspace_without_serving_remaining_bundled_installer(package_app, path):
    app, source = package_app
    original = source.read_bytes()
    for method in ['GET', 'HEAD']:
        response = app.test_client().open(path, method=method)
        assert response.status_code == 302
        assert response.headers['Location'] == '/?view=ax'
        assert response.headers['Cache-Control'] == 'private, no-store'
        assert response.headers['Vary'] == 'Cookie'
        assert 'Content-Disposition' not in response.headers
        assert 'ETag' not in response.headers
        assert response.mimetype != 'application/zip'
        assert original not in response.data
    assert source.read_bytes() == original


def test_redirect_does_not_use_public_url_or_reverse_proxy_headers(package_app):
    app, _ = package_app
    app.config['PUBLIC_URL'] = 'http://PntAiSquare.company.example:80/'
    response = app.test_client().get('/local-access/workspace-extension.zip?url=https://untrusted.example',
                                    base_url='http://0.0.0.0:5000', headers={
                                        'X-Forwarded-Host': 'untrusted.example',
                                        'X-Forwarded-Proto': 'https',
                                    })
    assert response.status_code == 302
    assert response.headers['Location'] == '/?view=ax'
    assert b'untrusted.example' not in response.data


def test_untrusted_forwarded_headers_and_query_do_not_choose_destination(package_app):
    app, _ = package_app
    response = app.test_client().get('/local-access/workspace-extension.zip?baseUrl=https://untrusted.example',
                                    base_url='http://company.example', headers={
                                        'X-Forwarded-Host': 'untrusted.example',
                                        'Forwarded': 'host=untrusted.example;proto=https',
                                    })
    assert response.status_code == 302
    assert response.headers['Location'] == '/?view=ax'
    assert b'untrusted.example' not in response.data


@pytest.mark.parametrize('path', ['/local-access/workspace-extension.zip', '/static/guides/' + SOURCE_NAME])
def test_old_links_work_without_any_bundled_installer(package_app, path):
    app, source = package_app
    source.unlink()
    response = app.test_client().get(path)
    assert response.status_code == 302
    assert response.headers['Location'] == '/?view=ax'
    assert 'Content-Disposition' not in response.headers


def test_existing_mcp_download_route_is_unchanged(package_app, monkeypatch):
    from pt_ai_square.backend import mcp_package
    app, _ = package_app
    calls = []
    def download():
        calls.append(True)
        return b'existing-mcp-package', 200, {'Content-Type': 'application/zip'}
    monkeypatch.setattr(mcp_package, 'download_package', download)
    for path in ['/local-access/mcp.zip', '/static/guides/pt-square-mcp.zip']:
        response = app.test_client().get(path)
        assert response.status_code == 200
        assert response.data == b'existing-mcp-package'
        assert response.mimetype == 'application/zip'
    assert len(calls) == 2


def test_existing_endpoint_identity_is_preserved_for_old_bookmarks(package_app):
    app, _ = package_app
    with app.test_request_context('/'):
        assert url_for('local_access.workspace_extension_download') == '/local-access/workspace-extension.zip'


@pytest.mark.parametrize('scope', ['read', 'publish'])
def test_both_download_paths_use_real_browser_auth_guard(package_app, monkeypatch, scope):
    from pt_ai_square.backend import auth
    from pt_ai_square.backend import local_access as access_module

    app, _ = package_app
    app.config.update(AUTH_MODE='sso', SESSION_COOKIE_SECURE=False)
    token = 'ptsq_' + 'A' * 43
    user = {'_id': 'employee', 'name': 'Employee', 'enabled': True, 'activeConnectionKeyId': 'key-1'}
    token_row = {'_id': hashlib.sha256(token.encode()).hexdigest(), 'id': 'key-1',
                 'user': 'employee', 'revoked': False, 'expires': None, 'scope': scope}

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
        login = anonymous.get(path)
        assert login.status_code == 302 and '/login?' in login.headers['Location']
        assert anonymous.get(path, headers={'Authorization': 'Bearer ' + token}).status_code == 403
        assert signed.get(path, headers={'Authorization': 'Bearer ' + token}).status_code == 403
        response = signed.get(path)
        assert response.status_code == 302 and response.headers['Location'] == '/?view=ax'
        assert token.encode() not in response.data and 'Content-Disposition' not in response.headers


def test_key_page_keeps_downloads_visible_with_collapsed_connection_steps(package_app):
    app, _ = package_app
    response = app.test_client().get('/local-access')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'href="/?view=ax"' in html
    assert '/local-access/workspace-extension.zip' not in html
    assert 'ax-workspace-extension-setup.exe' not in html
    assert 'P&T AI Square 확장 받기' not in html
    assert html.index('id="extension-title"') < html.index('id="mcp-title"')
    visible_html = re.sub(r'<details\b[^>]*>.*?</details>', '', html, flags=re.DOTALL)
    assert 'href="/local-access/mcp.zip"' in visible_html
    assert 'Connect.cmd' not in visible_html
    assert '처음 한 번, AI에 MCP 등록하기' not in visible_html
    procedures = re.findall(r'<details\b([^>]*)>(.*?)</details>', html, flags=re.DOTALL)
    procedures = [(attrs, body) for attrs, body in procedures if 'local-procedure' in attrs]
    assert len(procedures) == 2
    assert all(not re.search(r'\bopen\b', attrs) for attrs, _ in procedures)
    assert 'local-app-steps' in procedures[0][1]
    assert 'local-mcp-steps' in procedures[1][1]
    assert '채팅에서 연결 요청하기' in procedures[1][1]
    assert '같은 채팅에서 개인 KEY 입력하기' in procedures[1][1]
    assert 'id="token-scope"' not in html
    assert '신규 도구 등록' in html and '내 도구 업데이트' in html
    assert 'id="token-name"' not in html
    assert 'href="/?view=ax"' in visible_html
    assert 'href="/static/guides/MCP_LOCAL_GUIDE.html"' in visible_html
    assert 'Skill로 연결하기' not in html
    assert 'pt-square-receiver.zip' not in html
    assert 'PT_AI_SQUARE_파일배포_Skill.zip' not in html
