"""Photo origin configuration and no-network fallback without a MongoDB server."""
from email.message import Message
import io

from flask import Flask, g
import pytest

from pt_ai_square import config
from pt_ai_square.backend import people


def photo_app(base_url=''):
    app = Flask(__name__)
    app.config.update(AUTH_MODE='sso', DATA_MODE='mongodb', EMPLOYEE_PHOTO_BASE_URL=base_url)
    app.register_blueprint(people.people)
    @app.before_request
    def test_identity():
        g.user = {'id': '0012345'}
    with people._photo_lock:
        people._photo_cache.clear()
    return app


def test_unconfigured_photo_has_no_upstream_request(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError('Unconfigured photos must not create an upstream request')
    monkeypatch.setattr(people, 'build_opener', unexpected)
    with photo_app().app_context():
        assert people._photo_enabled('0012345') is False
        assert people._fetch_photo('0012345') is None
    assert photo_app().test_client().get('/api/me/photo').status_code == 404


def test_configured_photo_uses_only_operator_origin_and_separate_cache(monkeypatch):
    calls = []
    class Image(io.BytesIO):
        status = 200
        def __init__(self):
            super().__init__(b'\xff\xd8\xffphoto')
            self.headers = Message()
            self.headers['Content-Type'] = 'image/jpeg'
    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, dict(request.header_items()), timeout))
            return Image()
    monkeypatch.setattr(people, 'build_opener', lambda *handlers: Opener())
    app = photo_app('https://photos.company.example/pictures/')
    client = app.test_client()
    client.set_cookie('sso', 'secret')
    assert client.get('/api/me/photo', headers={'Authorization': 'Bearer browser-secret'}).status_code == 200
    assert client.get('/api/me/photo').status_code == 200
    app.config['EMPLOYEE_PHOTO_BASE_URL'] = 'https://second.company.example/images/'
    assert client.get('/api/me/photo').status_code == 200
    assert calls == [
        (base + '0012345.jpg', {'Accept': 'image/jpeg,image/png,image/webp,image/gif'}, 3)
        for base in ('https://photos.company.example/pictures/', 'https://second.company.example/images/')
    ]


@pytest.mark.parametrize('value', ['', 'https://photos.company.example/pictures', 'http://photos.company.example:8080/pictures/'])
def test_valid_photo_base_url(value):
    assert config.employee_photo_base_url(value) == (value.rstrip('/') + '/' if value else '')


@pytest.mark.parametrize('value', [
    'file:///private/photos', 'https://user:secret@photos.company.example/',
    'https://photos.company.example/?key=secret', 'https://photos.company.example/#fragment',
    'https://photos.company.example:99999/', 'https://photos.company.example/a b/',
    'https://photos.company.example/\nsecret', '//photos.company.example/', 'https://',
])
def test_invalid_photo_base_url_is_rejected(value):
    with pytest.raises(ValueError, match='PTAI_EMPLOYEE_PHOTO_BASE_URL'):
        config.employee_photo_base_url(value)


def test_photo_setting_is_optional_and_can_be_supplied_by_operator(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'BASE', tmp_path)
    monkeypatch.delenv('PTAI_EMPLOYEE_PHOTO_BASE_URL', raising=False)
    assert config.settings()['EMPLOYEE_PHOTO_BASE_URL'] == ''
    (tmp_path / 'runtime_config.py').write_text("PTAI_EMPLOYEE_PHOTO_BASE_URL = 'https://private.company.example/photos'\n", encoding='utf-8')
    assert config.settings()['EMPLOYEE_PHOTO_BASE_URL'] == 'https://private.company.example/photos/'
    monkeypatch.setenv('PTAI_EMPLOYEE_PHOTO_BASE_URL', 'https://environment.company.example/pictures')
    assert config.settings()['EMPLOYEE_PHOTO_BASE_URL'] == 'https://environment.company.example/pictures/'
