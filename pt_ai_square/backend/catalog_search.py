"""Employee-scoped, explainable catalog search; no private detail or DB access.

All data comes from the authenticated server identity. Recommendation signals
are aggregates of current department members; they never accept a caller's user
or department identity. Candidate limits are reported rather than presented as
an exhaustive global ranking.
"""
import re
import time
import unicodedata

from flask import g, jsonify, request
from werkzeug.exceptions import BadRequest

from .storage import db
from .tool_access import can_read

CANDIDATE_LIMIT = 5000
DEPARTMENT_MEMBER_LIMIT = 10000
MIN_DEPARTMENT_USERS = 5
DEPARTMENT_DAYS = 90
QUERY_FIELDS = ('name', 'workTags', 'desc', 'category', 'owner')
FIELD_WEIGHTS = {'name': 8, 'workTags': 6, 'desc': 2, 'category': 4, 'owner': 4, 'registrant': 5}
SYNONYM_GROUPS = (
    ('메일', '이메일', 'email', 'e-mail', 'mail'),
    ('회의록', '회의메모', '회의 메모', 'meeting minutes'),
    ('엑셀', 'excel', '스프레드시트', 'spreadsheet'),
    ('요약', 'summarize', 'summary'),
    ('조회', '검색', 'search', 'lookup'),
    ('보고서', 'report'),
    ('ppt', 'powerpoint', '파워포인트', '슬라이드', '발표자료', '발표 자료'),
    ('병합', '합치기', '합치', '합쳐', 'merge'),
    ('업무 기록', '작업 기록', '업무기록', '작업기록'),
    ('이어하기', '이어서', '재개', 'resume'),
    ('만들기', '만들', '생성', '작성', '제작', 'create'),
)
STOP_WORDS = {'도구', '기능', 'tool', 'tools', '찾아줘', '추천', '추천해줘',
              '우리', '우리팀', '팀', '부서', '쓸', '사용할', '알려줘',
              '좀', '줘', '주세요', '싶어', '싶어요', '싶습니다', '하고',
              '해', '할', '수', '있는', '있어', '있나요', '있을까',
              '전에', '하던', '했던', '하나로'}
# Explicit everyday action forms, not an unrestricted Korean stemmer. Keep the
# original token too, so a literal tool/registrant name remains discoverable.
ACTION_FORMS = {
    '합치는': '병합', '합치고': '병합', '합칠': '병합',
    '합쳐줘': '병합', '합쳐주세요': '병합',
    '만드는': '만들기', '만들어': '만들기', '만들고': '만들기',
    '만들어줘': '만들기', '만들어주세요': '만들기',
    '이어갈': '이어하기', '이어가고': '이어하기',
}
# Generic words may help, but must not outweigh the subject of a longer request
# (e.g. 회의 in "회의 내용을 정리해 줘"). Apply this both before and after the
# candidate cap; popularity is still only a tie-break for text relevance.
GENERIC_TERMS = {'파일', '자료', '내용', '업무', '작업', '정리',
                 '만들기', '만들', '생성', '작성', '제작', 'create'}
SORT_ALIASES = {'recent': 'realtime', 'all': 'cumulative', 'total': 'cumulative'}


def normalize(value):
    return unicodedata.normalize('NFKC', str(value or '')).casefold().strip()


def _query_stem(term):
    if term in ACTION_FORMS:
        return ACTION_FORMS[term]
    stem = re.sub(r'(?:해주는|해주세요|해줘|하는|하기|하고|해|으로|에서|을|를)$', '', term)
    return stem if len(stem) >= 2 else term


def query_groups(query):
    terms = re.findall(r'[\w]+(?:-[\w]+)*', normalize(query), flags=re.UNICODE)
    groups, index = {}, 0
    phrases = [(value.split(), values) for values in SYNONYM_GROUPS
               for value in values if ' ' in value]
    while index < len(terms):
        term, count = terms[index], 1
        stem = _query_stem(term)
        # Recognize spaced phrases as one concept (PPT / 발표 자료), avoiding
        # duplicate relevance points from several names for the same thing.
        group = None
        for words, values in phrases:
            if index + len(words) <= len(terms) and all(
                    word in {actual, _query_stem(actual)}
                    for word, actual in zip(words, terms[index:index + len(words)])):
                group, count = values, len(words)
                term = ' '.join(terms[index:index + count])
                break
        index += count
        if group is None:
            if term in STOP_WORDS or stem in STOP_WORDS:
                continue
            group = next((values for values in SYNONYM_GROUPS
                          if term in values or stem in values), (stem,))
        variants = groups.setdefault(group, list(group))
        if term not in variants:
            variants.append(term)
    if len(groups) > 12:
        raise BadRequest('검색 핵심 단어는 12개 이내로 입력하세요.')
    # Punctuation is literal; a query such as .* must not match the catalog.
    return ([tuple(variants) for variants in groups.values()] or [(normalize(query),)]) if query else []


