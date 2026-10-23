import hmac
import secrets
import time
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit, quote, unquote
from flask import g, request, session, jsonify, redirect, render_template, url_for
from .storage import db, ensure_user, public_user

IDENTITY_FIELDS=('emp_no','emp_name','emp_name_en','dept','email','dept_cd')
SSO_SESSION_KEY='_hcp_login'

def clear_identity():
    for key in (*IDENTITY_FIELDS,'logFlag',SSO_SESSION_KEY):session.pop(key,None)

def store_identity(values):
    # Identity is issued by the login SDK or local mock, never by request input.
    # Authorization still comes from the current database record on each request.
    if session.get('emp_no') and session['emp_no']!=values[0]:
        session.clear();session['csrf']=secrets.token_urlsafe(32)
    session.update(dict(zip(IDENTITY_FIELDS,values)))
    session['logFlag']=True
    session.permanent=True


def valid_sso_session(app):
    """Only accept a signed, bounded session issued by a successful HCP login."""
    login=session.get(SSO_SESSION_KEY)
    if not isinstance(login,dict) or session.get('logFlag') is not True:return False
    if not all(isinstance(session.get(key),str) for key in IDENTITY_FIELDS):return False
    if not session['emp_no'] or login.get('employee')!=session['emp_no']:return False
    issued=login.get('at')
    if isinstance(issued,bool) or not isinstance(issued,(int,float)):return False
    # Flask refreshes its cookie during activity; this timestamp does not move.
    return 0 <= time.time()-issued < app.permanent_session_lifetime.total_seconds()


def login_target(target,sub_path):
    if not sub_path:return target
    if '\\' in sub_path or any(part in {'.','..'} for part in sub_path.split('/')):
        return None
    parts=urlsplit(target)
    return urlunsplit((parts.scheme,parts.netloc,parts.path.rstrip('/')+'/'+quote(sub_path,safe='/'),parts.query,parts.fragment))


def sdk_redirect_error(target):
    """Validate SDK output without imposing a deployment scheme or port.

    This is not the policy for user-supplied ORIGIN, which stays same-origin.
    HCP deployments may return HTTP, HTTPS or a root-relative application path.
    """
    if not isinstance(target,str) or not target:return 'missing_url'
    if target!=target.strip() or any(ord(c)<32 or ord(c)==127 for c in target):return 'invalid_whitespace'
    if '\\' in target:return 'backslash'
    if target.startswith('//'):return 'network_path'
    try:
        parts=urlsplit(target)
        if parts.username is not None or parts.password is not None:return 'userinfo'
        if parts.scheme:
            if parts.scheme not in {'http','https'}:return 'unsupported_scheme'
            if not parts.hostname or any(c.isspace() for c in parts.netloc):return 'missing_host'
            parts.port  # Validate an explicit port without changing it.
        elif parts.netloc or not target.startswith('/'):
            return 'invalid_relative_path'
    except ValueError:
        return 'malformed_url'
    return None


def valid_origin(value):
    if not value:return True
    decoded=unquote(value)
    if any(ord(c)<32 for c in decoded) or '\\' in decoded:return False
    try:parts=urlsplit(decoded)
    except ValueError:return False
    if parts.scheme or parts.netloc:
        return parts.scheme==request.scheme and parts.netloc.casefold()==request.host.casefold() and not parts.username and not parts.password
    return decoded.startswith('/') and not decoded.startswith('//')

