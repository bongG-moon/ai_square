"""Date-filtered, bounded activity reporting without changing stored history."""
import csv
from datetime import datetime, timedelta
import io
from types import SimpleNamespace

import pytest
from pymongo.collection import Collection
from pymongo.errors import OperationFailure

from pt_ai_square.backend import activity_history as reports, mongo_activity
from pt_ai_square.backend.storage import db
from .conftest import ready


PERIOD = {'start': '2024-02-01', 'end': '2024-02-29', 'kind': 'all'}


def stamp(value):
    return datetime.fromisoformat(value).replace(tzinfo=reports.KST).timestamp()


def event(ident, created=None, **overrides):
    row = dict(_id=ident, tool=1, user='owner', kind='download',
               created=created if created is not None else stamp('2024-02-15T12:30:00'),
               version=1, counted=True)
    row.update(overrides)
    return row


def insert(app, rows):
    with app.app_context():
        db().activity.insert_many(rows)
        db().tools.update_one({'_id': 1}, {'$set': {'data.name': '장비 점검'}}, upsert=True)


def client(app):
    return ready(app, 'admin')[0]


def test_korean_calendar_range_includes_whole_end_day_and_leap_day(app):
    insert(app, [event('before', stamp('2024-01-31T23:59:59.999999')),
                 event('start', stamp('2024-02-01T00:00:00')),
                 event('end', stamp('2024-02-29T23:59:59.999999')),
                 event('after', stamp('2024-03-01T00:00:00'))])
    response = client(app).get('/api/activity', query_string=PERIOD)
    assert response.status_code == 200
    body = response.json
    assert [row['id'] for row in body['events']] == ['end', 'start']
    assert body['total'] == 2 and body['nextCursor'] is None
    assert body['filters'] == PERIOD and body['timezone'] == 'Asia/Seoul'
    assert response.headers['Cache-Control'] == 'no-store'


def test_default_range_is_last_thirty_korean_calendar_days(app):
    today = datetime.now(reports.KST).date()
    response = client(app).get('/api/activity')
    assert response.status_code == 200
    assert response.json['filters'] == dict(start=(today-timedelta(days=29)).isoformat(), end=today.isoformat(), kind='all')
    assert response.json['pageSize'] == 25


@pytest.mark.parametrize('params', [
    {'start': '2024-02-01'}, {'end': '2024-02-29'},
    {'start': '2024-02-30', 'end': '2024-03-01'},
    {'start': '2024-2-1', 'end': '2024-03-01'},
    {'start': '', 'end': ''}, {'start': '2024-03-01', 'end': '2024-02-29'},
    {'start': '9999-12-30', 'end': '9999-12-31'}, {'kind': 'view'},
    {'limit': '0'}, {'limit': '1000'}, {'limit': '-1'}, {'limit': '25.0'},
    {'before': 'not-a-signed-cursor'}, {'before': 'a'*4097},
])
def test_invalid_filters_and_cursors_are_rejected(app, params):
    assert client(app).get('/api/activity', query_string=params).status_code == 400


def test_action_filter_and_safe_projection_and_channel_attribution(app):
    insert(app, [event('api', tokenId='private-key-id', outbox=['private']),
                 event('web'), event('like', kind='like', tokenId='private-key-id'),
                 event('unlike', kind='unlike'), event('old', imported=True)])
    c = client(app)
    rows = {r['id']: r for r in c.get('/api/activity', query_string=PERIOD).json['events']}
    assert rows['api']['channel'] == 'api' and rows['web']['channel'] == 'web'
    assert all(rows[ident]['channel'] == 'unknown' for ident in ['like', 'unlike', 'old'])
    assert rows['api']['toolName'] == '장비 점검' and rows['api']['userName'] == 'owner'
    assert all('tokenId' not in row and 'outbox' not in row and '_id' not in row for row in rows.values())
    response = c.get('/api/activity', query_string={**PERIOD, 'kind': 'like'})
    assert response.json['total'] == 1
    assert [r['id'] for r in response.json['events']] == ['like']


def test_signed_cursor_keeps_ties_and_snapshot_after_anchor_deleted(app, monkeypatch):
    moment = stamp('2024-02-20T12:00:00')
    monkeypatch.setattr(reports, 'time', SimpleNamespace(time=lambda: moment))
    insert(app, [event(f'tie{n:03}', moment-1) for n in range(60)])
    c = client(app)
    first = c.get('/api/activity', query_string=PERIOD).json
    assert first['total'] == 60 and len(first['events']) == 25
    anchor = first['events'][-1]['id']
    with app.app_context():
        db().activity.delete_one({'_id': anchor})
        db().activity.insert_one(event('new-arrival', moment+1))
    monkeypatch.setattr(reports, 'time', SimpleNamespace(time=lambda: moment+2))
    second = c.get('/api/activity', query_string={**PERIOD, 'before': first['nextCursor']}).json
    third = c.get('/api/activity', query_string={**PERIOD, 'before': second['nextCursor']}).json
    ids = [r['id'] for page in [first, second, third] for r in page['events']]
    assert len(ids) == len(set(ids)) == 60
    assert ids == [f'tie{n:03}' for n in reversed(range(60))]
    assert third['nextCursor'] is None and 'new-arrival' not in ids
    latest = c.get('/api/activity', query_string=PERIOD).json
    assert latest['events'][0]['id'] == 'new-arrival'


def test_cursor_rejects_changed_filters_and_page_size(app):
    insert(app, [event(f'e{n:03}') for n in range(30)])
    c = client(app)
    cursor = c.get('/api/activity', query_string=PERIOD).json['nextCursor']
    for change in [{'kind': 'download'}, {'limit': '50'}, {'start': '2024-02-02'}]:
        response = c.get('/api/activity', query_string={**PERIOD, 'before': cursor, **change})
        assert response.status_code == 400


