import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import pytest
from .conftest import ready, publish as web_publish
from .test_receiver import server
from .test_package_declaration import declaration
from .test_personal_api_usage import issue
from pt_ai_square.backend.storage import db
from pt_ai_square.backend import mongo_activity as activity

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'static/guides/pt-file-distribution/scripts'
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location('publisher', SCRIPTS/'publish_client.py')
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
finally:
    sys.path.pop(0)


def test_skill_prepare_cli_publish_and_auto_update(app, server, tmp_path):
    owner, h = ready(app)
    token, _ = issue(owner, h)
    env = {**os.environ, 'PTAI_API_TOKEN':token['token']}
    config = tmp_path/'client.json'
    config.write_text(json.dumps({'baseUrl':server}))
    source = tmp_path/'source'; source.mkdir()
    (source/'ai-square.json').write_text(json.dumps(declaration(), ensure_ascii=False), encoding='utf-8')
    for name in ['main.py','requirements.txt','INSTALL.md']:
        (source/name).write_text('Example resource', encoding='utf-8')
    artifact=tmp_path/'tool.zip'
    def package():
        r=subprocess.run([sys.executable,'-X','utf8',str(SCRIPTS/'prepare_package.py'),str(source),str(artifact)],capture_output=True,encoding='utf-8')
        assert r.returncode==0,r.stderr
    package()
    plan=tmp_path/'publish-plan.json'
    prefix=[sys.executable,str(SCRIPTS/'publish_client.py'),'--config',str(config)]
    def cli(*args):
        r=subprocess.run(prefix+list(args),env=env,capture_output=True,encoding='utf-8',timeout=30)
        assert r.returncode==0,r.stderr
        assert token['token'] not in r.stdout+r.stderr
        return json.loads(r.stdout)
    prepared=cli('prepare','--artifact',str(artifact),'--plan',str(plan),'--org-id','organization-0','--category-id','category-0')
    assert prepared['metadata']['name']=='선언한 도구' and prepared['metadata']['type']=='MCP/Tool'
    assert prepared['action']=='new_tool' and not prepared['missing']
    assert 'approval' not in prepared['metadata']
    bad=subprocess.run(prefix+['publish','--plan',str(plan)],env=env,capture_output=True,encoding='utf-8')
    assert bad.returncode==2
    r=cli('publish','--plan',str(plan),'--visibility','approval')
    assert r['version']==1 and r['approval']
    assert owner.get('/api/tools/1').json['approval']
    assert cli('publish','--plan',str(plan),'--visibility','approval')['version']==1
    member,_=ready(app,'member')
    assert member.get('/download/1/1').status_code==403
    # New output file, same package ID + saved binding => same tool, v2.
    changed=tmp_path/'tool-v2.zip'
    (source/'main.py').write_text('updated resource')
    result=subprocess.run([sys.executable,'-X','utf8',str(SCRIPTS/'prepare_package.py'),str(source),str(changed)],capture_output=True,encoding='utf-8')
    assert result.returncode==0,result.stderr
    prepared=cli('prepare','--artifact',str(changed),'--plan',str(plan))
    assert prepared['action']=='new_version' and prepared['toolId']==1 and prepared['currentApproval']
    assert cli('publish','--plan',str(plan),'--visibility','public')['version']==2
    assert cli('publish','--plan',str(plan),'--visibility','public')['version']==2
    assert member.get('/download/1/2').status_code==200
    assert owner.get('/api/local-tokens').json['usage']['uploads']==2
    with app.app_context():
        assert db().tools.count_documents({})==1
        assert len(db().tools.find_one({'_id':1})['versions'])==2
    # Without a local binding, a unique managed packageId still resolves v2.
    client=publisher.Client(server,token['token'])
    found=publisher.prepare(client,changed,{},tmp_path/'elsewhere'/'plan.json')
    assert found['toolId']==1 and found['action']=='new_version'


