"""Real isolated-Mongo catalog ranking, access and recommendation contracts."""
import json
import time
from types import SimpleNamespace

import pytest
from pymongo.collection import Collection

from pt_ai_square.backend import catalog_search as catalog
from pt_ai_square.backend.mongo_activity import statistics, record_download, set_like
from pt_ai_square.backend.storage import db
from .conftest import ready


@pytest.fixture
def search_app(app):
    # The production route delegates to this callable. Keep this suite runnable
    # while the parallel endpoint/auth integration is being implemented.
    app.view_functions['local_access.search'] = catalog.search_catalog
    return app


def seed(app, tid, name='메일 조회', **changes):
    data = dict(name=name, desc='업무 메일 내용을 조회합니다.', type='MCP/Tool',
                platform='Claude', org='공통', orgId='organization-0',
                category='공통 업무', categoryId='category-0', workTags=['메일', '조회'],
                approval=False, guide='PRIVATE GUIDE', workflow=[{'text': 'PRIVATE FLOW'}])
    data.update(changes.pop('data', {}))
    row = dict(_id=tid, data=data, owner='owner', created=1000 + tid, deleted=False,
               revision=1, versions=[{'path': 'PRIVATE PATH', 'package': {'secret': 'SECRET PACKAGE'}}])
    row.update(changes)
    with app.app_context():
        db().tools.insert_one(row)
    return row


def client(app, uid='member', dept='D001'):
    c, h = ready(app, uid)
    with app.app_context():
        db().users.update_one({'_id': uid}, {'$set': {'dept_cd': dept}})
    return c, h


def vote(app, tid, uid, kind='download', when=None, **extra):
    when = time.time() if when is None else when
    row = dict(_id=f'{kind}:{tid}:{uid}', tool=tid, user=uid, kind=kind, created=when)
    row.update({'liked': True, 'firstLikedAt': when} if kind == 'like'
               else {'count': 1, 'firstDownloadedAt': when})
    row.update(extra)
    with app.app_context():
        db().activity_state.insert_one(row)


def department(app, tid, count=5, code='D001', prefix='colleague', when=None):
    with app.app_context():
        db().users.insert_many([dict(_id=prefix + str(i), name='PRIVATE PERSON', dept_cd=code,
                                    enabled=True) for i in range(count)])
    for i in range(count):
        vote(app, tid, prefix + str(i), when=when)


def test_catalog_preserves_summary_access_for_owner_admin_grantee_and_member(search_app):
    seed(search_app, 1, data={'approval': True})
    seed(search_app, 2, '삭제 도구', deleted=True)
    seed(search_app, 3, '삭제 중 도구', purge={'requested': True})
    c, _ = client(search_app)
    row = c.get('/api/catalog').json['items'][0]
    assert row['access'] == 'permission_required'
    assert row['name'] == '메일 조회'
    encoded = json.dumps(row, ensure_ascii=False)
    for secret in ['PRIVATE GUIDE', 'PRIVATE FLOW', 'PRIVATE PATH', 'SECRET PACKAGE', 'versions', 'workflow']:
        assert secret not in encoded
    assert c.get('/api/catalog').json['total'] == 1
    with search_app.app_context():
        db().access.insert_one({'tool': 1, 'user': 'member', 'granted': True})
    assert c.get('/api/catalog').json['items'][0]['access'] == 'approved'
    for uid in ['owner', 'admin']:
        c, _ = client(search_app, uid)
        assert c.get('/api/catalog').json['items'][0]['access'] == 'approved'


def test_name_tag_description_search_synonyms_and_exact_match(search_app):
    seed(search_app, 1, 'email reader')
    seed(search_app, 2, '메일', data={'desc': '내용', 'workTags': []})
    seed(search_app, 3, '설비 점검', data={'desc': 'mail 연동도 지원', 'workTags': []})
    seed(search_app, 4, '별도 도구', data={'desc': '내용', 'workTags': ['이메일']})
    c, _ = client(search_app)
    data = c.get('/api/catalog?q=메일').json
    assert data['total'] == 4
    assert data['items'][0]['id'] == 2
    assert all(row['reasons'] for row in data['items'])
    assert c.get('/api/catalog?q=3').json['items'][0]['id'] == 3
    assert c.get('/api/catalog?q=.*').json['total'] == 0


