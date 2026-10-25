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
from .test_package_declaration import declaration, bundle
from .test_personal_api_usage import issue
from .test_workflow import flow
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


@pytest.fixture(autouse=True)
def no_real_browser(monkeypatch):
    # Library paths still exercise review URL generation without opening a
    # real browser. The subprocess CLI below uses the same explicit stub.
    monkeypatch.setattr(publisher.webbrowser, 'open', lambda url: False)


CLI_BOOTSTRAP = (
    "import runpy,sys,webbrowser; from pathlib import Path; "
    "webbrowser.open=lambda url:False; "
    "script=sys.argv.pop(1); sys.path.insert(0,str(Path(script).parent)); "
    "sys.argv[0]=script; runpy.run_path(script,run_name='__main__')"
)


def approve_pending(owner, headers, pending, approval):
    assert pending['status'] == 'approval_required'
    assert pending['browserOpened'] is False
    draft_id = pending['draftId']
    current = owner.get('/api/publish-drafts/' + draft_id)
    assert current.status_code == 200 and current.json['status'] == 'pending'
    response = owner.post('/api/publish-drafts/' + draft_id + '/approve', headers=headers,
                          json={'approval': approval, 'reviewDigest': current.json['reviewDigest']})
    assert response.status_code == 200, response.json
    assert response.json['status'] == 'approved'
    return draft_id


def reviewed_publish(client, plan, visibility, owner, headers):
    pending = publisher.publish(client, plan, visibility)
    draft_id = approve_pending(owner, headers, pending, visibility == 'approval')
    result = publisher.publish(client, plan, visibility)
    assert owner.get('/api/publish-drafts/' + draft_id).json['status'] == 'committed'
    return result


