from unittest.mock import patch

import pytest

from pt_ai_square import create_app
from pt_ai_square import config


@pytest.fixture
def dummy(tmp_path):
    # A configured production-shaped URI must never be used in explicit dummy mode.
    with patch('pt_ai_square.init_db', side_effect=AssertionError('DB forbidden')), \
         patch('pt_ai_square.init_activity', side_effect=AssertionError('activity forbidden')), \
         patch('pt_ai_square.install_auth', side_effect=AssertionError('DB auth forbidden')):
        app = create_app(dict(TESTING=True, DATA_MODE='dummy', AUTH_MODE='mock',
                              MOCK_USER='0099001', MOCK_NAME='화면 확인 사용자', MOCK_ADMIN=False,
                              ADMIN_IDS='', MONGODB_URI='mongodb://configured.invalid/',
                              DATA_DIR=str(tmp_path/'never-created')))
        yield app.test_client()
    assert not (tmp_path/'never-created').exists()


def test_dummy_screen_contract_and_configured_identity(dummy):
    assert dummy.get('/').status_code == 200
    assert dummy.get('/health').json['storage'] == 'dummy'
    data = dummy.get('/api/bootstrap').json
    assert data['dataMode'] == 'dummy'
    assert data['authMode'] == 'mock'
    assert data['user']['id'] == '0099001'
    assert data['user']['role'] == 'user'
    assert len(data['items']) == 10
    assert {x['type'] for x in data['items']} == {'MCP/Tool','Skill','플러그인/하네스'}
    assert sum(x['ownerId']=='0099001' for x in data['items']) == 3
    assert [x['id'] for x in data['items'] if x['canManage']] == [1,2,3]
    item = dummy.get('/api/tools/1').json
    assert item['active'] == 2 and len(item['versions']) == 2
    assert dummy.get('/api/tools/99999').status_code == 404
    for url in ['/api/ideas','/api/notifications','/api/admins','/api/activity','/api/storage/candidates','/api/users?q=0099001']:
        assert dummy.get(url).status_code == 200
    assert dummy.get('/api/users?q=0099001').json['users'][0]['id'] == '0099001'
    assert dummy.get('/api/bootstrap').headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('method,url', [('POST','/api/tools'),('PUT','/api/tools/1/like'),
    ('PATCH','/api/tools/1'),('DELETE','/api/tools/1'),('POST','/api/ideas'),
    ('PUT','/api/admins/other'),('GET','/download/1/2'),('HEAD','/download/1/2')])
def test_dummy_rejects_writes_and_file_downloads(dummy,method,url):
    before=dummy.get('/api/bootstrap').json
    assert dummy.open(url,method=method).status_code == 409
    assert dummy.get('/api/bootstrap').json == before


def test_dummy_requires_mock_and_rejects_unknown_mode(tmp_path):
    with pytest.raises(ValueError,match='mock'):
        create_app(dict(DATA_MODE='dummy', AUTH_MODE='sso'))
    with pytest.raises(ValueError,match='PTAI_DATA_MODE'):
        create_app(dict(DATA_MODE='typo'))


def test_dummy_setting_default_and_environment_precedence(monkeypatch,tmp_path):
    monkeypatch.setattr(config,'BASE',tmp_path)
    monkeypatch.delenv('PTAI_DATA_MODE',raising=False)
    assert config.settings()['DATA_MODE']=='mongodb'
    (tmp_path/'runtime_config.py').write_text("PTAI_DATA_MODE = 'dummy'\n",encoding='utf-8')
    assert config.settings()['DATA_MODE']=='dummy'
    monkeypatch.setenv('PTAI_DATA_MODE','mongodb')
    assert config.settings()['DATA_MODE']=='mongodb'


def test_ax_workspace_dummy_is_read_only_and_separate(dummy):
    response=dummy.get('/api/ax-workspace')
    assert response.status_code == 200
    assert response.json['canManage'] is False
    assert {x['category'] for x in response.json['files']} == {'workspace','plugin','integration'}
    assert dummy.get(response.json['files'][0]['downloadUrl']).status_code == 409
    assert dummy.post('/api/ax-workspace').status_code == 409
    assert dummy.get('/api/deletions').json == {'jobs':[]}


def test_dummy_contributions_show_only_my_tools_with_full_totals(dummy):
    first = dummy.get('/api/me/contributions?pageSize=2').json
    second = dummy.get('/api/me/contributions?pageSize=2&page=2&user=sample-colleague').json
    assert first['dummy'] is True and first['totalItems'] == 3
    assert [row['id'] for row in first['items'] + second['items']] == [1, 2, 3]
    assert first['summary'] == second['summary']
    assert first['summary']['registered'] == 3
    assert first['summary']['score'] == sum(row['score'] for row in first['items'] + second['items'])
    assert dummy.get('/api/me/contributions?page=0').status_code == 400
    assert dummy.get('/api/me/contributions?pageSize=101').status_code == 400


def test_room_preview_and_holidays_do_not_need_database(dummy):
    from datetime import datetime, timedelta, timezone
    day = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    response = dummy.get(f'/api/immersion-room?start={day}&end={day}')
    assert response.status_code == 200
    assert response.json['dummy'] is True and response.json['canManage'] is False
    assert response.json['reservations'][0]['owner']['name'] == '예시 동료'
    assert dummy.post('/api/immersion-room/reservations', json={}).status_code == 409
    holidays = dummy.get('/api/immersion-room/holidays?start=2026-10-01&end=2026-10-31')
    assert holidays.status_code == 200 and len(holidays.json['holidays']) == 3
    assert dummy.get('/api/immersion-room?start=bad&end=bad').status_code == 400
