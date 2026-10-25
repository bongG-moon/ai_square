"""Pinned platform identity never rewrites an uploaded declaration or its bytes."""
import copy
import hashlib
import io
import json
import uuid

from pt_ai_square.backend.package_identity import fixed_package_id, identity_fields
from pt_ai_square.backend.storage import db
from pt_ai_square.backend import publish_drafts
from .conftest import ready, publish
from .test_package_declaration import bundle, declaration, post
from .test_personal_api_usage import issue
from .test_publish_drafts import approve, commit, fields


def archive(package_id):
    raw = declaration()
    raw['packageId'] = package_id
    return bundle(raw)


def check_identity(value, fixed, source):
    assert value['packageId'] == fixed
    assert value['sourcePackageId'] == source
    assert value['packageIdentityChanged'] is bool(fixed and source and fixed != source)


def test_first_identity_survives_different_source_ids_rollback_and_original_byte_downloads(app):
    browser, csrf = ready(app)
    blobs = [archive(value) for value in ('original-tool', 'rewritten-tool', 'third-tool')]
    receipts = []
    for index, blob in enumerate(blobs, 1):
        request_id = str(uuid.uuid4())
        response = post(browser, csrf, blob,
                        '/api/tools' if index == 1 else '/api/tools/1/versions',
                        expectedRevision=index - 1, clientRequestId=request_id,
                        packageId='forged-tool', sourcePackageId='forged-source', packageIdentityChanged=False)
        assert response.status_code == 201, response.json
        check_identity(response.json, 'original-tool', ('original-tool', 'rewritten-tool', 'third-tool')[index - 1])
        receipts.append(request_id)
        deployment = browser.get(response.json['deploymentUrl']).json
        check_identity(deployment, 'original-tool', deployment['package']['packageId'])
        assert deployment['sha256'] == hashlib.sha256(blob).hexdigest()
        downloaded = browser.get(deployment['downloadUrl'])
        assert downloaded.data == blob
        downloaded.close()
    detail = browser.get('/api/tools/1').json
    check_identity(detail, 'original-tool', 'third-tool')
    for version in detail['versions']:
        check_identity(version, 'original-tool', version['package']['packageId'])
    check_identity(browser.get('/api/tools/1/manifest').json, 'original-tool', 'third-tool')
    replay = post(browser, csrf, blobs[1], '/api/tools/1/versions', expectedRevision=1,
                  clientRequestId=receipts[1], packageId='ignored-again')
    assert replay.status_code == 200 and replay.json['replayed'] is True
    check_identity(replay.json, 'original-tool', 'rewritten-tool')
    check_identity(browser.get('/api/publish-requests/' + receipts[1]).json, 'original-tool', 'rewritten-tool')
    assert browser.post('/api/tools/1/rollback', headers=csrf,
                        json={'version': 1, 'expectedRevision': 3}).status_code == 200
    check_identity(browser.get('/api/tools/1/manifest').json, 'original-tool', 'original-tool')
    fourth = post(browser, csrf, archive('fourth-tool'), '/api/tools/1/versions', expectedRevision=4)
    assert fourth.status_code == 201 and fourth.json['version'] == 4
    check_identity(fourth.json, 'original-tool', 'fourth-tool')
    with app.app_context():
        stored = db().tools.find_one({'_id': 1})
        assert stored['packageId'] == 'original-tool'
        assert [v['package']['packageId'] for v in stored['versions']] == [
            'original-tool', 'rewritten-tool', 'third-tool', 'fourth-tool']


def test_legacy_identity_is_first_release_not_active_or_array_order_and_reads_do_not_migrate(app):
    browser, csrf = ready(app)
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    assert post(browser, csrf, archive('original-tool'), clientRequestId=first).status_code == 201
    assert post(browser, csrf, archive('next-tool'), '/api/tools/1/versions',
                expectedRevision=1, clientRequestId=second).status_code == 201
    with app.app_context():
        document = db().tools.find_one({'_id': 1})
        db().tools.update_one({'_id': 1}, {'$unset': {'packageId': ''},
            '$set': {'versions': list(reversed(document['versions']))}})
        before = copy.deepcopy(db().tools.find_one({'_id': 1}))
    for path in ['/api/tools/1', '/api/tools/1/manifest', '/api/tools/1/releases/2/deployment',
                 '/api/publish-requests/' + second]:
        response = browser.get(path)
        assert response.status_code == 200
        check_identity(response.json, 'original-tool', 'next-tool')
    with app.app_context():
        assert db().tools.find_one({'_id': 1}) == before
    assert browser.patch('/api/tools/1', headers=csrf,
                         json={'name': '이름만 변경', 'expectedRevision': 2,
                               'packageId': 'forged-tool'}).status_code == 200
    with app.app_context():
        stored = db().tools.find_one({'_id': 1})
        assert stored['packageId'] == 'original-tool'
        assert stored['versions'] == before['versions']


def test_first_valid_declaration_pins_identity_after_legacy_file_without_a_declaration(app):
    browser, csrf = ready(app)
    first = publish(browser, csrf)
    assert first.status_code == 201
    check_identity(first.json, None, None)
    with app.app_context():
        assert 'packageId' not in db().tools.find_one({'_id': 1})
    second = post(browser, csrf, archive('first-declaration'), '/api/tools/1/versions', expectedRevision=1)
    assert second.status_code == 201
    check_identity(second.json, 'first-declaration', 'first-declaration')
    third = post(browser, csrf, archive('different-declaration'), '/api/tools/1/versions', expectedRevision=2)
    assert third.status_code == 201
    check_identity(third.json, 'first-declaration', 'different-declaration')


