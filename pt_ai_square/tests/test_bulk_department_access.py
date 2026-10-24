"""Batch/group permissions against the disposable local MongoDB test database."""
import pytest
from flask import g
from pymongo.errors import OperationFailure
from werkzeug.exceptions import BadRequest
from pt_ai_square.backend import department_access, mongo_api
from pt_ai_square.backend.storage import db, ensure_user
from .conftest import ready, publish


def department(app, uid, name, code=''):
    with app.app_context():
        ensure_user(uid, uid, name, code)


def setup_private(app):
    owner, headers = ready(app)
    assert publish(owner, headers, approval=True).status_code == 201
    return owner, headers


def test_bulk_preview_dedup_and_unknown_do_not_grant(app):
    owner, h = setup_private(app)
    result = owner.post('/api/tools/1/grants/preview', json={
        'mode': 'users', 'value': 'member, other\nmember; missing'}, headers=h)
    assert result.status_code == 200
    assert [r['id'] for r in result.json['users']] == ['member', 'other']
    assert result.json['unknown'] == ['missing']
    with app.app_context():
        assert db().access.count_documents({'tool': 1}) == 0
    invalid = owner.post('/api/tools/1/grants', json={'users': ['member', 'missing']}, headers=h)
    assert invalid.status_code == 400
    with app.app_context():
        assert db().access.count_documents({'tool': 1}) == 0


def test_bulk_grant_repeated_request_and_legacy_single_are_idempotent(app):
    owner, h = setup_private(app)
    first = owner.post('/api/tools/1/grants', json={'users': ['member', 'other', 'member']}, headers=h)
    assert first.status_code == 200 and first.json['saved'] == ['member', 'other']
    second = owner.post('/api/tools/1/grants', json={'user': 'member'}, headers=h)
    assert second.status_code == 200 and second.json['alreadyGranted'] == ['member']
    rows = owner.get('/api/tools/1/grants').json['users']
    assert {row['id'] for row in rows} == {'member', 'other'}
    with app.app_context():
        assert len(db().access.find_one({'tool': 1, 'user': 'member'})['history']) == 1
    member, _ = ready(app, 'member')
    assert member.get('/api/tools/1').status_code == 200
    assert member.get('/download/1/1').status_code == 200


@pytest.mark.parametrize('body', [{'users': []}, {'users': [str(i) for i in range(101)]}, {'users': [None]}, {'users': 'member'}, {'users': ['']}])
def test_bulk_bad_payload_is_rejected_without_writes(app, body):
    owner, h = setup_private(app)
    result = owner.post('/api/tools/1/grants', json=body, headers=h)
    # A string users payload is accepted by the shared parser for pasted lists.
    if body == {'users': 'member'}:
        assert result.status_code == 200
    else:
        assert result.status_code == 400
        with app.app_context(): assert db().access.count_documents({}) == 0


def test_employee_paste_tolerates_trailing_separators_and_counts_unique_ids():
    assert department_access.employee_ids(',1001,1002,\n； ') == ['1001', '1002']
    assert department_access.employee_ids('1001,' * 101) == ['1001']
    assert department_access.employee_ids(['1001'] * 101) == ['1001']
    for invalid in [', \n;', 'x' * 12001, ['1001', ''], ['1001', None], [str(i) for i in range(101)]]:
        with pytest.raises(BadRequest): department_access.employee_ids(invalid)


def test_trailing_separators_bulk_preview_and_save(app):
    owner, h = setup_private(app)
    preview = owner.post('/api/tools/1/grants/preview', json={'mode': 'users', 'value': 'member,other,\n'}, headers=h)
    assert preview.status_code == 200 and preview.json['unknown'] == []
    assert preview.json['count'] == 2
    result = owner.post('/api/tools/1/grants', json={'users': 'member,other,\n'}, headers=h)
    assert result.status_code == 200 and result.json['saved'] == ['member', 'other']


def test_bulk_partial_write_failure_is_not_reported_as_success(app, monkeypatch):
    owner, h = setup_private(app)
    original = mongo_api.grant_employee
    def fail_other(t, uid):
        if uid == 'other': raise OperationFailure('private diagnostic omitted', code=225)
        return original(t, uid)
    monkeypatch.setattr(mongo_api, 'grant_employee', fail_other)
    result = owner.post('/api/tools/1/grants', json={'users': ['member', 'other']}, headers=h)
    assert result.status_code == 207 and result.json['ok'] is False
    assert result.json['saved'] == ['member'] and result.json['failed'][0]['id'] == 'other'
    assert 'private diagnostic' not in str(result.json)
    with app.app_context():
        assert db().access.find_one({'tool': 1, 'user': 'member'})['granted']
        assert db().access.find_one({'tool': 1, 'user': 'other'}) is None
    monkeypatch.setattr(mongo_api, 'grant_employee', original)
    retry = owner.post('/api/tools/1/grants', json={'users': ['member', 'other']}, headers=h)
    assert retry.json['alreadyGranted'] == ['member'] and retry.json['saved'] == ['other']


