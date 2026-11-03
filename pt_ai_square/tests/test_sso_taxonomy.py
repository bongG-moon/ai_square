"""SSO identity onboarding must not automatically enable catalog organizations."""
import pytest

from .conftest import FixtureSSO, publish, ready
from pt_ai_square.backend.storage import db


def use_profiles(app, profiles):
    class ProfileSSO(FixtureSSO):
        def get_sso_info(self, cookie):
            department, code = profiles.get(self.uid, ('공통', ''))
            return self.uid, self.uid, '', department, '', code
    app.config['SSO_FACTORY'] = ProfileSSO


def test_new_sso_org_is_inactive_but_accounts_can_log_in_and_publish(app):
    use_profiles(app, {'first': ('새로운 조직', 'NEW-DEPT'), 'second': ('새로운 조직', 'NEW-DEPT')})
    first, headers = ready(app, 'first')
    bootstrap = first.get('/api/bootstrap')
    assert bootstrap.status_code == 200
    org_id = bootstrap.json['user']['orgId']
    with app.app_context():
        organization = db().taxonomy.find_one({'_id': org_id})
        assert organization['name'] == '새로운 조직' and organization['enabled'] is False
        assert db().users.find_one({'_id': 'first'})['enabled'] is True
    assert org_id not in {row['id'] for row in first.get('/api/catalog/options').json['organizations']}
    assert publish(first, headers, org='새로운 조직').status_code == 400
    assert publish(first, headers, org='공통').status_code == 201

    # A fresh session and a different employee must reuse the inactive row.
    for uid in ('first', 'second'):
        client, _ = ready(app, uid)
        user = client.get('/api/bootstrap').json['user']
        assert user['orgId'] == org_id
        assert user['dept'] == '새로운 조직' and user['dept_cd'] == 'NEW-DEPT'
    with app.app_context():
        assert db().taxonomy.count_documents({'kind': 'organization', 'ssoCode': 'NEW-DEPT'}) == 1
        assert db().taxonomy.find_one({'_id': org_id})['enabled'] is False
    admin, _ = ready(app, 'admin')
    visible = {row['id']: row for row in admin.get('/api/bootstrap').json['organizations']}
    assert visible[org_id]['enabled'] is False


def test_admin_org_activation_and_existing_org_setting_survive_sso_login(app):
    use_profiles(app, {'first': ('새로운 조직', 'NEW-DEPT'), 'second': ('새로운 조직', 'NEW-DEPT'),
                       'existing': ('장비팀', 'EXISTING-DEPT')})
    first, _ = ready(app, 'first')
    org_id = first.get('/api/bootstrap').json['user']['orgId']
    admin, headers = ready(app, 'admin')
    assert admin.post('/api/taxonomy', json={
        'id': org_id, 'kind': 'organization', 'name': '새로운 조직', 'enabled': True,
    }, headers=headers).status_code == 200

    for uid in ('first', 'second'):
        client, _ = ready(app, uid)
        assert org_id in {row['id'] for row in client.get('/api/catalog/options').json['organizations']}
    existing, _ = ready(app, 'existing')
    assert existing.get('/api/bootstrap').json['user']['orgId'] == 'organization-2'
    with app.app_context():
        assert db().taxonomy.find_one({'_id': org_id})['enabled'] is True
        assert db().taxonomy.find_one({'_id': 'organization-2'})['enabled'] is True

    assert admin.post('/api/taxonomy', json={
        'id': org_id, 'kind': 'organization', 'name': '새로운 조직', 'enabled': False,
    }, headers=headers).status_code == 200
    second, _ = ready(app, 'second')
    assert second.get('/api/bootstrap').status_code == 200
    assert org_id not in {row['id'] for row in second.get('/api/catalog/options').json['organizations']}


@pytest.mark.parametrize('code', ['ORG-A', ''])
def test_new_member_of_transferred_sso_org_follows_target_without_recreation(app, code):
    use_profiles(app, {'first': ('A 조직', code), 'second': ('A 조직', code)})
    first, _ = ready(app, 'first')
    source_id = first.get('/api/bootstrap').json['user']['orgId']
    admin, headers = ready(app, 'admin')
    with app.app_context():
        assert db().taxonomy.find_one({'_id': source_id})['enabled'] is False
    result = admin.post(f'/api/taxonomy/{source_id}/delete', json={
        'confirmed': True, 'targetId': 'organization-3',
    }, headers=headers)
    assert result.status_code == 200
    assert result.json['moved']['users'] == 1

    for uid in ('first', 'second'):
        client, _ = ready(app, uid)
        user = client.get('/api/bootstrap').json['user']
        assert user['orgId'] == 'organization-3' and user['org'] == '기술팀'
        assert user['dept'] == 'A 조직' and user['dept_cd'] == code
    with app.app_context():
        assert db().taxonomy.count_documents({'kind': 'organization', 'name': 'A 조직'}) == 1
        assert db().taxonomy.find_one({'_id': source_id})['deleted'] is True
        assert db().taxonomy.find_one({'_id': 'organization-3'})['enabled'] is True