def test_skill_prepare_cli_publish_and_auto_update(app, server, tmp_path):
    owner, h = ready(app)
    token, _ = issue(owner, h)
    env = {**os.environ, 'PTAI_API_TOKEN':token['token']}
    config = tmp_path/'client.json'
    config.write_text(json.dumps({'baseUrl':server}))
    source = tmp_path/'source'; source.mkdir()
    (source/'ai-square.json').write_text(json.dumps(declaration(workflow=flow()), ensure_ascii=False), encoding='utf-8')
    for name in ['main.py','requirements.txt','INSTALL.md']:
        (source/name).write_text('Example resource', encoding='utf-8')
    artifact=tmp_path/'tool.zip'
    def package():
        r=subprocess.run([sys.executable,'-X','utf8',str(SCRIPTS/'prepare_package.py'),str(source),str(artifact)],capture_output=True,encoding='utf-8')
        assert r.returncode==0,r.stderr
    package()
    plan=tmp_path/'publish-plan.json'
    prefix=[sys.executable,'-X','utf8','-c',CLI_BOOTSTRAP,str(SCRIPTS/'publish_client.py'),'--config',str(config)]
    def cli(*args):
        r=subprocess.run(prefix+list(args),env=env,capture_output=True,encoding='utf-8',timeout=30)
        assert r.returncode==0,r.stderr
        assert token['token'] not in r.stdout+r.stderr
        return json.loads(r.stdout)
    prepared=cli('prepare','--artifact',str(artifact),'--plan',str(plan),'--org-id','organization-0','--category-id','category-0')
    assert prepared['metadata']['name']=='선언한 도구' and prepared['metadata']['type']=='MCP/Tool'
    assert prepared['metadata']['workflow'] == flow()
    assert prepared['action']=='new_tool' and not prepared['missing']
    assert 'approval' not in prepared['metadata']
    bad=subprocess.run(prefix+['publish','--plan',str(plan)],env=env,capture_output=True,encoding='utf-8')
    assert bad.returncode==2
    pending=cli('publish','--plan',str(plan),'--visibility','approval')
    assert pending['status']=='approval_required'
    assert cli('publish','--plan',str(plan),'--visibility','approval')['draftId']==pending['draftId']
    with app.app_context():
        assert db().tools.count_documents({})==0
        assert db().publish_drafts.count_documents({})==1
    draft_id=approve_pending(owner,h,pending,True)
    r=cli('publish','--plan',str(plan),'--visibility','approval')
    assert r['version']==1 and r['approval']
    assert owner.get('/api/publish-drafts/'+draft_id).json['status']=='committed'
    assert owner.get('/api/tools/1').json['approval']
    assert cli('publish','--plan',str(plan),'--visibility','approval')['version']==1
    member,_=ready(app,'member')
    assert member.get('/download/1/1').status_code==403
    # New output file: an ID match is a candidate, not a silent update decision.
    changed=tmp_path/'tool-v2.zip'
    (source/'main.py').write_text('updated resource')
    # A newly inspected ZIP without a flow must override the prior release.
    (source/'ai-square.json').write_text(json.dumps(declaration(), ensure_ascii=False), encoding='utf-8')
    result=subprocess.run([sys.executable,'-X','utf8',str(SCRIPTS/'prepare_package.py'),str(source),str(changed)],capture_output=True,encoding='utf-8')
    assert result.returncode==0,result.stderr
    prepared=cli('prepare','--artifact',str(changed),'--plan',str(plan))
    assert prepared['action']=='choose_target' and prepared['candidates'][0]['id']==1
    prepared=cli('prepare','--artifact',str(changed),'--plan',str(plan),'--tool','1')
    assert prepared['action']=='new_version' and prepared['toolId']==1 and prepared['currentApproval']
    assert prepared['metadata']['workflow'] is None
    pending=cli('publish','--plan',str(plan),'--visibility','public')
    assert owner.get('/api/tools/1').json['active']==1
    draft_id=approve_pending(owner,h,pending,False)
    assert cli('publish','--plan',str(plan),'--visibility','public')['version']==2
    assert owner.get('/api/publish-drafts/'+draft_id).json['status']=='committed'
    assert cli('publish','--plan',str(plan),'--visibility','public')['version']==2
    assert member.get('/download/1/2').status_code==200
    assert owner.get('/api/tools/1/manifest').json['workflow'] is None
    assert owner.get('/api/local-tokens').json['usage']['uploads']==2
    with app.app_context():
        assert db().tools.count_documents({})==1
        assert len(db().tools.find_one({'_id':1})['versions'])==2
    # Even a unique ID candidate without a binding needs the user's selection.
    client=publisher.Client(server,token['token'])
    found=publisher.prepare(client,changed,{},tmp_path/'elsewhere'/'plan.json')
    assert found['toolId'] is None and found['action']=='choose_target'
    assert found['candidates'][0]['id']==1
    # Preview and final publication must agree: a stale manual draft cannot
    # override the inspected ZIP's release-specific workflow.
    found=publisher.prepare(client,changed,{'workflow':flow('이전 초안')},tmp_path/'elsewhere'/'plan.json',tool_id=1)
    assert found['metadata']['workflow'] is None


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
    r=reviewed_publish(client,plan,'approval',owner,h)
    assert r['version']==1 and r['approval']
    assert owner.get('/download/1/1').data==md.read_bytes()
    assert owner.get('/api/tools/1/manifest').json['filename']=='SKILL.md'
    md.write_text('# 새 내용',encoding='utf-8')
    with pytest.raises(publisher.ClientError,match='변경'):
        publisher.publish(client,plan,'approval')
    assert publisher.prepare(client,md,{},plan)['action']=='choose_target'
    publisher.prepare(client,md,{},plan,tool_id=1)
    assert reviewed_publish(client,plan,'approval',owner,h)['version']==2
    # A different MD in the same directory must not silently replace this tool.
    other=tmp_path/'OTHER.md'; other.write_text('# another',encoding='utf-8')
    other_preview=publisher.prepare(client,other,fields,plan)
    assert other_preview['action']=='choose_target'
    assert all(row['reason']=='name' for row in other_preview['candidates'])
    assert publisher.prepare(client,other,fields,plan,new=True)['action']=='new_tool'


