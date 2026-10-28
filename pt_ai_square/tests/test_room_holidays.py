from datetime import date

import pytest
from werkzeug.exceptions import BadRequest

from pt_ai_square.backend.room_holidays import calendar_range, holiday_data, holiday_response


def test_bundled_holidays_include_lunar_substitutes_and_2026_additions():
    rows = {row['date']: row['name'] for row in holiday_data()['holidays']}
    assert len(rows) == len(holiday_data()['holidays'])
    for value in rows:
        assert date.fromisoformat(value).year in (2026, 2027)
    assert rows['2026-05-01'] == '노동절'
    assert rows['2026-07-17'] == '제헌절'
    assert rows['2026-06-03'] == '전국동시지방선거'
    assert rows['2027-02-07'] == '설날'
    assert rows['2027-09-15'] == '추석'
    assert '대체공휴일' in rows['2027-07-19']
    assert '대체공휴일' in rows['2027-12-27']
    assert '2027-06-07' not in rows  # Memorial Day has no substitute here.


def test_holiday_range_and_explicit_coverage_notice():
    result = holiday_response({'start': '2026-10-01', 'end': '2026-10-31'})
    assert [row['date'] for row in result['holidays']] == ['2026-10-03', '2026-10-05', '2026-10-09']
    assert result['notice'] == ''
    assert all(source['url'].startswith('https://') for source in result['sources'])
    future = holiday_response({'start': '2028-01-01', 'end': '2028-01-31'})
    assert future['holidays'] == [] and future['notice']
    assert future['coverage'] == {'startYear': 2026, 'endYear': 2027}


@pytest.mark.parametrize('start,end', [('2026-2-01', '2026-02-10'), ('2026-02-30', '2026-03-01'),
    ('2026-03-02', '2026-03-01'), ('2026-01-01', '2026-03-04'), ('', '')])
def test_invalid_calendar_ranges(start, end):
    with pytest.raises(BadRequest):
        calendar_range({'start': start, 'end': end})
