"""Employee/key-bound drafts with explicit API or optional browser confirmation."""
import copy
import hashlib
import hmac
import json
import time
import uuid
from flask import Blueprint, g, jsonify, request
from pymongo.errors import DuplicateKeyError, PyMongoError
from werkzeug.exceptions import BadRequest, Conflict, Forbidden, Gone, NotFound
from .storage import db, artifact_path, next_id
from .post_commit import followup_pending
from .package_identity import fixed_package_id, identity_fields
from .local_access import current_connection_key, effective_connection_scope, expiry_status
from .mongo_api import (publication_request, publication_artifact, publication_data,
                        publish_prepared, tool, check_revision, payload)

publish_drafts = Blueprint('publish_drafts', __name__)
DRAFT_LIFETIME_SECONDS = 24 * 60 * 60


def digest(row):
    values = {k: row.get(k) for k in ('user', 'keyId', 'toolId', 'expectedRevision', 'metadata')}
    # Existing drafts retain their original digest contract. New drafts bind the
    # reviewed stable identity as well as the unmodified source declaration.
    if 'packageId' in row:
        values['packageId'] = row['packageId']
    values['artifact'] = {k: row['artifact'].get(k) for k in ('name', 'size', 'sha', 'url', 'commands', 'package')}
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def own_draft(draft_id):
    try:
        canonical = str(uuid.UUID(draft_id))
    except (ValueError, AttributeError):
        raise NotFound('등록 초안을 찾을 수 없습니다.') from None
    row = db().publish_drafts.find_one({'_id': canonical, 'user': g.user['id']})
    if not row:
        raise NotFound('등록 초안을 찾을 수 없습니다.')
    token_id = getattr(g, 'api_token_id', None)
    if token_id and token_id != row['keyId']:
        raise Forbidden('이 초안을 준비한 연결 KEY가 아닙니다. 새 KEY로 초안을 다시 준비하세요.')
    return row


def active_key(row):
    key = db().local_tokens.find_one({'id': row['keyId'], 'user': row['user'], 'revoked': False})
    user = db().users.find_one({'_id': row['user'], 'enabled': {'$ne': False}})
    if (not key or not user or effective_connection_scope(key) != 'publish'
            or expiry_status(key) != 'active'
            or current_connection_key(row['user']) != row['keyId']):
        raise Forbidden('초안을 준비한 연결 KEY가 취소·교체되었습니다. 새 KEY로 다시 준비하세요.')


def public(row):
    artifact = row['artifact']
    target = {'packageId': row['packageId']} if 'packageId' in row else None
    if target is None and row.get('toolId') is not None:
        target = db().tools.find_one({'_id': row['toolId'], 'owner': row['user']},
                                    {'packageId': 1, 'versions.n': 1, 'versions.package.packageId': 1})
    value = dict(id=row['_id'], status=row['status'], created=row['created'], expires=row['expires'],
                 metadata=row['metadata'], toolId=row.get('toolId'), expectedRevision=row.get('expectedRevision'),
                 directCommitSupported=True,
                 reviewDigest=row['reviewDigest'], reviewUrl='/publish-review/' + row['_id'],
                 artifact=dict(name=artifact['name'], bytes=artifact['size'], sha256=artifact['sha'],
                               url=artifact['url'], commands=artifact.get('commands', {}),
                               packageRecognized=bool(artifact.get('package')),
                                packageWarning=artifact.get('packageWarning', '')),
                 **identity_fields(target, artifact.get('package')))
    if row.get('result'):
        value['result'] = row['result']
    return value


def remove_unreferenced(artifact, draft_id=None):
    """An uncertain write must never remove the only copy of committed bytes."""
    name = artifact.get('path')
    if not name:
        return True
    if db().tools.find_one({'versions.path': name}, {'_id': 1}):
        return True
    if db().workspace_files.find_one({'$or': [{'path': name}, {'versions.path': name}]}, {'_id': 1}):
        return True
    query = {'artifact.path': name, 'status': {'$ne': 'expired'}}
    if draft_id:
        query['_id'] = {'$ne': draft_id}
    if db().publish_drafts.find_one(query, {'_id': 1}):
        return True
    try:
        artifact_path(name).unlink(missing_ok=True)
    except OSError:
        # Preserve the original operation result; future expiry cleanup retries.
        from flask import current_app
        current_app.logger.warning('Deferred publish draft file cleanup')
        return False
    return True


