import io
import json
import time
import uuid
import pytest
from pymongo.errors import OperationFailure
from .conftest import ready, publish
from .test_personal_api_usage import issue
from pt_ai_square.backend.storage import db, artifact_path
from pt_ai_square.backend import publish_drafts


def fields(**changes):
    result = dict(name='메모 요약', desc='업무 메모를 정리합니다.', owner='등록자', orgId='organization-0',
                  categoryId='category-0', platform='Claude', type='Skill', guide='범위를 선택하여 설치하세요.',
                  environment='', changes='첫 공유', approval=False, workTags=['메모'], mode='file')
    result.update(changes)
    return result


def create_draft(api, auth, **changes):
    return api.post('/api/publish-drafts', headers=auth,
                    data={'metadata': json.dumps(fields(**changes)), 'artifact': (io.BytesIO(b'# Skill\nSummarize.'), 'SKILL.md')})


def approve(browser, csrf, draft, approval=False):
    return browser.post('/api/publish-drafts/' + draft['id'] + '/approve', headers=csrf,
                        json={'approval': approval, 'reviewDigest': draft['reviewDigest']})


def commit(api, auth, draft):
    return api.post('/api/publish-drafts/' + draft['id'] + '/commit', headers=auth, json={})


@pytest.mark.parametrize('stored_scope', ['new', 'read', 'missing', 'publish'])
def test_draft_review_commit_update_and_idempotency(app, stored_scope):
    owner, csrf = ready(app)
    token, auth = issue(owner, csrf)
    if stored_scope != 'new':
        with app.app_context():
            update = {'$unset': {'scope': ''}} if stored_scope == 'missing' else {'$set': {'scope': stored_scope}}
            db().local_tokens.update_one({'id': token['id']}, update)
    api = app.test_client()
    connection = api.get('/api/integration/me', headers=auth).json
    assert connection['key']['scope'] == 'publish'
    assert connection['capabilities']['publishDraft'] is True
    assert owner.get('/api/local-tokens').json['connectionKey']['scope'] == 'publish'
    response = create_draft(api, auth)
    assert response.status_code == 201, response.json
    first = response.json
    assert first['status'] == 'pending' and 'path' not in first['artifact']
    assert first['artifact']['name'] == 'SKILL.md'
    with app.app_context():
        assert db().tools.count_documents({}) == 0
    assert commit(api, auth, first).status_code == 409
    assert approve(owner, csrf, first, True).status_code == 200
    saved = commit(api, auth, first)
    assert saved.status_code == 201 and saved.json['version'] == 1
    again = commit(api, auth, first)
    assert again.status_code == 200 and again.json['replayed']
    member, _ = ready(app, 'member')
    assert member.get('/download/1/1').status_code == 403
    assert owner.get('/download/1/1').data == b'# Skill\nSummarize.'
    second = create_draft(api, auth, toolId=1, expectedRevision=1, changes='개선').json
    assert approve(owner, csrf, second).status_code == 200
    assert commit(api, auth, second).json['version'] == 2
    assert member.get('/download/1/2').status_code == 200
    assert owner.get('/api/local-tokens').json['usage']['uploads'] == 2
    with app.app_context():
        assert db().tools.count_documents({}) == 1
        assert len(db().tools.find_one({'_id': 1})['versions']) == 2
        assert db().tools.find_one({'_id': 1})['versions'][1]['apiUsage']['tokenId'] == token['id']
        saved_key = db().local_tokens.find_one({'id': token['id']})
        if stored_scope == 'missing':
            assert 'scope' not in saved_key
        else:
            assert saved_key['scope'] == ('publish' if stored_scope == 'new' else stored_scope)