def group_importance(variants):
    return 1 if any(word in GENERIC_TERMS for word in variants) else 4


def relevance(row, query, groups, registrant_name=''):
    data = row['data']
    values = {key: [normalize(x) for x in data.get(key, [])]
              if isinstance(data.get(key), list) else [normalize(data.get(key, ''))]
              for key in QUERY_FIELDS}
    values['registrant'] = [normalize(registrant_name)]
    exact = bool(query and (normalize(data.get('name')) == normalize(query)
                           or str(row['_id']) == query.strip()))
    matched, weight, fields = 0, 0, set()
    for variants in groups:
        hits = [key for key, texts in values.items()
                if any(variant in text for variant in variants for text in texts)]
        if hits:
            matched += group_importance(variants)
            weight += max(FIELD_WEIGHTS[key] for key in hits)
            fields.update(hits)
    return exact, matched, weight, sorted(fields)


def _first(field):
    """Use the legacy created date only when the newer field is absent."""
    return {'$cond': [{'$eq': [{'$type': '$' + field}, 'missing']}, '$created', '$' + field]}


def _statistics(ids, now):
    """Bulk equivalent of mongo_activity.statistics, with parity regression tests.

    Aggregate on the DB instead of transferring every activity row. Download
    rows are deduplicated by (tool, user) using their earliest counted date,
    exactly as the shared web ranking does. Updates with a null first date do
    not count. Likes use their original date even after unlike/re-like.
    """
    result = {tid: dict(likes=0, downloads=0, views=0, recentLikes=0, recentDownloads=0,
                       rankScore=0, totalRankScore=0) for tid in ids}
    if not ids:
        return result
    cutoff = now - 7 * 86400
    rows = db().activity_state.aggregate([
        {'$match': {'tool': {'$in': ids}}},
        {'$facet': {
            'views': [
                {'$match': {'kind': 'view'}},
                {'$group': {'_id': '$tool', 'count': {'$sum': '$count'}}},
            ],
            'likes': [
                {'$match': {'kind': 'like', 'liked': True}},
                {'$set': {'first': _first('firstLikedAt')}},
                {'$group': {'_id': '$tool', 'count': {'$sum': 1}, 'recent': {'$sum': {
                    '$cond': [{'$and': [{'$gte': ['$first', cutoff]}, {'$lte': ['$first', now]}]}, 1, 0]}}}},
            ],
            'downloads': [
                {'$match': {'kind': 'download', 'count': {'$gt': 0}}},
                {'$set': {'first': _first('firstDownloadedAt')}},
                {'$match': {'first': {'$ne': None}}},
                {'$group': {'_id': {'tool': '$tool', 'user': '$user'}, 'first': {'$min': '$first'}}},
                {'$group': {'_id': '$_id.tool', 'count': {'$sum': 1}, 'recent': {'$sum': {
                    '$cond': [{'$and': [{'$gte': ['$first', cutoff]}, {'$lte': ['$first', now]}]}, 1, 0]}}}},
            ],
        }},
    ], maxTimeMS=5000)
    for group in rows:
        for row in group['views']:
            result[row['_id']]['views'] = row['count']
        for kind, recent in [('likes', 'recentLikes'), ('downloads', 'recentDownloads')]:
            for row in group[kind]:
                result[row['_id']][kind] = row['count']
                result[row['_id']][recent] = row['recent']
    for values in result.values():
        values['rankScore'] = values['recentLikes'] * 2 + values['recentDownloads']
        values['totalRankScore'] = values['likes'] * 2 + values['downloads']
    return result