def test_department_search_code_select_and_dynamic_membership(app):
    owner, h = setup_private(app)
    member, _ = ready(app, 'member')
    other, _ = ready(app, 'other')
    department(app, 'member', '융합기술팀', 'D001')
    department(app, 'other', '융합기술팀', 'D002')
    search = owner.post('/api/tools/1/grants/preview', json={'mode': 'department', 'value': '융합'}, headers=h)
    assert {row['code'] for row in search.json['departments']} == {'D001', 'D002'}
    result = owner.post('/api/tools/1/grants/departments', json={'departments': [{'code': 'D001', 'name': '융합기술팀'}]}, headers=h)
    assert result.status_code == 200 and result.json['revision'] == 2
    assert member.get('/api/tools/1').status_code == 200
    assert member.get('/download/1/1').status_code == 200
    assert other.get('/api/tools/1').status_code == 403
    department(app, 'other', '부서 이름 변경', 'D001')
    assert other.get('/api/tools/1').status_code == 200
    department(app, 'member', '다른팀', 'D009')
    assert member.get('/api/tools/1').status_code == 403
    row = owner.get('/api/tools/1/grants').json['departments'][0]
    assert row['memberCount'] == 1 and row['name'] == '부서 이름 변경'


def test_department_code_collapse_and_no_code_exact_matching(app):
    owner, h = setup_private(app)
    member, _ = ready(app, 'member')
    other, _ = ready(app, 'other')
    department(app, 'member', '동일부서', '')
    department(app, 'other', '동일부서', 'DIFFERENT')
    result = owner.post('/api/tools/1/grants/departments', json={'departments': [{'code': '', 'name': '동일부서'}]}, headers=h)
    assert result.status_code == 200
    assert member.get('/api/tools/1').status_code == 200
    assert other.get('/api/tools/1').status_code == 403
    department(app, 'member', '부서A', 'SAME')
    department(app, 'other', '부서B', 'SAME')
    search = owner.post('/api/tools/1/grants/preview', json={'mode': 'department', 'value': 'SAME'}, headers=h)
    assert search.json['count'] == 1 and search.json['departments'][0]['memberCount'] == 2


def test_department_revoke_preserves_direct_grants_and_marks_inheritance(app):
    owner, h = setup_private(app)
    member, _ = ready(app, 'member')
    department(app, 'member', '팀', 'A')
    owner.post('/api/tools/1/grants', json={'users': ['member']}, headers=h)
    owner.post('/api/tools/1/grants/departments', json={'departments': [{'code': 'A', 'name': '팀'}]}, headers=h)
    grants = owner.get('/api/tools/1/grants').json
    assert grants['users'][0]['inheritedDepartments'][0]['code'] == 'A'
    rule = grants['departments'][0]
    revoked = owner.delete('/api/tools/1/grants/departments/'+rule['id'], json={'expectedRevision': grants['revision']}, headers=h)
    assert revoked.status_code == 200
    assert member.get('/api/tools/1').status_code == 200
    owner.post('/api/requests/1:member/decision', json={'status': '회수', 'reason': '종료'}, headers=h)
    assert member.get('/api/tools/1').status_code == 403


def test_department_grant_atomic_revision_and_retry(app):
    owner, h = setup_private(app)
    department(app, 'member', '팀', 'A')
    body = {'departments': [{'code': 'A', 'name': '팀'}], 'expectedRevision': 1}
    assert owner.post('/api/tools/1/grants/departments', json=body, headers=h).status_code == 200
    assert owner.post('/api/tools/1/grants/departments', json=body, headers=h).status_code == 409
    del body['expectedRevision']
    result = owner.post('/api/tools/1/grants/departments', json=body, headers=h)
    assert result.json['revision'] == 2
    assert len(owner.get('/api/tools/1/grants').json['departments']) == 1


def test_unknown_and_disabled_profiles_cannot_create_or_use_department_rule(app):
    owner, h = setup_private(app)
    member, _ = ready(app, 'member')
    department(app, 'member', '팀', 'A')
    assert owner.post('/api/tools/1/grants/departments', json={'departments': [{'code': 'unknown', 'name': '팀'}]}, headers=h).status_code == 400
    assert owner.post('/api/tools/1/grants/departments', json={'departments': [{'code': 'A', 'name': '팀'}]}, headers=h).status_code == 200
    with app.app_context(): db().users.update_one({'_id': 'member'}, {'$set': {'enabled': False}})
    assert member.get('/api/tools/1').status_code == 401
    result = owner.post('/api/tools/1/grants/preview', json={'mode': 'users', 'value': 'member'}, headers=h)
    assert result.json['unknown'] == ['member']
    assert owner.get('/api/tools/1/grants').json['departments'][0]['memberCount'] == 0


