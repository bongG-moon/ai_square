"""Environment > private Python file > defaults, matching the reference Portal."""
import os
import runpy
from pathlib import Path

BASE = Path(__file__).resolve().parent

def settings():
    path = BASE / 'runtime_config.py'
    try: private = runpy.run_path(str(path)) if path.exists() else {}
    except Exception: raise ValueError('runtime_config.py의 Python 문법과 설정값을 확인하세요.') from None
    mapping=private.get('SETTINGS',{})
    if not isinstance(mapping,dict): raise ValueError('runtime_config.py의 SETTINGS는 dict 형식이어야 합니다.')
    private={**mapping,**{k:v for k,v in private.items() if k.isupper()}}
    def get(name, default=''):
        return os.environ.get('PTAI_' + name) or private.get('PTAI_' + name, default)
    mode = str(get('AUTH_MODE', 'mock')).lower()
    if mode not in {'sso', 'mock'}:
        raise ValueError('PTAI_AUTH_MODE는 sso 또는 mock만 지원합니다. local 로그인 모드는 제거되었습니다.')
    def named(name, default=''):
        return os.environ.get(name) or private.get(name, default)
    backend='mongodb'
    return dict(HOST=str(get('HOST','127.0.0.1')),PORT=int(get('PORT',5080)),ACTIVITY_BACKEND=backend,
                MONGODB_URI=str(named('MONGODB_URI','')).strip(),
                MONGODB_DATABASE=str(named('MONGODB_DATABASE','pt_ai_square')),
                ACTIVITY_COLLECTION=str(get('ACTIVITY_COLLECTION','square_activity_events')),
                MONGODB_TIMEOUT_MS=int(get('MONGODB_TIMEOUT_MS',3000)),
                AUTH_MODE=mode, DATA_DIR=str(get('DATA_DIR', BASE / 'instance')),
                SECRET_KEY=str(get('SECRET_KEY')), ADMIN_IDS=str(get('ADMIN_IDS', '')),
                SESSION_COOKIE_NAME=str(get('SESSION_COOKIE_NAME','pt_ai_square_session')),
                MOCK_USER=str(get('MOCK_USER','1000001')), MOCK_NAME=str(get('MOCK_NAME','개발 사용자')),
                MOCK_ADMIN=str(get('MOCK_ADMIN','false')).lower()=='true',
                SESSION_COOKIE_SECURE=str(get('COOKIE_SECURE','true' if mode=='sso' else 'false')).lower()=='true',
                MAX_CONTENT_LENGTH=int(get('MAX_UPLOAD_MB',128))*1024*1024,
                STORAGE_QUOTA=int(get('STORAGE_QUOTA_MB',5120))*1024*1024)