def test_team_preference_only_breaks_relevance_ties(search_app):
    seed(search_app, 1, '메일 조회 A')
    seed(search_app, 2, '메일 조회 B')
    seed(search_app, 3, '메뉴 검색', data={'desc': '메뉴 조회', 'workTags': ['검색']})
    department(search_app, 1)
    department(search_app, 3, 10, prefix='other-voter')
    c, _ = client(search_app)
    data = c.get('/api/catalog?q=메일 조회하는 도구').json
    assert [x['id'] for x in data['items']] == [1, 2, 3]
    assert data['items'][0]['departmentPreference']['distinctUsers'] == 5
    assert data['recommendation']['status'] == 'applied'
    assert data['dataAsOf'] > 0
    assert 'PRIVATE PERSON' not in json.dumps(data)
    assert 'colleague0' not in json.dumps(data)
    assert 'other-voter' not in json.dumps(data)


@pytest.mark.parametrize('uid', ['member', 'admin'])
def test_department_is_server_identity_not_query_user_or_department(search_app, uid):
    seed(search_app, 1, '메일 A')
    seed(search_app, 2, '메일 B')
    department(search_app, 1, code='D001')
    department(search_app, 2, 8, code='D002', prefix='other-team')
    c, _ = client(search_app, uid)
    data = c.get('/api/catalog?q=메일&userId=other&dept_cd=D002&dept=D002').json
    assert data['items'][0]['id'] == 1
    assert data['items'][1]['departmentPreference']['status'] == 'insufficient_sample'


def test_small_samples_no_department_name_inference_and_90_day_window(search_app):
    seed(search_app, 1)
    seed(search_app, 2)
    department(search_app, 1, 4)
    department(search_app, 2, 5, prefix='old-voter', when=time.time()-91*86400)
    c, _ = client(search_app)
    data = c.get('/api/catalog').json
    assert data['recommendation']['status'] == 'insufficient_sample'
    assert all('distinctUsers' not in row['departmentPreference'] for row in data['items'])
    # Similar names, prefixes, request orgId or shared taxonomy are not identity.
    with search_app.app_context():
        db().users.update_many({}, {'$set': {'dept': '개발팀', 'orgId': 'organization-0'}})
        db().users.update_one({'_id': 'member'}, {'$set': {'dept_cd': ''}})
    assert c.get('/api/catalog?orgId=organization-0').json['recommendation']['status'] == 'department_unknown'


def test_moved_disabled_requester_and_update_only_users_do_not_create_team_sample(search_app):
    seed(search_app, 1)
    department(search_app, 1, 7)
    c, _ = client(search_app)
    with search_app.app_context():
        db().users.update_one({'_id': 'colleague0'}, {'$set': {'dept_cd': 'D001-child'}})
        db().users.update_one({'_id': 'colleague1'}, {'$set': {'enabled': False}})
        db().activity_state.update_one({'user': 'colleague2'}, {'$set': {'firstDownloadedAt': None}})
    vote(search_app, 1, 'member')
    assert c.get('/api/catalog').json['recommendation']['status'] == 'insufficient_sample'


def test_rankings_match_shared_web_metrics_and_tie_breaks(search_app, monkeypatch):
    now = time.time()
    monkeypatch.setattr(catalog, 'time', SimpleNamespace(time=lambda: now))
    for tid in range(1, 5):
        seed(search_app, tid)
    vote(search_app, 1, 'a', 'like', now-8*86400)
    vote(search_app, 1, 'b', 'like', now-8*86400)
    vote(search_app, 1, 'c', when=now-8*86400)
    vote(search_app, 2, 'a', 'like', now-60)
    vote(search_app, 2, 'a', when=now-60)
    vote(search_app, 3, 'a', when=now-60)
    vote(search_app, 3, 'b', when=now-60)
    vote(search_app, 3, 'c', when=now-60)
    # Legacy duplicate download is still one person, including first date.
    vote(search_app, 3, 'a', when=now-8*86400, _id='legacy-download')
    vote(search_app, 4, 'future', 'like', now+86400)
    vote(search_app, 4, 'update', firstDownloadedAt=None)
    vote(search_app, 4, 'boundary', when=now-7*86400)
    with search_app.app_context():
        shared = statistics([1, 2, 3, 4], 'member', now)
        bulk = catalog._statistics([1, 2, 3, 4], now)
        assert bulk == {tid: {k: v for k, v in row.items() if k != 'liked'} for tid, row in shared.items()}
    c, _ = client(search_app)
    for mode in ['realtime', 'cumulative']:
        data = c.get('/api/catalog?sort='+mode).json
        score, downloads, likes = ('rankScore', 'recentDownloads', 'recentLikes') if mode == 'realtime' else ('totalRankScore', 'downloads', 'likes')
        expected = sorted(shared, key=lambda tid: (-shared[tid][score], -shared[tid][downloads], -shared[tid][likes], -(1000+tid), tid))
        assert [row['id'] for row in data['items']] == expected
        assert data['recommendation']['status'] == 'not_used_for_ranking'


