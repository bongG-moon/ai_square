import importlib.util
import json
from pathlib import Path
import pytest
from .conftest import ready
from .test_receiver import receiver
from .test_personal_api_usage import issue


def test_corporate_http_requires_exact_opt_in(tmp_path):
    with pytest.raises(receiver.ClientError):
        receiver.Client('http://intranet.example', 'ptsq_'+'a'*43)
    client = receiver.Client('http://intranet.example', 'ptsq_'+'a'*43,
                             allow_http_origin='http://intranet.example')
    assert client.url == 'http://intranet.example'
    for url in ('http://other.example', 'http://intranet.example:80', 'http://intranet.example.evil'):
        with pytest.raises(receiver.ClientError):
            receiver.Client(url, allow_http_origin='http://intranet.example')
    for url in ('http://user:secret@intranet.example', 'http://intranet.example?key=x', 'http://intranet.example\\evil'):
        with pytest.raises(receiver.ClientError):
            receiver.Client(url, allow_http_origin='http://intranet.example')
    path = tmp_path/'config.json'
    assert receiver.main(['--config', str(path), 'configure', '--url', 'http://intranet.example', '--allow-http']) == 0
    value = json.loads(path.read_text(encoding='utf-8'))
    assert value == {'baseUrl':'http://intranet.example', 'allowHttpOrigin':'http://intranet.example'}
    assert receiver.NoRedirect().redirect_request(None,None,302,'',{},'http://other.example') is None


def test_review_page_session_only_and_escaped_id(app):
    owner, headers = ready(app)
    token, auth = issue(owner, headers)
    response = owner.get('/publish-review/not-a-real-draft')
    assert response.status_code == 200
    assert b'publish_review.js' in response.data
    assert response.headers['Cache-Control'] == 'no-store'
    assert app.test_client().get('/publish-review/not-a-real-draft', headers=auth).status_code == 403
    assert app.test_client().get('/publish-review/not-a-real-draft').status_code == 302
    escaped = owner.get('/publish-review/%22%3E%3Csvg%20onload=alert(1)%3E')
    assert b'<svg onload=' not in escaped.data


def test_version_check_http_is_explicit():
    script=Path(__file__).resolve().parents[1]/'static/guides/pt-file-distribution/scripts/version_check.py'
    spec=importlib.util.spec_from_file_location('version_http',script)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with pytest.raises(ValueError):
        module.check_version('http://intranet.example',1,1)
    class Offline:
        def open(self, request, timeout):
            assert request.full_url.startswith('http://intranet.example/')
            raise OSError('offline')
    assert module.check_version('http://intranet.example',1,1,opener=Offline(),allow_http_origin='http://intranet.example')['status']=='unavailable'