@pytest.mark.parametrize('change,expected', [
    ({}, flow()),
    ({'workflow': flow('새 자료 입력')}, flow('새 자료 입력')),
    ({'workflow': None}, None),
])
def test_manual_release_workflow_preserved_replaced_or_removed(app, server, tmp_path, change, expected):
    owner, h = ready(app); token, _ = issue(owner, h)
    client = publisher.Client(server, token['token'])
    md = tmp_path/'SKILL.md'; md.write_text('# 회의록 정리', encoding='utf-8')
    fields = dict(name='회의록', desc='회의 자료를 정리합니다.', platform='Claude', type='Skill',
                  guide='설치 범위를 선택하세요.', orgId='organization-0', categoryId='category-0',
                  workflow=flow())
    plan = tmp_path/'plan.json'
    publisher.prepare(client, md, fields, plan)
    assert reviewed_publish(client, plan, 'public', owner, h)['version'] == 1
    md.write_text('# 회의록 정리\n업데이트', encoding='utf-8')
    prepared = publisher.prepare(client, md, change, plan, tool_id=1)
    assert prepared['action'] == 'new_version' and prepared['metadata']['workflow'] == expected
    assert reviewed_publish(client, plan, 'public', owner, h)['version'] == 2
    current = owner.get('/api/tools/1').json
    assert current['workflow'] == expected
    assert current['versions'][0]['workflow'] == expected
    assert current['versions'][1]['workflow'] == flow()
    assert owner.get('/api/tools/1/manifest').json['workflow'] == expected
    assert owner.get('/download/1/2').data == md.read_bytes()
    assert owner.post('/api/tools/1/rollback', headers=h,
                      json={'version': 1, 'expectedRevision': 2}).status_code == 200
    assert owner.get('/api/tools/1/manifest').json['workflow'] == flow()


def test_changed_zip_identity_updates_explicit_tool_and_preserves_original_bytes(app, server, tmp_path):
    owner, headers = ready(app)
    token, _ = issue(owner, headers)
    client = publisher.Client(server, token['token'])
    artifact = tmp_path/'release.zip'
    original = bundle()
    artifact.write_bytes(original)
    plan = tmp_path/'plan.json'
    fields = dict(orgId='organization-0', categoryId='category-0')
    publisher.prepare(client, artifact, fields, plan, new=True)
    first = reviewed_publish(client, plan, 'public', owner, headers)
    assert first['packageId'] == first['sourcePackageId'] == 'sample-tool'
    changed = declaration()
    changed.update(packageId='new-project-build', entryPoint='requirements.txt', changes='완전히 새 파일 구성')
    second_bytes = bundle(changed)
    artifact.write_bytes(second_bytes)
    preview = publisher.prepare(client, artifact, {}, plan)
    assert preview['action'] == 'choose_target'
    assert preview['candidates'][0]['id'] == first['id']
    assert preview['candidates'][0]['reason'] == 'same_source_path'
    with pytest.raises(publisher.ClientError, match='--tool'):
        publisher.publish(client, plan, 'public')
    preview = publisher.prepare(client, artifact, {}, plan, tool_id=first['id'])
    assert preview['packageId'] == 'sample-tool'
    assert preview['sourcePackageId'] == 'new-project-build' and preview['packageIdentityChanged']
    second = reviewed_publish(client, plan, 'public', owner, headers)
    assert second['id'] == first['id'] and second['version'] == 2
    assert second['packageId'] == 'sample-tool' and second['sourcePackageId'] == 'new-project-build'
    assert owner.get(f'/download/{first["id"]}/1').data == original
    assert owner.get(f'/download/{first["id"]}/2').data == second_bytes == artifact.read_bytes()
    current = owner.get(f'/api/tools/{first["id"]}').json
    assert current['packageId'] == 'sample-tool'
    assert current['versions'][0]['package']['packageId'] == 'new-project-build'
    assert current['versions'][0]['package']['entryPoint'] == 'requirements.txt'
    state = publisher.read_json(plan.parent/'.ai-square-publish-state.json')
    assert state['toolId'] == first['id'] and state['packageId'] == 'sample-tool'
    assert state['sourcePackageId'] == 'new-project-build'
    # A changed declaration is not a new automatic alias for this tool.
    assert client.get('/api/publish-targets?packageId=new-project-build')['items'] == []
    assert client.get('/api/publish-targets?packageId=sample-tool')['items'][0]['id'] == first['id']
    # A different output file can still update the selected tool explicitly.
    other = tmp_path/'different-build.zip'
    other.write_bytes(second_bytes)
    preview = publisher.prepare(client, other, {}, plan)
    assert preview['action'] == 'choose_target' and preview['toolId'] is None
    assert preview['candidates'][0]['id'] == first['id'] and preview['candidates'][0]['reason'] == 'name'
    preview = publisher.prepare(client, other, {}, plan, tool_id=first['id'])
    assert preview['toolId'] == first['id'] and preview['action'] == 'new_version'
    assert not preview['requiresTargetSelection']
    unrelated = declaration()
    unrelated.update(packageId='unrelated-build', name='완전히 다른 도구')
    other.write_bytes(bundle(unrelated))
    preview = publisher.prepare(client, other, {}, plan)
    assert preview['action'] == 'new_tool' and not preview['candidates']


