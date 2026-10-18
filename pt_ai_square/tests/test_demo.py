import pytest
from pymongo.errors import ServerSelectionTimeoutError
from pt_ai_square import create_app
from pt_ai_square import config

def test_unconfigured_defaults_to_demo(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'BASE',tmp_path)
    monkeypatch.delenv('MONGODB_URI',raising=False)
    from unittest.mock import patch
    with patch('pt_ai_square.init_db',side_effect=AssertionError('Demo must not connect to MongoDB')):
        app=create_app({'TESTING':True,'DATA_DIR':str(tmp_path/'data')})
    client=app.test_client()
    assert client.get('/').status_code==200
    assert client.get('/health').json['storage']=='demo'
    data=client.get('/api/bootstrap').json
    assert data['demo'] and len(data['items'])==10
    assert not (tmp_path/'data').exists()
    assert client.get('/api/tools/1').json['name'].startswith('[예시]')
    for path in ['/api/ideas','/api/notifications','/api/admins','/api/users?q=체험','/api/activity','/api/storage/candidates']:
        assert client.get(path).status_code==200
    assert client.get('/api/tools/999').status_code==404
    for method,path in [('post','/api/tools'),('put','/api/tools/1/like'),('patch','/api/tools/1'),('delete','/api/tools/1'),('post','/api/tools/1/versions'),('get','/download/1/1')]:
        response=getattr(client,method)(path)
        assert response.status_code==409 and response.json['demo']
    assert client.get('/api/bootstrap').json==data

def test_configured_failure_never_becomes_demo(tmp_path):
    from unittest.mock import patch
    with patch('pt_ai_square.init_db',side_effect=ServerSelectionTimeoutError('offline')):
        with pytest.raises(ServerSelectionTimeoutError):
            create_app({'MONGODB_URI':'mongodb://configured.invalid/','DATA_DIR':str(tmp_path)})
