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


def test_registrant_name_and_contact_search_preserve_identity_and_access(search_app):
    seed(search_app, 1, '회의 정리', data={'approval': True, 'owner': '지원 담당',
                                      'desc': '회의 기록', 'workTags': []})
    seed(search_app, 2, '일정 정리', owner='other', data={'owner': '김하늘',
                                                    'desc': '일정 기록', 'workTags': []})
    seed(search_app, 3, '삭제 도구', deleted=True)
    seed(search_app, 4, '삭제 중 도구', purge={'requested': True})
    with search_app.app_context():
        db().users.update_one({'_id': 'owner'}, {'$set': {'name': '김하늘'}})
        db().users.update_one({'_id': 'other'}, {'$set': {'name': 'Lee (AX)'}})
    c, h = client(search_app)
    issued = c.post('/api/local-tokens', headers=h, json={'name': '검색 연결'})
    auth = {'Authorization': 'Bearer ' + issued.json['token']}
    api = search_app.test_client()
    for caller, headers in [(c, {}), (api, auth)]:
        result = caller.get('/api/catalog', query_string={'q': '김하늘'}, headers=headers)
        assert result.status_code == 200
        assert result.json['total'] == 2
        first, second = result.json['items']
        assert [first['id'], second['id']] == [1, 2]
        assert first['registrantName'] == '김하늘' and first['owner'] == '지원 담당'
        assert first['access'] == 'permission_required'
        assert any('등록자 이름' in reason for reason in first['reasons'])
        assert second['registrantName'] == 'Lee (AX)' and second['owner'] == '김하늘'
        assert any('담당자 이름' in reason for reason in second['reasons'])
        assert 'PRIVATE' not in json.dumps(result.json)
        assert caller.get('/api/tools/1', headers=headers).status_code == 403
        assert caller.get('/api/catalog?q=.*', headers=headers).json['total'] == 0
    assert c.get('/api/catalog?q=lee').json['items'][0]['id'] == 2
    assert c.get('/api/catalog?q=하늘').json['items'][0]['id'] == 1
    with search_app.app_context():
        db().users.update_one({'_id': 'owner'}, {'$set': {'name': '김새봄'}})
    assert c.get('/api/catalog?q=김새봄').json['items'][0]['id'] == 1
    assert [row['id'] for row in c.get('/api/catalog?q=김하늘').json['items']] == [2]


def test_registrant_relevance_is_applied_before_candidate_cap(search_app, monkeypatch):
    for tid in range(1, 5):
        seed(search_app, tid, '참고 도구', owner='other',
             data={'desc': '김하늘 관련 자료', 'workTags': []})
    seed(search_app, 99, '회의 정리', data={'desc': '기록', 'workTags': []})
    with search_app.app_context():
        db().users.update_one({'_id': 'owner'}, {'$set': {'name': '김하늘'}})
    monkeypatch.setattr(catalog, 'CANDIDATE_LIMIT', 1)
    c, _ = client(search_app)
    result = c.get('/api/catalog?q=김하늘').json
    assert result['total'] == 5 and result['complete'] is False
    assert [row['id'] for row in result['items']] == [99]


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


def test_small_samples_and_90_day_window_also_apply_to_exact_department_names(search_app):
    seed(search_app, 1)
    seed(search_app, 2)
    department(search_app, 1, 4)
    department(search_app, 2, 5, prefix='old-voter', when=time.time()-91*86400)
    c, _ = client(search_app)
    data = c.get('/api/catalog').json
    assert data['recommendation']['status'] == 'insufficient_sample'
    assert all('distinctUsers' not in row['departmentPreference'] for row in data['items'])
    # Exact server-side department names can match if the code is unavailable,
    # but the same sample threshold and time window still apply.
    with search_app.app_context():
        db().users.update_many({}, {'$set': {'dept': '개발팀', 'orgId': 'organization-0'}})
        db().users.update_one({'_id': 'member'}, {'$set': {'dept_cd': ''}})
    meta = c.get('/api/catalog?orgId=organization-0').json['recommendation']
    assert meta['status'] == 'insufficient_sample'
    assert meta['identitySource'] == 'department_name'


