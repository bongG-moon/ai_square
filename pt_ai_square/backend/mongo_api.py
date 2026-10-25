import copy
import hashlib
import json
import re
import time
import uuid
from urllib.parse import urlsplit
from flask import Blueprint, current_app, g, jsonify, request, send_file, session
from werkzeug.exceptions import BadRequest, Forbidden, NotFound, Conflict
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from .storage import db, next_id, audit_event, stage_upload, artifact_path, used_bytes, purge_deleted, admin_ids, all_admin_ids, event, deliver_notifications
from . import activity
from .request_files import stage_attachments, attachment_path, public_attachments, cleanup_unreferenced_attachments
from .package_contract import registration_fields, normalize_workflow
from .storage_capacity import snapshot as storage_snapshot
from . import post_commit
from . import permanent_delete
from .install_profiles import normalize_install_profile
from . import department_access
from .tool_access import can_read
from .catalog_snapshot import CatalogSnapshot

api = Blueprint('api', __name__)
TYPE_ALIASES={'MCP':'MCP/Tool','Tool':'MCP/Tool','Skill':'Skill','플러그인':'플러그인/하네스','하네스':'플러그인/하네스'}

def admin():
    if g.user['role'] != 'admin': raise Forbidden('관리자만 사용할 수 있습니다.')

def manager(t): return g.user['role'] == 'admin' or t['owner'] == g.user['id']

def tool(tid, manage=False, trash=False):
    t = db().tools.find_one({'_id': tid})
    if not t or (t.get('deleted') and not (trash and manager(t))): raise NotFound('기능을 찾을 수 없습니다.')
    if t.get('purge'): raise Conflict('영구 삭제 처리 중인 도구입니다. 삭제를 마무리해 주세요.')
    if manage and not manager(t): raise Forbidden('등록자 또는 관리자만 변경할 수 있습니다.')
    return t

def allowed(t, uid=None):
    uid = uid or g.user['id']
    # Read exact stored SSO fields, not the editable catalog organization alias.
    profile = (g.user if uid == g.user['id'] and not t.get('departmentGrants')
               else db().users.find_one({'_id': uid}))
    if can_read(t, uid, profile, administrator=uid in all_admin_ids()):
        return True
    return can_read(t, uid, profile, personal_grant=bool(db().access.find_one(
        {'tool': t['_id'], 'user': uid, 'granted': True})))

def usable(t):
    if not allowed(t): raise Forbidden('조회 권한이 필요합니다. 권한을 신청해 주세요.')

def payload():
    raw = request.get_json(silent=True)
    if not isinstance(raw, dict): raise BadRequest('요청 형식을 확인해 주세요.')
    return raw

def text(raw, key, limit, required=True):
    v = raw.get(key, '')
    if not isinstance(v, str) or len(v.strip()) > limit or (required and not v.strip()): raise BadRequest(f'{key}: 필수 입력과 최대 {limit}자를 확인해 주세요.')
    return v.strip()

def category(raw, kind, existing=None):
    key = 'org' if kind == 'organization' else 'category'
    value = raw.get(key + 'Id')
    q = {'kind': kind, '_id': value} if value else {'kind': kind, 'name': raw.get(key)}
    row = db().taxonomy.find_one(q)
    if not row or (not row['enabled'] and (not existing or existing.get(key+'Id') != row['_id'])): raise BadRequest('현재 사용할 수 있는 조직·업무를 선택해 주세요.')
    return row

def metadata(raw, existing=None):
    data = {k: text(raw, k, n, k not in {'environment', 'changes'}) for k, n in {'name': 50, 'desc': 200, 'owner': 100, 'platform': 20, 'type': 20, 'guide': 10000, 'environment': 200, 'changes': 2000}.items()}
    data['type']=TYPE_ALIASES.get(data['type'],data['type'])
    for k, choices in {'platform': {'Claude','ChatGPT','기타'}, 'type': {'MCP/Tool','Skill','플러그인/하네스'}}.items():
        if data[k] not in choices: raise BadRequest('프로그램과 유형을 확인해 주세요.')
    for kind, key in [('organization','org'), ('category','category')]:
        row = category(raw, kind, existing); data[key+'Id'] = row['_id']; data[key] = row['name']
    approval = raw.get('approval', False)
    if not isinstance(approval, bool): raise BadRequest('권한 설정을 확인해 주세요.')
    data.update(approval=approval, visibility='전체 공개', audience=[])
    tags = raw.get('workTags', [])
    if isinstance(tags, str): tags = re.split('[,，\n]', tags)
    if not isinstance(tags, list) or any(not isinstance(x, str) for x in tags): raise BadRequest('관련 업무를 확인해 주세요.')
    data['workTags'] = list(dict.fromkeys(' '.join(x.split()) for x in tags if x.strip()))
    if len(data['workTags']) > 8 or any(len(x) > 30 for x in data['workTags']): raise BadRequest('관련 업무는 최대 8개, 각 30자입니다.')
    try: data['workflow']=normalize_workflow(raw.get('workflow'))
    except ValueError as error: raise BadRequest(str(error)) from None
    data['installProfile']=normalize_install_profile(raw.get('installProfile'))
    return data

def resolved(t, snapshot=None):
    data = copy.deepcopy(t['data'])
    data['type']=TYPE_ALIASES.get(data.get('type'),data.get('type'))
    for key in ['org','category']:
        row = snapshot.taxonomy.get(data.get(key+'Id')) if snapshot is not None else db().taxonomy.find_one({'_id': data.get(key+'Id')})
        if row: data[key] = row['name']
    return data

def add_outbox(update, entry):
    """Preserve an existing notification when adding its durable audit job."""
    push = update.setdefault('$push', {})
    previous = push.get('outbox')
    if previous is None:
        push['outbox'] = entry
    elif '$each' in previous:
        previous['$each'].append(entry)
    else:
        push['outbox'] = {'$each': [previous, entry]}


def deliver_pending(collection, document_id):
    return post_commit.followup_pending('deliver-'+collection, deliver_notifications, collection, document_id)


def cas(t, update, audit_message=None):
    if audit_message:
        add_outbox(update, audit_event(audit_message))
    update.setdefault('$inc', {})['revision'] = 1
    if not db().tools.update_one({'_id': t['_id'], 'revision': t['revision'], 'purge': {'$exists': False}}, update).modified_count:
        raise Conflict('다른 변경이 반영되었습니다. 새로고침 후 다시 시도해 주세요.')
    return deliver_pending('tools', t['_id'])

def check_revision(t, raw):
    if raw.get('expectedRevision') != t['revision']: raise Conflict('변경된 버전이 있습니다. 새로고침해 주세요.')

def subscribe(tid, uid, enabled=True):
    probe=event([], '', {'type':'tool','id':tid}, 'subscription')
    return db().subscriptions.find_one_and_update({'tool':tid,'user':uid}, {'$set': {'enabled': enabled},'$push':{'outbox':probe}}, upsert=True,return_document=ReturnDocument.AFTER)

def cleanup_late_tool_write(tid):
    return post_commit.followup_pending('deleted-tool-write',permanent_delete.cleanup_if_deleted,'tool',tid)

def followers(t):
    return [x['user'] for x in db().subscriptions.find({'tool': t['_id'], 'enabled': True}) if allowed(t, x['user'])]

def name_of(uid, snapshot=None):
    if snapshot is not None: return snapshot.name_of(uid)
    row = db().users.find_one({'_id': uid}); return row['name'] if row else uid

