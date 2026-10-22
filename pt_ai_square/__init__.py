import os
import secrets
from pathlib import Path
from flask import Flask, jsonify, render_template
from werkzeug.exceptions import HTTPException
from pymongo.errors import PyMongoError
from .config import settings
from .backend.storage import init_db, db
from .backend.auth import install_auth
from .backend.api import api
from .backend.activity import init_activity

def create_app(overrides=None):
    app=Flask(__name__)
    app.config['TEMPLATES_AUTO_RELOAD']=True
    app.config.update(settings())
    if overrides: app.config.update(overrides)
    if app.config['AUTH_MODE'] not in {'sso','mock'}:
        raise ValueError('PTAI_AUTH_MODE는 sso 또는 mock만 지원합니다.')
    app.config['MOCK_USER']=str(app.config['MOCK_USER']).strip()
    if app.config['AUTH_MODE']=='mock' and (not app.config['MOCK_USER'] or len(app.config['MOCK_USER'])>100):
        raise ValueError('PTAI_MOCK_USER에 시험할 사번을 문자열로 입력하세요.')
    if app.config['DATA_MODE'] not in {'mongodb','dummy'}:
        raise ValueError('PTAI_DATA_MODE는 mongodb 또는 dummy만 지원합니다.')
    if app.config['DATA_MODE']=='dummy':
        if app.config['AUTH_MODE']!='mock':
            raise ValueError('dummy는 로컬 화면 확인용입니다. PTAI_AUTH_MODE를 mock으로 설정하세요. 회사 SSO에서는 mongodb를 사용하세요.')
        from .backend.dummy_api import install_dummy
        install_dummy(app)
    else:
        if not app.config['MONGODB_URI'].strip() or not app.config['MONGODB_DATABASE'].strip():
            raise ValueError('runtime_config.py에 MONGODB_URI와 MONGODB_DATABASE를 입력하세요. 로컬에서도 같은 MongoDB 저장 기능을 사용합니다.')
        data=Path(app.config['DATA_DIR']).resolve();data.mkdir(parents=True,exist_ok=True)
        (data/'artifacts').mkdir(exist_ok=True)
        app.config['DATA_DIR']=str(data)
        init_db(app);init_activity(app)
        @app.before_request
        def migration_guard():
            if db().migrations.find_one({'state':'running'}, {'_id':1}):
                return jsonify(error='데이터 이전 중입니다. 이전 작업을 완료한 후 다시 접속해 주세요.'),503
        install_auth(app);app.register_blueprint(api)
        from .backend.local_access import local_access
        app.register_blueprint(local_access)
        from .backend.people import people
        app.register_blueprint(people)
    @app.get('/')
    def index(): return render_template('index.html')
    @app.get('/health')
    def health():
        if app.config['DATA_MODE']=='mongodb': db().command('ping')
        return jsonify(status='ok',service='P&T AI SQUARE',storage=app.config['DATA_MODE'],version='3.3')
    @app.errorhandler(HTTPException)
    def http_error(error): return jsonify(error=error.description),error.code
    @app.errorhandler(PyMongoError)
    def mongo_error(error):
        app.logger.error('MongoDB unavailable: %s', type(error).__name__)
        return jsonify(error='MongoDB 연결을 확인할 수 없습니다. 저장 결과를 확인한 후 다시 시도해 주세요.'),503
    @app.errorhandler(Exception)
    def unexpected(error):
        app.logger.exception('Request failed')
        return jsonify(error='요청을 처리하지 못했습니다. 다시 시도하거나 운영자에게 알려주세요.'),500
    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        if response.mimetype=='application/json': response.headers['Cache-Control']='no-store'
        return response
    return app
