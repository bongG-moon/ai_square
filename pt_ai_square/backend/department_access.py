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


def department_id(code, name):
    # A stable code survives a display-name change. Name-only rules are exact.
    value = 'code:' + code if code else 'name:' + name
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:32]


def departments():
    grouped = {}
    for row in db().users.find({'enabled': True}, {'dept': 1, 'dept_cd': 1}):
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
    if rule.get('code'):
        return code == rule['code']
    # A code-less fallback never spans several different coded departments
    # simply because their displayed names happen to coincide.
    return not code and bool(name) and name == rule.get('name')


def department_rules(tool):
    current = {row['id']: row for row in departments()}
    return [dict(id=row['id'], code=row['code'],
                 name=current.get(row['id'], row)['name'],
                 memberCount=current.get(row['id'], {}).get('memberCount', 0))
            for row in tool.get('departmentGrants', [])]


def selected_departments(raw):
    if not isinstance(raw, list) or not raw or len(raw) > MAX_DEPARTMENTS:
        raise BadRequest('부서는 한 번에 1개부터 50개까지 선택해 주세요.')
    known = {row['id']: row for row in departments()}
    selected = {}
    for item in raw:
        if not isinstance(item, dict):
            raise BadRequest('부서 검색 결과에서 항목을 선택해 주세요.')
        code, name = item.get('code', ''), item.get('name', '')
        if not isinstance(code, str) or not isinstance(name, str) or len(code) > 100 or len(name) > 200:
            raise BadRequest('부서 정보를 확인해 주세요.')
        key = department_id(code.strip(), name.strip())
        if key not in known:
            raise BadRequest('확인할 수 없는 부서입니다. 부서를 다시 검색해 주세요.')
        selected[key] = {field: known[key][field] for field in ('id', 'code', 'name')}
    return list(selected.values())
