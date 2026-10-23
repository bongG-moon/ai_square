"""Distinguish operation failures without leaking private driver messages."""
import re

import pytest
from pymongo.errors import (
    AutoReconnect, BulkWriteError, DuplicateKeyError, ExecutionTimeout,
    NetworkTimeout, OperationFailure, PyMongoError,
    ServerSelectionTimeoutError, WTimeoutError,
)

from pt_ai_square.backend.mongo_errors import mongo_diagnostic
from pt_ai_square.tests.conftest import ready


PRIVATE = 'mongodb://private-user:private-password@private-host/employee-data'


@pytest.mark.parametrize('error,expected,mongo_code', [
    (AutoReconnect(PRIVATE), 'DB-CONNECTION', None),
    (ServerSelectionTimeoutError(PRIVATE), 'DB-CONNECTION', None),
    (NetworkTimeout(PRIVATE), 'DB-TIMEOUT', None),
    (ExecutionTimeout(PRIVATE, 50), 'DB-TIMEOUT', 50),
    (WTimeoutError(PRIVATE, 64), 'DB-TIMEOUT', 64),
    (OperationFailure(PRIVATE, 18), 'DB-AUTHENTICATION', 18),
    (OperationFailure(PRIVATE, 13), 'DB-PERMISSION', 13),
    (DuplicateKeyError(PRIVATE, 11000), 'DB-DUPLICATE', 11000),
    (OperationFailure(PRIVATE, 121), 'DB-DOCUMENT', 121),
    (OperationFailure(PRIVATE, 225), 'DB-SESSION-ORDER', 225),
    (OperationFailure(PRIVATE, 40324), 'DB-OPERATION', 40324),
    (BulkWriteError({'writeErrors': [{'code': 11000, 'errmsg': PRIVATE, 'op': {'secret': PRIVATE}}]}), 'DB-BULK-WRITE', 65),
    (PyMongoError(PRIVATE), 'DB-ERROR', None),
])
def test_diagnostic_only_includes_static_text_and_numeric_code(error, expected, mongo_code):
    diagnostic = mongo_diagnostic(error)
    assert diagnostic['code'] == expected
    assert diagnostic['mongo_code'] == mongo_code
    assert PRIVATE not in str(diagnostic)
    assert set(diagnostic) == {'code', 'mongo_code', 'message'}


@pytest.mark.parametrize('code', [PRIVATE, True, -1, 2**40])
def test_server_code_is_validated_before_disclosure(code):
    diagnostic = mongo_diagnostic(OperationFailure(PRIVATE, code))
    assert diagnostic['mongo_code'] is None
    assert PRIVATE not in str(diagnostic)


def test_healthy_ping_does_not_hide_login_write_permission_failure(app, monkeypatch, caplog):
    from pt_ai_square.backend import auth
    client = app.test_client()
    health = client.get('/health')
    assert health.status_code == 200 and health.json['storage'] == 'mongodb'
    client.set_cookie('test_employee', 'owner')

    def denied(*args, **kwargs):
        raise OperationFailure(PRIVATE, 13, {'errmsg': PRIVATE, 'code': 13})

    monkeypatch.setattr(auth, 'ensure_user', denied)
    response = client.get('/login')
    assert response.status_code == 503
    diagnostic = response.json['diagnostic']
    assert diagnostic['code'] == 'DB-PERMISSION'
    assert diagnostic['mongo_code'] == 13
    assert '권한' in response.json['error']
    assert 'DB-PERMISSION' in response.json['error']
    assert re.fullmatch('[0-9a-f]{12}', diagnostic['reference'])
    assert diagnostic['reference'] in caplog.text
    assert PRIVATE not in response.get_data(as_text=True) + caplog.text
    assert 'HCP SSO failure' not in caplog.text
    with client.session_transaction() as session:
        assert '_hcp_login' not in session
    assert client.get('/api/bootstrap').status_code == 401


def test_api_read_failure_stays_json_even_with_browser_accept(app, monkeypatch, caplog):
    client, _ = ready(app)
    endpoint = next(rule.endpoint for rule in app.url_map.iter_rules() if rule.rule == '/api/bootstrap')

    def unsupported():
        raise OperationFailure(PRIVATE, 40324, {'errmsg': PRIVATE, 'pipeline': PRIVATE})

    monkeypatch.setitem(app.view_functions, endpoint, unsupported)
    response = client.get('/api/bootstrap', headers={'Accept': 'text/html'})
    assert response.status_code == 503 and response.is_json
    assert response.json['diagnostic']['code'] == 'DB-OPERATION'
    assert response.json['diagnostic']['mongo_code'] == 40324
    assert 'DB-OPERATION' in response.json['error']
    assert '40324' in response.json['error']
    assert response.headers['Cache-Control'] == 'no-store'
    assert PRIVATE not in response.get_data(as_text=True) + caplog.text


def test_browser_failure_shows_readable_diagnostics_without_sso_instructions(app, monkeypatch):
    from pt_ai_square.backend import auth
    client = app.test_client()
    client.set_cookie('test_employee', 'owner')

    def invalid_document(*args, **kwargs):
        raise OperationFailure(PRIVATE, 121)

    monkeypatch.setattr(auth, 'ensure_user', invalid_document)
    response = client.get('/login', headers={'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'})
    text = response.get_data(as_text=True)
    assert response.status_code == 503 and response.mimetype == 'text/html'
    assert 'DB-DOCUMENT' in text and '<code>121</code>' in text
    assert '문의 번호' in text and '홈으로 이동' in text
    assert 'SSO 사용 설정' not in text and PRIVATE not in text
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['X-Frame-Options'] == 'DENY'


def test_health_error_retains_json_and_no_automatic_retry(app, monkeypatch):
    calls = []

    def failed_health():
        calls.append('ping')
        raise AutoReconnect(PRIVATE)

    monkeypatch.setitem(app.view_functions, 'health', failed_health)
    response = app.test_client().get('/health', headers={'Accept': 'text/html'})
    assert response.status_code == 503 and response.is_json
    assert response.json['diagnostic']['code'] == 'DB-CONNECTION'
    assert calls == ['ping']


def test_diagnostic_log_uses_route_template_and_effective_option_without_path_values(app,monkeypatch,caplog):
    client,headers=ready(app)
    endpoint=next(rule.endpoint for rule in app.url_map.iter_rules() if rule.rule=='/api/local-tokens/<token_id>')
    def failed(token_id):raise OperationFailure(PRIVATE,225)
    monkeypatch.setitem(app.view_functions,endpoint,failed)
    response=client.delete('/api/local-tokens/private-row-identity?private-query-value',headers=headers)
    assert response.status_code==503
    assert 'method=DELETE route=/api/local-tokens/<token_id> retry_writes=False' in caplog.text
    assert PRIVATE not in caplog.text
    assert 'private-row-identity' not in caplog.text and 'private-query-value' not in caplog.text