def cleanup_expired():
    # Never TTL-delete draft rows: the disk artifact needs an explicit,
    # recoverable cleanup. Committing rows remain for ambiguous-write recovery.
    for row in db().publish_drafts.find({'user': g.user['id'], 'expires': {'$lte': time.time()}, 'cleanupComplete': {'$ne': True},
                                       'status': {'$in': ['pending', 'approved', 'expired']}}).sort([('cleanupAttemptAt', 1), ('created', 1)]).limit(20):
        if row['status'] != 'expired':
            result = db().publish_drafts.update_one({'_id': row['_id'], 'status': row['status']},
                                                   {'$set': {'status': 'expired', 'cleanupAttemptAt': time.time()}})
            if not result.modified_count:
                continue
        else:
            db().publish_drafts.update_one({'_id': row['_id'], 'status': 'expired'},
                                           {'$set': {'cleanupAttemptAt': time.time()}})
        try:
            if remove_unreferenced(row['artifact'], row['_id']):
                db().publish_drafts.update_one({'_id': row['_id'], 'status': 'expired'},
                                               {'$set': {'cleanupComplete': True}})
        except (PyMongoError, OSError):
            continue  # The row remains an explicit cleanup retry record.


def not_expired(row):
    if row['expires'] <= time.time() or row['status'] == 'expired':
        raise Gone('등록 초안의 24시간 확인 기간이 지났습니다. 새 초안을 준비하세요.')


def current_target(row):
    if row.get('toolId') is None:
        return None
    target = tool(row['toolId'])
    if target['owner'] != row['user']:
        raise Forbidden('연결 KEY로는 본인이 등록한 도구만 새 버전을 게시할 수 있습니다.')
    check_revision(target, {'expectedRevision': row['expectedRevision']})
    return target


def verify_bytes(row):
    if not row['artifact'].get('path'):
        return
    path = artifact_path(row['artifact']['path'])
    try:
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        size = path.stat().st_size
    except OSError:
        raise Conflict('준비된 배포 파일을 찾을 수 없습니다. 새 초안을 준비하세요.') from None
    if actual != row['artifact']['sha'] or size != row['artifact']['size']:
        raise Conflict('확인한 배포 파일과 현재 파일이 다릅니다. 새 초안을 준비하세요.')


def saved_result(row):
    request_key = hashlib.sha256((row['user'] + ':' + row['_id']).encode()).hexdigest()
    saved = db().tools.find_one({'owner': row['user'], 'versions.publishRequest.key': request_key})
    if not saved:
        return None
    version = next(v for v in saved['versions'] if v.get('publishRequest', {}).get('key') == request_key)
    return dict(id=saved['_id'], version=version['n'], replayed=True, pending=False,
                packageRecognized=bool(version.get('package')),
                packageWarning=version.get('packageWarning', ''),
                deploymentUrl=f'/api/tools/{saved["_id"]}/releases/{version["n"]}/deployment' if version.get('package') else None,
                **identity_fields(saved, version.get('package')))