def feedback_row(c, snapshot=None):
    return dict(id=c['_id'],tool=c['tool'],user=c['user'],author=name_of(c['user'],snapshot),kind=c['kind'],text=c['body'],status=c.get('status','접수'),created=c['created'],revision=c.get('revision',0),replies=[dict(r,author=name_of(r['user'],snapshot)) for r in c.get('replies',[])])

def serialize(t, stats, now, registrants=None, snapshot=None):
    data = resolved(t,snapshot)
    access = snapshot.access.get(t['_id']) if snapshot is not None else db().access.find_one({'tool':t['_id'],'user':g.user['id']})
    can_read = t['_id'] in snapshot.readable if snapshot is not None else allowed(t)
    # Public card fields are deliberate. All other content is withheld server-side.
    if not can_read: data = {k:data[k] for k in ['name','desc','org','orgId','category','categoryId','platform','type','workTags','approval','visibility','audience','owner']}
    data.update(guide=data.get('guide',''),environment=data.get('environment',''),changes=data.get('changes',''))
    versions = []
    if can_read:
        for v in reversed(t.get('versions', [])):
            versions.append(dict(n=v['n'],age=int((now-v['created'])/86400),size=round(v['size']/1048576,3),bytes=v['size'],refs=0,note=v['note'],deleted=v.get('deleted',False),withdrawn=v.get('withdrawn',False),sha256=v['sha'],filename=v['name'],created=v['created'],url=v['url'] if not v.get('deleted') and not v.get('withdrawn') else '',package=v.get('package'),packageWarning=v.get('packageWarning',''),installProfile=v.get('data',{}).get('installProfile') if not v.get('deleted') and not v.get('withdrawn') else None,workflow=v.get('data',{}).get('workflow') if not v.get('deleted') and not v.get('withdrawn') else None,commands=v.get('commands',{}) if not v.get('deleted') and not v.get('withdrawn') else {},deploymentUrl=f'/api/tools/{t["_id"]}/releases/{v["n"]}/deployment' if v.get('package') and not v.get('deleted') and not v.get('withdrawn') else None))
    current = next((v for v in t.get('versions',[]) if v['n']==t['active']), None)
    subscription = snapshot.subscriptions.get(t['_id']) if snapshot is not None else db().subscriptions.find_one({'tool':t['_id'],'user':g.user['id']})
    if snapshot is not None:
        registrar = snapshot.users.get(t['owner'], {}).get('name', '')
    elif registrants is None:
        account = db().users.find_one({'_id': t['owner']}, {'name': 1})
        registrar = account.get('name', '') if account else ''
    else:
        registrar = registrants.get(t['owner'], '')
    data.update(registrantId=t['owner'], registrantName=registrar or '등록자 정보 없음')
    comments = (snapshot.feedback.get(t['_id'], []) if snapshot is not None else db().feedback.find({'tool':t['_id']}).sort('created',-1)) if can_read else []
    return dict(data,id=t['_id'],ownerId=t['owner'],created=t['created'],editorial=t['_id'],hidden=bool(t.get('deleted')),deleted=bool(t.get('deleted')),purgePending=bool(t.get('purge')),active=t['active'],fallback=t['fallback'],revision=t['revision'],updatePaused=t.get('paused',False),**stats,canManage=manager(t),access='approved' if can_read else 'pending' if access and access['status']=='대기' else 'none',accessDecision=access.get('decision','') if access else '',versions=versions,comments=[feedback_row(c,snapshot) for c in comments],url=current['url'] if current and can_read else '',mode='command' if current and current.get('commands') else 'server' if current and current['url'] else 'zip',support='설치·연결 안내',subscribed=bool(subscription and subscription['enabled']),icon={'MCP/Tool':'plug','Skill':'file-text','플러그인/하네스':'layers-2'}[data['type']])

def access_rows(snapshot=None):
    result=[]
    for r in snapshot.access_rows if snapshot is not None else db().access.find().sort([('updated',-1),('_id',1)]):
        t=snapshot.tools.get(r['tool']) if snapshot is not None else db().tools.find_one({'_id':r['tool']})
        if not t or not manager(t): continue
        result.append(dict(id=r['_id'],itemId=r['tool'],name=t['data']['name'],user=r['user'],who=name_of(r['user'],snapshot),reason=r.get('reason',''),status=r['status'],decision=r.get('decision',''),granted=r.get('granted',False),source=r.get('source','신청'),history=r.get('history',[]),ownerId=t['owner']))
    return result

@api.get('/api/bootstrap')
def bootstrap():
    now=time.time()
    ts=list(db().tools.find({'$or':[{'deleted':{'$ne':True}}, {'owner':g.user['id']}] } if g.user['role']!='admin' else {}).sort('_id',1))
    stats=activity.statistics([t['_id'] for t in ts],g.user['id'],now)
    taxonomy_rows=list(db().taxonomy.find().sort([('order',1),('name',1)]))
    snapshot=CatalogSnapshot(ts,g.user,taxonomy_rows)
    taxonomy=[dict(id=r['_id'],name=r['name'],kind=r['kind'],enabled=r['enabled'],order=r.get('order',0),owner=r.get('owner','')) for r in taxonomy_rows]
    retention=db().settings.find_one({'_id':'retention'})
    retention={key:retention[key] for key in ('keep','days')}
    return jsonify(items=[serialize(t,stats[t['_id']],now,snapshot=snapshot) for t in ts],user={k:v for k,v in g.user.items() if k!='enabled'},csrf=session['csrf'],authMode=current_app.config['AUTH_MODE'],organizations=[x for x in taxonomy if x['kind']=='organization'],categories=[x for x in taxonomy if x['kind']=='category'],requests=access_rows(snapshot),policy=retention,rankAsOf=now,activityBackend='mongodb',unread=db().notifications.count_documents({'user':g.user['id'],'read':False}),audit=[r['action'] for r in db().audit.find().sort('created',-1).limit(30)] if g.user['role']=='admin' else [],storage=dict(storage_snapshot(),pending=sum(1 for t in ts for v in t.get('versions',[]) if v.get('deleted') and v.get('path'))) if g.user['role']=='admin' else None)

@api.get('/api/tools/<int:tid>')
def details(tid):
    t=tool(tid);usable(t)
    return jsonify(serialize(t,activity.statistics([tid],g.user['id'],time.time())[tid],time.time()))


@api.post('/api/tools/<int:tid>/view')
def record_view(tid):
    t = tool(tid)
    usable(t)
    if payload() != {}:
        raise BadRequest('상세 열람 요청의 항목을 확인해 주세요.')
    result = activity.record_view(tid, g.user['id'])
    result['pending'] = cleanup_late_tool_write(tid) or result['pending']
    return jsonify(result)

def publish_followup_pending(tid):
    return deliver_pending('tools',tid)


def publication_request_key(request_id):
    """The browser's opaque request ID is always scoped to its signed-in employee."""
    try: request_id=str(uuid.UUID(request_id))
    except (ValueError,TypeError,AttributeError): raise BadRequest('clientRequestId는 UUID여야 합니다.')
    return hashlib.sha256((g.user['id']+':'+request_id).encode()).hexdigest()