def _department_signals(ids, now):
    code = g.user.get('dept_cd')
    meta = {'status': 'department_unknown', 'windowDays': DEPARTMENT_DAYS,
            'minimumDistinctUsers': MIN_DEPARTMENT_USERS}
    if not isinstance(code, str) or not code.strip() or not ids:
        return {}, meta
    # One bounded bulk lookup. Department names/prefixes and orgId are never
    # treated as proof of team membership. Exclude the requester and disabled
    # users, and use today's recorded department rather than a historical one.
    members = list(db().users.find(
        {'dept_cd': code, 'enabled': {'$ne': False}, '_id': {'$ne': g.user['id']}},
        {'_id': 1}).limit(DEPARTMENT_MEMBER_LIMIT + 1))
    if len(members) > DEPARTMENT_MEMBER_LIMIT:
        meta['status'] = 'department_too_large'
        return {}, meta
    if len(members) < MIN_DEPARTMENT_USERS:
        meta['status'] = 'insufficient_sample'
        return {}, meta
    cutoff = now - DEPARTMENT_DAYS * 86400
    rows = db().activity_state.aggregate([
        {'$match': {'tool': {'$in': ids}, 'user': {'$in': [r['_id'] for r in members]}}},
        {'$set': {'first': {'$cond': [{'$eq': ['$kind', 'like']},
                                   _first('firstLikedAt'), _first('firstDownloadedAt')]}}},
        {'$match': {'$or': [{'kind': 'like', 'liked': True},
                           {'kind': 'download', 'count': {'$gt': 0}}],
                    'first': {'$ne': None}}},
        {'$group': {'_id': {'tool': '$tool', 'user': '$user', 'kind': '$kind'},
                    'first': {'$min': '$first'}}},
        {'$match': {'first': {'$gte': cutoff, '$lte': now}}},
        {'$group': {'_id': {'tool': '$_id.tool', 'user': '$_id.user'},
                    'score': {'$sum': {'$cond': [{'$eq': ['$_id.kind', 'like']}, 2, 1]}}}},
        {'$group': {'_id': '$_id.tool', 'distinctUsers': {'$sum': 1}, 'score': {'$sum': '$score'}}},
        {'$match': {'distinctUsers': {'$gte': MIN_DEPARTMENT_USERS}}},
    ], maxTimeMS=5000)
    signals = {row['_id']: {'distinctUsers': row['distinctUsers'], 'score': row['score']} for row in rows}
    meta['status'] = 'applied' if signals else 'insufficient_sample'
    return signals, meta


def _candidates(query, projection, q, groups, registrant_matches):
    if not q:
        return list(db().tools.find(query, projection).sort('_id', 1).limit(CANDIDATE_LIMIT))
    # Select the best lexical matches before applying the candidate cap. An
    # arbitrary first/last N slice would hide an exact name match in a large
    # catalog. Mongo fields were validated on registration; no user pipeline
    # operators or unescaped regex are accepted here.
    text_fields = {key: ('$data.' + key if key != 'workTags' else {
        '$reduce': {'input': {'$ifNull': ['$data.workTags', []]}, 'initialValue': '',
                    'in': {'$concat': ['$$value', ' ', '$$this']}}}) for key in QUERY_FIELDS}
    group_hits, group_weights = [], []
    for variants in groups:
        pattern = '|'.join(re.escape(word) for word in variants)
        hits = {key: {'$regexMatch': {'input': {'$ifNull': [value, '']}, 'regex': pattern, 'options': 'i'}}
                for key, value in text_fields.items()}
        # Actual registering account names are resolved once, separate from the
        # editable contact label in data.owner. Only owner IDs enter the pipeline.
        matching_ids = [uid for uid, name in registrant_matches.items()
                        if any(variant in normalize(name) for variant in variants)]
        hits['registrant'] = {'$in': ['$owner', {'$literal': matching_ids}]}
        group_hits.append({'$cond': [{'$or': list(hits.values())}, group_importance(variants), 0]})
        group_weights.append({'$max': [{'$cond': [hit, FIELD_WEIGHTS[key], 0]} for key, hit in hits.items()]})
    return list(db().tools.aggregate([
        {'$match': query}, {'$project': projection},
        {'$set': {
            '_searchExact': {'$or': [
                {'$eq': [{'$toLower': '$data.name'}, {'$literal': normalize(q)}]},
                {'$eq': [{'$toString': '$_id'}, {'$literal': q}]}]},
            '_searchMatches': {'$sum': group_hits}, '_searchWeight': {'$sum': group_weights},
        }},
        {'$sort': {'_searchExact': -1, '_searchMatches': -1, '_searchWeight': -1, '_id': 1}},
        {'$limit': CANDIDATE_LIMIT},
    ], maxTimeMS=5000))