@publish_drafts.post('/api/publish-drafts')
def create():
    if getattr(g, 'api_token_scope', None) != 'publish':
        raise Forbidden('본인의 개인 연결 KEY로 초안을 준비하세요.')
    raw = publication_request()
    tid = raw.pop('toolId', None)
    if tid is not None and (type(tid) is not int or tid <= 0):
        raise BadRequest('toolId는 양의 정수입니다.')
    target = tool(tid) if tid is not None else None
    if target and target['owner'] != g.user['id']:
        raise Forbidden('관리자 KEY도 본인의 도구만 새 버전으로 게시할 수 있습니다.')
    if target:
        if type(raw.get('expectedRevision')) is not int:
            raise BadRequest('expectedRevision은 정수입니다.')
        check_revision(target, raw)
    followup_pending('publish-draft-expiry', cleanup_expired)
    raw.setdefault('owner', g.user['name'])
    raw.setdefault('mode', 'file')
    request_id = raw.pop('clientRequestId', None)
    if request_id is not None:
        try:
            request_id = str(uuid.UUID(request_id))
        except (ValueError, TypeError, AttributeError):
            raise BadRequest('clientRequestId는 UUID여야 합니다.') from None
    draft_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f'ptai:{g.user["id"]}:{g.api_token_id}:{request_id}')) if request_id else str(uuid.uuid4())
    artifact = publication_artifact(raw)
    try:
        data = publication_data(raw, artifact, target)
        data['mode'] = raw['mode']
        now = time.time()
        row = dict(_id=draft_id, user=g.user['id'], keyId=g.api_token_id, toolId=tid,
                   expectedRevision=target['revision'] if target else None, metadata=data, artifact=artifact,
                    packageId=fixed_package_id(target, artifact.get('package')),
                   status='pending', created=now, expires=now + DRAFT_LIFETIME_SECONDS)
        # A stable target survives a successful insert whose response/result
        # marker was lost, even if an administrator later purges the tool.
        row['reservedToolId'] = tid if tid is not None else next_id('tools')
        row['reviewDigest'] = digest(row)
        row['creationDigest'] = row['reviewDigest']
        try:
            db().publish_drafts.insert_one(row)
        except DuplicateKeyError:
            previous = own_draft(draft_id)
            candidate_digest = row['reviewDigest']
            if 'packageId' not in previous:
                # A retry of a pre-upgrade request must use the original digest
                # schema as well; its uploaded metadata and bytes still match.
                legacy_candidate = dict(row)
                legacy_candidate.pop('packageId', None)
                candidate_digest = digest(legacy_candidate)
            if previous.get('creationDigest', previous['reviewDigest']) != candidate_digest:
                raise Conflict('같은 초안 요청 번호의 내용이 달라졌습니다. 새 요청 번호로 준비하세요.')
            followup_pending('duplicate-draft-file', remove_unreferenced, artifact)
            return jsonify(public(previous)), 200
        return jsonify(public(row)), 201
    except Exception:
        followup_pending('failed-draft-file', remove_unreferenced, artifact)
        raise


@publish_drafts.get('/api/publish-drafts/<draft_id>')
def details(draft_id):
    row = own_draft(draft_id)
    value = public(row)
    if row['status'] in {'pending', 'approved'} and row['expires'] <= time.time():
        value['status'] = 'expired'
    return jsonify(value)


@publish_drafts.post('/api/publish-drafts/<draft_id>/approve')
def approve(draft_id):
    # Bearer endpoints are denied in token_user as well. Approval is a real
    # logged-in browser request with the app's existing CSRF validation.
    if getattr(g, 'api_token_id', None):
        raise Forbidden('웹 화면에서 등록 내용을 확인하고 승인하세요.')
    row = own_draft(draft_id)
    raw = payload()
    if set(raw) != {'approval', 'reviewDigest'} or type(raw.get('approval')) is not bool or not isinstance(raw.get('reviewDigest'), str):
        raise BadRequest('검토한 내용과 공개 범위를 명시적으로 확인해 주세요.')
    if (not raw['reviewDigest'].isascii()
            or not hmac.compare_digest(raw['reviewDigest'], row['reviewDigest'])):
        raise Conflict('검토 화면과 현재 초안이 다릅니다. 화면을 새로고침하세요.')
    not_expired(row)
    active_key(row)
    current_target(row)
    verify_bytes(row)
    if row['status'] != 'pending':
        raise Conflict('이미 확인했거나 게시가 시작된 초안입니다.')
    # Check the original reviewed content before applying the browser's explicit
    # visibility choice. Rehashing first would legitimize an altered draft.
    if row['reviewDigest'] != digest(row):
        raise Conflict('검토한 초안 내용이 변경되었습니다. 새 초안을 준비하세요.')
    approved = copy.deepcopy(row)
    approved['metadata']['approval'] = raw['approval']
    approved['reviewDigest'] = digest(approved)
    approved.update(status='approved', approvedAt=time.time(), approvedBy=g.user['id'],
                    approvalSource='browser', approvedDigest=approved['reviewDigest'])
    result = db().publish_drafts.update_one({'_id': row['_id'], 'status': 'pending', 'reviewDigest': row['reviewDigest']},
        {'$set': {k: approved[k] for k in ('metadata', 'reviewDigest', 'status', 'approvedAt', 'approvedBy',
                                         'approvalSource', 'approvedDigest')}})
    if not result.modified_count:
        raise Conflict('다른 화면에서 초안이 변경되었습니다.')
    return jsonify(public(approved))