def test_fixed_id_search_ignores_source_aliases_and_filters_before_twenty_result_limit(app):
    owner, csrf = ready(app)
    assert post(owner, csrf, archive('original-tool')).status_code == 201
    assert post(owner, csrf, archive('next-tool'), '/api/tools/1/versions', expectedRevision=1).status_code == 201
    assert post(owner, csrf, archive('next-tool')).status_code == 201
    _, auth = issue(owner, csrf)
    api = app.test_client()
    with app.app_context():
        db().tools.update_one({'_id': 1}, {'$unset': {'packageId': ''}})
    result = api.get('/api/publish-targets?packageId=next-tool', headers=auth)
    assert [row['id'] for row in result.json['items']] == [2]
    original = api.get('/api/publish-targets?packageId=original-tool', headers=auth).json['items']
    assert [row['id'] for row in original] == [1]
    check_identity(original[0], 'original-tool', 'next-tool')
    assert api.get('/api/publish-targets?packageId=absent-tool&q=' + '선언', headers=auth).json['items'] == []
    with app.app_context():
        template = db().tools.find_one({'_id': 2})
        for number in range(100, 125):
            db().tools.insert_one({**template, '_id': number, 'packageId': 'another-fixed-id'})
        for number in range(3, 24):
            db().tools.insert_one({**template, '_id': number})
        db().tools.insert_one({**template, '_id': 999, 'owner': 'other'})
    result = api.get('/api/publish-targets?packageId=next-tool', headers=auth)
    assert result.status_code == 200
    assert [row['id'] for row in result.json['items']] == list(range(23, 3, -1))
    assert all(row['packageId'] == 'next-tool' for row in result.json['items'])


def make_draft(api, auth, blob, **changes):
    data = fields(type='MCP/Tool', **changes)
    return api.post('/api/publish-drafts', headers=auth,
                    data={'metadata': json.dumps(data), 'artifact': (io.BytesIO(blob), 'source.zip')})


def test_key_update_with_different_source_id_requires_web_review_and_preserves_owner_boundary(app):
    owner, csrf = ready(app)
    assert post(owner, csrf, archive('original-tool')).status_code == 201
    _, auth = issue(owner, csrf)
    api = app.test_client()
    blob = archive('different-tool')
    response = make_draft(api, auth, blob, toolId=1, expectedRevision=1, packageId='forged-tool')
    assert response.status_code == 201
    draft = response.json
    check_identity(draft, 'original-tool', 'different-tool')
    check_identity(api.get('/api/publish-drafts/' + draft['id'], headers=auth).json,
                   'original-tool', 'different-tool')
    assert commit(api, auth, draft).status_code == 409
    assert approve(owner, csrf, draft).status_code == 200
    saved = commit(api, auth, draft)
    assert saved.status_code == 201
    check_identity(saved.json, 'original-tool', 'different-tool')
    again = commit(api, auth, draft)
    assert again.status_code == 200 and again.json['replayed']
    check_identity(again.json, 'original-tool', 'different-tool')
    downloaded = owner.get('/download/1/2')
    assert downloaded.data == blob
    downloaded.close()
    admin, admin_csrf = ready(app, 'admin')
    _, admin_auth = issue(admin, admin_csrf)
    assert make_draft(api, admin_auth, archive('third-tool'), toolId=1, expectedRevision=2).status_code == 403
    assert post(api, auth, archive('third-tool'), '/api/tools/1/versions', expectedRevision=2).status_code == 409


def test_new_draft_identity_is_digest_bound_and_legacy_draft_digest_contract_is_unchanged(app):
    owner, csrf = ready(app)
    assert post(owner, csrf, archive('original-tool')).status_code == 201
    _, auth = issue(owner, csrf)
    api = app.test_client()
    draft = make_draft(api, auth, archive('different-tool'), toolId=1, expectedRevision=1).json
    assert approve(owner, csrf, draft).status_code == 200
    with app.app_context():
        db().publish_drafts.update_one({'_id': draft['id']}, {'$set': {'packageId': 'tampered-tool'}})
    assert commit(api, auth, draft).status_code == 409
    legacy_blob = archive('legacy-next')
    legacy_request = str(uuid.uuid4())
    legacy = make_draft(api, auth, legacy_blob, toolId=1, expectedRevision=1,
                        clientRequestId=legacy_request).json
    with app.app_context():
        row = db().publish_drafts.find_one({'_id': legacy['id']})
        row.pop('packageId')
        digest = publish_drafts.digest(row)
        db().publish_drafts.update_one({'_id': legacy['id']},
            {'$unset': {'packageId': ''}, '$set': {'reviewDigest': digest, 'creationDigest': digest}})
    retry = make_draft(api, auth, legacy_blob, toolId=1, expectedRevision=1,
                       clientRequestId=legacy_request)
    assert retry.status_code == 200 and retry.json['reviewDigest'] == digest
    legacy = api.get('/api/publish-drafts/' + legacy['id'], headers=auth).json
    check_identity(legacy, 'original-tool', 'legacy-next')
    assert approve(owner, csrf, legacy).status_code == 200
    result = commit(api, auth, legacy)
    assert result.status_code == 201
    check_identity(result.json, 'original-tool', 'legacy-next')


def test_identity_fallback_keeps_first_valid_declaration_even_if_withdrawn_or_deleted():
    source = {'packageId': 'incoming-id'}
    tool = {'versions': [
        {'n': 3, 'package': {'packageId': 'new-id'}},
        {'n': 1, 'package': {'packageId': 'INVALID'}},
        {'n': 2, 'package': {'packageId': 'first-id'}, 'deleted': True, 'withdrawn': True},
    ]}
    assert fixed_package_id(tool, source) == 'first-id'
    tool['packageId'] = 'pinned-id'
    check_identity(identity_fields(tool, source), 'pinned-id', 'incoming-id')