def test_repeat_download_update_and_rel_like_do_not_boost_recent_counts(search_app):
    seed(search_app, 1)
    now = time.time()
    vote(search_app, 1, 'member', when=now-8*86400)
    vote(search_app, 1, 'member', 'like', when=now-8*86400)
    with search_app.app_context():
        for _ in range(4):
            record_download(1, 'member', 2, update=True)
            record_download(1, 'member', 1)
            set_like(1, 'member', False)
            set_like(1, 'member', True)
        record_download(1, 'update-only', 2, update=True)
    c, _ = client(search_app)
    metric = c.get('/api/catalog').json['items'][0]['statistics']
    assert metric == dict(downloads=1, likes=1, recentLikes=0, recentDownloads=0, rankScore=0, totalRankScore=3)


def test_filters_pagination_newest_and_aliases(search_app):
    for tid in range(1, 4):
        seed(search_app, tid, data={'type': 'Skill', 'platform': 'ChatGPT'})
    seed(search_app, 4)
    c, _ = client(search_app)
    data = c.get('/api/catalog?q=메일&type=Skill&platform=ChatGPT&orgId=organization-0&sort=newest&limit=2').json
    assert [r['id'] for r in data['items']] == [3, 2]
    assert data['total'] == 3 and data['nextOffset'] == 2
    assert c.get('/api/catalog?type=Skill&sort=newest&offset=2').json['items'][0]['id'] == 1
    assert c.get('/api/catalog?sort=all').json['sort'] == 'cumulative'
    assert c.get('/api/catalog?sort=recent').json['sort'] == 'realtime'
    for query in ['limit=0', 'limit=no', 'offset=-1', 'sort=invalid', 'platform=unknown', 'type=invalid']:
        assert c.get('/api/catalog?'+query).status_code == 400


def test_candidate_and_department_caps_are_reported_without_false_global_rank(search_app, monkeypatch):
    for tid in range(1, 5):
        seed(search_app, tid)
    department(search_app, 1)
    monkeypatch.setattr(catalog, 'CANDIDATE_LIMIT', 2)
    monkeypatch.setattr(catalog, 'DEPARTMENT_MEMBER_LIMIT', 3)
    c, _ = client(search_app)
    data = c.get('/api/catalog').json
    assert data['total'] == 4 and data['evaluatedCount'] == 2
    assert data['complete'] is False and data['warning']
    assert data['nextOffset'] is None
    assert data['recommendation']['status'] == 'department_too_large'


def test_candidate_cap_keeps_exact_and_strong_lexical_matches(search_app, monkeypatch):
    for tid in range(1, 6):
        seed(search_app, tid, '기타 도구', data={'desc': '메일을 부가적으로 지원', 'workTags': []})
    seed(search_app, 99, '메일')
    seed(search_app, 100, '메일 연동')
    monkeypatch.setattr(catalog, 'CANDIDATE_LIMIT', 2)
    c, _ = client(search_app)
    data = c.get('/api/catalog?q=메일').json
    assert data['complete'] is False
    assert [row['id'] for row in data['items']] == [99, 100]


def test_catalog_bulk_lookups_are_not_per_tool(search_app, monkeypatch):
    for tid in range(1, 31):
        seed(search_app, tid)
    department(search_app, 1)
    c, _ = client(search_app)
    calls = []
    original = Collection.find
    def observed(self, *args, **kwargs):
        calls.append(self.name)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Collection, 'find', observed)
    response = c.get('/api/catalog?limit=100')
    assert response.status_code == 200
    assert len(response.json['items']) == 30
    # One metadata query each, regardless of the number of catalog rows.
    assert calls.count('taxonomy') <= 2  # Auth public_user resolves its one org.
    assert calls.count('access') == 1
    assert calls.count('users') <= 2  # Authentication plus bulk department list.


def test_personal_key_can_search_but_cannot_obtain_private_history(search_app):
    seed(search_app, 1, data={'approval': True})
    c, h = client(search_app)
    issued = c.post('/api/local-tokens', headers=h, json={'name': '검색 연결', 'scope': 'read'})
    assert issued.status_code == 201
    auth = {'Authorization': 'Bearer '+issued.json['token']}
    api = search_app.test_client()
    response = api.get('/api/catalog?q=메일', headers=auth)
    assert response.status_code == 200
    assert response.json['items'][0]['access'] == 'permission_required'
    assert api.get('/api/tools/1', headers=auth).status_code == 403
    assert api.get('/api/activity', headers=auth).status_code == 403
    assert 'PRIVATE' not in json.dumps(response.json)