@pytest.mark.parametrize('stored_scope', ['read', 'missing', 'publish'])
def test_direct_key_publish_requires_browser_review_and_admin_owner_only(app, stored_scope):
    owner, csrf = ready(app)
    assert publish(owner, csrf).status_code == 201
    admin, acsrf = ready(app, 'admin')
    token, auth = issue(admin, acsrf)
    with app.app_context():
        update = {'$unset': {'scope': ''}} if stored_scope == 'missing' else {'$set': {'scope': stored_scope}}
        db().local_tokens.update_one({'id': token['id']}, update)
    api = app.test_client()
    assert publish(api, auth, tid=1, revision=1).status_code == 409
    assert api.post('/api/tools', headers=auth, json={'confirmed': True}).json['code'] == 'publish_draft_required'
    assert create_draft(api, auth, toolId=1, expectedRevision=1).status_code == 403
    for method, path in [('delete', '/api/tools/1'), ('patch', '/api/tools/1'),
                         ('post', '/api/tools/1/grants'), ('post', '/api/tools/1/grants/departments'),
                         ('put', '/api/admins/other'), ('put', '/api/storage/limits')]:
        # Even the matching admin cookie/CSRF cannot elevate a bearer request.
        assert getattr(admin, method)(path, headers={**acsrf, **auth}, json={}).status_code == 403
    # Browser administrator workflows remain intact.
    assert publish(admin, acsrf, tid=1, revision=1).status_code == 201


def test_admin_key_publish_candidates_are_owner_only(app):
    owner, csrf = ready(app)
    publish(owner, csrf)
    admin, acsrf = ready(app, 'admin')
    publish(admin, acsrf)
    _, auth = issue(admin, acsrf)
    with app.app_context():
        db().tools.update_many({}, {'$set': {'versions.0.package': {'packageId': 'memo-tool'}}})
    rows = app.test_client().get('/api/publish-targets?packageId=memo-tool', headers=auth)
    assert rows.status_code == 200 and [r['id'] for r in rows.json['items']] == [2]


def test_publish_candidates_support_name_or_no_package_id_and_are_bounded(app):
    owner, csrf = ready(app)
    publish(owner, csrf, name='Memo [v1]', desc='회의 업무를 정리합니다.', workTags=['메일 요약'])
    other, other_csrf = ready(app, 'other')
    publish(other, other_csrf, name='Memo [v1]')
    _, auth = issue(owner, csrf)
    api = app.test_client()
    for q in ('Memo [v1]', '회의 업무', '메일 요약'):
        result = api.get('/api/publish-targets', query_string={'q': q}, headers=auth)
        assert result.status_code == 200
        assert [row['id'] for row in result.json['items']] == [1]
    assert api.get('/api/publish-targets?q=%5B', headers=auth).status_code == 200
    assert api.get('/api/publish-targets?q=.%2A', headers=auth).json['items'] == []
    assert api.get('/api/publish-targets', query_string={'q': 'a' * 201}, headers=auth).status_code == 400
    assert api.get('/api/publish-targets?packageId=INVALID', headers=auth).status_code == 400
    with app.app_context():
        original = db().tools.find_one({'_id': 1})
        for tool_id in range(100, 125):
            db().tools.insert_one({**original, '_id': tool_id})
    latest = api.get('/api/publish-targets', headers=auth)
    assert latest.status_code == 200 and len(latest.json['items']) == 20
    assert latest.json['items'][0]['id'] == 124


def test_invalid_web_publish_request_id_cleans_staged_file(app):
    owner, csrf = ready(app)
    assert publish(owner, csrf, clientRequestId='invalid').status_code == 400
    with app.app_context():
        assert not list(artifact_path('x').parent.glob('*'))


def test_cached_read_key_request_supports_drafts_but_cookie_only_cannot_prepare(app):
    owner, csrf = ready(app)
    _, auth = issue(owner, csrf, 'read')
    api = app.test_client()
    assert create_draft(api, auth).status_code == 201
    assert create_draft(owner, csrf).status_code == 403
    info = api.get('/api/integration/me', headers=auth).json
    assert info['user']['id'] == 'owner' and info['key']['scope'] == 'publish'
    assert info['capabilities']['publishDraft'] is True
    assert 'token' not in json.dumps(info)