def test_exact_department_name_fallback_ranks_peers_without_disclosing_people(search_app):
    seed(search_app, 1, '메일 조회 A')
    seed(search_app, 2, '메일 조회 B')
    department(search_app, 1, code='')
    department(search_app, 2, 8, code='D999', prefix='unrelated')
    with search_app.app_context():
        db().users.update_many({'_id': {'$regex': '^colleague'}}, {'$set': {'dept': 'AI 개발팀'}})
        db().users.update_many({'_id': {'$regex': '^unrelated'}}, {'$set': {'dept': 'AI 개발팀 지원'}})
    c, h = client(search_app, dept='')
    with search_app.app_context():
        db().users.update_one({'_id': 'member'}, {'$set': {'dept': 'AI 개발팀'}})
    token = c.post('/api/local-tokens', headers=h, json={'name': '부서명 추천'}).json['token']
    for caller, headers in [(c, {}), (search_app.test_client(), {'Authorization': 'Bearer ' + token})]:
        response = caller.get('/api/catalog', query_string={'q': '메일 내용 찾아줘',
                              'dept': 'AI 개발팀 지원', 'dept_cd': 'D999'}, headers=headers)
        assert response.status_code == 200
        data = response.json
        assert [row['id'] for row in data['items']] == [1, 2]
        assert data['recommendation']['identitySource'] == 'department_name'
        assert data['items'][0]['departmentPreference'] == {
            'status': 'applied', 'distinctUsers': 5, 'identitySource': 'department_name'}
        assert data['items'][1]['departmentPreference']['status'] == 'insufficient_sample'
        assert 'PRIVATE PERSON' not in json.dumps(data) and 'colleague0' not in json.dumps(data)


def test_department_code_precedes_same_name_and_ambiguous_names_are_not_combined(search_app):
    seed(search_app, 1)
    seed(search_app, 2)
    department(search_app, 1, code='D001')
    department(search_app, 2, 8, code='D002', prefix='same-name')
    c, _ = client(search_app)
    with search_app.app_context():
        db().users.update_many({}, {'$set': {'dept': '개발팀'}})
    known = c.get('/api/catalog').json
    assert known['items'][0]['id'] == 1
    assert known['recommendation']['identitySource'] == 'department_code'
    with search_app.app_context():
        db().users.update_one({'_id': 'member'}, {'$set': {'dept_cd': ''}})
    unknown = c.get('/api/catalog').json
    assert unknown['recommendation']['status'] == 'department_ambiguous'
    assert all('distinctUsers' not in row['departmentPreference'] for row in unknown['items'])
    # A shared default label does not identify one team, either.
    with search_app.app_context():
        db().users.update_many({}, {'$set': {'dept': '공통', 'dept_cd': ''}})
    assert c.get('/api/catalog').json['recommendation']['status'] == 'department_unknown'


def test_department_name_fallback_requires_enough_enabled_current_peers(search_app):
    seed(search_app, 1)
    department(search_app, 1, 5, code='D001')
    c, _ = client(search_app, dept='')
    with search_app.app_context():
        db().users.update_many({}, {'$set': {'dept': 'AI 개발팀'}})
        db().users.update_one({'_id': 'colleague0'}, {'$set': {'enabled': False}})
    assert c.get('/api/catalog').json['recommendation']['status'] == 'insufficient_sample'
    with search_app.app_context():
        db().users.update_one({'_id': 'colleague0'}, {'$set': {'enabled': True, 'dept': '개발팀'}})
    assert c.get('/api/catalog').json['recommendation']['status'] == 'insufficient_sample'


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
    assert metric == dict(downloads=1, likes=1, views=0, recentLikes=0, recentDownloads=0, rankScore=0, totalRankScore=3)


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


