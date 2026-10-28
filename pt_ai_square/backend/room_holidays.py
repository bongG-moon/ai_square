"""Bundled Korean holidays: usable on the company network without external calls."""
from datetime import date
from functools import lru_cache
import json
from pathlib import Path
import re

from flask import jsonify, request
from werkzeug.exceptions import BadRequest


def calendar_range(args):
    values = []
    for key in ('start', 'end'):
        value = args.get(key, '')
        if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise BadRequest('조회할 시작일과 종료일을 YYYY-MM-DD 형식으로 입력해 주세요.')
        try:
            values.append(date.fromisoformat(value))
        except ValueError:
            raise BadRequest('달력에 있는 날짜를 입력해 주세요.')
    start, end = values
    if not 0 <= (end - start).days < 62:
        raise BadRequest('한 번에 조회할 수 있는 기간은 최대 62일입니다.')
    return start, end


@lru_cache(maxsize=1)
def holiday_data():
    path = Path(__file__).resolve().parents[1] / 'data' / 'kr_holidays.json'
    return json.loads(path.read_text(encoding='utf-8'))


def holiday_response(args):
    start, end = calendar_range(args)
    data = holiday_data()
    coverage = data['coverage']
    missing = start.year < coverage['startYear'] or end.year > coverage['endYear']
    return dict(holidays=[row for row in data['holidays'] if start.isoformat() <= row['date'] <= end.isoformat()],
                coverage=coverage, sources=data['sources'], updated=data['updated'],
                notice='이 기간의 일부 공휴일 자료가 아직 없습니다. 주말만 표시되는 날짜가 있으니 운영자에게 확인해 주세요.' if missing else '')


def install_room_holidays(app):
    @app.get('/api/immersion-room/holidays')
    def immersion_room_holidays():
        return jsonify(holiday_response(request.args))
