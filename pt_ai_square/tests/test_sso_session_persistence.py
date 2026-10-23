"""SSO session continuity across deployment updates and worker processes."""
from pt_ai_square import create_app
from .conftest import ready


def test_legacy_session_reauthenticates_once(app):
    client,_=ready(app)
    with client.session_transaction() as session:
        # The previous release issued these same six fields and logFlag,
        # but did not issue the verified-login timestamp.
        assert session['logFlag'] is True
        session.pop('_hcp_login')
    response=client.get('/api/bootstrap')
    assert response.status_code==401 and '/login?' in response.json['login']
    assert client.get(response.json['login']).status_code==302
    assert client.get('/api/bootstrap').status_code==200
    assert client.get('/').status_code==200


def test_mongodb_session_secret_keeps_login_across_workers(app):
    config=dict(app.config,SECRET_KEY='')
    first=create_app(config)
    second=None
    try:
        browser,_=ready(first)
        cookie=browser.get_cookie(first.config['SESSION_COOKIE_NAME'])
        class LoginMustNotRun:
            def __init__(self,request):raise RuntimeError('SDK unavailable after login')
        second=create_app(dict(config,SSO_FACTORY=LoginMustNotRun))
        assert first.secret_key==second.secret_key
        other_worker=second.test_client()
        other_worker.set_cookie(second.config['SESSION_COOKIE_NAME'],cookie.value)
        assert other_worker.get('/').status_code==200
        assert other_worker.get('/api/bootstrap').json['user']['id']=='owner'
    finally:
        first.extensions['square_mongo_client'].close()
        if second:second.extensions['square_mongo_client'].close()