def install_auth(app):
    app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',PERMANENT_SESSION_LIFETIME=timedelta(hours=8))

    @app.before_request
    def authenticate():
        if request.endpoint in {'static','health'}: return
        session.setdefault('csrf',secrets.token_urlsafe(32))
        mode=app.config['AUTH_MODE']
        g.user=None
        identity=None
        if request.headers.get('Authorization'):
            # Mock remains loopback-only, including personal tokens.
            if mode=='mock' and request.remote_addr not in {'127.0.0.1','::1'}:
                return jsonify(error='시험 인증은 로컬 PC에서만 사용할 수 있습니다.'),403
            from .local_access import token_user
            g.user=token_user()
            return
        if request.endpoint=='login' and not valid_origin(request.args.get('ORIGIN','')):
            return jsonify(error='로그인 후 이동할 주소는 이 서비스의 주소여야 합니다.'),400
        if mode=='mock':
            session.pop(SSO_SESSION_KEY,None)
            if request.remote_addr not in {'127.0.0.1','::1'}:
                return jsonify(error='시험 인증은 로컬 PC에서만 사용할 수 있습니다.'),403
            uid=app.config['MOCK_USER']
            if not db().users.find_one({'_id':uid}): ensure_user(uid,app.config['MOCK_NAME'])
            g.user=public_user(db().users.find_one({'_id':uid}))
            identity=(uid,g.user['name'],'',g.user['org'],'',g.user.get('dept_cd',''))
        elif mode=='sso':
            # The company SDK belongs to /login. Refresh, downloads and writes
            # use the signed login session, not another SDK call on an API URL.
            if valid_sso_session(app):
                user=db().users.find_one({'_id':session['emp_no']})
                if user:g.user=public_user(user)
        if g.user and not g.user['enabled']:
            g.sso_disabled=True
            g.user=None
        if g.user and identity:store_identity(identity)
        elif not g.user:clear_identity()
        if request.endpoint=='login': return
        if not g.user:
            if request.path.startswith('/api/') or request.path.startswith('/download/'):
                return jsonify(error='로그인이 필요합니다.',login=url_for('login',ORIGIN=url_for('index',_external=True))),401
            return redirect(url_for('login',ORIGIN=request.url))
        if request.method in {'POST','PUT','PATCH','DELETE'}:
            supplied=request.headers.get('X-CSRF-Token') or request.form.get('csrf','')
            if not hmac.compare_digest(str(session['csrf']),str(supplied)):
                return jsonify(error='화면이 오래 열려 있었거나 요청을 확인할 수 없습니다. 새로고침해 주세요.'),403

    @app.get('/login')
    @app.get('/login/<path:sub_path>')
    def login(sub_path=None):
        if app.config['AUTH_MODE']=='sso':
            if getattr(g,'sso_disabled',False):
                return render_template('login.html',mode='sso',error='비활성 사용자입니다. 관리자에게 확인해 주세요.'),403
            if g.user:
                target=login_target(request.args.get('ORIGIN') or url_for('index'),sub_path)
                if target is None:return jsonify(error='로그인 경로를 확인해 주세요.'),400
                return redirect(target)
            stage='import'
            identity=None
            try:
                factory=app.config.get('SSO_FACTORY')
                if factory is None:
                    from hcputil.auth.sso import SSO
                    factory=SSO
                stage='initialize'
                sso=factory(request)
                stage='redirect_url'
                target=sso.redirect_url
                cookie=request.headers.get('Cookie','')
                stage='check_day_cookie'
                if cookie and sso.check_day_cookie(cookie) is True:
                    stage='get_sso_info'
                    uid,name,name_en,dept,email,dept_code=sso.get_sso_info(cookie)
                    stage='identity'
                    uid=str(uid or '').strip()
                    if not uid or len(uid)>100:raise ValueError('invalid identity')
                    identity=(uid,str(name or uid)[:100],str(name_en or '')[:100],str(dept or '공통')[:80],str(email or '')[:254],str(dept_code or '')[:100])
            except Exception as error:
                clear_identity()
                # Do not log exception messages/tracebacks: SDK errors may embed
                # cookies, tokens, addresses or personal information.
                app.logger.error('HCP SSO failure stage=%s error=%s',stage,type(error).__name__)
                return render_template('login.html',error='HCP SSO 모듈·쿠키 검증 설정을 확인해 주세요. 다른 인증 모드로 자동 전환하지 않습니다.',mode='sso'),503
            reason=sdk_redirect_error(target)
            if reason:
                app.logger.error('HCP SSO failure stage=redirect_url reason=%s',reason)
                return render_template('login.html',error='HCP SSO가 반환한 로그인 이동 주소 형식을 확인해 주세요.',mode='sso'),503
            target=login_target(target,sub_path)
            if target is None:return jsonify(error='로그인 경로를 확인해 주세요.'),400
            if identity:
                # Database failures are deliberately outside the SDK catch so
                # the shared MongoDB handler reports the actual storage failure.
                uid,name,_,dept,_,dept_code=identity
                ensure_user(uid,name,dept,org_code=dept_code or None)
                g.user=public_user(db().users.find_one({'_id':uid}))
                if not g.user['enabled']:
                    clear_identity()
                    return render_template('login.html',mode='sso',error='비활성 사용자입니다. 관리자에게 확인해 주세요.'),403
                store_identity(identity)
                session['csrf']=secrets.token_urlsafe(32)
                session[SSO_SESSION_KEY]={'employee':uid,'at':time.time()}
            return redirect(target)
        if g.user:return redirect(url_for('index'))
        error='설정한 시험 사번이 비활성 상태입니다. 관리자에게 확인해 주세요.' if app.config['AUTH_MODE']=='mock' else '회사 로그인 인증이 필요합니다.'
        return render_template('login.html',mode=app.config['AUTH_MODE'],error=error),401

    @app.post('/api/logout')
    def logout():
        session.clear()
        return jsonify(ok=True,sso=app.config['AUTH_MODE']=='sso')
