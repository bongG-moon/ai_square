"""The detail hint only reflects the authenticated KEY's own publish scope."""
import pytest

from .conftest import publish, ready
from .test_personal_api_usage import issue
from pt_ai_square.backend.storage import db


def test_detail_hint_is_owner_key_only_and_not_web_admin_authority(app):
    owner, headers = ready(app, 'owner')
    assert publish(owner, headers).status_code == 201
    _, owner_auth = issue(owner, headers)
    member, member_headers = ready(app, 'member')
    _, member_auth = issue(member, member_headers)
    admin, admin_headers = ready(app, 'admin')
    _, admin_auth = issue(admin, admin_headers)
    api = app.test_client()

    owner_detail = api.get('/api/tools/1', headers=owner_auth)
    assert owner_detail.status_code == 200
    assert owner_detail.json['canPublishOwnUpdate'] is True
    assert api.get('/api/tools/1', headers=member_auth).json['canPublishOwnUpdate'] is False
    admin_detail = api.get('/api/tools/1', headers=admin_auth)
    assert admin_detail.json['canManage'] is True
    assert admin_detail.json['canPublishOwnUpdate'] is False
    assert owner.get('/api/tools/1').json['canPublishOwnUpdate'] is False
    assert admin.get('/api/tools/1').json['canPublishOwnUpdate'] is False


@pytest.mark.parametrize('stored_scope', ['read', 'publish', 'missing'])
def test_hint_matches_legacy_effective_connection_scope(app, stored_scope):
    owner, headers = ready(app)
    assert publish(owner, headers).status_code == 201
    token, auth = issue(owner, headers)
    with app.app_context():
        change = {'$unset': {'scope': ''}} if stored_scope == 'missing' else {'$set': {'scope': stored_scope}}
        db().local_tokens.update_one({'id': token['id']}, change)
    response = app.test_client().get('/api/tools/1', headers=auth)
    assert response.status_code == 200
    # Historical read/missing scopes have the same effective publish capability.
    assert response.json['canPublishOwnUpdate'] is True


def test_hint_does_not_bypass_key_or_tool_lifecycle(app):
    owner, headers = ready(app)
    assert publish(owner, headers, approval=True).status_code == 201
    _, auth = issue(owner, headers)
    api = app.test_client()
    assert api.get('/api/tools/1', headers=auth).json['canPublishOwnUpdate'] is True
    # No hint or protected details for a member who has not been granted access.
    member, member_headers = ready(app, 'member')
    _, member_auth = issue(member, member_headers)
    assert api.get('/api/tools/1', headers=member_auth).status_code == 403
    with app.app_context():
        db().tools.update_one({'_id': 1}, {'$set': {'deleted': True}})
    assert api.get('/api/tools/1', headers=auth).status_code == 404
    with app.app_context():
        db().tools.update_one({'_id': 1}, {'$set': {'deleted': False, 'purge': {'stage': 'in_progress'}}})
    assert api.get('/api/tools/1', headers=auth).status_code == 409
