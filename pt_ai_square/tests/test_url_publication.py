"""HTTP links share the existing publication/review boundaries with HTTPS links."""
import json
import uuid
from pathlib import Path

import pytest
from werkzeug.exceptions import BadRequest

from pt_ai_square.backend.publication_urls import publication_url
from pt_ai_square.backend.storage import db
from .conftest import ready
from .test_personal_api_usage import issue
from .test_publish_drafts import fields, approve, commit


VALID_URLS = [
    'http://intranet/tools/mail',
    'http://tools.department.example.test:8080/path?query=value#section',
    'https://tools.example.test/download?version=2',
    'http://127.0.0.1:5000/',
    'http://10.20.30.40:65535/',
    'http://[::1]:5000/',
    'https://[2001:db8::1234]/tool',
    'http://사내도구.테스트/안내',
    'http://intranet./path',
    'HTTP://INTRANET:80/path',
]

INVALID_URLS = [
    None, 123, True, {}, [], '', '  ',
    'ftp://intranet/file', 'file:///C:/private', 'javascript:alert(1)',
    '//intranet/path', '/local/path', 'http:intranet/path', 'http:///path',
    'http://', 'http://user:secret@intranet/', 'http://user@intranet/',
    'http://@intranet/', 'http://:secret@intranet/',
    'http://intranet:abc/', 'http://intranet:65536/', 'http://intranet:0/',
    'http://intranet:-1/', 'http://intranet:/',
    'http://[::1/', 'http://[not-an-ip]/', 'http://[::1]suffix/',
    'http://[fe80::1%25eth0]/', 'http://[v1.future]/',
    'http://bad host/', 'http://bad_host/', 'http://.intranet/',
    'http://intranet../', 'http://-intranet/', 'http://intranet-/',
    'http://%69ntranet/', 'http://999.1.2.3/', 'http://127.1/',
    'http://intranet\\@other/', 'http://intranet/path with space',
    'http://intranet/\npath', '\thttp://intranet/', 'http://intranet/\r',
    'http://intranet/\x00', 'http://intranet/\x7f', 'http://intranet/\x80',
    'http://intranet/\ud800', 'http://\udfff/path',
    'http://' + 'a' * 64 + '.test/',
    'http://' + '.'.join(['a' * 63] * 4) + '/',
    'http://intranet/' + 'x' * 2048,
]


def web_publish(browser, csrf, url, tid=None, **changes):
    metadata = fields(mode='url', url=url, **changes)
    endpoint = '/api/tools' if tid is None else f'/api/tools/{tid}/versions'
    return browser.post(endpoint, headers=csrf, data={'metadata': json.dumps(metadata)})


def draft_publish(api, auth, url, **changes):
    return api.post('/api/publish-drafts', headers=auth,
                    data={'metadata': json.dumps(fields(mode='url', url=url, **changes))})


@pytest.mark.parametrize('url', VALID_URLS)
def test_syntax_validator_preserves_supported_http_https_links(url):
    assert publication_url('  ' + url + '  ') == url


@pytest.mark.parametrize('url', INVALID_URLS)
def test_syntax_validator_returns_clean_bad_request_for_malformed_links(url):
    with pytest.raises(BadRequest) as error:
        publication_url(url)
    assert error.value.code == 400
    assert error.value.description == '인증정보 없는 올바른 HTTP 또는 HTTPS 주소를 입력해 주세요.'


def test_validator_never_resolves_or_fetches_links(monkeypatch):
    import socket
    import urllib.request
    import http.client

    def unexpected(*args, **kwargs):
        raise AssertionError('Publication URL validation must not resolve or fetch the target')

    monkeypatch.setattr(socket, 'getaddrinfo', unexpected)
    monkeypatch.setattr(urllib.request, 'urlopen', unexpected)
    monkeypatch.setattr(http.client.HTTPConnection, 'request', unexpected)
    assert publication_url('http://unresolvable-internal-host:8080/tool')


def test_web_http_new_update_manifest_and_versions_preserve_link_only_artifacts(app):
    browser, csrf = ready(app)
    for index, url in enumerate(VALID_URLS, 1):
        response = web_publish(browser, csrf, '  ' + url + '  ',
                               None if index == 1 else 1, expectedRevision=index - 1)
        assert response.status_code == 201, response.json
        assert response.json['id'] == 1 and response.json['version'] == index
        manifest = browser.get('/api/tools/1/manifest').json
        assert manifest['url'] == url and manifest['downloadUrl'] is None
        assert manifest['bytes'] == 0 and manifest['sha256'] == ''
        assert manifest['packageId'] is None and manifest['sourcePackageId'] is None
        assert browser.get('/api/tools/1').json['url'] == url
    with app.app_context():
        tool = db().tools.find_one({'_id': 1})
        assert [v['url'] for v in tool['versions']] == VALID_URLS
        assert all(v['path'] is None and not v['name'] for v in tool['versions'])
    assert not list((Path(app.config['DATA_DIR']) / 'artifacts').iterdir())
    assert browser.get('/download/1/1').status_code == 400