@pytest.mark.parametrize('size', [25, 50, 100])
def test_supported_page_sizes_replace_unbounded_growth(app, size):
    insert(app, [event(f'e{n:03}') for n in range(105)])
    response = client(app).get('/api/activity', query_string={**PERIOD, 'limit': str(size)})
    assert len(response.json['events']) == size
    assert response.json['total'] == 105 and response.json['nextCursor']


def test_list_and_csv_require_admin_web_session_even_for_admin_key(app):
    c, headers = ready(app, 'admin')
    token = c.post('/api/local-tokens', headers=headers, json={}).json['token']
    member, _ = ready(app, 'member')
    for path in ['/api/activity', '/api/activity/export']:
        assert member.get(path, query_string=PERIOD).status_code == 403
        assert app.test_client().get(path, query_string=PERIOD).status_code in {302, 401}
        assert c.get(path, query_string=PERIOD, headers={'Authorization': 'Bearer '+token}).status_code == 403


def test_csv_exports_entire_filter_not_just_current_page_and_uses_ascii_filename(app):
    insert(app, [event(f'e{n:03}') for n in range(31)] + [event('like', kind='like')])
    c = client(app)
    page = c.get('/api/activity', query_string={**PERIOD, 'kind': 'download'}).json
    assert len(page['events']) == 25
    response = c.get('/api/activity/export', query_string={**PERIOD, 'kind': 'download', 'before': page['nextCursor'], 'limit': '25'})
    assert response.status_code == 200 and response.data.startswith(b'\xef\xbb\xbf')
    assert response.mimetype == 'text/csv' and response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Content-Disposition'] == 'attachment; filename="activity-20240201-20240229.csv"'
    table = list(csv.reader(io.StringIO(response.data.decode('utf-8-sig'))))
    assert len(table) == 32 and all(row[1] == '다운로드' for row in table[1:])
    assert table[1][0] == '2024-02-15 12:30:00'


@pytest.mark.parametrize('name', ['  =SUM(1,2)\n"한글 도구"', '\t+SUM(1,2)', '\n한글 도구'])
def test_csv_handles_korean_quotes_newlines_and_spreadsheet_formula_text(app, name):
    insert(app, [event('formula', tokenId='private-key-id')])
    with app.app_context():
        db().tools.update_one({'_id': 1}, {'$set': {'data.name': name}})
        db().users.update_one({'_id': 'owner'}, {'$set': {'name': '@수식 사용자'}})
    response = client(app).get('/api/activity/export', query_string=PERIOD)
    table = list(csv.reader(io.StringIO(response.data.decode('utf-8-sig'))))
    assert len(table) == 2 and len(table[1]) == len(table[0]) == 9
    assert table[1][2] == "'" + name and table[1][5] == "'@수식 사용자"
    assert table[1][7] == 'API 연결'
    assert 'private-key-id' not in response.data.decode('utf-8-sig')


def test_empty_export_contains_headers_and_no_phantom_record(app):
    response = client(app).get('/api/activity/export', query_string=PERIOD)
    assert response.status_code == 200
    assert len(list(csv.reader(io.StringIO(response.data.decode('utf-8-sig'))))) == 1


def test_export_cap_rejects_instead_of_silently_truncating(app, monkeypatch):
    insert(app, [event(f'e{n}') for n in range(3)])
    monkeypatch.setattr(reports, 'EXPORT_LIMIT', 2)
    response = client(app).get('/api/activity/export', query_string=PERIOD)
    assert response.status_code == 400 and response.is_json
    assert '기간' in response.json['error'] and 'Content-Disposition' not in response.headers


@pytest.mark.parametrize('failed_batch', [1, 2])
def test_enrichment_failure_returns_json_error_before_csv_success(app, monkeypatch, failed_batch):
    insert(app, [event(f'e{n:04}') for n in range(1 if failed_batch == 1 else 1001)])
    original, calls = reports._public, []
    def fail(rows):
        calls.append(len(rows))
        if len(calls) == failed_batch:
            raise OperationFailure('private server error', code=225)
        return original(rows)
    monkeypatch.setattr(reports, '_public', fail)
    response = client(app).get('/api/activity/export', query_string=PERIOD)
    assert response.status_code == 503 and response.is_json
    assert len(calls) == failed_batch
    assert 'private server error' not in response.get_data(as_text=True)
    assert 'Content-Disposition' not in response.headers


def test_reads_do_not_flush_pending_writes_and_batch_enrichment(app, monkeypatch):
    insert(app, [event(f'e{n:03}') for n in range(30)])
    def no_flush(*args, **kwargs):
        raise AssertionError('Read reporting must not flush pending writes')
    monkeypatch.setattr(mongo_activity, 'flush', no_flush)
    seen = []
    original = Collection.find
    def capture(collection, *args, **kwargs):
        condition = args[0].get('_id', {}) if args else {}
        if collection.name in {'tools', 'users'} and isinstance(condition, dict) and '$in' in condition:
            seen.append(collection.name)
        return original(collection, *args, **kwargs)
    monkeypatch.setattr(Collection, 'find', capture)
    c = client(app)
    assert c.get('/api/activity', query_string=PERIOD).status_code == 200
    assert seen.count('tools') == seen.count('users') == 1
    assert c.get('/api/activity/export', query_string=PERIOD).status_code == 200
    assert seen.count('tools') == seen.count('users') == 2


def test_indexes_cover_date_sort_and_filtered_date_sort(app):
    with app.app_context():
        keys = [list(row['key'].items()) for row in db().activity.list_indexes()]
        assert [('created', -1), ('_id', -1)] in keys
        assert [('kind', 1), ('created', -1), ('_id', -1)] in keys