@pytest.mark.parametrize('invalidated', ['revoked', 'expired', 'disabled', 'unknown-scope', 'null-scope'])
def test_legacy_key_invalidated_after_review_cannot_create_approve_or_commit(app, invalidated):
    owner, csrf = ready(app)
    token, auth = issue(owner, csrf)
    with app.app_context():
        db().local_tokens.update_one({'id': token['id']}, {'$set': {'scope': 'read'}})
    api = app.test_client()
    draft = create_draft(api, auth).json
    pending = create_draft(api, auth).json
    assert approve(owner, csrf, draft).status_code == 200
    with app.app_context():
        if invalidated == 'disabled':
            db().users.update_one({'_id': 'owner'}, {'$set': {'enabled': False}})
        else:
            changes = {'revoked': {'revoked': True}, 'expired': {'expires': time.time() - 1},
                       'unknown-scope': {'scope': ['publish']}, 'null-scope': {'scope': None}}
            db().local_tokens.update_one({'id': token['id']}, {'$set': changes[invalidated]})
    assert create_draft(api, auth).status_code == 401
    assert commit(api, auth, draft).status_code == 401
    # A browser session cannot complete a stale KEY's draft either.
    assert approve(owner, csrf, pending).status_code in {401, 403}
    assert commit(owner, csrf, draft).status_code in {401, 403}
    with app.app_context():
        assert db().tools.count_documents({}) == 0


def test_review_requires_same_owner_session_csrf_digest_and_explicit_visibility(app):
    owner, csrf = ready(app)
    _, auth = issue(owner, csrf)
    api = app.test_client()
    draft = create_draft(api, auth).json
    path = '/api/publish-drafts/' + draft['id'] + '/approve'
    assert api.post(path, headers=auth, json={'approval': False, 'reviewDigest': draft['reviewDigest']}).status_code == 403
    assert owner.post(path, json={'approval': False, 'reviewDigest': draft['reviewDigest']}).status_code == 403
    other, oh = ready(app, 'other')
    assert approve(other, oh, draft).status_code == 404
    assert owner.post(path, headers=csrf, json={'reviewDigest': draft['reviewDigest']}).status_code == 400
    assert owner.post(path, headers=csrf, json={'approval': 'false', 'reviewDigest': draft['reviewDigest']}).status_code == 400
    assert owner.post(path, headers=csrf, json={'approval': False, 'reviewDigest': 'forged'}).status_code == 409
    assert approve(owner, csrf, draft).status_code == 200


def test_reissued_key_invalidates_old_draft_even_for_browser_commit(app):
    owner, csrf = ready(app)
    _, auth = issue(owner, csrf)
    api = app.test_client()
    draft = create_draft(api, auth).json
    assert approve(owner, csrf, draft).status_code == 200
    _, new_auth = issue(owner, csrf)
    assert commit(api, auth, draft).status_code == 401
    assert commit(api, new_auth, draft).status_code == 403
    assert commit(owner, csrf, draft).status_code == 403
    with app.app_context():
        assert db().tools.count_documents({}) == 0


def test_stale_tool_revision_cannot_approve_or_publish(app):
    owner, csrf = ready(app)
    publish(owner, csrf)
    _, auth = issue(owner, csrf)
    api = app.test_client()
    stale = create_draft(api, auth, toolId=1, expectedRevision=1).json
    approved = create_draft(api, auth, toolId=1, expectedRevision=1).json
    assert approve(owner, csrf, approved).status_code == 200
    publish(owner, csrf, tid=1, revision=1)
    assert approve(owner, csrf, stale).status_code == 409
    assert commit(api, auth, approved).status_code == 409


def test_changed_approved_bytes_or_metadata_rejected(app):
    owner, csrf = ready(app)
    _, auth = issue(owner, csrf)
    api = app.test_client()
    draft = create_draft(api, auth).json
    assert approve(owner, csrf, draft).status_code == 200
    with app.app_context():
        stored = db().publish_drafts.find_one({'_id': draft['id']})
        artifact_path(stored['artifact']['path']).write_bytes(b'tampered')
    assert commit(api, auth, draft).status_code == 409
    other = create_draft(api, auth).json
    assert approve(owner, csrf, other).status_code == 200
    with app.app_context():
        db().publish_drafts.update_one({'_id': other['id']}, {'$set': {'metadata.name': 'changed'}})
    assert commit(api, auth, other).status_code == 409