@pytest.mark.parametrize('source_url', ['http://mcp.example.internal:8080/mcp', 'https://api.example.test/v1/tools'])
def test_url_publish_client_keeps_source_link_without_creating_a_package(app, server, tmp_path, monkeypatch, source_url):
    owner, headers = ready(app)
    token, _ = issue(owner, headers)
    client = publisher.Client(server, token['token'])
    fields = dict(name='원격 연결 도구', desc='등록한 주소와 연결 안내를 제공합니다.', platform='Claude',
                  type='MCP/Tool', guide='사용하는 프로그램에서 서버 주소와 인증 방식을 확인하세요.',
                  orgId='organization-0', categoryId='category-0', mode='url', url=source_url)
    calls = []
    original = publisher.multipart
    def recording_multipart(client, endpoint, artifact, metadata=None):
        calls.append((endpoint, artifact))
        return original(client, endpoint, artifact, metadata)
    monkeypatch.setattr(publisher, 'multipart', recording_multipart)
    plan = tmp_path/'publish-url.json'
    prepared = publisher.prepare(client, None, fields, plan, new=True)
    assert prepared['action'] == 'new_tool' and prepared['metadata']['url'] == source_url
    assert not prepared['missing'] and calls == []
    stored_plan = publisher.read_json(plan)
    assert stored_plan['artifact'] is None and stored_plan['artifactSha256'] is None
    pending = publisher.publish(client, plan, 'public')
    with app.app_context():
        assert db().tools.count_documents({}) == 0
    approve_pending(owner, headers, pending, False)
    result = publisher.publish(client, plan, 'public')
    assert result['version'] == 1 and calls == [('/api/publish-drafts', None)]
    manifest = owner.get(f'/api/tools/{result["id"]}/manifest').json
    assert manifest['url'] == source_url and manifest['downloadUrl'] is None
    assert manifest['package'] is None and manifest['installProfile'] is None
    assert not list((Path(app.config['DATA_DIR'])/'artifacts').iterdir())


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


def test_mock_cli_requires_publish_key_and_explicit_web_review(app, server, tmp_path):
    app.config.update(AUTH_MODE='mock', MOCK_USER='owner')
    client=publisher.Client(server)
    md=tmp_path/'SKILL.md'; md.write_text('# local',encoding='utf-8')
    fields=dict(name='로컬',desc='로컬 확인',platform='Claude',type='Skill',guide='설치 범위를 선택하세요.',
                orgId='organization-0',categoryId='category-0')
    plan=tmp_path/'plan.json'
    publisher.prepare(client,md,fields,plan)
    with pytest.raises(publisher.ClientError):
        publisher.publish(client,plan,'public')
    owner,h=ready(app)
    read_key,_=issue(owner,h,scope='read')
    reader=publisher.Client(server,read_key['token'])
    with pytest.raises(publisher.ClientError):
        publisher.publish(reader,plan,'public')
    with app.app_context():
        assert db().publish_drafts.count_documents({})==0
        assert db().tools.count_documents({})==0
    publish_key,_=issue(owner,h)
    writer=publisher.Client(server,publish_key['token'])
    pending=publisher.publish(writer,plan,'public')
    with app.app_context():
        assert db().tools.count_documents({})==0
    approve_pending(owner,h,pending,False)
    assert publisher.publish(writer,plan,'public')['version']==1


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
