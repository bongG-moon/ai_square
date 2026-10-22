import json
import sqlite3
from pathlib import Path
from pt_ai_square import create_app
from pt_ai_square.backend.storage import db
from pt_ai_square.backend.migrate_legacy import migrate
from .conftest import ready

def test_readonly_legacy_migration_preserves_ids_and_retry(app,tmp_path):
    source=tmp_path/'old.sqlite3';con=sqlite3.connect(source)
    con.executescript('CREATE TABLE users(id TEXT,name TEXT,org TEXT,role TEXT,password TEXT,enabled INTEGER);CREATE TABLE tools(id INTEGER,owner TEXT,data TEXT,created REAL,active INTEGER,fallback INTEGER,revision INTEGER,hidden INTEGER,paused INTEGER);CREATE TABLE versions(tool INTEGER,n INTEGER,path TEXT,name TEXT,size INTEGER,sha TEXT,url TEXT,note TEXT,created REAL,withdrawn INTEGER,deleted INTEGER,data TEXT);CREATE TABLE requests(id INTEGER,tool INTEGER,user TEXT,reason TEXT,status TEXT,decision TEXT);')
    con.execute('INSERT INTO users VALUES (?,?,?,?,?,?)',('legacy','이전 사용자','공통','member',None,1))
    data=dict(name='이전 도구',desc='설명',org='공통',category='공통 업무',platform='Claude',type='Skill',owner='담당자',guide='guide',environment='',changes='',approval=True,visibility='전체 공개',audience=[],workTags=[])
    con.execute('INSERT INTO tools VALUES (?,?,?,?,?,?,?,?,?)',(41,'owner',json.dumps(data),100,3,2,9,0,0))
    con.execute('INSERT INTO versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(41,3,None,'',0,'','https://example.com','v3',100,0,0,json.dumps({'guide':'guide','environment':'','platform':'Claude','type':'Skill'})))
    con.execute('INSERT INTO requests VALUES (?,?,?,?,?,?)',(7,41,'legacy','필요','승인','확인'));con.commit();con.close()
    original=source.read_bytes()
    with app.app_context():
        first=migrate(source);second=migrate(source);assert first==second
        assert db().tools.find_one({'_id':41})['revision']==9
        assert db().access.find_one({'tool':41,'user':'legacy'})['granted']
        assert db().counters.find_one({'_id':'tools'})['value']==41
    assert original==source.read_bytes()
    c,_=ready(app,'legacy');assert c.get('/api/tools/41').status_code==200

def test_sso_mapping_and_fail_closed(app):
    class SSO:
        def __init__(self,request):pass
        def check_day_cookie(self,cookie):return True
        def get_sso_info(self,cookie):return ('employee','직원','','장비팀','','D100')
    app.config.update(AUTH_MODE='sso',SSO_FACTORY=SSO)
    c=app.test_client();c.set_cookie('company','test')
    first=c.get('/api/bootstrap');assert first.status_code==200
    org_id=first.json['user']['orgId']
    with app.app_context():db().taxonomy.update_one({'_id':org_id},{'$set':{'name':'장비기술팀'}})
    second=c.get('/api/bootstrap');assert second.json['user']['org']=='장비기술팀'
    assert second.json['user']['dept']=='장비팀'
    assert second.json['user']['dept_cd']=='D100'
    class Broken(SSO):
        def get_sso_info(self,cookie):raise RuntimeError('failure')
    app.config['SSO_FACTORY']=Broken
    assert c.get('/api/bootstrap').status_code==503

def test_python_config_and_native_env_priority(monkeypatch,tmp_path):
    from pt_ai_square import config
    monkeypatch.setattr(config,'BASE',tmp_path)
    (tmp_path/'runtime_config.py').write_text("SETTINGS={'MONGODB_DATABASE':'from_mapping'}\nPTAI_AUTH_MODE='sso'\nMONGODB_URI='mongodb://localhost:27018/'\nPTAI_ADMIN_IDS='a,b'\n",encoding='utf-8')
    monkeypatch.delenv('MONGODB_DATABASE',raising=False)
    assert config.settings()['MONGODB_DATABASE']=='from_mapping'
    monkeypatch.setenv('MONGODB_DATABASE','native_environment')
    assert config.settings()['MONGODB_DATABASE']=='native_environment'
    assert config.settings()['ADMIN_IDS']=='a,b'
    assert config.settings()['ACTIVITY_BACKEND']=='mongodb'
