"""Taxonomy removal preserves related content and the exact SSO identity."""
import copy
import threading
import time

import pytest
from pymongo.errors import AutoReconnect

from .conftest import publish, ready
from pt_ai_square.backend.storage import db, ensure_user, init_db
from pt_ai_square.backend import mongo_api, taxonomy_delete


def remove(client, headers, key, target=None, **extra):
    body = {'confirmed': True, **extra}
    if target is not None:
        body['targetId'] = target
    return client.post(f'/api/taxonomy/{key}/delete', json=body, headers=headers)


def test_admin_confirmation_and_default_organization_protection(app):
    member, h = ready(app)
    admin, ah = ready(app, 'admin')
    assert member.get('/api/taxonomy/category-2/deletion-preview').status_code == 403
    assert remove(member, h, 'category-2').status_code == 403
    assert admin.post('/api/taxonomy/category-2/delete', json={'confirmed': True}).status_code == 403
    for value in (None, False, 'true', 1):
        assert remove(admin, ah, 'category-2', confirmed=value).status_code == 400
    preview = admin.get('/api/taxonomy/organization-0/deletion-preview').json
    assert preview['protected'] and preview['reason']
    assert remove(admin, ah, 'organization-0', 'organization-1').status_code == 400
    assert remove(admin, ah, 'missing').status_code == 404


def test_empty_category_deletion_idempotent_hidden_and_not_reseeded(app):
    admin, ah = ready(app, 'admin')
    preview = admin.get('/api/taxonomy/category-2/deletion-preview').json
    assert preview['usage']['total'] == 0
    assert 'category-2' not in {r['id'] for r in preview['targets']}
    first = remove(admin, ah, 'category-2')
    assert first.status_code == 200 and first.json['deleted'] and not first.json['pending']
    retry = remove(admin, ah, 'category-2')
    assert retry.status_code == 200 and retry.json['replayed']
    assert remove(admin, ah, 'category-2', 'category-1').status_code == 409
    with app.app_context():
        assert db().taxonomy.find_one({'_id': 'category-2'})['deleted']
        init_db(app)
        assert db().taxonomy.count_documents({'kind': 'category', 'name': '장비'}) == 1
    assert 'category-2' not in {r['id'] for r in admin.get('/api/bootstrap').json['categories']}
    assert 'category-2' not in {r['id'] for r in admin.get('/api/catalog/options').json['categories']}
    assert admin.post('/api/taxonomy', headers=ah, json={
        'id': 'category-2', 'kind': 'category', 'name': '다시 쓰기'}).status_code == 404
    assert admin.post('/api/taxonomy', headers=ah, json={
        'kind': 'category', 'name': '장비'}).status_code == 409


def test_category_transfer_preserves_tools_trash_requests_and_package(app):
    owner, h = ready(app)
    admin, ah = ready(app, 'admin')
    assert publish(owner, h, category='장비').status_code == 201
    assert publish(owner, h, category='장비', name='휴지통 도구').status_code == 201
    assert owner.delete('/api/tools/2', json={'expectedRevision': 1}, headers=h).status_code == 200
    assert owner.post('/api/ideas', json={'name': '요청', 'desc': '이 기능이 필요합니다', 'category': '장비'}, headers=h).status_code == 201
    with app.app_context():
        before = list(db().tools.find().sort('_id'))
    preview = admin.get('/api/taxonomy/category-2/deletion-preview').json
    assert preview['usage'] == {'tools': 2, 'ideas': 1, 'users': 0, 'total': 3}
    assert remove(admin, ah, 'category-2').status_code == 409
    result = remove(admin, ah, 'category-2', 'category-1')
    assert result.status_code == 200 and result.json['moved']['tools'] == 2
    with app.app_context():
        after = list(db().tools.find().sort('_id'))
        for old, new in zip(before, after):
            assert new['data']['categoryId'] == 'category-1' and new['data']['category'] == '제조'
            assert new['versions'] == old['versions'] and new['owner'] == old['owner']
            assert new['revision'] == old['revision'] + 1 and new['deleted'] == old['deleted']
        idea = db().ideas.find_one({'_id': 1})
        assert idea['categoryId'] == 'category-1' and idea['category'] == '제조' and idea['revision'] == 1
    # A stale prepared payload cannot recreate a deleted classification.
    assert publish(owner, h, category='장비').status_code == 400
    assert owner.patch('/api/tools/1', json={'name': '오래된 편집', 'expectedRevision': 1}, headers=h).status_code == 409
    assert owner.get('/api/tools/1').json['category'] == '제조'


@pytest.mark.parametrize('target', [None, 'category-2', 'organization-1', 'missing', 'category-3'])
def test_in_use_category_rejects_invalid_destination_without_changes(app, target):
    owner, h = ready(app)
    admin, ah = ready(app, 'admin')
    assert publish(owner, h, category='장비').status_code == 201
    with app.app_context():
        db().taxonomy.update_one({'_id': 'category-3'}, {'$set': {'enabled': False}})
    assert remove(admin, ah, 'category-2', target).status_code in {400, 409}
    with app.app_context():
        assert not db().taxonomy.find_one({'_id': 'category-2'}).get('deletion')
        assert db().tools.find_one({'_id': 1})['data']['categoryId'] == 'category-2'


