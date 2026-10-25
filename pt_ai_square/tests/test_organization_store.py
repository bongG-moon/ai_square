"""Optional store against real Flask + Mongo contracts and the canonical installer."""
import importlib.util
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from .conftest import ready, publish
from .test_personal_api_usage import issue
from .test_receiver import server
from .test_mcp_real_api import fields
from pt_ai_square.backend.storage import db, ensure_user
from pt_ai_square.backend import mongo_activity

SCRIPT = Path(__file__).resolve().parents[2]/'organization-store/worker.py'
spec = importlib.util.spec_from_file_location('store_real_api', SCRIPT)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def test_key_like_uses_web_idempotent_state_and_only_narrow_mutation(app):
    owner, h = ready(app)
    assert publish(owner, h).status_code == 201
    _, auth = issue(owner, h, 'read')
    client = app.test_client()
    assert client.get('/api/integration/me', headers=auth).json['capabilities']['like'] is True
    for _ in range(3):
        response = client.put('/api/tools/1/like', headers=auth, json={'liked': True})
        assert response.status_code == 200 and response.json['count'] == 1
    assert owner.get('/api/tools/1').json['liked'] is True
    catalog = client.get('/api/catalog', headers=auth).json['items'][0]
    assert catalog['liked'] is True and catalog['statistics']['likes'] == 1
    assert owner.put('/api/tools/1/like', headers=h, json={'liked': False}).status_code == 200
    assert client.get('/api/catalog', headers=auth).json['items'][0]['liked'] is False
    for path in ('/api/local-tokens', '/api/tools/1', '/api/tools/1/grants'):
        assert client.put(path, headers=auth, json={'liked': True}).status_code in {403, 405}
    assert client.delete('/api/tools/1', headers=auth).status_code == 403
    assert client.put('/api/tools/1/like', headers=auth, json={'liked': 'true'}).status_code == 400
    with app.app_context():
        assert db().activity_state.count_documents({'tool': 1, 'kind': 'like', 'user': 'owner'}) == 1


def test_registrant_is_real_publisher_not_editable_contact_label(app):
    owner, h = ready(app)
    assert publish(owner, h, owner='담당부서 연락처').status_code == 201
    member, mh = ready(app, 'member')
    _, auth = issue(member, mh, 'read')
    with app.app_context():
        db().users.update_one({'_id': 'owner'}, {'$set': {'name': '실제 등록자'}})
    client = app.test_client()
    catalog = client.get('/api/catalog', headers=auth).json['items'][0]
    detail = client.get('/api/tools/1', headers=auth).json
    for item in (catalog, detail):
        assert item['owner'] == '담당부서 연락처'
        assert item['registrantId'] == 'owner' and item['registrantName'] == '실제 등록자'
    with app.app_context():
        db().users.delete_one({'_id': 'owner'})
    assert client.get('/api/catalog', headers=auth).json['items'][0]['registrantName'] == '등록자 정보 없음'


def test_views_only_explicit_open_share_web_key_cooldown_and_do_not_change_rank(app):
    owner, h = ready(app)
    assert publish(owner, h).status_code == 201
    _, auth = issue(owner, h, 'read')
    api = app.test_client()
    assert api.get('/api/integration/me', headers=auth).json['capabilities']['view'] is True
    for _ in range(3):
        assert api.get('/api/tools/1', headers=auth).json['views'] == 0
        assert api.get('/api/tools/1/manifest', headers=auth).status_code == 200
    first = owner.post('/api/tools/1/view', headers=h, json={})
    assert first.status_code == 200 and first.json['views'] == 1 and first.json['counted']
    second = api.post('/api/tools/1/view', headers=auth, json={})
    assert second.status_code == 200 and second.json['views'] == 1 and not second.json['counted']
    with app.app_context():
        db().activity_state.update_one({'tool': 1, 'kind': 'view'}, {'$inc': {'lastViewedAt': -1801}})
    assert api.post('/api/tools/1/view', headers=auth, json={}).json['views'] == 2
    catalog = api.get('/api/catalog', headers=auth).json['items'][0]['statistics']
    assert catalog['views'] == 2 and catalog['rankScore'] == catalog['totalRankScore'] == 0
    assert owner.get('/api/tools/1').json['views'] == 2
    assert api.post('/api/tools/1/view', headers=auth, json={'user': 'other'}).status_code == 400
    with app.app_context():
        assert db().activity_state.count_documents({'tool': 1, 'kind': 'view'}) == 1
        assert db().activity.count_documents({'tool': 1, 'kind': 'view'}) == 0
        assert not db().activity_state.find_one({'tool': 1, 'kind': 'view'}).get('outbox')


def test_view_permission_and_concurrent_count_are_atomic(app):
    owner, h = ready(app)
    assert publish(owner, h, approval=True).status_code == 201
    member, mh = ready(app, 'member')
    _, auth = issue(member, mh, 'read')
    assert app.test_client().post('/api/tools/1/view', headers=auth, json={}).status_code == 403
    def visit(_):
        with app.app_context():
            return mongo_activity.record_view(1, 'owner')
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(visit, range(24)))
    assert sum(result['counted'] for result in results) == 1
    with app.app_context():
        assert db().activity_state.find_one({'tool': 1, 'kind': 'view'})['count'] == 1