def test_conversational_subject_ranking_precedes_popularity_and_candidate_cap(search_app, monkeypatch):
    seed(search_app, 1, '폴더 정리', data={
        'desc': '폴더 내용을 정리합니다.', 'workTags': ['파일 정리'], 'category': '공통 업무'})
    seed(search_app, 99, '회의록 만들기', data={
        'desc': '회의에서 결정한 일을 정리합니다.', 'workTags': ['회의 기록'], 'category': '공통 업무'})
    department(search_app, 1, 8)
    c, _ = client(search_app)
    query = {'q': '회의 내용을 정리해 줘'}
    results = c.get('/api/catalog', query_string=query).json
    assert [row['id'] for row in results['items']] == [99, 1]
    monkeypatch.setattr(catalog, 'CANDIDATE_LIMIT', 1)
    limited = c.get('/api/catalog', query_string=query).json
    assert limited['total'] == 2 and limited['complete'] is False
    assert [row['id'] for row in limited['items']] == [99]


@pytest.mark.parametrize('query, name', [
    ('엑셀 파일을 하나로 합치고 싶어', 'Excel 병합'),
    ('PPT 발표 자료 만들기', 'PowerPoint 제작'),
    ('전에 하던 업무를 이어서 하고 싶어', '업무 이어하기'),
    ('meeting minutes', '회의록'),
    ('코드에서', '코드에서'),
    ('매주 받은 엑셀 여러 개를 한 파일로 합치고 싶어요', 'Excel 병합'),
    ('회의록 길어서 핵심만 정리해주는 기능', '회의록 요약'),
    ('PPT 발표자료 만들고 싶어요', 'PowerPoint 제작'),
    ('메일 내용 찾아줘', 'Email 조회'),
    ('메일에서 첨부파일만 모으고 싶어', 'Email attachment collect'),
    ('두 엑셀에서 다른 부분 찾아주는 기능이 필요해요', 'Excel diff'),
    ('이미지 속 글자를 엑셀로 바꾸고 싶어요', 'OCR 변환'),
])
def test_conversational_and_literal_queries_reach_the_database_candidates(search_app, query, name):
    seed(search_app, 42, name, data={'desc': '등록 설명', 'workTags': [], 'category': '분류'})
    c, h = client(search_app)
    key = c.post('/api/local-tokens', headers=h, json={'name': '일상 표현 검색'}).json['token']
    for caller, headers in [(c, {}), (search_app.test_client(), {'Authorization': 'Bearer ' + key})]:
        response = caller.get('/api/catalog', query_string={'q': query}, headers=headers)
        assert response.status_code == 200
        assert [row['id'] for row in response.json['items']] == [42]
        assert response.json['items'][0]['reasons']
        assert response.json['queryInterpretation']['method'] == 'local_concept_matching'
        assert response.json['queryInterpretation']['concepts']


def test_natural_language_synonyms_are_ranked_before_popularity_and_cap(search_app, monkeypatch):
    seed(search_app, 1, '폴더 정리', data={'desc': '여러 파일을 자동으로 정리합니다.',
                                        'workTags': ['자료'], 'category': '공통 업무'})
    seed(search_app, 99, 'OCR 변환', data={'desc': 'Excel로 결과를 저장합니다.',
                                         'workTags': [], 'category': '공통 업무'})
    department(search_app, 1, 8)
    c, _ = client(search_app)
    query = {'q': '이미지 속 글자를 엑셀로 바꾸고 싶어요'}
    result = c.get('/api/catalog', query_string=query).json
    assert result['items'][0]['id'] == 99
    monkeypatch.setattr(catalog, 'CANDIDATE_LIMIT', 1)
    assert c.get('/api/catalog', query_string=query).json['items'][0]['id'] == 99


def test_related_ties_use_department_then_overall_popularity_with_evidence(search_app):
    for tid in range(1, 4):
        seed(search_app, tid, f'메일 조회 {tid}')
    department(search_app, 1)
    for i in range(8):
        vote(search_app, 2, f'other{i}', kind='like')
    vote(search_app, 3, 'one-reader')
    c, _ = client(search_app)
    results = c.get('/api/catalog', query_string={'q': '메일 내용 찾아줘'}).json
    assert [row['id'] for row in results['items']] == [1, 2, 3]
    assert any('같은 부서 구성원 5명' in reason for reason in results['items'][0]['reasons'])
    assert any('좋아요 8개' in reason for reason in results['items'][1]['reasons'])


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
    assert calls.count('users') <= 3  # Authentication, one registrar batch, one department batch.


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