@publish_drafts.post('/api/publish-drafts/<draft_id>/commit')
def commit(draft_id):
    row = own_draft(draft_id)
    active_key(row)
    raw_confirmation = payload()
    explicit_confirmation = bool(raw_confirmation)
    if explicit_confirmation:
        if (set(raw_confirmation) != {'confirmed', 'reviewDigest'}
                or raw_confirmation.get('confirmed') is not True
                or not isinstance(raw_confirmation.get('reviewDigest'), str)):
            raise BadRequest('확인한 초안의 reviewDigest와 confirmed=true를 함께 보내세요.')
        # Invalid Unicode must return a normal conflict, not a raw exception.
        if (not raw_confirmation['reviewDigest'].isascii()
                or not hmac.compare_digest(raw_confirmation['reviewDigest'], row['reviewDigest'])):
            raise Conflict('확인한 내용과 현재 초안이 다릅니다. 초안을 다시 확인하세요.')
    api_confirmation = (row['status'] == 'pending' and explicit_confirmation
                        and getattr(g, 'api_token_id', None) == row['keyId'])
    if row['status'] not in {'approved', 'committing', 'committed'} and not api_confirmation:
        not_expired(row)
        raise Conflict('등록 내용과 공개 범위를 확인한 뒤 같은 KEY로 confirmed=true와 reviewDigest를 보내세요. 웹에서도 승인할 수 있습니다.')
    result = saved_result(row)
    if result:
        followup_pending('publish-draft-result', db().publish_drafts.update_one,
                         {'_id': row['_id']}, {'$set': {'status': 'committed', 'result': result}})
        return jsonify(result), 200
    if row['status'] == 'committed':
        raise Conflict('이 초안은 이미 게시 처리되었습니다. 삭제된 도구는 다시 게시하지 않습니다.')
    from .permanent_delete import deletion_started
    if deletion_started('tool', row['reservedToolId']):
        raise Conflict('이 초안으로 게시한 도구가 삭제되었습니다. 이전 초안으로 다시 게시하지 않습니다.')
    not_expired(row)
    current_target(row)
    verify_bytes(row)
    if row['reviewDigest'] != digest(row):
        raise Conflict('승인된 내용이 변경되었습니다. 새 초안을 준비하세요.')
    if row.get('approvedDigest', row['reviewDigest']) != row['reviewDigest']:
        raise Conflict('확인한 초안 내용이 변경되었습니다. 새 초안을 준비하세요.')
    changes = {'status': 'committing'}
    if api_confirmation:
        # This proves an authenticated API caller confirmed these exact bytes
        # and metadata, not that a human or a particular MCP host did so.
        changes.update(approvedAt=time.time(), approvedBy=g.user['id'],
                       approvalSource='api', approvedDigest=row['reviewDigest'])
    active_key(row)
    eligible = ['pending'] if api_confirmation else ['approved', 'committing']
    changed = db().publish_drafts.update_one({'_id': row['_id'], 'status': {'$in': eligible},
                                            'reviewDigest': row['reviewDigest']},
                                           {'$set': changes})
    if not changed.matched_count:
        raise Conflict('게시 상태가 변경되었습니다. 초안을 다시 확인하세요.')
    raw = dict(row['metadata'], clientRequestId=row['_id'])
    if row.get('toolId') is not None:
        raw['expectedRevision'] = row['expectedRevision']
    # A browser commit uses the originating key for upload attribution too.
    g.api_token_id = row['keyId']
    response, status = publish_prepared(raw, row['artifact'], row.get('toolId'), cleanup_on_failure=False,
                                       draft_id=row['_id'], new_tool_id=row['reservedToolId'])
    result = response.get_json()
    pending = followup_pending('publish-draft-result', db().publish_drafts.update_one,
                              {'_id': row['_id']}, {'$set': {'status': 'committed', 'result': result, 'committedAt': time.time()}})
    if pending:
        result['pending'] = True
    return jsonify(result), status