@api.get('/api/publish-requests/<request_id>')
def publication_receipt(request_id):
    """Recover a lost publish response without uploading or performing follow-up writes.

    Absence is deliberately unconfirmed: the original request can still be running.
    The connection-KEY allowlist excludes this browser-only recovery endpoint too.
    """
    if getattr(g, 'api_token_id', None):
        raise Forbidden('게시 결과 확인은 로그인한 웹 화면에서만 사용할 수 있습니다.')
    request_key=publication_request_key(request_id)
    stored=db().tools.find_one(
        {'versions.publishRequest.key':request_key},
        {'owner':1,'deleted':1,'purge':1,
         'versions':{'$elemMatch':{'publishRequest.key':request_key}},
         'outbox':{'$slice':1},'postCommit':{'$slice':1}})
    if not stored or stored.get('deleted') or stored.get('purge') or not manager(stored):
        return jsonify(status='unconfirmed')
    version=next((v for v in stored.get('versions',[])
                  if v.get('publishRequest',{}).get('key')==request_key),None)
    if version is None:
        return jsonify(status='unconfirmed')
    recognized=bool(version.get('package'))
    return jsonify(status='confirmed',id=stored['_id'],version=version['n'],
                   pending=bool(stored.get('outbox') or stored.get('postCommit')),
                   packageRecognized=recognized,packageWarning=version.get('packageWarning',''),
                   deploymentUrl=f'/api/tools/{stored["_id"]}/releases/{version["n"]}/deployment' if recognized else None)


@api.post('/api/tools')
@api.post('/api/tools/<int:tid>/versions')
def publish(tid=None):
    if getattr(g, 'api_token_id', None):
        return jsonify(error='API KEY 게시에는 웹에서 승인한 등록 초안이 필요합니다.', code='publish_draft_required', draftUrl='/api/publish-drafts'),409
    if tid is not None: tool(tid,True)
    raw=publication_request()
    artifact=publication_artifact(raw)
    return publish_prepared(raw,artifact,tid)


def publication_request():
    try: raw=json.loads(request.form.get('metadata',''))
    except (ValueError,TypeError): raise BadRequest('등록 정보를 확인해 주세요.')
    if not isinstance(raw,dict): raise BadRequest('등록 정보를 확인해 주세요.')
    return raw


def publication_artifact(raw):
    if raw.get('mode')=='url':
        url=text(raw,'url',2048);parts=urlsplit(url)
        if parts.scheme!='https' or not parts.hostname or parts.username or parts.password: raise BadRequest('인증정보 없는 HTTPS 주소를 입력해 주세요.')
        artifact=dict(path=None,name='',size=0,sha='',url=url)
    elif raw.get('mode')=='command':
        commands={scope:text(raw,key,8000,False) for scope,key in [('project','commandProject'),('user','commandUser')]}
        if not any(commands.values()): raise BadRequest('최소 하나의 설치 범위에 명령어를 입력해 주세요.')
        artifact=dict(path=None,name='',size=0,sha='',url='',commands=commands)
    elif raw.get('mode') in {'file',None}: artifact=stage_upload(request.files.get('artifact'))
    else: raise BadRequest('파일·URL·명령어 중 등록 방식을 선택해 주세요.')
    return artifact


def publication_data(raw, artifact, t=None):
    raw=copy.deepcopy(raw)
    package=artifact.get('package')
    if package:
        raw={**registration_fields(package),**raw}
        raw['workflow']=package.get('workflow')
        if any(raw.get(k)!=package[k] for k in ['platform','type']):
            raise BadRequest('프로그램·유형이 ZIP 배포 정보와 다릅니다. ai-square.json 또는 입력값을 맞춰 주세요.')
        previous=next((v.get('package') for v in reversed(t['versions']) if v.get('package')),None) if t else None
        if previous and previous['packageId']!=package['packageId']:
            raise BadRequest('새 버전의 packageId가 기존 도구와 다릅니다. 다른 도구는 새로 등록하세요.')
    return metadata(raw,t['data'] if t else None)


