import hmac
import secrets
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit, quote, unquote
from flask import g, request, session, jsonify, redirect, render_template, url_for
from .storage import db, ensure_user, public_user

IDENTITY_FIELDS=('emp_no','emp_name','emp_name_en','dept','email','dept_cd')

def clear_identity():
    for key in (*IDENTITY_FIELDS,'logFlag'):session.pop(key,None)

def store_identity(values):
    # These session fields match the HCP sample, but are not a replacement for
    # checking the current SSO cookie and current database permissions.
    if session.get('emp_no') and session['emp_no']!=values[0]:
        session.clear();session['csrf']=secrets.token_urlsafe(32)
    session.update(dict(zip(IDENTITY_FIELDS,values)))
    session['logFlag']=True
    session.permanent=True

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
        if request.endpoint=='login' and not valid_origin(request.args.get('ORIGIN','')):
            return jsonify(error='로그인 후 이동할 주소는 이 서비스의 주소여야 합니다.'),400
        if mode=='mock':
            if request.remote_addr not in {'127.0.0.1','::1'}:
                return jsonify(error='시험 인증은 로컬 PC에서만 사용할 수 있습니다.'),403
            uid=app.config['MOCK_USER']
            if not db().users.find_one({'_id':uid}): ensure_user(uid,app.config['MOCK_NAME'])
            g.user=public_user(db().users.find_one({'_id':uid}))
            identity=(uid,g.user['name'],'',g.user['org'],'','')
        elif mode=='sso':
            try:
                # Same HCP interface as the user's reference Flask Portal.
                factory=app.config.get('SSO_FACTORY')
                if factory is None:
                    from hcputil.auth.sso import SSO
                    factory=SSO
                sso=factory(request);g.sso=sso
                cookie=request.headers.get('Cookie','')
                if cookie and sso.check_day_cookie(cookie) is True:
                    uid,name,name_en,dept,email,dept_code=sso.get_sso_info(cookie)
                    uid=str(uid).strip()
                    if not uid: raise ValueError('empty identity')
                    dept=str(dept or '공통')[:80]
                    ensure_user(uid,str(name or uid)[:100],dept,org_code=str(dept_code or '')[:100] or None)
                    g.user=public_user(db().users.find_one({'_id':uid}))
                    identity=(uid,str(name or uid)[:100],str(name_en or '')[:100],dept,str(email or '')[:254],str(dept_code or '')[:100])
            except Exception:
                clear_identity()
                return (jsonify(error='HCP SSO 인증을 확인할 수 없습니다. 운영 설정을 확인해 주세요.'),503) if request.path.startswith('/api/') else (render_template('login.html',error='HCP SSO 모듈·쿠키 검증 설정을 확인해 주세요. 다른 인증 모드로 자동 전환하지 않습니다.',mode=mode),503)
        if g.user and not g.user['enabled']:
            g.sso_disabled=True
            g.user=None
        if g.user:store_identity(identity)
        else:clear_identity()
        if request.method in {'POST','PUT','PATCH','DELETE'}:
            supplied=request.headers.get('X-CSRF-Token') or request.form.get('csrf','')
            if not hmac.compare_digest(str(session['csrf']),str(supplied)):
                return jsonify(error='화면이 오래 열려 있었거나 요청을 확인할 수 없습니다. 새로고침해 주세요.'),403
        if request.endpoint=='login': return
        if not g.user:
            if request.path.startswith('/api/') or request.path.startswith('/download/'):
                return jsonify(error='로그인이 필요합니다.',login=url_for('login',ORIGIN=url_for('index',_external=True))),401
            return redirect(url_for('login',ORIGIN=request.url))

    @app.get('/login')
    @app.get('/login/<path:sub_path>')
    def login(sub_path=None):
        if app.config['AUTH_MODE']=='sso':
            if getattr(g,'sso_disabled',False):
                return render_template('login.html',mode='sso',error='비활성 사용자입니다. 관리자에게 확인해 주세요.'),403
            # The HCP SDK consumes the original Flask request (including ORIGIN)
            # and provides the redirect URL, just as in the deployment sample.
            target=str(getattr(g.sso,'redirect_url',''))
            try:parts=urlsplit(target)
            except ValueError:parts=None
            if not parts or parts.scheme!='https' or not parts.netloc or parts.username or parts.password:
                return render_template('login.html',error='HCP SSO의 HTTPS 로그인 주소를 확인해 주세요.',mode='sso'),503
            if sub_path:
                if '\\' in sub_path or any(part in {'.','..'} for part in sub_path.split('/')):
                    return jsonify(error='로그인 경로를 확인해 주세요.'),400
                target=urlunsplit((parts.scheme,parts.netloc,parts.path.rstrip('/')+'/'+quote(sub_path,safe='/'),parts.query,parts.fragment))
            return redirect(target)
        if g.user:return redirect(url_for('index'))
        error='설정한 시험 사번이 비활성 상태입니다. 관리자에게 확인해 주세요.' if app.config['AUTH_MODE']=='mock' else '회사 로그인 인증이 필요합니다.'
        return render_template('login.html',mode=app.config['AUTH_MODE'],error=error),401

    @app.post('/api/logout')
    def logout():
        session.clear()
        return jsonify(ok=True,sso=app.config['AUTH_MODE']=='sso')
