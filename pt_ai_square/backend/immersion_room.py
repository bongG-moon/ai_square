"""One-room calendar with atomic, overlap-safe half-day reservations."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
import time
import uuid

from flask import Blueprint, g, jsonify, request
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from werkzeug.exceptions import BadRequest, Conflict, Forbidden, NotFound

from .storage import db
from .mongo_store import event, deliver_notifications
from .post_commit import followup_pending


immersion_room = Blueprint('immersion_room', __name__)
KST = timezone(timedelta(hours=9))
ACTIVE = ('pending', 'approved')


def today():
    return datetime.now(KST).date()


def _date(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise BadRequest(f'{label}를 YYYY-MM-DD 형식으로 입력해 주세요.')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise BadRequest(f'{label}가 올바른 날짜가 아닙니다.') from None


def _range(start, end, maximum):
    first, last = _date(start, '시작일'), _date(end, '종료일')
    if first > last:
        raise BadRequest('종료일은 시작일보다 빠를 수 없습니다.')
    if (last - first).days >= maximum:
        raise BadRequest(f'한 번에 최대 {maximum}일까지 선택할 수 있습니다.')
    return first, last


def _text(value, label, maximum, required=True):
    if not isinstance(value, str):
        raise BadRequest(f'{label}를 글자로 입력해 주세요.')
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        raise BadRequest(f'{label}는 {"1~" if required else "최대 "}{maximum}자로 입력해 주세요.')
    if any(ord(c) < 32 and c not in '\n\t' for c in value) or '\x7f' in value:
        raise BadRequest(f'{label}에 사용할 수 없는 문자가 있습니다.')
    return value


def _body(allowed):
    raw = request.get_json(silent=True)
    if not isinstance(raw, dict) or set(raw) - set(allowed):
        raise BadRequest('예약 요청 형식을 확인해 주세요.')
    return raw


def _public(row):
    admin = g.user['role'] == 'admin'
    mine = row['owner']['id'] == g.user['id']
    return dict(id=row['_id'], startDate=row['startDate'], endDate=row['endDate'],
                slot=row['slot'], title=row['title'], purpose=row['purpose'],
                status=row['status'], owner=row['owner'], revision=row['revision'],
                created=row['created'], updated=row['updated'], reason=row.get('reason', ''),
                canCancel=row['status'] in ACTIVE and (admin or mine),
                canReject=admin and row['status'] == 'pending',
                canApprove=admin and row['status'] == 'pending' and row['startDate'] >= today().isoformat())


@immersion_room.get('/api/immersion-room')
def calendar():
    first, last = _range(request.args.get('start'), request.args.get('end'), 62)
    query = {'startDate': {'$lte': last.isoformat()}, 'endDate': {'$gte': first.isoformat()}}
    if g.user['role'] != 'admin':
        query['$or'] = [{'status': {'$in': list(ACTIVE)}}, {'owner.id': g.user['id']}]
    # Active bookings are inherently bounded by two slots per day. Histories
    # are bounded separately so cancelled/rejected records cannot grow a month
    # response without limit or hide the actual occupied slots.
    active = list(db().room_reservations.find({**query, 'status': {'$in': list(ACTIVE)}})
                  .sort([('startDate', 1), ('slot', 1), ('created', 1)]))
    history = list(db().room_reservations.find({**query, 'status': {'$nin': list(ACTIVE)}})
                   .sort([('updated', -1), ('_id', 1)]).limit(101))
    return jsonify(reservations=[_public(row) for row in active + history[:100]],
                   today=today().isoformat(), canManage=g.user['role'] == 'admin',
                   historyTruncated=len(history) > 100)


@immersion_room.get('/api/immersion-room/admin/reservations')
def admin_reservations():
    if g.user['role'] != 'admin':
        raise Forbidden('관리자만 예약 신청 내역을 확인할 수 있습니다.')
    status = request.args.get('status', 'pending')
    if status not in {'pending', 'history', 'all'}:
        raise BadRequest('예약 상태 필터를 확인해 주세요.')
    try:
        page = int(request.args.get('page', '1'))
        page_size = int(request.args.get('pageSize', '20'))
    except (TypeError, ValueError):
        raise BadRequest('페이지 정보를 확인해 주세요.') from None
    if not 1 <= page <= 1000 or not 1 <= page_size <= 50:
        raise BadRequest('페이지 정보를 확인해 주세요.')
    query = {'status': 'pending'} if status == 'pending' else ({'status': {'$in': ['approved', 'rejected', 'cancelled']}} if status == 'history' else {})
    order = [('startDate', 1), ('_id', 1)] if status == 'pending' else [('updated', -1), ('_id', -1)]
    collection = db().room_reservations
    total = collection.count_documents(query)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    rows = collection.find(query).sort(order).skip((page - 1) * page_size).limit(page_size)
    return jsonify(reservations=[_public(row) for row in rows], total=total,
                   page=page, pageSize=page_size, totalPages=total_pages)


@immersion_room.get('/api/immersion-room/reservations/<reservation_id>')
def reservation_detail(reservation_id):
    row = db().room_reservations.find_one({'_id': reservation_id})
    if not row or (row['status'] not in ACTIVE and g.user['role'] != 'admin' and row['owner']['id'] != g.user['id']):
        raise NotFound('예약을 찾을 수 없습니다.')
    return jsonify(reservation=_public(row))


def _retry(existing, fingerprint):
    if existing['fingerprint'] != fingerprint:
        raise Conflict('같은 요청 번호에 다른 내용이 들어 있습니다. 새 예약으로 신청해 주세요.')
    return jsonify(reservation=_public(existing), created=False)


@immersion_room.post('/api/immersion-room/reservations')
def create():
    raw = _body({'startDate', 'endDate', 'slot', 'title', 'purpose', 'clientRequestId'})
    first, last = _range(raw.get('startDate'), raw.get('endDate'), 31)
    slot = raw.get('slot', 'all')
    if not isinstance(slot, str) or slot not in {'all', 'am', 'pm'}:
        raise BadRequest('사용 시간은 종일, 오전, 오후 중에서 선택해 주세요.')
    title = _text(raw.get('title'), '예약 제목', 100)
    purpose = _text(raw.get('purpose'), '사용 목적', 2000)
    key = raw.get('clientRequestId')
    try:
        if not isinstance(key, str) or len(key) != 36:
            raise ValueError()
        key = str(uuid.UUID(key))
    except (ValueError, AttributeError):
        raise BadRequest('예약 요청 번호가 올바르지 않습니다. 화면을 새로고침해 주세요.') from None
    fingerprint = hashlib.sha256(json.dumps([first.isoformat(), last.isoformat(), slot, title, purpose],
                                            ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    identity = {'owner.id': g.user['id'], 'clientRequestId': key}
    existing = db().room_reservations.find_one(identity)
    if existing:
        return _retry(existing, fingerprint)
    if first < today():
        raise BadRequest('지난 날짜에는 새 예약을 신청할 수 없습니다.')
    keys = [f'{(first + timedelta(days=n)).isoformat()}:{half}'
            for n in range((last - first).days + 1)
            for half in (('am', 'pm') if slot == 'all' else (slot,))]
    now = time.time()
    admin = g.user['role'] == 'admin'
    row = dict(_id=str(uuid.uuid4()), startDate=first.isoformat(), endDate=last.isoformat(),
               slot=slot, slotKeys=keys, title=title, purpose=purpose,
               status='approved' if admin else 'pending',
               owner={'id': g.user['id'], 'name': g.user['name'], 'org': g.user.get('org', '')},
               revision=1, created=now, updated=now, reason='', clientRequestId=key,
               fingerprint=fingerprint,
               decisions=[dict(status='approved' if admin else 'pending', user=g.user['id'], at=now)])
    try:
        # A unique multikey index reserves every half-day in this ONE insert.
        # A collision rolls back the whole document, including multi-day stays.
        db().room_reservations.insert_one(row)
    except DuplicateKeyError:
        existing = db().room_reservations.find_one(identity)
        if existing:
            return _retry(existing, fingerprint)
        raise Conflict('선택한 기간에 승인 대기 또는 승인된 예약이 있습니다. 다른 날짜나 시간대를 선택해 주세요.') from None
    return jsonify(reservation=_public(row), created=True), 201


@immersion_room.patch('/api/immersion-room/reservations/<reservation_id>')
def change_status(reservation_id):
    raw = _body({'status', 'expectedRevision', 'reason'})
    status = raw.get('status')
    if not isinstance(status, str) or status not in {'approved', 'rejected', 'cancelled'}:
        raise BadRequest('예약 상태가 올바르지 않습니다.')
    expected = raw.get('expectedRevision')
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 1:
        raise BadRequest('예약 정보를 새로고침한 뒤 다시 시도해 주세요.')
    reason = _text(raw.get('reason', ''), '처리 사유', 500, required=False)
    row = db().room_reservations.find_one({'_id': reservation_id})
    if not row:
        raise NotFound('예약을 찾을 수 없습니다.')
    admin = g.user['role'] == 'admin'
    if not admin and (status != 'cancelled' or row['owner']['id'] != g.user['id']):
        raise Forbidden('본인의 예약만 취소할 수 있습니다. 승인은 관리자에게 요청해 주세요.')
    # A response can be lost after the atomic transition. An identical retry
    # returns the committed state; it never repeats the transition/history.
    if row['status'] == status and row['revision'] == expected + 1:
        decision = row.get('decisions', [])[-1:]
        if decision and decision[0]['user'] == g.user['id'] and row.get('reason', '') == reason:
            followup_pending('room-notification', deliver_notifications, 'room_reservations', reservation_id)
            return jsonify(reservation=_public(row))
    if row['revision'] != expected:
        raise Conflict('다른 사람이 예약을 변경했습니다. 최신 내용을 확인해 주세요.')
    if row['status'] not in ACTIVE or (status in {'approved', 'rejected'} and row['status'] != 'pending'):
        raise Conflict('현재 상태에서는 요청한 처리를 할 수 없습니다.')
    if status == 'approved' and row['startDate'] < today().isoformat():
        raise Conflict('시작일이 지난 예약은 승인할 수 없습니다. 취소 후 새 날짜로 신청해 주세요.')
    now = time.time()
    update = {'$set': {'status': status, 'updated': now, 'reason': reason},
              '$inc': {'revision': 1},
              '$push': {'decisions': {'status': status, 'user': g.user['id'], 'at': now}}}
    if admin and row['owner']['id'] != g.user['id']:
        label = {'approved': '승인', 'rejected': '반려', 'cancelled': '취소'}[status]
        update['$push']['outbox'] = event(
            [row['owner']['id']], f'AI 몰입룸 예약이 {label}되었습니다: {row["title"]}',
            {'type': 'room', 'id': reservation_id, 'startDate': row['startDate']}, 'room')
    if status in {'rejected', 'cancelled'}:
        # Remove, rather than leave an empty array/null: the sparse unique index
        # then releases all half-days and skips this historical reservation.
        update['$unset'] = {'slotKeys': ''}
    saved = db().room_reservations.find_one_and_update(
        {'_id': reservation_id, 'revision': expected, 'status': row['status']},
        update, return_document=ReturnDocument.AFTER)
    if not saved:
        raise Conflict('다른 사람이 예약을 변경했습니다. 최신 내용을 확인해 주세요.')
    if 'outbox' in update['$push']:
        followup_pending('room-notification', deliver_notifications, 'room_reservations', reservation_id)
    return jsonify(reservation=_public(saved))
