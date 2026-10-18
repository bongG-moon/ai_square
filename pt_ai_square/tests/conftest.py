import io
import json
import os
import uuid
import zipfile
import pytest
from pt_ai_square import create_app
from pt_ai_square.storage import db, ensure_user

@pytest.fixture
def app(tmp_path):
    name='ptai_test_'+uuid.uuid4().hex
    app=create_app({'TESTING':True,'AUTH_MODE':'local','ADMIN_IDS':'admin','SECRET_KEY':'test-session-key','SESSION_COOKIE_SECURE':False,'DATA_DIR':str(tmp_path),'MONGODB_URI':os.environ.get('PTAI_TEST_MONGO_URI','mongodb://127.0.0.1:27018/'),'MONGODB_DATABASE':name,'MONGODB_TIMEOUT_MS':1000})
    with app.app_context():
        for uid in ['admin','owner','member','other']:ensure_user(uid,uid,'공통')
    yield app
    client=app.extensions['square_mongo_client']
    assert name.startswith('ptai_test_')
    client.drop_database(name);client.close()

def ready(app,uid='owner'):
    c=app.test_client()
    with c.session_transaction() as s:s['user_id']=uid;s['csrf']='test-csrf-'+uid
    return c,{'X-CSRF-Token':'test-csrf-'+uid}

def publish(c,h,tid=None,revision=None,**overrides):
    m=dict(name='장비 점검',desc='점검 기록을 정리합니다.',owner='담당자',org='공통',category='공통 업무',platform='Claude',type='Skill',guide='SECRET INSTALL GUIDE',environment='Python',approval=False,workTags=['점검','보고서'],changes='first',mode='file')
    m.update(overrides)
    if revision is not None:m['expectedRevision']=revision
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr('SKILL.md','# Internal skill')
    b.seek(0)
    return c.post('/api/tools'+(f'/{tid}/versions' if tid else ''),data={'metadata':json.dumps(m),'artifact':(b,'skill.zip')},headers=h)