def test_expired_pending_draft_files_cleaned_on_next_create(app):
    owner, csrf = ready(app)
    _, auth = issue(owner, csrf)
    api = app.test_client()
    draft = create_draft(api, auth).json
    with app.app_context():
        stored = db().publish_drafts.find_one({'_id': draft['id']})
        path = artifact_path(stored['artifact']['path'])
        db().publish_drafts.update_one({'_id': draft['id']}, {'$set': {'expires': time.time() - 1}})
    assert approve(owner, csrf, draft).status_code == 410
    assert create_draft(api, auth).status_code == 201
    assert not path.exists()
    assert api.get('/api/publish-drafts/' + draft['id'], headers=auth).json['status'] == 'expired'


def test_expiry_cleanup_advances_beyond_twenty_completed_rows(app):
    import copy
    owner, csrf = ready(app)
    _, auth = issue(owner, csrf)
    api = app.test_client()
    draft = create_draft(api, auth).json
    paths = []
    with app.app_context():
        template = db().publish_drafts.find_one({'_id': draft['id']})
        for _ in range(25):
            row = copy.deepcopy(template)
            row['_id'] = str(uuid.uuid4())
            row['artifact']['path'] = uuid.uuid4().hex + '.md'
            row['expires'] = time.time() - 1
            path = artifact_path(row['artifact']['path'])
            path.write_bytes(b'old draft')
            paths.append(path)
            db().publish_drafts.insert_one(row)
    assert create_draft(api, auth).status_code == 201
    assert sum(path.exists() for path in paths) == 5
    assert create_draft(api, auth).status_code == 201
    assert not any(path.exists() for path in paths)
    with app.app_context():
        assert db().publish_drafts.count_documents({'cleanupComplete': True}) == 25