def test_md_preserved_and_package_candidate_lookup(app, server, tmp_path):
    owner,h=ready(app); token,_=issue(owner,h)
    client=publisher.Client(server,token['token'])
    md=tmp_path/'SKILL.md'; md.write_text('# 회의록\n정리해 주세요.',encoding='utf-8')
    fields=dict(name='회의록',desc='설명을 정리합니다.',platform='Claude',type='Skill',guide='프로젝트 또는 사용자 범위를 선택하세요.',
                orgId='organization-0',categoryId='category-0',workTags=['회의록'])
    plan=tmp_path/'plan.json'
    publisher.prepare(client,md,fields,plan)
    with pytest.raises(publisher.ClientError):
        publisher.publish(client,plan,None)
    r=publisher.publish(client,plan,'approval')
    assert owner.get('/download/1/1').data==md.read_bytes()
    assert owner.get('/api/tools/1/manifest').json['filename']=='SKILL.md'
    md.write_text('# 새 내용',encoding='utf-8')
    with pytest.raises(publisher.ClientError,match='변경'):
        publisher.publish(client,plan,'approval')
    publisher.prepare(client,md,{},plan)
    assert publisher.publish(client,plan,'approval')['version']==2
    # A different MD in the same directory must not silently replace this tool.
    other=tmp_path/'OTHER.md'; other.write_text('# another',encoding='utf-8')
    assert publisher.prepare(client,other,fields,plan)['action']=='new_tool'


def test_key_missing_opens_safe_auth_page(app, server, tmp_path, monkeypatch, capsys):
    import square_client
    config=tmp_path/'client.json'; config.write_text(json.dumps({'baseUrl':server}))
    visited=[]
    monkeypatch.setattr(square_client.webbrowser,'open',lambda url:visited.append(url) or True)
    monkeypatch.delenv('PTAI_API_TOKEN',raising=False)
    monkeypatch.delenv('PTAI_READ_TOKEN',raising=False)
    # Local SSO (unlike mock) requires a key; 401 opens our configured site's page.
    assert publisher.main(['--config',str(config),'prepare','--plan',str(tmp_path/'plan.json')])==1
    assert visited==[server+'/local-access']
    assert 'authUrl' in capsys.readouterr().err


def test_mock_publish_without_key_uses_own_csrf_session(app, server, tmp_path):
    app.config.update(AUTH_MODE='mock', MOCK_USER='owner')
    client=publisher.Client(server)
    md=tmp_path/'SKILL.md'; md.write_text('# local',encoding='utf-8')
    fields=dict(name='로컬',desc='로컬 확인',platform='Claude',type='Skill',guide='설치 범위를 선택하세요.',
                orgId='organization-0',categoryId='category-0')
    plan=tmp_path/'plan.json'
    publisher.prepare(client,md,fields,plan)
    assert publisher.publish(client,plan,'public')['version']==1


def test_update_http_never_counts_first_download(app):
    owner,h=ready(app); web_publish(owner,h)
    token,auth=issue(owner,h)
    response=app.test_client().get('/download/1/1?purpose=update',headers=auth)
    assert response.status_code==200
    assert owner.get('/api/tools/1').json['downloads']==0
    assert owner.get('/api/local-tokens').json['usage']['downloads']==0
    assert owner.get('/api/local-tokens').json['history'][0]['purpose']=='update'
    assert app.test_client().get('/download/1/1?purpose=invalid',headers=auth).status_code==400


def test_lifetime_download_update_and_legacy_rows(app, monkeypatch):
    c,h=ready(app); web_publish(c,h)
    clock=[1_800_000_000.0]
    monkeypatch.setattr(activity.time,'time',lambda:clock[0])
    with app.app_context():
        activity.record_download(1,'updater',2,update=True)
        assert activity.statistics([1],'updater',clock[0])[1]['downloads']==0
        activity.record_download(1,'member',1)
        clock[0]+=10*86400
        activity.record_download(1,'member',2)
        activity.record_download(1,'member',2,update=True)
        stats=activity.statistics([1],'member',clock[0])[1]
        assert stats['downloads']==1 and stats['recentDownloads']==0
        for i in range(2):
            db().activity_state.insert_one(dict(_id=f'legacy-{i}',tool=2,user='old',kind='download',count=2,created=clock[0]-(10-i)*86400))
        activity.record_download(2,'old',3)
        stats=activity.statistics([2],'old',clock[0])[2]
        assert stats['downloads']==1 and stats['recentDownloads']==0
        activity.flush()
        assert db().activity.count_documents({'user':'member','counted':True})==1