def search_catalog():
    from .mongo_api import TYPE_ALIASES
    from .storage import all_admin_ids

    q = request.args.get('q', '').strip()
    if len(q) > 200:
        raise BadRequest('검색어는 200자 이내로 입력하세요.')
    try:
        limit, offset = int(request.args.get('limit', '20')), int(request.args.get('offset', '0'))
    except ValueError:
        raise BadRequest('limit와 offset은 정수입니다.') from None
    if not 1 <= limit <= 100 or not 0 <= offset <= 100000:
        raise BadRequest('limit는 1~100, offset은 0~100000입니다.')
    mode = SORT_ALIASES.get(request.args.get('sort', 'recommended'), request.args.get('sort', 'recommended'))
    if mode not in {'recommended', 'realtime', 'cumulative', 'newest'}:
        raise BadRequest('정렬은 recommended, realtime, cumulative, newest 중 선택하세요.')
    query = {'deleted': {'$ne': True}, 'purge': {'$exists': False}}
    groups = query_groups(q)
    registrant_matches = {}
    if q:
        patterns = list(dict.fromkeys(re.escape(word) for group in groups for word in group))
        pattern = '|'.join(patterns)
        # A single account-name lookup also lets registrant-only matches enter
        # the lexical candidate cap. Never accept a caller's asserted owner.
        registrant_matches = {user['_id']: user['name'] for user in db().users.find(
            {'name': {'$regex': pattern, '$options': 'i'}}, {'name': 1}, max_time_ms=5000)}
        alternatives = [{'data.' + field: {'$regex': pattern, '$options': 'i'}} for field in QUERY_FIELDS]
        if registrant_matches:
            alternatives.append({'owner': {'$in': list(registrant_matches)}})
        if q.isascii() and q.isdigit():
            alternatives.append({'_id': int(q)})
        query['$or'] = alternatives
    kind = request.args.get('type', '')
    if kind:
        kind = TYPE_ALIASES.get(kind, kind)
        if kind not in {'MCP/Tool', 'Skill', '플러그인/하네스'}:
            raise BadRequest('도구 유형을 확인하세요.')
        query['data.type'] = {'$in': [kind] + [k for k, v in TYPE_ALIASES.items() if v == kind]}
    if request.args.get('orgId'):
        query['data.orgId'] = request.args['orgId']
    platform = request.args.get('platform', '')
    if platform:
        if platform not in {'Claude', 'ChatGPT', '기타'}:
            raise BadRequest('프로그램을 확인하세요.')
        query['data.platform'] = platform

    projection = {('data.' + k): 1 for k in (*QUERY_FIELDS, 'type', 'platform', 'org', 'orgId', 'categoryId', 'approval', 'owner')}
    projection.update(owner=1, created=1, departmentGrants=1)
    total = db().tools.count_documents(query, maxTimeMS=5000)
    rows = _candidates(query, projection, q, groups, registrant_matches)
    # Resolve actual registering accounts in one query, not a user lookup per
    # result. data.owner is an editable contact label, not the registrar.
    registrants = {user['_id']: user.get('name', '') for user in db().users.find(
        {'_id': {'$in': list({row.get('owner') for row in rows} - {None})}}, {'name': 1})}
    ids = [r['_id'] for r in rows]
    now = time.time()
    stats = _statistics(ids, now)
    signals, recommendation = _department_signals(ids, now) if mode == 'recommended' else ({}, {
        'status': 'not_used_for_ranking', 'windowDays': DEPARTMENT_DAYS,
        'minimumDistinctUsers': MIN_DEPARTMENT_USERS})
    recommendation['explanation'] = {
        'applied': '최근 90일 같은 부서의 서로 다른 구성원 5명 이상이 활용한 경우에만 추천에 반영합니다.',
        'insufficient_sample': '같은 부서 활용 표본이 부족한 항목은 검색 관련도와 전사 집계로 추천합니다.',
        'department_unknown': '확인된 부서 코드가 없어 조직 선호를 사용하지 않습니다.',
        'department_too_large': '부서 구성원 범위가 커 조직 선호를 생략했습니다. 검색 관련도와 전사 집계를 사용합니다.',
        'not_used_for_ranking': '이 정렬은 조직 선호를 반영하지 않습니다.',
    }[recommendation['status']]
    taxonomy_ids = {r['data'].get(key) for r in rows for key in ('orgId', 'categoryId')}
    taxonomy = {r['_id']: r['name'] for r in db().taxonomy.find({'_id': {'$in': list(taxonomy_ids - {None})}}, {'name': 1})}
    granted = {r['tool'] for r in db().access.find(
        {'user': g.user['id'], 'tool': {'$in': ids}, 'granted': True}, {'tool': 1})}
    is_admin = g.user['id'] in all_admin_ids()
    # Exact stored SSO fields are needed only for department-granted rows;
    # public/personal checks reuse authentication without a second user query.
    profile = (db().users.find_one({'_id': g.user['id']})
               if any(row.get('departmentGrants') for row in rows) else g.user)
    liked = {r['tool'] for r in db().activity_state.find(
        {'user': g.user['id'], 'tool': {'$in': ids}, 'kind': 'like', 'liked': True}, {'tool': 1})}
    prepared = []
    labels = {'name': '이름', 'workTags': '관련 업무 태그', 'desc': '설명', 'category': '업무 분류',
              'owner': '담당자 이름', 'registrant': '등록자 이름'}
    for row in rows:
        tid, data = row['_id'], row['data']
        exact, matches, weight, fields = relevance(row, q, groups, registrants.get(row.get('owner'), ''))
        signal = signals.get(tid)
        metric = stats[tid]
        recent = mode == 'realtime'
        rank_key = (-(metric['rankScore'] if recent else metric['totalRankScore']),
                    -(metric['recentDownloads'] if recent else metric['downloads']),
                    -(metric['recentLikes'] if recent else metric['likes']),
                    -row.get('created', 0), tid)
        if mode == 'recommended':
            # Organization preference only breaks equal textual relevance; it
            # cannot promote an unrelated/popular tool over a stronger match.
            key = (-int(exact), -matches, -weight, -min(15, signal['score'] if signal else 0), *rank_key)
        elif mode == 'newest':
            key = (-row.get('created', 0), tid)
        else:
            key = rank_key
        reasons = []
        if exact:
            reasons.append('이름 또는 항목 번호가 정확히 일치합니다.')
        elif fields:
            reasons.append('검색어 또는 비슷한 업무 표현이 ' + '·'.join(labels[f] for f in fields) + '에 포함됩니다.')
        if signal:
            reasons.append(f'최근 {DEPARTMENT_DAYS}일 같은 부서 구성원 {signal["distinctUsers"]}명이 좋아요 또는 최초 다운로드로 활용했습니다.')
        if mode in {'realtime', 'cumulative'}:
            reasons.append(('최근 7일' if recent else '전체 기간') + ' 좋아요 × 2 + 고유 다운로드 × 1 기준입니다.')
        if not reasons:
            reasons.append('최근 등록 순서입니다.' if mode == 'newest' else '검색 관련도가 같은 경우 전사 누적 집계를 참고합니다.')
        access = can_read(row, g.user['id'], profile, administrator=is_admin,
                          personal_grant=tid in granted)
        item = {k: data.get(k, [] if k == 'workTags' else '') for k in ('name', 'desc', 'platform', 'org', 'orgId', 'category', 'workTags')}
        item.update(id=tid, type=TYPE_ALIASES.get(data.get('type'), data.get('type')),
                    owner=data.get('owner', ''), registrantId=row.get('owner'),
                    registrantName=registrants.get(row.get('owner'), '') or '등록자 정보 없음',
                    org=taxonomy.get(data.get('orgId'), data.get('org', '')),
                    category=taxonomy.get(data.get('categoryId'), data.get('category', '')),
                    access='approved' if access else 'permission_required',
                    statistics=metric, reasons=reasons, liked=tid in liked,
                    departmentPreference=({'status': 'applied', 'distinctUsers': signal['distinctUsers']}
                                          if signal else {'status': recommendation['status'] if recommendation['status'] != 'applied' else 'insufficient_sample'}))
        prepared.append((key, item))
    prepared.sort(key=lambda pair: pair[0])
    complete = total <= CANDIDATE_LIMIT
    available = len(prepared)
    return jsonify(items=[item for _, item in prepared[offset:offset + limit]], total=total,
                   nextOffset=offset + limit if offset + limit < available else None,
                   sort=mode, dataAsOf=now, recommendation=recommendation,
                   complete=complete, evaluatedCount=available, candidateLimit=CANDIDATE_LIMIT,
                   warning=None if complete else '검색 결과가 많아 일부 후보만 평가했습니다. 조직·유형·검색어로 범위를 좁혀 주세요. 전체 순위가 아닙니다.')
