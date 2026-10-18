import hmac
import secrets
import time
from datetime import timedelta
from urllib.parse import urlsplit
from flask import g, request, session, jsonify, redirect, render_template, current_app
from werkzeug.security import check_password_hash
from .storage import db, ensure_user, public_user

def install_auth(app):
    app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',PERMANENT_SESSION_LIFETIME=timedelta(hours=8))

    @app.before_request
    def authenticate():
        if request.endpoint in {'static','health'}: return
        session.setdefault('csrf',secrets.token_urlsafe(32))
        mode=app.config['AUTH_MODE']
        g.user=None
        if mode=='mock':
            if request.remote_addr not in {'127.0.0.1','::1'}:
                return jsonify(error='시험 인증은 로컬 PC에서만 사용할 수 있습니다.'),403
            uid=app.config['MOCK_USER']
            if not db().users.find_one({'_id':uid}): ensure_user(uid,app.config['MOCK_NAME'])
            g.user=public_user(db().users.find_one({'_id':uid}))
        elif mode=='sso':
            try:
                # Same HCP interface as the user's reference Flask Portal.
                factory=app.config.get('SSO_FACTORY')
                if factory is None:
                    from hcputil.auth.sso import SSO
                    factory=SSO
                sso=factory(request)
                cookie=request.headers.get('Cookie','')
                if cookie and sso.check_day_cookie(cookie) is True:
                    uid,name,_,dept,_,dept_code=sso.get_sso_info(cookie)
                    uid=str(uid).strip()
                    if not uid: raise ValueError('empty identity')
                    dept=str(dept or '공통')[:80]
                    ensure_user(uid,str(name or uid)[:100],dept,org_code=str(dept_code or '')[:100] or None)
                    g.user=public_user(db().users.find_one({'_id':uid}))
                elif request.endpoint=='login':
                    target=str(getattr(sso,'redirect_url',''))
                    if urlsplit(target).scheme!='https' or not urlsplit(target).netloc:
                        return render_template('login.html',error='HCP SSO의 HTTPS 로그인 주소를 확인해 주세요.',mode=mode),503
                    return redirect(target)
            except Exception:
                return (jsonify(error='HCP SSO 인증을 확인할 수 없습니다. 운영 설정을 확인해 주세요.'),503) if request.path.startswith('/api/') else (render_template('login.html',error='HCP SSO 모듈·쿠키 검증 설정을 확인해 주세요. 다른 인증 모드로 자동 전환하지 않습니다.',mode=mode),503)
        elif session.get('user_id'):
            row=db().users.find_one({'_id':session['user_id']})
            if row: g.user=public_user(row)
        if g.user and not g.user['enabled']: g.user=None
        if request.method in {'POST','PUT','PATCH','DELETE'}:
            supplied=request.headers.get('X-CSRF-Token') or request.form.get('csrf','')
            if not hmac.compare_digest(str(session['csrf']),str(supplied)):
                return jsonify(error='화면이 오래 열려 있었거나 요청을 확인할 수 없습니다. 새로고침해 주세요.'),403
        if request.endpoint=='login': return
        if not g.user:
            if request.path.startswith('/api/') or request.path.startswith('/download/'):
                return jsonify(error='로그인이 필요합니다.',login='/login'),401
            return redirect('/login')

    @app.route('/login',methods=['GET','POST'])
    def login():
        if g.user: return redirect('/')
        if app.config['AUTH_MODE']!='local':
            return render_template('login.html',mode=app.config['AUTH_MODE'],error='회사 로그인 인증이 필요합니다.'),401
        error=''
        if request.method=='POST':
            uid=request.form.get('user_id','').strip()[:100]
            key=(request.remote_addr or '')+':'+uid
            now=time.time()
            attempt=db().login_attempts.find_one({'_id':key})
            if attempt and attempt['count']>=8 and attempt['until']>now:
                return render_template('login.html',mode='local',error='로그인 시도가 많습니다. 15분 뒤 다시 시도해 주세요.'),429
            row=db().users.find_one({'_id':uid})
            if row and row['enabled'] and row.get('password') and check_password_hash(row['password'],request.form.get('password','')):
                session.clear();session.update(user_id=uid,csrf=secrets.token_urlsafe(32));session.permanent=True
                db().login_attempts.delete_one({'_id':key})
                return redirect('/')
            count=attempt['count']+1 if attempt and attempt['until']>now else 1
            db().login_attempts.update_one({'_id':key},{'$set':{'count':count,'until':now+900}},upsert=True)
            error='아이디 또는 비밀번호를 확인해 주세요.'
        return render_template('login.html',mode='local',error=error)

    @app.post('/api/logout')
    def logout():
        session.clear()
        return jsonify(ok=True,sso=app.config['AUTH_MODE']=='sso')