def test_department_catalog_and_details_match_and_do_not_leak_other_user_likes(app):
    owner, h = ready(app)
    assert publish(owner, h, approval=True).status_code == 201
    member, mh = ready(app, 'member')
    other, oh = ready(app, 'other')
    _, auth = issue(member, mh, 'read')
    _, other_auth = issue(other, oh, 'read')
    with app.app_context():
        ensure_user('member', 'Member', 'Team A', 'TEAM-A')
        ensure_user('other', 'Other', 'Team A', 'TEAM-B')
    assert owner.post('/api/tools/1/grants/departments', headers=h,
                      json={'departments': [{'code': 'TEAM-A', 'name': 'Team A'}]}).status_code == 200
    api = app.test_client()
    assert api.get('/api/catalog', headers=auth).json['items'][0]['access'] == 'approved'
    assert api.get('/api/tools/1', headers=auth).status_code == 200
    assert api.put('/api/tools/1/like', headers=auth, json={'liked': True}).status_code == 200
    denied = api.get('/api/catalog', headers=other_auth).json['items'][0]
    assert denied['access'] == 'permission_required' and denied['liked'] is False
    assert api.put('/api/tools/1/like', headers=other_auth, json={'liked': True}).status_code == 403
    assert api.get('/api/tools/1', headers=other_auth).status_code == 403
    with app.app_context():
        ensure_user('member', 'Member', 'Team B', 'TEAM-B')
    assert api.get('/api/catalog', headers=auth).json['items'][0]['access'] == 'permission_required'
    assert api.get('/download/1/1', headers=auth).status_code == 403


@pytest.mark.parametrize('scope', ['project', 'directory', 'user'])
def test_store_real_api_install_like_download_update_rollback(app, server, tmp_path, monkeypatch, scope):
    owner, h = ready(app)
    issued, _ = issue(owner, h)
    monkeypatch.setenv('PTAI_API_TOKEN', issued['token'])
    home, workspace, data = [tmp_path / x for x in ('home', 'workspace', 'extension-data')]
    for path in (home, workspace, data):
        path.mkdir()
    source = workspace/'SKILL.md'
    source.write_text('---\nname: store-test\ndescription: Fixture\n---\n# One\n', encoding='utf-8')
    config = tmp_path/'existing-mcp/config.json'
    worker.save_config(config, server, [workspace, data], allow_http=True, download_directory=data)
    publisher = worker.Runtime(worker.Settings(config), home=home)
    def release(changes, tool_id=None):
        metadata = fields(); metadata['changes'] = changes
        draft = publisher.prepare_publish(metadata, str(source), target='update' if tool_id else 'new', tool_id=tool_id)
        approved = owner.post('/api/publish-drafts/'+draft['id']+'/approve', headers=h,
                              json={'approval': False, 'reviewDigest': draft['reviewDigest']})
        assert approved.status_code == 200
        return publisher.publish_item(draft['id'])
    first = release('First')
    store = worker.Store(data, {'workspace': str(workspace)}, home=home, existing_config=config)
    chosen = tmp_path/'selected-directory'; chosen.mkdir()
    if scope == 'directory':
        info = chosen.stat()
        store.context.update(selectedDirectory=str(chosen), selectedDirectoryIdentity=[info.st_dev, info.st_ino], directoryToken='a'*43)
    before = config.read_bytes()
    assert store.dispatch('connect', {'reuseExisting': True})['configured']
    tid = first['id']
    assert store.dispatch('options')['organizations']
    assert store.dispatch('catalog', {'q': '업무 메모'})['items'][0]['id'] == tid
    assert store.dispatch('detail', {'toolId': tid})['canInstall']
    for _ in range(2):
        assert store.dispatch('like', {'toolId': tid, 'liked': True})['count'] == 1
    download = store.dispatch('download', {'toolId': tid, 'update': True})
    assert download['downloaded'] and not download['installed'] and download['purpose'] == 'download'
    plan = store.dispatch('prepareInstall', {'toolId': tid, 'scope': scope})
    assert plan['scopeDir'] == str(chosen if scope == 'directory' else home if scope == 'user' else workspace)
    installed = store.dispatch('install', dict(plan, confirmed=True))
    assert installed['installed']
    target = Path(installed['destination'])/'SKILL.md'
    assert target.read_bytes() == source.read_bytes()
    original = target.read_bytes()
    assert store.dispatch('checkUpdates')['items'][0]['result']['status'] == 'current'
    source.write_text('# Two\n', encoding='utf-8')
    release('Second', tid)
    assert store.dispatch('checkUpdates')['items'][0]['result']['status'] == 'update_available'
    plan2 = store.dispatch('prepareInstall', {'toolId': tid, 'scope': scope})
    second = store.dispatch('install', dict(plan2, confirmed=True))
    assert target.read_bytes() == source.read_bytes()
    assert store.dispatch('verify', {'installationId': second['installationId']})['filesIntact']
    assert owner.get(f'/api/tools/{tid}').json['downloads'] == 1
    assert owner.get(f'/api/tools/{tid}').json['likes'] == 1
    with app.app_context():
        assert db().activity.count_documents({'tool': tid, 'kind': 'download', 'counted': True}) == 1
        assert db().activity.count_documents({'tool': tid, 'kind': 'download', 'purpose': 'update'}) == 1
    store.dispatch('rollback', dict(installationId=second['installationId'], confirmed=True))
    assert target.read_bytes() == original
    assert store.dispatch('installations')['items'][0]['release'] == 1
    assert config.read_bytes() == before
    store.dispatch('disconnect')
    assert config.read_bytes() == before and target.read_bytes() == original
