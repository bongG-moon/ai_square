"""Authenticated employee profiles and all-time sharing contribution rankings."""
from collections import OrderedDict
from http.client import HTTPException
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from flask import Blueprint, Response, current_app, g, jsonify, request
from werkzeug.exceptions import BadRequest

from .storage import db

people = Blueprint('people', __name__)
PHOTO_MAX_BYTES = 1024 * 1024
PHOTO_TIMEOUT = 3
_photo_cache = OrderedDict()
_photo_lock = threading.Lock()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # The upstream URL is fixed. Do not forward a request to a login page,
        # another host or an attacker-controlled redirect target.
        return None


def _image_type(data):
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


def _fetch_photo(employee):
    base_url = current_app.config.get('EMPLOYEE_PHOTO_BASE_URL', '')
    if not base_url:
        return None
    request = Request(base_url + employee + '.jpg', headers={'Accept': 'image/jpeg,image/png,image/webp,image/gif'})
    # Construct a fresh request: the browser's SSO cookie and API key are never
    # forwarded to the photo service. Only the employee number is in the path.
    with build_opener(_NoRedirect()).open(request, timeout=PHOTO_TIMEOUT) as upstream:
        if upstream.status != 200:
            return None
        declared = upstream.headers.get_content_type()
        if declared not in {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}:
            return None
        length = upstream.headers.get('Content-Length')
        if length and (not length.isdigit() or int(length) > PHOTO_MAX_BYTES):
            return None
        data = upstream.read(PHOTO_MAX_BYTES + 1)
        actual = _image_type(data)
        if not data or len(data) > PHOTO_MAX_BYTES or actual != declared:
            return None
        return data, actual


def _photo_enabled(employee):
    # Local/mock identities never leave this service, even if numeric.
    return (current_app.config['AUTH_MODE'] == 'sso'
            and current_app.config['DATA_MODE'] == 'mongodb'
            and bool(current_app.config.get('EMPLOYEE_PHOTO_BASE_URL'))
            and re.fullmatch(r'[0-9]{1,20}', employee) is not None)


def _photo_response(employee):
    if not _photo_enabled(employee):
        return Response(status=404, headers={'Cache-Control': 'private, no-store'})
    now = time.monotonic()
    cache_key = (current_app.config['EMPLOYEE_PHOTO_BASE_URL'], employee)
    with _photo_lock:
        cached = _photo_cache.get(cache_key)
        if cached and cached[0] > now:
            _photo_cache.move_to_end(cache_key)
            result = cached[1]
        else:
            cached = None
    if not cached:
        try:
            result = _fetch_photo(employee)
        except (HTTPError, URLError, OSError, TimeoutError, HTTPException, ValueError):
            result = None
        with _photo_lock:
            _photo_cache[cache_key] = (now + (300 if result else 30), result)
            _photo_cache.move_to_end(cache_key)
            while len(_photo_cache) > 128:
                _photo_cache.popitem(last=False)
    if not result:
        # The main UI keeps the employee's initial visible when the intranet
        # photo is absent or unavailable. Do not expose upstream errors.
        return Response(status=404, headers={'Cache-Control': 'private, no-store'})
    data, mime = result
    # The URL is /api/me/photo for every signed-in employee. Browser caching
    # must not show a previous employee's face after an account switch; the
    # bounded server cache above is keyed by the configured origin and employee.
    return Response(data, mimetype=mime, headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@people.get('/api/me/photo')
def photo():
    return _photo_response(str(g.user['id']))


@people.get('/api/people/<employee>/photo')
def contributor_photo(employee):
    # This is a portrait for a platform contributor, not a general employee
    # directory proxy. Check eligibility before consulting the image cache too.
    if (not _photo_enabled(employee)
            or not db().users.find_one({'_id': employee, 'enabled': {'$ne': False}}, {'_id': 1})
            or not (db().tools.find_one({'owner': employee}, {'_id': 1})
                    or db().deletion_jobs.find_one({'kind': 'tool', 'contribution.schemaVersion': 1,
                                                   'contribution.owner': employee}, {'_id': 1}))):
        return Response(status=404, headers={'Cache-Control': 'private, no-store'})
    return _photo_response(employee)


def _ranking_pipeline():
    from .contributions import ranking_pipeline
    return ranking_pipeline()


@people.get('/api/me/contributions')
def my_contributions():
    # Owner identity always comes from the authenticated session, including admins.
    from .contributions import personal_details
    values = {}
    for name, default, maximum in [('page', 1, 1000000), ('pageSize', 20, 100)]:
        raw = request.args.get(name, str(default))
        if not re.fullmatch(r'[0-9]{1,7}', raw) or not 1 <= int(raw) <= maximum:
            raise BadRequest('페이지와 표시 개수를 확인해 주세요.')
        values[name] = int(raw)
    response = jsonify(personal_details(g.user['id'], values['page'], values['pageSize']))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@people.get('/api/people/ranking')
def ranking():
    # One aggregation computes totals without loading raw transfer history into
    # Python or querying tool details individually. It exposes user totals only,
    # never the titles/content of permission-restricted tools.
    rows = db().tools.aggregate(_ranking_pipeline(), allowDiskUse=True)
    items, me, total = [], None, 0
    for total, row in enumerate(rows, 1):
        row.update(id=row.pop('_id'), rank=total)
        row['isMe'] = row['id'] == g.user['id']
        row['photoUrl'] = f"/api/people/{row['id']}/photo" if _photo_enabled(str(row['id'])) else None
        if total <= 10:
            items.append(row)
        if row['isMe']:
            me = row
    if me is None:
        me = dict(id=g.user['id'], name=g.user['name'], org=g.user['org'], rank=None,
                  registered=0, likes=0, downloads=0, score=0, isMe=True, photoUrl=None)
    return jsonify(items=items, me=me, totalUsers=total, period='all', asOf=time.time(),
        weights=dict(registered=5, likes=2, downloads=1),
        method='등록 도구 × 5 + 받은 좋아요 × 2 + 다운로드 수 × 1 (전체 기간)',
        tieBreak='동점은 등록 수, 좋아요, 다운로드, 사번 순입니다. 본인 반응과 반복 수신, 업데이트는 제외하며 삭제한 도구의 기여도는 유지합니다.')
