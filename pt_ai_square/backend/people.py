"""Authenticated employee profiles and all-time sharing contribution rankings."""
from collections import OrderedDict
from http.client import HTTPException
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from flask import Blueprint, Response, current_app, g, jsonify

from .storage import db

people = Blueprint('people', __name__)
PHOTO_BASE = 'http://skynet.skhynix.com/portalWeb/uploadfile/pictures/'
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
    request = Request(PHOTO_BASE + employee + '.jpg', headers={'Accept': 'image/jpeg,image/png,image/webp,image/gif'})
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
            and re.fullmatch(r'[0-9]{1,20}', employee) is not None)


def _photo_response(employee):
    if not _photo_enabled(employee):
        return Response(status=404, headers={'Cache-Control': 'private, no-store'})
    now = time.monotonic()
    with _photo_lock:
        cached = _photo_cache.get(employee)
        if cached and cached[0] > now:
            _photo_cache.move_to_end(employee)
            result = cached[1]
        else:
            cached = None
    if not cached:
        try:
            result = _fetch_photo(employee)
        except (HTTPError, URLError, OSError, TimeoutError, HTTPException, ValueError):
            result = None
        with _photo_lock:
            _photo_cache[employee] = (now + (300 if result else 30), result)
            _photo_cache.move_to_end(employee)
            while len(_photo_cache) > 128:
                _photo_cache.popitem(last=False)
    if not result:
        # The main UI keeps the employee's initial visible when the intranet
        # photo is absent or unavailable. Do not expose upstream errors.
        return Response(status=404, headers={'Cache-Control': 'private, no-store'})
    data, mime = result
    # The URL is /api/me/photo for every signed-in employee. Browser caching
    # must not show a previous employee's face after an account switch; the
    # bounded server cache above is separately keyed by employee number.
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
            or not db().tools.find_one({'owner': employee, 'deleted': {'$ne': True}}, {'_id': 1})):
        return Response(status=404, headers={'Cache-Control': 'private, no-store'})
    return _photo_response(employee)


def _ranking_pipeline():
    # Downloads use the same lifetime identity as tool rankings. Old daily rows
    # count once per tool/user; the newer firstDownloadedAt:null marks update-
    # only receipts and must not fall back to their created timestamp.
    download_first = {'$cond': [
        {'$eq': [{'$type': '$firstDownloadedAt'}, 'missing']}, '$created', '$firstDownloadedAt',
    ]}
    return [
        {'$match': {'deleted': {'$ne': True}}},
        {'$lookup': {'from': 'users', 'localField': 'owner', 'foreignField': '_id', 'as': 'creator'}},
        {'$unwind': '$creator'},
        {'$match': {'creator.enabled': {'$ne': False}}},
        {'$lookup': {'from': 'activity_state', 'let': {'toolId': '$_id', 'creatorId': '$owner'}, 'pipeline': [
            {'$match': {'$expr': {'$and': [
                {'$eq': ['$tool', '$$toolId']}, {'$ne': ['$user', '$$creatorId']},
                {'$in': ['$kind', ['like', 'download']]},
            ]}}},
            {'$group': {'_id': {'user': '$user', 'kind': '$kind'},
                'liked': {'$max': {'$cond': [{'$and': [{'$eq': ['$kind', 'like']}, {'$eq': ['$liked', True]}]}, 1, 0]}},
                'downloaded': {'$max': {'$cond': [{'$and': [
                    {'$eq': ['$kind', 'download']}, {'$gt': [{'$ifNull': ['$count', 0]}, 0]},
                    {'$ne': [{'$ifNull': [download_first, None]}, None]},
                ]}, 1, 0]}},
            }},
            {'$group': {'_id': None, 'likes': {'$sum': '$liked'}, 'downloads': {'$sum': '$downloaded'}}},
        ], 'as': 'activity'}},
        {'$group': {'_id': '$owner', 'name': {'$first': '$creator.name'},
            'dept': {'$first': '$creator.dept'}, 'orgId': {'$first': '$creator.orgId'},
            'registered': {'$sum': 1},
            'likes': {'$sum': {'$ifNull': [{'$arrayElemAt': ['$activity.likes', 0]}, 0]}},
            'downloads': {'$sum': {'$ifNull': [{'$arrayElemAt': ['$activity.downloads', 0]}, 0]}},
        }},
        {'$set': {'score': {'$add': [{'$multiply': ['$registered', 5]}, {'$multiply': ['$likes', 2]}, '$downloads']}}},
        {'$lookup': {'from': 'taxonomy', 'localField': 'orgId', 'foreignField': '_id', 'as': 'organization'}},
        {'$set': {'org': {'$ifNull': ['$dept', {'$ifNull': [{'$arrayElemAt': ['$organization.name', 0]}, '공통']}]}}},
        {'$sort': {'score': -1, 'registered': -1, 'likes': -1, 'downloads': -1, '_id': 1}},
        {'$project': {'organization': 0, 'dept': 0, 'orgId': 0}},
    ]


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
        method='등록 도구 × 5 + 받은 좋아요 × 2 + 고유 다운로드 × 1 · 전체 기간',
        tieBreak='동점은 등록 수, 좋아요, 다운로드, 사번 순입니다. 본인 반응·반복 수신·업데이트·삭제 도구는 제외합니다.')