def test_disabled_owner_and_admin_never_bypass_authorization(app):
    owner, h = setup_private(app)
    admin, _ = ready(app, 'admin')
    with app.app_context():
        record = db().tools.find_one({'_id': 1})
        db().users.update_many({'_id': {'$in': ['owner', 'admin']}}, {'$set': {'enabled': False}})
    assert owner.get('/api/tools/1').status_code == 401
    assert admin.get('/api/tools/1').status_code == 401
    with app.test_request_context('/'):
        # Followers and other explicit-user checks read the current DB state.
        g.user = {'id': 'member', 'enabled': True}
        assert mongo_api.allowed(record, 'owner') is False
        assert mongo_api.allowed(record, 'admin') is False
        # The already-authenticated request profile is also checked first.
        g.user = {'id': 'owner', 'enabled': False}
        assert mongo_api.allowed(record) is False


def test_owner_and_admin_only_and_csrf_still_required(app):
    owner, h = setup_private(app)
    other, oh = ready(app, 'other')
    for path, method, body in [
        ('/api/tools/1/grants', 'get', None),
        ('/api/tools/1/grants/preview', 'post', {'mode': 'users', 'value': 'member'}),
        ('/api/tools/1/grants', 'post', {'users': ['member']}),
        ('/api/tools/1/grants/departments', 'post', {'departments': [{'code': '', 'name': '공통'}]}),
        ('/api/tools/1/grants/departments/x', 'delete', {})]:
        assert getattr(other, method)(path, json=body, headers=oh).status_code == 403
    assert owner.post('/api/tools/1/grants', json={'users': ['member']}).status_code == 403
    admin, ah = ready(app, 'admin')
    assert admin.get('/api/tools/1/grants').status_code == 200
    assert admin.post('/api/tools/1/grants', json={'users': ['member']}, headers=ah).status_code == 200


def test_api_key_can_read_group_authorized_tool_but_never_manage_grants(app):
    owner, h = setup_private(app)
    member, mh = ready(app, 'member')
    department(app, 'member', '팀', 'A')
    owner.post('/api/tools/1/grants/departments', json={'departments': [{'code': 'A', 'name': '팀'}]}, headers=h)
    token = member.post('/api/local-tokens', json={'name': 'test', 'scope': 'publish'}, headers=mh).json['token']
    bearer = {'Authorization': 'Bearer '+token}
    assert member.get('/api/tools/1', headers=bearer).status_code == 200
    assert member.get('/download/1/1', headers=bearer).status_code == 200
    for uid in ['owner', 'admin']:
        actor, ah = ready(app, uid)
        key = actor.post('/api/local-tokens', json={'name': 'test', 'scope': 'publish'}, headers=ah).json['token']
        auth = {'Authorization': 'Bearer '+key}
        assert actor.get('/api/tools/1/grants', headers=auth).status_code == 403
        assert actor.post('/api/tools/1/grants/preview', json={'mode': 'users', 'value': 'member'}, headers=auth).status_code == 403
        assert actor.post('/api/tools/1/grants', json={'users': ['member']}, headers=auth).status_code == 403
        assert actor.post('/api/tools/1/grants/departments', json={'departments': [{'code': 'A', 'name': '팀'}]}, headers=auth).status_code == 403
        assert actor.delete('/api/tools/1/grants/departments/x', headers=auth).status_code == 403


def test_department_primary_failure_is_not_hidden_and_followup_failure_is_deferred(app, monkeypatch):
    owner, h = setup_private(app)
    department(app, 'member', '팀', 'A')
    original = mongo_api.cas
    def fail_primary(*args, **kwargs): raise OperationFailure('fixture', code=225)
    monkeypatch.setattr(mongo_api, 'cas', fail_primary)
    result = owner.post('/api/tools/1/grants/departments', json={'departments': [{'code': 'A', 'name': '팀'}]}, headers=h)
    assert result.status_code >= 400
    with app.app_context(): assert not db().tools.find_one({'_id': 1}).get('departmentGrants')
    monkeypatch.setattr(mongo_api, 'cas', original)
    def fail_followup(*args, **kwargs): raise OperationFailure('fixture', code=225)
    monkeypatch.setattr(mongo_api, 'deliver_notifications', fail_followup)
    result = owner.post('/api/tools/1/grants/departments', json={'departments': [{'code': 'A', 'name': '팀'}]}, headers=h)
    assert result.status_code == 200 and result.json['pending'] is True
    with app.app_context():
        saved = db().tools.find_one({'_id': 1})
        assert saved['departmentGrants'][0]['code'] == 'A' and saved['outbox']
