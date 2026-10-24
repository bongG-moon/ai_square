"""Read-only recovery of browser publications whose HTTP response was lost."""
import copy
import uuid

import pytest
from pymongo.collection import Collection

from pt_ai_square.backend import mongo_api
from pt_ai_square.backend.storage import db
from .conftest import publish, ready
from .test_personal_api_usage import issue


def receipt(client, request_id):
    return client.get('/api/publish-requests/' + request_id)


def test_saved_zip_and_old_version_receipts_return_the_matching_release(app):
    browser, csrf = ready(app)
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    assert publish(browser, csrf, clientRequestId=first).status_code == 201
    assert publish(browser, csrf, tid=1, revision=1,
                   changes='새 기능', clientRequestId=second).status_code == 201
    for request_id, number in ((first, 1), (second, 2)):
        result = receipt(browser, request_id)
        assert result.status_code == 200
        assert result.json == dict(status='confirmed', id=1, version=number,
                                   pending=False, packageRecognized=False,
                                   packageWarning='', deploymentUrl=None)
        assert result.headers['Cache-Control'] == 'no-store'
    with app.app_context():
        assert db().tools.count_documents({}) == 1
        assert len(db().tools.find_one({'_id': 1})['versions']) == 2


def test_receipt_preserves_package_result_without_exposing_server_paths(app):
    browser, csrf = ready(app)
    request_id = str(uuid.uuid4())
    assert publish(browser, csrf, clientRequestId=request_id).status_code == 201
    with app.app_context():
        db().tools.update_one({'_id': 1}, {'$set': {
            'versions.0.package': {'packageId': 'example-skill'},
            'versions.0.packageWarning': '배포 정보 일부를 확인해 주세요.',
        }})
    result = receipt(browser, request_id).json
    assert result['packageRecognized'] is True
    assert result['packageWarning'] == '배포 정보 일부를 확인해 주세요.'
    assert result['deploymentUrl'] == '/api/tools/1/releases/1/deployment'
    assert set(result) == {'status', 'id', 'version', 'pending',
                           'packageRecognized', 'packageWarning', 'deploymentUrl'}


def test_missing_and_legacy_publications_are_unconfirmed_not_failed(app):
    browser, csrf = ready(app)
    assert publish(browser, csrf).status_code == 201  # Legacy versions lack request IDs.
    result = receipt(browser, str(uuid.uuid4()))
    assert result.status_code == 200 and result.json == {'status': 'unconfirmed'}


@pytest.mark.parametrize('employee', ['member', 'admin'])
def test_request_ids_are_employee_scoped_even_for_administrators(app, employee):
    owner, csrf = ready(app)
    request_id = str(uuid.uuid4())
    assert publish(owner, csrf, approval=True, clientRequestId=request_id).status_code == 201
    stranger, _ = ready(app, employee)
    response = receipt(stranger, request_id)
    assert response.status_code == 200 and response.json == {'status': 'unconfirmed'}
    assert receipt(owner, request_id).json['status'] == 'confirmed'


@pytest.mark.parametrize('changes', [
    {'deleted': True},
    {'purge': {'state': 'running'}},
    {'owner': 'other'},
])
def test_current_tool_state_and_management_access_are_rechecked(app, changes):
    browser, csrf = ready(app)
    request_id = str(uuid.uuid4())
    assert publish(browser, csrf, clientRequestId=request_id).status_code == 201
    with app.app_context():
        db().tools.update_one({'_id': 1}, {'$set': changes})
    result = receipt(browser, request_id)
    assert result.status_code == 200 and result.json == {'status': 'unconfirmed'}


def test_administrator_receipt_requires_current_management_rights(app):
    owner, csrf = ready(app)
    assert publish(owner, csrf).status_code == 201
    administrator, admin_csrf = ready(app, 'admin')
    request_id = str(uuid.uuid4())
    assert publish(administrator, admin_csrf, tid=1, revision=1,
                   clientRequestId=request_id).status_code == 201
    assert receipt(administrator, request_id).json['version'] == 2
    app.config['ADMIN_IDS'] = ''
    assert receipt(administrator, request_id).json == {'status': 'unconfirmed'}


@pytest.mark.parametrize('request_id', ['not-a-uuid', '123', 'x' * 100])
def test_invalid_request_ids_are_rejected(app, request_id):
    browser, _ = ready(app)
    result = receipt(browser, request_id)
    assert result.status_code == 400


def test_uuid_canonicalization_matches_the_publish_identity(app):
    browser, csrf = ready(app)
    value = uuid.uuid4()
    assert publish(browser, csrf, clientRequestId=value.hex.upper()).status_code == 201
    assert receipt(browser, str(value)).json['status'] == 'confirmed'


def test_browser_session_is_required_and_connection_keys_are_not_allowed(app):
    owner, csrf = ready(app)
    request_id = str(uuid.uuid4())
    assert publish(owner, csrf, clientRequestId=request_id).status_code == 201
    _, auth = issue(owner, csrf)
    anonymous = app.test_client()
    assert receipt(anonymous, request_id).status_code == 401
    response = anonymous.get('/api/publish-requests/' + request_id, headers=auth)
    assert response.status_code == 403
    assert 'id' not in response.json and 'version' not in response.json


@pytest.mark.parametrize('queue', ['outbox', 'postCommit'])
def test_receipt_never_writes_or_delivers_pending_work(app, monkeypatch, queue):
    browser, csrf = ready(app)
    request_id = str(uuid.uuid4())
    assert publish(browser, csrf, clientRequestId=request_id).status_code == 201
    with app.app_context():
        db().tools.update_one({'_id': 1}, {'$set': {queue: [{'id': 'still-pending'}]}})
        original = copy.deepcopy(db().tools.find_one({'_id': 1}))
        audit_count = db().audit.count_documents({})

    def unexpected(*args, **kwargs):
        pytest.fail('A publish receipt must not write or deliver follow-up work')

    for operation in ('insert_one', 'insert_many', 'update_one', 'update_many',
                      'replace_one', 'delete_one', 'delete_many',
                      'find_one_and_update', 'find_one_and_replace', 'find_one_and_delete'):
        monkeypatch.setattr(Collection, operation, unexpected)
    monkeypatch.setattr(mongo_api, 'deliver_notifications', unexpected)
    monkeypatch.setattr(mongo_api.activity, 'flush', unexpected)
    response = receipt(browser, request_id)
    assert response.status_code == 200 and response.json['pending'] is True
    with app.app_context():
        assert db().tools.find_one({'_id': 1}) == original
        assert db().audit.count_documents({}) == audit_count