def test_invalid_web_links_are_400_and_do_not_mutate_new_or_existing_tools(app):
    browser, csrf = ready(app)
    for url in INVALID_URLS:
        response = web_publish(browser, csrf, url)
        assert response.status_code == 400, (url, response.json)
        assert response.json['error'] == '인증정보 없는 올바른 HTTP 또는 HTTPS 주소를 입력해 주세요.'
    with app.app_context():
        assert db().tools.count_documents({}) == 0
    assert web_publish(browser, csrf, 'http://intranet/start').status_code == 201
    for url in INVALID_URLS:
        assert web_publish(browser, csrf, url, 1, expectedRevision=1).status_code == 400
    with app.app_context():
        tool = db().tools.find_one({'_id': 1})
        assert tool['revision'] == 1 and len(tool['versions']) == 1
        assert tool['versions'][0]['url'] == 'http://intranet/start'


def test_http_web_ownership_revision_csrf_and_request_replay_guards(app):
    browser, csrf = ready(app)
    request_id = str(uuid.uuid4())
    assert web_publish(browser, {}, 'http://intranet/').status_code == 403
    assert web_publish(browser, csrf, 'http://intranet/', clientRequestId=request_id).status_code == 201
    replay = web_publish(browser, csrf, 'http://intranet/', clientRequestId=request_id)
    assert replay.status_code == 200 and replay.json['replayed']
    assert web_publish(browser, csrf, 'http://intranet/changed', clientRequestId=request_id).status_code == 409
    assert web_publish(browser, csrf, 'http://intranet/v2', 1, expectedRevision=0).status_code == 409
    other, other_csrf = ready(app, 'other')
    assert web_publish(other, other_csrf, 'http://intranet/v2', 1, expectedRevision=1).status_code == 403
    update_id = str(uuid.uuid4())
    assert web_publish(browser, csrf, 'http://intranet/v2', 1,
                       expectedRevision=1, clientRequestId=update_id).status_code == 201
    replay = web_publish(browser, csrf, 'http://intranet/v2', 1,
                         expectedRevision=1, clientRequestId=update_id)
    assert replay.status_code == 200 and replay.json['version'] == 2
    with app.app_context():
        assert db().tools.count_documents({}) == 1
        assert len(db().tools.find_one({'_id': 1})['versions']) == 2


def test_http_key_draft_requires_owner_browser_approval_for_new_and_update(app):
    owner, csrf = ready(app)
    _, auth = issue(owner, csrf)
    api = app.test_client()
    assert web_publish(api, auth, 'http://intranet/').status_code == 409
    created = draft_publish(api, auth, 'http://intranet/tool', clientRequestId=str(uuid.uuid4()))
    assert created.status_code == 201, created.json
    draft = created.json
    assert draft['artifact']['url'] == 'http://intranet/tool'
    assert commit(api, auth, draft).status_code == 409
    assert approve(owner, {}, draft).status_code == 403
    assert approve(api, auth, draft).status_code == 403
    assert approve(owner, csrf, draft, True).status_code == 200
    saved = commit(api, auth, draft)
    assert saved.status_code == 201 and saved.json['version'] == 1
    member, _ = ready(app, 'member')
    assert member.get('/api/tools/1/manifest').status_code == 403
    updated = draft_publish(api, auth, 'http://intranet/tool/v2', toolId=1, expectedRevision=1)
    assert updated.status_code == 201, updated.json
    assert approve(owner, csrf, updated.json).status_code == 200
    assert commit(api, auth, updated.json).status_code == 201
    assert commit(api, auth, updated.json).json['replayed']
    assert member.get('/api/tools/1/manifest').json['url'] == 'http://intranet/tool/v2'
    admin, admin_csrf = ready(app, 'admin')
    _, admin_auth = issue(admin, admin_csrf)
    assert draft_publish(api, admin_auth, 'http://intranet/other', toolId=1, expectedRevision=2).status_code == 403
    assert draft_publish(api, auth, 'http://intranet/stale', toolId=1, expectedRevision=1).status_code == 409


def test_malformed_links_cannot_be_saved_as_key_drafts(app):
    owner, csrf = ready(app)
    _, auth = issue(owner, csrf)
    api = app.test_client()
    for url in INVALID_URLS:
        response = draft_publish(api, auth, url)
        assert response.status_code == 400, (url, response.json)
    with app.app_context():
        assert db().publish_drafts.count_documents({}) == 0
        assert db().tools.count_documents({}) == 0
