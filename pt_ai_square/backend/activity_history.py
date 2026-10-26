"""Read-only, bounded administrator activity browsing and CSV exports."""
import csv
from datetime import date, datetime, time as day_time, timedelta, timezone
import io
import math
import re
import time

from flask import Response, current_app
from itsdangerous import BadData, URLSafeSerializer
from werkzeug.exceptions import BadRequest

from .storage import db


KST = timezone(timedelta(hours=9))
KINDS = {'all', 'like', 'unlike', 'download'}
PAGE_SIZES = {25, 50, 100}
EXPORT_LIMIT = 50_000
QUERY_TIMEOUT_MS = 5_000
SORT = [('created', -1), ('_id', -1)]
FIELDS = {'_id': 1, 'created': 1, 'kind': 1, 'tool': 1, 'user': 1,
          'version': 1, 'counted': 1, 'imported': 1, 'tokenId': 1}
LABELS = {'like': '좋아요', 'unlike': '좋아요 취소', 'download': '다운로드'}


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise BadRequest('시작일과 종료일을 YYYY-MM-DD 형식으로 입력해 주세요.')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise BadRequest('실제 달력에 있는 날짜를 선택해 주세요.') from None


def filters(args):
    start, end = args.get('start'), args.get('end')
    if start is None and end is None:
        last = datetime.now(KST).date()
        first = last - timedelta(days=29)
    elif start is None or end is None:
        raise BadRequest('조회할 시작일과 종료일을 함께 선택해 주세요.')
    else:
        first, last = _date(start), _date(end)
    if first > last:
        raise BadRequest('시작일은 종료일보다 늦을 수 없습니다.')
    # The exclusive upper bound must remain a representable calendar date.
    if last == date.max:
        raise BadRequest('종료일은 9999-12-30 이전으로 선택해 주세요.')
    kind = args.get('kind', 'all')
    if kind not in KINDS:
        raise BadRequest('올바른 활동 유형을 선택해 주세요.')
    return {'start': first.isoformat(), 'end': last.isoformat(), 'kind': kind}


def _query(selected, as_of):
    first = datetime.combine(_date(selected['start']), day_time.min, KST)
    after = datetime.combine(_date(selected['end']) + timedelta(days=1), day_time.min, KST)
    query = {'created': {'$gte': first.timestamp(), '$lt': after.timestamp(), '$lte': as_of}}
    if selected['kind'] != 'all':
        query['kind'] = selected['kind']
    return query


def _signer():
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt='activity-history-v1')


def _page_size(args):
    raw = args.get('limit', '25')
    if raw not in {'25', '50', '100'}:
        raise BadRequest('한 페이지에 25, 50 또는 100개씩 조회할 수 있습니다.')
    return int(raw)


def _cursor(args, selected, size):
    value = args.get('before')
    if not value:
        return None, time.time()
    if len(value) > 4096:
        raise BadRequest('페이지 정보가 올바르지 않습니다. 첫 페이지부터 다시 조회해 주세요.')
    try:
        data = _signer().loads(value)
        if (not isinstance(data, dict) or data.get('filters') != selected
                or data.get('limit') != size or not isinstance(data.get('id'), str)
                or not data['id'] or len(data['id']) > 256):
            raise ValueError
        for key in ('created', 'asOf'):
            number = data.get(key)
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                raise ValueError
        if data['created'] > data['asOf']:
            raise ValueError
    except (BadData, ValueError, TypeError):
        raise BadRequest('조회 조건이나 페이지 정보가 변경되었습니다. 첫 페이지부터 다시 조회해 주세요.') from None
    return data, data['asOf']


def _rows(query, limit):
    return list(db().activity.find(query, FIELDS).sort(SORT).limit(limit).max_time_ms(QUERY_TIMEOUT_MS))


def _channel(row):
    # Earlier like events did not record their client. Do not invent attribution.
    if row.get('imported') or row.get('kind') != 'download':
        return 'unknown'
    return 'api' if row.get('tokenId') else 'web'


