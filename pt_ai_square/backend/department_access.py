"""Department grants use signed-in employee profiles, never catalog categories."""
import hashlib
import re
from collections import Counter

from werkzeug.exceptions import BadRequest

from .storage import db

MAX_USERS = 100
MAX_DEPARTMENTS = 50


def employee(row):
    return {'id': row['_id'], 'name': row.get('name', row['_id']),
            'dept': str(row.get('dept') or ''), 'deptCode': str(row.get('dept_cd') or '')}


def employee_ids(value):
    if isinstance(value, str):
        if len(value) > 12000:
            raise BadRequest('사번은 한 번에 최대 100명까지 추가할 수 있습니다.')
        value = [item for item in re.split(r'[\s,，;；]+', value.strip()) if item]
    if not isinstance(value, list) or not value:
        raise BadRequest('사번은 한 번에 1명부터 100명까지 입력해 주세요.')
    if any(not isinstance(item, str) or not item.strip() or len(item.strip()) > 100 for item in value):
        raise BadRequest('사번 형식을 확인해 주세요.')
    unique = list(dict.fromkeys(item.strip() for item in value))
    if len(unique) > MAX_USERS:
        raise BadRequest('사번은 한 번에 1명부터 100명까지 입력해 주세요.')
    return unique


def resolve_employees(ids):
    found = {row['_id']: employee(row) for row in db().users.find(
        {'_id': {'$in': ids}, 'enabled': True}, {'name': 1, 'dept': 1, 'dept_cd': 1})}
    return [found[uid] for uid in ids if uid in found], [uid for uid in ids if uid not in found]


def department_id(code, name, match=None):
    # A stable code survives a display-name change. Name-only rules are exact.
    # Explicit exact-name grants must not widen existing code-less fallbacks.
    value = 'exact-name:' + name if match == 'name' else 'code:' + code if code else 'name:' + name
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:32]


def department_values(value, input_mode):
    """Only comma separates departments; interior whitespace is significant."""
    if not isinstance(input_mode, str) or input_mode not in {'search', 'code', 'name'}:
        raise BadRequest('부서 검색·코드·이름 입력 중 하나를 선택해 주세요.')
    if not isinstance(value, str) or len(value) > 12000:
        raise BadRequest('부서 입력은 12,000자 이내로 작성해 주세요.')
    values = list(dict.fromkeys(item.strip() for item in value.split(',') if item.strip()))
    if not values or len(values) > MAX_DEPARTMENTS:
        raise BadRequest('부서는 한 번에 1개부터 50개까지 입력해 주세요.')
    limit = 100 if input_mode == 'code' else 200
    if any(len(item) > limit for item in values):
        raise BadRequest(f'각 부서 {"코드" if input_mode == "code" else "이름 또는 검색어"}는 {limit}자 이내로 입력해 주세요.')
    return values


def profiles():
    return list(db().users.find({'enabled': True}, {'dept': 1, 'dept_cd': 1}))


def departments(active_profiles=None):
    grouped = {}
    for row in profiles() if active_profiles is None else active_profiles:
        code, name = str(row.get('dept_cd') or '').strip(), str(row.get('dept') or '').strip()
        if not (code or name):
            continue
        key = department_id(code, name)
        group = grouped.setdefault(key, {'id': key, 'code': code, 'names': Counter(), 'memberCount': 0})
        group['names'][name] += 1
        group['memberCount'] += 1
    result = []
    for group in grouped.values():
        names = sorted(group.pop('names').items(), key=lambda item: (-item[1], item[0]))
        result.append(dict(group, name=names[0][0] or group['code']))
    return sorted(result, key=lambda row: (row['name'], row['code']))


def group_matches(rule, profile):
    code = str(profile.get('dept_cd') or '').strip()
    name = str(profile.get('dept') or '').strip()
    if rule.get('match') == 'name':
        return bool(name) and name == rule.get('name')
    if rule.get('code'):
        return code == rule['code']
    # A code-less fallback never spans several different coded departments
    # simply because their displayed names happen to coincide.
    return not code and bool(name) and name == rule.get('name')


def department_rules(tool):
    active = profiles()
    current = {row['id']: row for row in departments(active)}
    result = []
    for row in tool.get('departmentGrants', []):
        saved = dict(id=row['id'], code=row['code'],
                     name=current.get(row['id'], row)['name'],
                     memberCount=sum(group_matches(row, profile) for profile in active))
        if 'match' in row: saved['match'] = row['match']
        result.append(saved)
    return result


def preview_departments(value, input_mode='search'):
    values = department_values(value, input_mode)
    active = profiles()
    known = departments(active)
    if input_mode == 'search':
        # Search is forgiving; explicit code grants still use exact spelling.
        found = [row for row in known if any(term.casefold() in row['name'].casefold()
                 or term.casefold() in row['code'].casefold() for term in values)]
        return found[:50], len(found)
    if input_mode == 'code':
        codes = {row['code']: row for row in known if row['code']}
        result = [dict(id=department_id(value, ''), code=value,
                       name=codes.get(value, {}).get('name', value), match='code',
                       memberCount=codes.get(value, {}).get('memberCount', 0)) for value in values]
    else:
        result = [dict(id=department_id('', value, 'name'), code='', name=value, match='name',
                       memberCount=sum(group_matches({'match': 'name', 'name': value}, profile)
                                       for profile in active)) for value in values]
    return result, len(result)


def selected_departments(raw):
    if not isinstance(raw, list) or not raw or len(raw) > MAX_DEPARTMENTS:
        raise BadRequest('부서는 한 번에 1개부터 50개까지 선택해 주세요.')
    known = {row['id']: row for row in departments()}
    selected = {}
    for item in raw:
        if not isinstance(item, dict):
            raise BadRequest('부서 검색 결과에서 항목을 선택해 주세요.')
        code, name = item.get('code', ''), item.get('name', '')
        if not isinstance(code, str) or not isinstance(name, str):
            raise BadRequest('부서 정보를 확인해 주세요.')
        code, name = code.strip(), name.strip()
        if len(code) > 100 or len(name) > 200:
            raise BadRequest('부서 정보를 확인해 주세요.')
        match = item.get('match')
        if 'match' in item and (not isinstance(match, str) or match not in {'code', 'name'}):
            raise BadRequest('부서 권한의 일치 기준을 확인해 주세요.')
        if match == 'name':
            if code or not name or ',' in name:
                raise BadRequest('이름 일치 권한은 부서명 한 개와 빈 부서 코드로 입력해 주세요.')
            key = department_id('', name, 'name')
            selected[key] = dict(id=key, code='', name=name, match='name')
            continue
        if match == 'code':
            if not code or ',' in code:
                raise BadRequest('코드 일치 권한은 부서 코드 한 개를 입력해 주세요.')
            key = department_id(code, '')
            selected[key] = dict(id=key, code=code, name=known.get(key, {}).get('name', code), match='code')
            continue
        key = department_id(code, name)
        if key not in known:
            raise BadRequest('확인할 수 없는 부서입니다. 부서를 다시 검색해 주세요.')
        selected[key] = {field: known[key][field] for field in ('id', 'code', 'name')}
    return list(selected.values())