def test_organization_transfer_preserves_sso_and_repeated_login_follows_alias(app):
    owner, h = ready(app)
    admin, ah = ready(app, 'admin')
    assert publish(owner, h, org='장비팀').status_code == 201
    with app.app_context():
        ensure_user('employee', '구성원', '장비팀', org_code='DEPT-OLD')
        ensure_user('target-employee', '대상 구성원', '기술팀', org_code='DEPT-NEW')
        db().tools.update_one({'_id': 1}, {'$set': {'departmentGrants': [{'kind': 'code', 'value': 'DEPT-OLD'}]}})
        before = copy.deepcopy(db().users.find_one({'_id': 'employee'}))
    preview = admin.get('/api/taxonomy/organization-2/deletion-preview').json
    assert preview['usage'] == {'tools': 1, 'ideas': 0, 'users': 1, 'total': 2}
    assert remove(admin, ah, 'organization-2', 'organization-3').status_code == 200
    with app.app_context():
        after = db().users.find_one({'_id': 'employee'})
        assert after == {**before, 'orgId': 'organization-3'}
        ensure_user('employee', '구성원', '장비팀', org_code='DEPT-OLD')
        ensure_user('new-employee', '새 구성원', '장비팀', org_code='DEPT-OLD')
        for uid in ('employee', 'new-employee'):
            row = db().users.find_one({'_id': uid})
            assert row['orgId'] == 'organization-3' and row['dept'] == '장비팀' and row['dept_cd'] == 'DEPT-OLD'
        assert db().taxonomy.find_one({'_id': 'organization-3'})['ssoCode'] == 'DEPT-NEW'
        assert db().taxonomy.find_one({'_id': 'organization-2'})['ssoCode'] == 'DEPT-OLD'
        assert db().tools.find_one({'_id': 1})['departmentGrants'] == [{'kind': 'code', 'value': 'DEPT-OLD'}]
        assert db().taxonomy.count_documents({'kind': 'organization', 'name': '장비팀'}) == 1


def test_unused_organization_future_sso_uses_common_without_recreation(app):
    admin, ah = ready(app, 'admin')
    assert remove(admin, ah, 'organization-2').status_code == 200
    with app.app_context():
        ensure_user('future', '새 구성원', '장비팀', org_code='OLD-CODE')
        user = db().users.find_one({'_id': 'future'})
        assert user['orgId'] == 'organization-0' and user['dept_cd'] == 'OLD-CODE' and user['dept'] == '장비팀'
        assert not db().taxonomy.find_one({'_id': 'organization-0'}).get('ssoCode')


def test_partial_failure_keeps_target_locked_and_retry_finishes_once(app, monkeypatch):
    owner, h = ready(app)
    admin, ah = ready(app, 'admin')
    assert publish(owner, h, category='장비').status_code == 201
    assert owner.post('/api/ideas', json={'name': '요청', 'desc': '필요합니다', 'category': '장비'}, headers=h).status_code == 201
    original = taxonomy_delete._move_references
    def partial(source, target):
        db().tools.update_many({'data.categoryId': source['_id']}, {
            '$set': {'data.categoryId': target['_id'], 'data.category': target['name']}, '$inc': {'revision': 1}})
        raise AutoReconnect('isolated failure')
    monkeypatch.setattr(taxonomy_delete, '_move_references', partial)
    assert remove(admin, ah, 'category-2', 'category-1').status_code == 503
    preview = admin.get('/api/taxonomy/category-2/deletion-preview').json
    assert preview['pending'] and not preview['deleted'] and preview['lockedTargetId'] == 'category-1'
    assert preview['usage'] == {'tools': 0, 'ideas': 1, 'users': 0, 'total': 1}
    assert remove(admin, ah, 'category-2', 'category-3').status_code == 409
    assert remove(admin, ah, 'category-1', 'category-3').status_code == 409
    assert admin.post('/api/taxonomy', json={'id': 'category-1', 'kind': 'category', 'name': '변경'}, headers=ah).status_code == 409
    assert publish(owner, h, category='장비').status_code == 400
    monkeypatch.setattr(taxonomy_delete, '_move_references', original)
    assert remove(admin, ah, 'category-2', 'category-1').status_code == 200
    assert remove(admin, ah, 'category-2', 'category-1').json['replayed']
    with app.app_context():
        assert db().tools.find_one({'_id': 1})['revision'] == 2
        assert db().ideas.find_one({'_id': 1})['categoryId'] == 'category-1'
        assert db().audit.count_documents({'action': '업무 분류 장비 삭제 / 제조으로 이관'}) == 1


def test_delete_waits_for_publication_then_transfers_new_reference(app, monkeypatch):
    owner, h = ready(app)
    admin, ah = ready(app, 'admin')
    entered, release, deleting = threading.Event(), threading.Event(), threading.Event()
    original = mongo_api.publication_data
    def pause(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(mongo_api, 'publication_data', pause)
    results = {}
    def create(): results['publish'] = publish(owner, h, category='장비')
    def erase():
        deleting.set()
        results['delete'] = remove(admin, ah, 'category-2', 'category-1')
    publisher = threading.Thread(target=create)
    deleter = threading.Thread(target=erase)
    publisher.start()
    try:
        assert entered.wait(5)
        deleter.start()
        assert deleting.wait(5)
        time.sleep(.1)
    finally:
        release.set()
        publisher.join(8)
        if deleter.ident:
            deleter.join(8)
    assert not publisher.is_alive() and not deleter.is_alive()
    assert results['publish'].status_code == 201 and results['delete'].status_code == 200
    with app.app_context():
        assert db().tools.find_one({'_id': 1})['data']['categoryId'] == 'category-1'
        assert db().tools.count_documents({'data.categoryId': 'category-2'}) == 0
