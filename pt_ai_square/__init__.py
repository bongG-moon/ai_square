import os
import secrets
from pathlib import Path
from flask import Flask, jsonify, make_response, render_template, request, session
from werkzeug.exceptions import HTTPException
from pymongo.errors import PyMongoError
from .config import settings
from .backend.storage import init_db, db
from .backend.auth import IDENTITY_FIELDS, install_auth
from .backend.api import api
from .backend.activity import init_activity
from .backend.mongo_errors import mongo_diagnostic

def create_app(overrides=None):
    """Factory retained for isolated tests and the optional local CLI."""
    return init_app(Flask(__name__), overrides)


def init_app(app, overrides=None):
    """Attach the platform to the Flask instance exported by web_main.py.

    This function never starts a server or chooses a listening host/port.
    """
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
        from .backend.publish_drafts import publish_drafts
        app.register_blueprint(publish_drafts)
        from .backend.people import people
        app.register_blueprint(people)
        from .backend.ax_workspace import ax_workspace
        app.register_blueprint(ax_workspace)
    @app.get('/')
    def index():
        return render_template('index.html', **{key: session.get(key) for key in IDENTITY_FIELDS})
    @app.get('/publish-review/<draft_id>')
    def publish_review(draft_id):
        # Authentication and POST CSRF protection stay in the normal SSO/session
        # boundary. Personal KEY callers cannot access this browser-only page.
        response=make_response(render_template('publish_review.html', draft_id=draft_id,
                                              csrf=session.get('csrf','')))
        response.headers['Cache-Control']='no-store'
        return response
    @app.get('/health')
    def health():
        if app.config['DATA_MODE']=='mongodb': db().command('ping')
        return jsonify(status='ok',service='P&T AI SQUARE',storage=app.config['DATA_MODE'],version='3.3')
    @app.errorhandler(HTTPException)
    def http_error(error): return jsonify(error=error.description),error.code
    @app.errorhandler(PyMongoError)
    def mongo_error(error):
        diagnostic=mongo_diagnostic(error)
        diagnostic['reference']=secrets.token_hex(6)
        # Log only allowlisted categories, a numeric code and our reference.
        # Exception text/tracebacks may contain DB addresses or document data.
        method=request.method if request.method in {'GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'} else 'OTHER'
        route=request.url_rule.rule if request.url_rule else '<unmatched>'
        app.logger.error('MongoDB request failed diagnostic=%s mongo_code=%s reference=%s method=%s route=%s retry_writes=%s',
                         diagnostic['code'], diagnostic['mongo_code'], diagnostic['reference'],
                         method, route, app.config.get('MONGODB_RETRY_WRITES',False))
        code_label='진단 코드: '+diagnostic['code']
        if diagnostic['mongo_code'] is not None:
            code_label+=' · MongoDB 코드: '+str(diagnostic['mongo_code'])
        code_label+=' · 문의 번호: '+diagnostic['reference']
        guidance='등록·수정·삭제 중이었다면 목록에서 반영 여부를 먼저 확인한 뒤 다시 시도해 주세요.'
        message=diagnostic['message']+' '+guidance+' ['+code_label+']'
        # API clients and /health always retain the JSON error contract.
        wants_html=(request.endpoint!='health' and not request.path.startswith('/api/')
                    and not request.is_json and request.accept_mimetypes.best_match(
                        ['application/json','text/html'])=='text/html')
        if wants_html:
            response=make_response(render_template('database_error.html',
                                   diagnostic=diagnostic, guidance=guidance),503)
        else:
            response=make_response(jsonify(error=message,diagnostic=diagnostic),503)
        response.headers['Cache-Control']='no-store'
        return response
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