def test_expiry_cleanup_failed_file_deletion_is_retryable(app, monkeypatch):
    from pathlib import Path
    owner, csrf = ready(app)
    _, auth = issue(owner, csrf)
    api = app.test_client()
    draft = create_draft(api, auth).json
    with app.app_context():
        row = db().publish_drafts.find_one({'_id': draft['id']})
        path = artifact_path(row['artifact']['path'])
        db().publish_drafts.update_one({'_id': row['_id']}, {'$set': {'expires': time.time() - 1}})
    unlink = Path.unlink
    def failed(candidate, *args, **kwargs):
        if candidate == path:
            raise PermissionError('test locked file')
        return unlink(candidate, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', failed)
    assert create_draft(api, auth).status_code == 201
    assert path.exists()
    with app.app_context():
        row = db().publish_drafts.find_one({'_id': draft['id']})
        assert not row.get('cleanupComplete')
    monkeypatch.setattr(Path, 'unlink', unlink)
    assert create_draft(api, auth).status_code == 201
    assert not path.exists()


def test_draft_creation_request_id_reuses_same_file_and_rejects_changed_content(app):
    owner, csrf = ready(app)
    _, auth = issue(owner, csrf)
    api = app.test_client()
    request_id = str(uuid.uuid4())
    draft = create_draft(api, auth, clientRequestId=request_id).json
    assert approve(owner, csrf, draft, True).status_code == 200
    again = create_draft(api, auth, clientRequestId=request_id)
    assert again.status_code == 200 and again.json['id'] == draft['id']
    assert create_draft(api, auth, clientRequestId=request_id, name='다른 이름').status_code == 409
    with app.app_context():
        assert db().publish_drafts.count_documents({}) == 1
        assert len(list((artifact_path('x').parent).iterdir())) == 1


def test_post_publish_result_write_failure_retry_does_not_duplicate(app, monkeypatch):
    owner, csrf = ready(app)
    _, auth = issue(owner, csrf)
    api = app.test_client()
    draft = create_draft(api, auth).json
    assert approve(owner, csrf, draft).status_code == 200
    original = publish_drafts.followup_pending
    def defer(operation, callback, *args):
        if operation == 'publish-draft-result':
            return True
        return original(operation, callback, *args)
    monkeypatch.setattr(publish_drafts, 'followup_pending', defer)
    result = commit(api, auth, draft)
    assert result.status_code == 201 and result.json['pending']
    with app.app_context():
        db().publish_drafts.update_one({'_id': draft['id']}, {'$set': {'expires': time.time() - 1}})
    assert api.get('/api/publish-drafts/' + draft['id'], headers=auth).json['status'] == 'committing'
    assert commit(api, auth, draft).json['replayed']
    with app.app_context():
        assert db().tools.count_documents({}) == 1


def test_ambiguous_result_followed_by_permanent_delete_cannot_recreate_tool(app, monkeypatch):
    owner, csrf = ready(app)
    _, auth = issue(owner, csrf)
    api = app.test_client()
    draft = create_draft(api, auth).json
    approve(owner, csrf, draft)
    original = publish_drafts.followup_pending
    monkeypatch.setattr(publish_drafts, 'followup_pending',
                        lambda operation, callback, *args: True if operation == 'publish-draft-result' else original(operation, callback, *args))
    first = commit(api, auth, draft)
    assert first.status_code == 201
    tid = first.json['id']
    admin, headers = ready(app, 'admin')
    assert admin.delete(f'/api/tools/{tid}', headers=headers, json={'expectedRevision': 1}).status_code == 200
    assert admin.post(f'/api/tools/{tid}/purge', headers=headers, json={'expectedRevision': 2}).status_code == 200
    assert commit(api, auth, draft).status_code == 409
    with app.app_context():
        assert db().tools.count_documents({}) == 0


def test_primary_publish_failure_does_not_become_success(app, monkeypatch):
    owner, csrf = ready(app)
    _, auth = issue(owner, csrf)
    api = app.test_client()
    draft = create_draft(api, auth).json
    assert approve(owner, csrf, draft).status_code == 200
    def fail(*args, **kwargs):
        raise OperationFailure('injected', 225)
    monkeypatch.setattr(publish_drafts, 'publish_prepared', fail)
    assert commit(api, auth, draft).status_code == 503
    with app.app_context():
        row = db().publish_drafts.find_one({'_id': draft['id']})
        assert row['status'] == 'committing' and artifact_path(row['artifact']['path']).exists()
        assert db().tools.count_documents({}) == 0


def test_install_profile_is_reviewed_stored_and_version_specific(app):
    owner, csrf = ready(app)
    _, auth = issue(owner, csrf)
    api = app.test_client()
    profile = dict(schemaVersion=1, kind='skill', host='claude', slug='memo-skill', scopes=['project', 'user'], entrypoint='SKILL.md')
    draft = create_draft(api, auth, installProfile=profile).json
    assert draft['metadata']['installProfile'] == profile
    approve(owner, csrf, draft)
    assert commit(api, auth, draft).status_code == 201
    assert owner.get('/api/tools/1/manifest').json['installProfile'] == profile
    assert owner.get('/api/tools/1').json['versions'][0]['installProfile'] == profile
    second = create_draft(api, auth, toolId=1, expectedRevision=1).json
    approve(owner, csrf, second)
    assert commit(api, auth, second).status_code == 201
    assert owner.get('/api/tools/1/manifest').json['installProfile'] is None
    assert owner.get('/api/tools/1').json['versions'][1]['installProfile'] == profile


@pytest.mark.parametrize('bad', [True, [], {'schemaVersion': True},
    dict(schemaVersion=1, kind='skill', host='claude', slug='memo-skill', scopes=['project'], entrypoint='../other'),
    dict(schemaVersion=1, kind='skill', host='claude', slug='memo-skill', scopes=['project'], entrypoint='SKILL.md', shell='rm'),
    dict(schemaVersion=1, kind='mcp', host='claude', slug='memo-mcp', scopes=['user'], entrypoint='main.py', command={'executable':'cmd', 'args': []}),
    dict(schemaVersion=1, kind='installer', host='other', slug='memo-app', scopes=['user'], entrypoint='setup.exe', installerArgs={'project': []}),
])
def test_invalid_install_profile_rejected_without_file_leak(app, bad):
    owner, csrf = ready(app)
    _, auth = issue(owner, csrf)
    assert create_draft(app.test_client(), auth, installProfile=bad).status_code == 400
    with app.app_context():
        assert db().publish_drafts.count_documents({}) == 0
        assert not list(artifact_path('x').parent.glob('*'))