def _public(rows):
    """Resolve names in two queries per batch, with no per-event DB reads."""
    if not rows:
        return []
    tools = {row['_id']: row.get('data', {}).get('name', '삭제된 기능') for row in
             db().tools.find({'_id': {'$in': list({r['tool'] for r in rows})}},
                             {'data.name': 1}).max_time_ms(QUERY_TIMEOUT_MS)}
    users = {row['_id']: row.get('name', str(row['_id'])) for row in
             db().users.find({'_id': {'$in': list({r['user'] for r in rows})}},
                             {'name': 1}).max_time_ms(QUERY_TIMEOUT_MS)}
    return [dict(id=str(row['_id']), created=row['created'], kind=row['kind'],
                 tool=row['tool'], toolName=tools.get(row['tool'], '삭제된 기능'),
                 user=row['user'], userName=users.get(row['user'], str(row['user'])),
                 version=row.get('version'), counted=bool(row.get('counted')),
                 imported=bool(row.get('imported')), channel=_channel(row)) for row in rows]


def page(args):
    selected, size = filters(args), _page_size(args)
    cursor, as_of = _cursor(args, selected, size)
    query = _query(selected, as_of)
    total = db().activity.count_documents(query, maxTimeMS=QUERY_TIMEOUT_MS)
    if cursor:
        query = {'$and': [query, {'$or': [
            {'created': {'$lt': cursor['created']}},
            {'created': cursor['created'], '_id': {'$lt': cursor['id']}}
        ]}]}
    rows = _rows(query, size + 1)
    more, rows = len(rows) > size, rows[:size]
    next_cursor = None
    if more:
        last = rows[-1]
        next_cursor = _signer().dumps(dict(filters=selected, limit=size, asOf=as_of,
                                         created=last['created'], id=str(last['_id'])))
    return dict(events=_public(rows), nextCursor=next_cursor, total=total,
                pageSize=size, filters=selected, timezone='Asia/Seoul', backend='mongodb')


def _csv_cell(value):
    text = '' if value is None else str(value)
    # CSV quoting protects structure; this protects spreadsheet formula execution.
    if text.startswith(('\t', '\r', '\n')) or text.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + text
    return text


def _ranking(row):
    if row['imported']:
        return '기존 집계 이전'
    if row['kind'] == 'download':
        return '최초 다운로드 반영' if row['counted'] else '반복·업데이트 제외'
    return {'like': '좋아요 추가', 'unlike': '좋아요 취소'}.get(row['kind'], '—')


def export_csv(args):
    selected = filters(args)
    # Export is the complete selected range, independent of the current page.
    rows = _rows(_query(selected, time.time()), EXPORT_LIMIT + 1)
    if len(rows) > EXPORT_LIMIT:
        raise BadRequest('CSV는 한 번에 최대 50,000건까지 받을 수 있습니다. 기간이나 활동 유형을 좁혀 다시 다운로드해 주세요.')
    output = io.StringIO(newline='')
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(['일시 (한국 시간)', '활동', '도구', '도구 ID', '버전', '사용자', '사번', '이용 경로', '집계 구분'])
    # Finish reads and serialization before sending a success header. A DB error
    # must remain an error response, never a successful but incomplete CSV file.
    for offset in range(0, len(rows), 1000):
        for row in _public(rows[offset:offset + 1000]):
            values = [datetime.fromtimestamp(row['created'], KST).strftime('%Y-%m-%d %H:%M:%S'),
                      LABELS.get(row['kind'], row['kind']), row['toolName'], row['tool'],
                      f"v{row['version']}" if row['version'] else '', row['userName'], row['user'],
                      {'web': '웹', 'api': 'API 연결'}.get(row['channel'], '확인 불가'), _ranking(row)]
            writer.writerow([_csv_cell(value) for value in values])
    filename = 'activity-{}-{}.csv'.format(selected['start'].replace('-', ''), selected['end'].replace('-', ''))
    response = Response(output.getvalue().encode('utf-8-sig'), content_type='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.headers['Cache-Control'] = 'no-store'
    return response