def publish_prepared(raw, artifact, tid=None, *, cleanup_on_failure=True, draft_id=None, new_tool_id=None):
    # Internal entrypoint accepts already staged bytes; no nested HTTP request or
    # client-controlled confirmation header can reach this path.
    committed=False
    try:
        t=tool(tid,True) if tid else None
        if (getattr(g,'api_token_id',None) or draft_id) and t and t['owner']!=g.user['id']:
            raise Forbidden('연결 KEY로는 본인이 등록한 도구만 새 버전을 게시할 수 있습니다.')
        if getattr(g,'api_token_id',None) and not draft_id:
            raise Forbidden('승인된 게시 초안이 필요합니다.')
        request_id=raw.get('clientRequestId')
        request_key=publication_request_key(request_id) if request_id is not None else None
        package=artifact.get('package')
        data=publication_data(raw,artifact,t)
        fingerprint=hashlib.sha256(json.dumps(dict(target=tid,data=data,sha=artifact['sha'],url=artifact['url'],commands=artifact.get('commands',{})),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        def replay():
            existing=db().tools.find_one({'versions.publishRequest.key':request_key})
            if not existing: return None
            saved=next(v for v in existing['versions'] if v.get('publishRequest',{}).get('key')==request_key)
            if saved['publishRequest']['fingerprint']!=fingerprint:
                raise Conflict('같은 게시 요청 번호의 내용이 다릅니다. 새 준비안을 생성하세요.')
            return jsonify(id=existing['_id'],version=saved['n'],replayed=True,
                           pending=publish_followup_pending(existing['_id'])),200
        if request_key:
            previous_response=replay()
            if previous_response: return previous_response
        if t: check_revision(t,raw)
        n=max([v['n'] for v in t['versions']],default=0)+1 if t else 1
        version=dict(artifact,n=n,note=data['changes'] or '공유 버전 등록',created=time.time(),deleted=False,withdrawn=False,data={k:data[k] for k in ['guide','environment','platform','type','workflow','installProfile']})
        if getattr(g, 'api_token_id', None):
            version['apiUsage'] = dict(user=g.user['id'], tokenId=g.api_token_id)
        if request_key:
            version['publishRequest']=dict(key=request_key,fingerprint=fingerprint)
        if not t: tid=new_tool_id if new_tool_id is not None else next_id('tools')
        job=audit_event(f'{data["name"]} v{n} 게시', subscription={'tool':tid,'user':g.user['id']})
        if t:
            future=dict(t,data=data)
            e=event(followers(future),f'{data["name"]} v{n} 업데이트',{'type':'tool','id':tid},'release')
            pending=cas(t,{'$set':{'data':data,'active':n,'fallback':t['active'],'paused':False},'$push':{'versions':version,'outbox':{'$each':[e,job]}}})
        else:
            try: db().tools.insert_one({'_id':tid,'owner':g.user['id'],'data':data,'created':time.time(),'active':1,'fallback':1,'revision':1,'deleted':False,'paused':False,'versions':[version],'outbox':[job]})
            except DuplicateKeyError:
                if request_key:
                    previous_response=replay()
                    if previous_response: return previous_response
                raise
        committed=True
        if not t: pending=publish_followup_pending(tid)
        return jsonify(id=tid,version=n,pending=pending,packageRecognized=bool(package),packageWarning=artifact.get('packageWarning',''),deploymentUrl=f'/api/tools/{tid}/releases/{n}/deployment' if package else None),201
    finally:
        if cleanup_on_failure and not committed and artifact['path']:
            # A network timeout may follow a committed write. Never remove a potentially referenced file.
            try: referenced=db().tools.find_one({'versions.path':artifact['path']},{'_id':1})
            except Exception: referenced=True
            if not referenced: artifact_path(artifact['path']).unlink(missing_ok=True)

@api.post('/api/packages/inspect')
def inspect_package():
    """Authenticated, CSRF-protected preview. Temporary upload is always removed."""
    artifact=stage_upload(request.files.get('artifact'))
    try:
        package=artifact.get('package')
        return jsonify(recognized=bool(package),package=package,
                       metadata=registration_fields(package) if package else {},
                       sha256=artifact['sha'],bytes=artifact['size'],warning=artifact.get('packageWarning',''),
                       notice='배포 정보와 필수 파일을 확인했습니다. 코드 실행·설치 검증은 포함하지 않습니다.' if package else '배포 정보를 읽지 못했거나 포함하지 않은 파일입니다. 등록 항목과 설치 안내를 직접 입력하여 게시할 수 있습니다.')
    finally:
        artifact_path(artifact['path']).unlink(missing_ok=True)

@api.patch('/api/tools/<int:tid>')
def edit(tid):
    t=tool(tid,True);raw=payload();check_revision(t,raw)
    merged={**resolved(t),**raw}
    for k in ['org','category']:
        if k in raw and k+'Id' not in raw: merged.pop(k+'Id',None)
    data=metadata(merged,t['data'])
    if data['workflow']!=t['data'].get('workflow'):
        raise BadRequest('동작 흐름은 배포 버전에 연결됩니다. 변경한 흐름을 새 버전으로 등록하세요.')
    if data['installProfile']!=t['data'].get('installProfile'):
        raise BadRequest('설치 정보는 새 버전으로 등록하세요.')
    current_package=next((v.get('package') for v in t['versions'] if v['n']==t['active']),None)
    if current_package and any(data[k]!=current_package[k] for k in ['platform','type']):
        raise BadRequest('프로그램·유형은 현재 배포 정보와 일치해야 합니다. 변경한 패키지를 새 버전으로 등록하세요.')
    pending=cas(t,{'$set':{'data':data}},f'{data["name"]} 등록 정보 수정')
    return jsonify(ok=True,pending=pending)

@api.delete('/api/tools/<int:tid>')
def delete_tool(tid):
    t=tool(tid,True);check_revision(t,payload())
    pending=cas(t,{'$set':{'deleted':True,'deletedAt':time.time()}},f'{t["data"]["name"]} 휴지통 이동')
    return jsonify(ok=True,pending=pending)

@api.post('/api/tools/<int:tid>/restore')
def restore(tid):
    t=tool(tid,True,True);check_revision(t,payload())
    pending=cas(t,{'$set':{'deleted':False}},f'{t["data"]["name"]} 복원')
    return jsonify(ok=True,pending=pending)

@api.post('/api/tools/<int:tid>/purge')
def purge_tool(tid):
    admin()
    result=permanent_delete.remove('tool',tid,payload().get('expectedRevision'))
    return jsonify(result),202 if result['pending'] else 200

@api.get('/api/deletions')
def pending_deletions():
    admin()
    rows=db().deletion_jobs.find({'state':{'$ne':'complete'}}).sort('created',1).limit(100)
    return jsonify(jobs=[dict(id=r['_id'],kind=r['kind'],entityId=r['entityId'],
                              revision=r['revision'],created=r['created']) for r in rows])

@api.put('/api/tools/<int:tid>/like')
def like(tid):
    t=tool(tid);usable(t);value=payload().get('liked')
    if not isinstance(value,bool): raise BadRequest('좋아요 상태를 확인해 주세요.')
    count=activity.set_like(tid,g.user['id'],value)
    pending=cleanup_late_tool_write(tid)
    pending=post_commit.followup_pending('like-activity',activity.flush,tid,g.user['id'],50) or pending
    return jsonify(liked=value,count=count,pending=pending or count is None,
                   historyPending=pending,countsPending=count is None)

@api.put('/api/tools/<int:tid>/subscription')
def subscription(tid):
    t=tool(tid);usable(t);value=payload().get('enabled')
    if not isinstance(value,bool): raise BadRequest('알림 설정을 확인해 주세요.')
    row=subscribe(tid,g.user['id'],value)
    return jsonify(ok=True,pending=deliver_pending('subscriptions',row['_id']))

@api.post('/api/tools/<int:tid>/requests')
def access_request(tid):
    t=tool(tid);reason=text(payload(),'reason',2000);uid=g.user['id'];key=f'{tid}:{uid}'
    if allowed(t): raise Conflict('이미 조회할 수 있는 기능입니다.')
    e=event([t['owner'],*all_admin_ids()],f'{name_of(uid)}님의 {t["data"]["name"]} 권한 신청',{'type':'access','id':tid},'approval')
    old=db().access.find_one({'_id':key})
    if old and old['status']=='대기': raise Conflict('이미 승인 대기 중입니다.')
    values={'tool':tid,'user':uid,'reason':reason,'status':'대기','decision':'','granted':False,'source':'신청','updated':time.time()}
    if old:
        result=db().access.update_one({'_id':key,'updated':old['updated'],'granted':False},{'$set':values,'$push':{'outbox':e,'history':{'status':'대기','actor':uid,'at':time.time(),'reason':reason}}})
        if not result.modified_count: raise Conflict('권한 상태가 변경되었습니다.')
    else:
        try: db().access.insert_one(dict(values,_id=key,outbox=[e],history=[{'status':'대기','actor':uid,'at':time.time(),'reason':reason}]))
        except DuplicateKeyError: raise Conflict('이미 신청했습니다.')
    pending=cleanup_late_tool_write(tid)
    return jsonify(ok=True,pending=deliver_pending('access',key) or pending)

@api.post('/api/requests/<rid>/decision')
def decide(rid):
    r=db().access.find_one({'_id':rid})
    if not r: raise NotFound()
    t=tool(r['tool'],True);raw=payload();status=text(raw,'status',10)
    if status not in {'승인','반려','회수'}: raise BadRequest('처리 상태를 확인해 주세요.')
    if (status=='회수' and not r.get('granted')) or (status!='회수' and r['status']!='대기'): raise Conflict('이미 처리된 신청입니다.')
    reason=text(raw,'reason',2000,status in {'반려','회수'})
    e=event([r['user']],f'{t["data"]["name"]} 권한 {status}',{'type':'tool','id':r['tool']},'approval')
    job=audit_event(f'권한 {rid} {status}',subscription={'tool':r['tool'],'user':r['user']} if status=='승인' else None)
    e.update(audit=job['audit'])
    if 'subscription' in job: e['subscription']=job['subscription']
    result=db().access.update_one({'_id':rid,'updated':r['updated']},{'$set':{'status':r['status'] if status=='회수' else status,'granted':status=='승인','decision':reason,'updated':time.time(),'decidedBy':g.user['id']},'$push':{'outbox':e,'history':{'status':status,'actor':g.user['id'],'at':time.time(),'reason':reason}}})
    if not result.modified_count: raise Conflict('이미 처리된 신청입니다.')
    pending=cleanup_late_tool_write(t['_id'])
    return jsonify(ok=True,pending=deliver_pending('access',rid) or pending)

@api.post('/api/tools/<int:tid>/grants')
def grant(tid):
    t=grant_tool(tid);raw=payload()
    ids=department_access.employee_ids(raw.get('users') if 'users' in raw else [text(raw,'user',100)])
    _,unknown=department_access.resolve_employees(ids)
    if unknown: raise BadRequest('확인할 수 없는 사번이 있습니다. 로그인 이력이 있는 활성 사용자만 선택해 주세요.')
    saved=[];already=[];failed=[];pending=False
    for uid in ids:
        try:
            old=db().access.find_one({'tool':tid,'user':uid,'granted':True})
            if old:
                already.append(uid)
                continue
            job_pending=grant_employee(t,uid)
            saved.append(uid);pending=job_pending or pending
        except PyMongoError as error:
            # Some members may already be saved. Never label the whole batch
            # a success or roll back independently committed grants.
            post_commit.log_deferred('bulk-grant-result-uncertain',error)
            failed.append({'id':uid,'error':'저장 결과를 확인하지 못했습니다. 권한 목록을 새로 확인한 뒤 다시 시도해 주세요.'})
    return jsonify(ok=not failed,saved=saved,alreadyGranted=already,failed=failed,pending=pending),207 if failed else 200

def grant_tool(tid):
    # Defense in depth in addition to the API KEY endpoint allowlist.
    if getattr(g,'api_token_id',None) or request.headers.get('Authorization'):
        raise Forbidden('연결 KEY로는 조회 권한을 변경하거나 권한 목록을 볼 수 없습니다.')
    return tool(tid,True)

def grant_employee(t,uid):
    tid=t['_id']
    e=event([uid],f'{t["data"]["name"]} 조회 권한이 부여되었습니다.',{'type':'tool','id':tid},'approval')
    e.update(audit=audit_event(f'도구 {tid} 사용자 {uid} 직접 승인')['audit'],subscription={'tool':tid,'user':uid})
    saved=db().access.find_one_and_update({'tool':tid,'user':uid},{'$setOnInsert':{'_id':f'{tid}:{uid}','reason':''},'$set':{'status':'승인','granted':True,'source':'직접 추가','decision':'','decidedBy':g.user['id'],'updated':time.time()},'$push':{'outbox':e,'history':{'status':'직접 승인','actor':g.user['id'],'at':time.time()}}},upsert=True,return_document=ReturnDocument.AFTER)
    pending=cleanup_late_tool_write(tid)
    return deliver_pending('access',saved['_id']) or pending

@api.get('/api/tools/<int:tid>/grants')
def grants(tid):
    t=grant_tool(tid);rows=[]
    for access in db().access.find({'tool':tid,'granted':True}):
        profile=db().users.find_one({'_id':access['user']})
        user=department_access.employee(profile or {'_id':access['user']})
        rows.append(dict(user,requestId=access['_id'],source=access.get('source','신청'),
                         enabled=bool(profile and profile.get('enabled',True)),
                         inheritedDepartments=[{field:rule[field] for field in ('id','name','code','match') if field in rule}
                             for rule in t.get('departmentGrants',[])
                             if profile and department_access.group_matches(rule,profile)]))
    return jsonify(users=rows,departments=department_access.department_rules(t),revision=t['revision'])

@api.post('/api/tools/<int:tid>/grants/preview')
def preview_grants(tid):
    grant_tool(tid);raw=payload();mode=raw.get('mode');value=text(raw,'value',12000)
    if mode=='users':
        users,unknown=department_access.resolve_employees(department_access.employee_ids(value))
        return jsonify(mode=mode,users=users,unknown=unknown,count=len(users))
    if mode!='department': raise BadRequest('사번 또는 부서 검색을 선택해 주세요.')
    input_mode=raw.get('departmentInput','search')
    rows,count=department_access.preview_departments(value,input_mode)
    return jsonify(mode=mode,departmentInput=input_mode,departments=rows,count=count,truncated=count>len(rows))

@api.post('/api/tools/<int:tid>/grants/departments')
def grant_departments(tid):
    t=grant_tool(tid);raw=payload()
    if 'expectedRevision' in raw: check_revision(t,raw)
    selected=department_access.selected_departments(raw.get('departments'))
    existing={row['id']:row for row in t.get('departmentGrants',[])}
    added=[row for row in selected if row['id'] not in existing]
    if len(existing)+len(added)>department_access.MAX_DEPARTMENTS:
        raise BadRequest('한 도구에는 최대 50개 부서의 권한을 설정할 수 있습니다.')
    pending=False
    if added:
        rules=[*existing.values(),*added]
        pending=cas(t,{'$set':{'departmentGrants':rules}},f'도구 {tid} 부서 조회 권한 {len(added)}개 추가')
        t=dict(t,departmentGrants=rules,revision=t['revision']+1)
    # No post-commit reads are required to report the committed rule.
    return jsonify(ok=True,departments=[dict(row,memberCount=None) for row in t.get('departmentGrants',[])],revision=t['revision'],pending=pending)

@api.delete('/api/tools/<int:tid>/grants/departments/<rule_id>')
def revoke_department(tid,rule_id):
    t=grant_tool(tid);raw=request.get_json(silent=True) or {}
    if not isinstance(raw,dict): raise BadRequest('요청 형식을 확인해 주세요.')
    if 'expectedRevision' in raw: check_revision(t,raw)
    rules=[row for row in t.get('departmentGrants',[]) if row['id']!=rule_id]
    if len(rules)==len(t.get('departmentGrants',[])):
        return jsonify(ok=True,revision=t['revision'],pending=False)
    pending=cas(t,{'$set':{'departmentGrants':rules}},f'도구 {tid} 부서 조회 권한 회수')
    return jsonify(ok=True,revision=t['revision']+1,pending=pending)

@api.post('/api/tools/<int:tid>/comments')
def comment(tid):
    t=tool(tid);usable(t);raw=payload();kind=text(raw,'kind',20)
    if kind not in {'개선 의견','사용 후기','오류 제보','아이디어 제안'}: raise BadRequest('피드백 종류를 확인해 주세요.')
    cid=next_id('feedback');e=event([t['owner'],*all_admin_ids()],f'{g.user["name"]}님이 {t["data"]["name"]}에 피드백을 남겼습니다.',{'type':'feedback','id':tid,'feedbackId':cid},'feedback')
    e['subscription']={'tool':tid,'user':g.user['id']}
    db().feedback.insert_one({'_id':cid,'tool':tid,'user':g.user['id'],'kind':kind,'body':text(raw,'text',4000),'created':time.time(),'status':'접수','revision':0,'replies':[],'outbox':[e]})
    pending=cleanup_late_tool_write(tid)
    return jsonify(ok=True,id=cid,pending=deliver_pending('feedback',cid) or pending),201

@api.post('/api/feedback/<int:fid>/reply')
def feedback_reply(fid):
    c=db().feedback.find_one({'_id':fid})
    if not c: raise NotFound()
    t=tool(c['tool']);usable(t);raw=payload()
    if not manager(t) and c['user']!=g.user['id']: raise Forbidden('작성자·등록자·관리자만 답변할 수 있습니다.')
    body=text(raw,'text',4000,False);status=raw.get('status',c['status'])
    if status not in {'접수','검토 중','반영 중','반영 완료','보류'}: raise BadRequest('처리 상태를 확인해 주세요.')
    if not manager(t) and status!=c['status']: raise Forbidden('담당자만 상태를 변경할 수 있습니다.')
    if not body and status==c['status']: raise BadRequest('답변 또는 변경할 상태를 입력해 주세요.')
    e=event([c['user'],t['owner'],*all_admin_ids()],f'{t["data"]["name"]} 피드백에 답변·상태 변경이 있습니다.',{'type':'feedback','id':t['_id'],'feedbackId':fid},'feedback')
    result=db().feedback.update_one({'_id':fid,'revision':c['revision']},{'$set':{'status':status},'$inc':{'revision':1},'$push':{'outbox':e,'replies':{'user':g.user['id'],'text':body,'status':status,'created':time.time()}}})
    if not result.modified_count: raise Conflict('다른 답변이 반영되었습니다. 새로고침해 주세요.')
    pending=cleanup_late_tool_write(t['_id'])
    return jsonify(ok=True,pending=deliver_pending('feedback',fid) or pending)

@api.get('/api/ideas')
def ideas():
    result=[]
    query={} if g.user['role']=='admin' else {'purge':{'$exists':False}}
    for i in db().ideas.find(query).sort('created',-1):
        i['attachments']=public_attachments(i)
        i=dict(i);i['id']=i.pop('_id');i.pop('outbox',None);i['deletionPending']=bool(i.pop('purge',None));i['author']=name_of(i['user']);i['assigneeName']=name_of(i['assignee']) if i.get('assignee') else ''
        i['replies']=[dict(r,author=name_of(r['user'])) for r in i.get('replies',[])]
        linked=db().tools.find_one({'_id':i.get('tool'),'deleted':{'$ne':True}})
        i['toolName']=linked['data']['name'] if linked else '';result.append(i)
    return jsonify(ideas=result)

@api.post('/api/ideas')
def idea():
    if request.mimetype=='multipart/form-data':
        try: raw=json.loads(request.form.get('metadata',''))
        except (ValueError,TypeError): raise BadRequest('요청 내용을 확인하세요.')
        if not isinstance(raw,dict): raise BadRequest('요청 내용을 확인하세요.')
    else: raw=payload()
    name=text(raw,'name',100);cat=category(raw,'category');body=text(raw,'desc',4000)
    iid=next_id('ideas');attachments=stage_attachments(request.files.getlist('attachments'))
    try:
        db().ideas.insert_one({'_id':iid,'user':g.user['id'],'name':name,'body':body,'attachments':attachments,'category':cat['name'],'categoryId':cat['_id'],'created':time.time(),'status':'접수 대기','assignee':None,'tool':None,'revision':0,'replies':[],'outbox':[event(all_admin_ids(),f'{g.user["name"]}님의 새 기능 요청: {name}',{'type':'idea','id':iid},'idea')]})
    except Exception:
        cleanup_unreferenced_attachments(attachments)
        raise
    return jsonify(ok=True,id=iid,pending=deliver_pending('ideas',iid)),201

@api.get('/api/ideas/<int:iid>/attachments/<aid>')
def idea_attachment(iid,aid):
    i=db().ideas.find_one({'_id':iid,'purge':{'$exists':False}})
    a=next((a for a in (i or {}).get('attachments',[]) if a['id']==aid),None)
    if not a: raise NotFound('첨부파일을 찾을 수 없습니다.')
    path=attachment_path(a['path'])
    if not path.is_file(): raise NotFound('첨부파일을 찾을 수 없습니다.')
    return send_file(path,as_attachment=True,download_name=a['name'],mimetype='application/octet-stream')

@api.patch('/api/ideas/<int:iid>')
def update_idea(iid):
    i=db().ideas.find_one({'_id':iid})
    if not i: raise NotFound()
    if i.get('purge'): raise Conflict('삭제 처리 중인 요청입니다. 삭제를 마무리해 주세요.')
    raw=payload();status=raw.get('status',i['status']);claim=raw.get('claim',False)
    statuses={'접수 대기','담당자 지정','개발 중','보류','구현 완료'}
    if not isinstance(status,str) or status not in statuses: raise BadRequest('진행 상태를 확인해 주세요.')
    if not isinstance(claim,bool): raise BadRequest('담당자 지정 여부를 확인해 주세요.')
    if raw.get('expectedRevision')!=i['revision']: raise Conflict('다른 사용자가 변경했습니다. 새로고침해 주세요.')
    owner=g.user['role']=='admin' or i.get('assignee')==g.user['id']
    updates={};reply=text(raw,'text',4000,False)
    if claim:
        if i.get('assignee') or i['status']!='접수 대기': raise Conflict('이미 담당자가 지정된 요청입니다.')
        updates.update(assignee=g.user['id'],status='담당자 지정')
    elif status!=i['status']:
        if not owner: raise Forbidden('개발 담당자 또는 관리자만 상태를 변경할 수 있습니다.')
        transitions={'접수 대기':{'보류'},'담당자 지정':{'개발 중','보류','접수 대기'},'개발 중':{'구현 완료','보류','접수 대기'},'보류':{'접수 대기','개발 중'},'구현 완료':{'개발 중'}}
        if g.user['role']!='admin' and status not in transitions.get(i['status'],set()): raise BadRequest('다음 진행 상태를 확인해 주세요.')
        if status=='구현 완료':
            tid=raw.get('tool')
            if isinstance(tid,bool) or not isinstance(tid,int): raise BadRequest('구현한 기능을 선택해 주세요.')
            t=tool(tid);usable(t);updates['tool']=tid
        if status=='접수 대기': updates['assignee']=None
        if status in {'담당자 지정','개발 중'} and not i.get('assignee'): updates['assignee']=g.user['id']
        if status!='구현 완료': updates['tool']=None
        updates['status']=status
    if not updates and not reply: raise BadRequest('답변 또는 변경할 내용을 입력해 주세요.')
    recipients={i['user'],i.get('assignee'),*all_admin_ids(),*(r['user'] for r in i.get('replies',[]))}-{None}
    e=event(recipients,f'{i["name"]} · {updates.get("status", "새 답변")}',{'type':'idea','id':iid},'idea')
    if updates.get('tool'): e['toolCheck']=updates['tool']
    if updates: e['audit']=audit_event(f'기능 요청 {iid} {updates.get("status", i["status"])} 상태 변경')['audit']
    op={'$inc':{'revision':1},'$push':{'outbox':e}}
    if updates: op['$set']=updates
    if reply: op['$push']['replies']={'user':g.user['id'],'text':reply,'created':time.time()}
    if not db().ideas.update_one({'_id':iid,'revision':i['revision'],'purge':{'$exists':False}},op).modified_count: raise Conflict('다른 사용자가 먼저 처리했습니다.')
    pending=cleanup_late_tool_write(updates['tool']) if updates.get('tool') else False
    return jsonify(ok=True,pending=deliver_pending('ideas',iid) or pending)

@api.delete('/api/ideas/<int:iid>')
def delete_idea(iid):
    admin()
    result=permanent_delete.remove('idea',iid,payload().get('expectedRevision'))
    return jsonify(result),202 if result['pending'] else 200

@api.get('/api/notifications')
def notifications():
    deletion_pending=post_commit.followup_pending('deletion-reconciliation',permanent_delete.reconcile_completed)
    pending=post_commit.followup_pending('activity-maintenance',activity.flush,None,None,50)
    pending=post_commit.followup_pending('notification-maintenance',deliver_notifications) or pending or deletion_pending
    query={'user':g.user['id']}
    if request.args.get('unread')=='true': query['read']=False
    before=request.args.get('before')
    if before:
        n=db().notifications.find_one({'_id':before,'user':g.user['id']})
        if n: query['$or']=[{'created':{'$lt':n['created']}},{'created':n['created'],'_id':{'$lt':before}}]
    rows=list(db().notifications.find(query).sort([('created',-1),('_id',-1)]).limit(51));more=len(rows)>50;rows=rows[:50]
    for row in rows: row['id']=row.pop('_id')
    return jsonify(notifications=rows,nextCursor=rows[-1]['id'] if more else None,unread=db().notifications.count_documents({'user':g.user['id'],'read':False}),pending=pending)

@api.put('/api/notifications/read')
def read_notifications():
    raw=payload();q={'user':g.user['id']}
    if raw.get('id'): q['_id']=text(raw,'id',200)
    elif raw.get('all') is not True: raise BadRequest('읽음 처리할 알림을 선택해 주세요.')
    db().notifications.update_many(q,{'$set':{'read':True}});return jsonify(ok=True)

@api.get('/api/users')
def users():
    # Only grant-management surfaces may search employee identities.
    if g.user['role']!='admin' and not db().tools.find_one({'owner':g.user['id'],'deleted':{'$ne':True}}): raise Forbidden()
    term=request.args.get('q','').strip()[:100]
    q={'enabled':True}
    if term: q['$or']=[{'_id':{'$regex':re.escape(term),'$options':'i'}},{'name':{'$regex':re.escape(term),'$options':'i'}}]
    return jsonify(users=[{'id':r['_id'],'name':r['name']} for r in db().users.find(q).limit(30)])

@api.post('/api/taxonomy')
def taxonomy():
    admin();raw=payload();kind=raw.get('kind');name=text(raw,'name',80)
    if kind not in {'organization','category'}: raise BadRequest('분류 종류를 확인해 주세요.')
    enabled=raw.get('enabled',True);order=raw.get('order',0)
    if not isinstance(enabled,bool) or type(order)!=int or not 0<=order<=999: raise BadRequest('사용 여부와 표시 순서를 확인해 주세요.')
    key=raw.get('id') or uuid.uuid4().hex
    if raw.get('id') and not db().taxonomy.find_one({'_id':key,'kind':kind}): raise NotFound()
    if key=='organization-0' and (not enabled or name!='공통'): raise BadRequest('공통 조직은 유지해 주세요.')
    job=audit_event(f'{kind} {name} 설정 변경')
    try: db().taxonomy.update_one({'_id':key},{'$set':{'kind':kind,'name':name,'enabled':enabled,'order':order,'owner':text(raw,'owner',100,False)},'$push':{'outbox':job}},upsert=True)
    except DuplicateKeyError: raise Conflict('같은 이름의 항목이 있습니다.')
    return jsonify(ok=True,id=key,pending=deliver_pending('taxonomy',key))

@api.get('/api/admins')
def admins():
    admin();return jsonify(admins=[{'id':uid,'name':name_of(uid),'base':uid in admin_ids()} for uid in sorted(all_admin_ids())])

@api.put('/api/admins/<uid>')
def set_admin(uid):
    if g.user['id'] not in admin_ids(): raise Forbidden('기본 관리자만 추가 관리자를 지정·해제할 수 있습니다.')
    if uid in admin_ids(): raise Conflict('기본 관리자는 runtime_config.py에서 변경해 주세요.')
    active=payload().get('active')
    if not isinstance(active,bool) or not db().users.find_one({'_id':uid,'enabled':True}): raise BadRequest('사용자와 설정값을 확인해 주세요.')
    e=event([uid],f'관리자 권한이 {"부여" if active else "해제"}되었습니다.',{'type':'admin'},'admin')
    e['audit']=audit_event(f'관리자 {uid} {"지정" if active else "해제"}')['audit']
    db().administrators.update_one({'_id':uid},{'$set':{'active':active,'actor':g.user['id'],'updated':time.time()},'$push':{'outbox':e}},upsert=True)
    return jsonify(ok=True,pending=deliver_pending('administrators',uid))

@api.get('/api/activity')
def activity_history():
    admin();rows,cursor=activity.history(request.args.get('before'))
    for row in rows:
        t=db().tools.find_one({'_id':row['tool']});row['toolName']=t['data']['name'] if t else '삭제된 기능';row['userName']=name_of(row['user'])
    return jsonify(events=rows,nextCursor=cursor,backend='mongodb')

@api.post('/api/tools/<int:tid>/rollback')
def rollback(tid):
    t=tool(tid,True);raw=payload();check_revision(t,raw);n=raw.get('version');vs=copy.deepcopy(t['versions'])
    v=next((v for v in vs if v['n']==n),None)
    if not v or v.get('deleted') or v.get('withdrawn') or n==t['active'] or not v.get('data'): raise Conflict('복구 가능한 버전을 선택해 주세요.')
    if v['path'] and not artifact_path(v['path']).is_file(): raise Conflict('복구 파일이 없습니다.')
    for x in vs:
        if x['n']==t['active']: x['withdrawn']=True
    data={**t['data'],**v['data'],'workflow':v['data'].get('workflow'),'installProfile':v['data'].get('installProfile')};e=event(followers(t),f'{data["name"]} v{n}으로 복구되었습니다.',{'type':'tool','id':tid},'release')
    pending=cas(t,{'$set':{'data':data,'versions':vs,'active':n,'fallback':n,'paused':True},'$push':{'outbox':e}},f'도구 {tid} v{n} 복구')
    return jsonify(ok=True,pending=pending)

def delete_version(tid,n):
    t=tool(tid,True,True)
    if n in {t['active'],t['fallback']}: raise Conflict('현재 배포·복구용 버전은 삭제할 수 없습니다.')
    vs=copy.deepcopy(t['versions']);v=next((v for v in vs if v['n']==n),None)
    if not v: raise NotFound()
    v['deleted']=True
    return cas(t,{'$set':{'versions':vs}},f'도구 {tid} v{n} 파일 삭제 예약')

@api.delete('/api/tools/<int:tid>/versions/<int:n>')
def remove_version(tid,n):
    pending=delete_version(tid,n)
    pending=post_commit.followup_pending('file-purge',purge_deleted) or pending
    return jsonify(ok=True,pending=pending)

def candidates():
    p=db().settings.find_one({'_id':'retention'});result=[]
    for t in db().tools.find():
        vs=sorted([v for v in t['versions'] if not v.get('deleted')],key=lambda x:x['n'],reverse=True)
        for v in vs[p['keep']:]:
            if v['n'] not in {t['active'],t['fallback']} and time.time()-v['created']>p['days']*86400: result.append({'tool':t['_id'],'version':v['n'],'bytes':v['size']})
    return result

@api.put('/api/storage/policy')
def policy():
    admin();raw=payload()
    if raw.get('keep') not in {2,3,5} or raw.get('days') not in {30,90,180}: raise BadRequest('보관 기준을 확인해 주세요.')
    db().settings.update_one({'_id':'retention'},{'$set':{'keep':raw['keep'],'days':raw['days']},'$push':{'outbox':audit_event('보관 기준 변경')}})
    return jsonify(ok=True,pending=deliver_pending('settings','retention'))

@api.get('/api/storage/limits')
def storage_limits():
    admin()
    return jsonify(storage=storage_snapshot())

@api.put('/api/storage/limits')
def update_storage_limits():
    admin();raw=payload()
    if raw.get('mode') not in {'manual','auto'}: raise BadRequest('직접 지정 또는 자동 계산을 선택하세요.')
    for key,minimum in [('quotaBytes',1024**2),('reserveBytes',0),('expectedRevision',0)]:
        value=raw.get(key)
        if type(value) is not int or not minimum<=value<=2**50:
            raise BadRequest('한도·확보할 공간·설정 버전 값을 확인하세요.')
    values={key:raw[key] for key in ['mode','quotaBytes','reserveBytes']}
    values.update(updated=time.time(),updatedBy=g.user['id'])
    revision=raw['expectedRevision']+1
    job=audit_event(
        f'파일 저장 한도 변경: {raw["mode"]}, 한도 {raw["quotaBytes"]} bytes, 여유 공간 {raw["reserveBytes"]} bytes')
    saved_policy=dict(values,revision=revision,source='admin')
    # Filesystem/read errors occur before the authoritative policy write.
    saved_snapshot=storage_snapshot(policy_value=saved_policy)
    if raw['expectedRevision']==0:
        try: db().settings.insert_one(dict(values,_id='storage_limits',revision=revision,outbox=[job]))
        except DuplicateKeyError: raise Conflict('다른 관리자가 설정을 변경했습니다. 새로고침 후 다시 적용하세요.')
    else:
        changed=db().settings.update_one({'_id':'storage_limits','revision':raw['expectedRevision']},
            {'$set':values,'$inc':{'revision':1},'$push':{'outbox':job}})
        if not changed.matched_count: raise Conflict('다른 관리자가 설정을 변경했습니다. 새로고침 후 다시 적용하세요.')
    pending=deliver_pending('settings','storage_limits')
    return jsonify(storage=saved_snapshot,ok=True,pending=pending)

@api.get('/api/storage/candidates')
def storage_preview():
    admin();return jsonify(candidates=candidates())

@api.post('/api/storage/cleanup')
def cleanup():
    admin();chosen=payload().get('candidates')
    if not isinstance(chosen,list) or len(chosen)>1000: raise BadRequest('정리 대상을 확인해 주세요.')
    valid={(x['tool'],x['version']) for x in candidates()}
    if any(not isinstance(x,dict) or (x.get('tool'),x.get('version')) not in valid for x in chosen): raise Conflict('정리 대상이 변경되었습니다.')
    followups_pending=False
    for x in chosen:
        followups_pending=delete_version(x['tool'],x['version']) or followups_pending
    purge_pending=post_commit.followup_pending('file-purge',purge_deleted)
    # Deletion markers are durable. A follow-up count must not turn them into
    # an apparent failed save; unknown counts remain explicitly pending.
    from pymongo.errors import PyMongoError
    try:
        pending_files=sum(1 for t in db().tools.find() for v in t['versions'] if v.get('deleted') and v.get('path'))
        counts_pending=False
    except PyMongoError as error:
        post_commit.log_deferred('purge-count',error)
        pending_files=None;counts_pending=True
    return jsonify(ok=True,pending=True if counts_pending else pending_files or purge_pending,
                   pendingFiles=pending_files,countsPending=counts_pending,followupsPending=followups_pending)

@api.get('/download/<int:tid>/<int:n>')
def download(tid,n):
    purpose=request.args.get('purpose','download')
    if purpose not in {'download','update'}: raise BadRequest('수신 용도를 확인하세요.')
    t=tool(tid);usable(t);v=next((v for v in t['versions'] if v['n']==n),None)
    if not v or v.get('deleted') or v.get('withdrawn'): raise NotFound('배포 가능한 파일이 없습니다.')
    if not v['path']: raise BadRequest('설치·연결 안내를 확인해 주세요.')
    path=artifact_path(v['path'])
    if not path.is_file(): raise NotFound('배포 파일을 찾을 수 없습니다.')
    response=send_file(path,as_attachment=True,download_name=v['name'],mimetype='application/octet-stream',conditional=False)
    if request.method!='HEAD':
        activity.record_download(tid,g.user['id'],n,token_id=getattr(g,'api_token_id',None),update=purpose=='update')
        cleanup_late_tool_write(tid)
        post_commit.followup_pending('download-history',activity.flush,tid,g.user['id'],50)
    response.headers['Cache-Control']='no-store';return response

@api.get('/api/tools/<int:tid>/manifest')
def manifest(tid):
    t=tool(tid);usable(t);v=next(v for v in t['versions'] if v['n']==t['active'])
    if v.get('deleted') or v.get('withdrawn'):
        raise NotFound('현재 배포 가능한 버전이 없습니다.')
    return jsonify(schemaVersion=1,toolId=tid,revision=t['revision'],release=t['active'],filename=v['name'],updatePaused=t.get('paused',False),downloadUrl=f'/download/{tid}/{t["active"]}' if v['path'] else None,url=v['url'],sha256=v['sha'],bytes=v['size'],package=v.get('package'),packageWarning=v.get('packageWarning',''),workflow=v.get('data',{}).get('workflow'),installProfile=v.get('data',{}).get('installProfile'),commands=v.get('commands',{}),deploymentUrl=f'/api/tools/{tid}/releases/{v["n"]}/deployment' if v.get('package') else None,managedInstall=False,notice='배포 원본은 그대로 보관합니다. PC 자동 설치·파일 교체는 수행하지 않습니다.')

@api.get('/api/tools/<int:tid>/releases/<int:n>/deployment')
def deployment_info(tid,n):
    t=tool(tid);usable(t)
    v=next((v for v in t['versions'] if v['n']==n),None)
    if not v or v.get('deleted') or v.get('withdrawn') or not v.get('package'):
        raise NotFound('사용 가능한 배포 정보가 없습니다.')
    response=jsonify(schemaVersion=1,toolId=tid,release=n,activeRelease=t['active'],
        package=v['package'],filename=v['name'],sha256=v['sha'],bytes=v['size'],
        downloadUrl=f'/download/{tid}/{n}',versionCheckUrl=f'/api/tools/{tid}/version-check?release={n}',
        authenticationRequired=True,managedInstall=False,
        installationGuide=v['data']['guide'],environment=v['data']['environment'],workflow=v['data'].get('workflow'),installProfile=v['data'].get('installProfile'),
        notice='상대 주소는 이 웹 서비스 주소 기준입니다. 실제 설치 후 이 배포 번호를 기록하세요. SSO 인증 연결과 실행 시 확인 코드는 도구 제작자가 연결해야 합니다.')
    response.headers['Content-Disposition']=f'attachment; filename="ai-square-{tid}-v{n}.json"'
    return response

@api.get('/api/tools/<int:tid>/version-check')
def version_check(tid):
    """Compare a locally recorded release with the active deployment; no mutation."""
    t=tool(tid);usable(t)
    value=request.args.get('release','')
    if not re.fullmatch(r'[1-9][0-9]{0,8}',value):
        raise BadRequest('현재 설치된 배포 번호를 release에 양의 정수로 입력해 주세요.')
    installed=int(value);active=t['active']
    known=next((v for v in t['versions'] if v['n']==installed),None)
    if not known:
        status='unknown_release';message='설치 버전을 확인할 수 없습니다. 등록한 도구 ID와 배포 번호를 확인해 주세요.'
    elif installed==active:
        status='current';message=f'현재 배포 버전 v{active}를 사용 중입니다.'
    elif installed>active:
        status='rollback_available';message=f'서버 배포가 v{active}로 복구되었습니다. 현재 설치된 v{installed}의 안내를 확인해 주세요.'
    else:
        status='update_available';message=f'새 버전 v{active}가 있습니다. 현재 설치된 버전은 v{installed}입니다.'
    return jsonify(schemaVersion=1,toolId=tid,installedRelease=installed,activeRelease=active,revision=t['revision'],status=status,message=message,installedWithdrawn=bool(known and known.get('withdrawn')),updatePaused=t.get('paused',False),checkedAt=time.time(),checkOnly=True)
