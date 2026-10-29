"""End-to-end local MCP orchestration against the actual Flask+Mongo contracts."""
import sys
import asyncio
from datetime import timedelta
import io
import json
import os
import zipfile
from pathlib import Path
import pytest
from .conftest import ready
from .test_receiver import server
from .test_personal_api_usage import issue
from pt_ai_square.backend.storage import db

PACKAGE=Path(__file__).resolve().parents[1]/'integrations/pt-square-mcp'
sys.path.insert(0,str(PACKAGE))
from pt_square_mcp.config import Settings, save_config, SquareError
from pt_square_mcp.runtime import Runtime


def fields():
    return dict(name='업무 메모 요약',desc='주어진 업무 메모의 핵심과 할 일을 요약합니다.',platform='Claude',type='Skill',
                guide='프로젝트 또는 내 계정 범위를 선택하세요.',orgId='organization-0',categoryId='category-0',
                approval=False,changes='첫 배포',workTags=['메모','요약'],packageId='test.memo-summary',entryPoint='SKILL.md',
                workflow={'steps':[{'title':'메모 읽기','description':'입력한 업무 메모를 읽습니다.'},{'title':'요약','description':'핵심을 정리합니다.'}]},
                installProfile={'schemaVersion':1,'kind':'skill','host':'claude','slug':'mcp-e2e-memo','scopes':['project','user'],'entrypoint':'SKILL.md'})


def chat_publish(runtime, draft):
    assert draft['serverReviewRequired'] is False
    assert draft['requiresConfirmation'] is True and draft['approvalMethod'] == 'chat'
    return runtime.publish_item(draft['id'], review_digest=draft['reviewDigest'], confirmed=True)


def no_web_approval(app, monkeypatch):
    def forbidden():
        pytest.fail('MCP chat-confirmed publishing must not call the browser approval endpoint')
    monkeypatch.setitem(app.view_functions, 'publish_drafts.approve', forbidden)


@pytest.mark.parametrize('as_folder',[False,True])
def test_real_mcp_new_update_install_counts_and_rollback(app,server,tmp_path,monkeypatch,as_folder):
    no_web_approval(app,monkeypatch)
    home=tmp_path/'fake-home';home.mkdir()
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:home))
    owner,h=ready(app); key,_=issue(owner,h)
    monkeypatch.setenv('PTAI_API_TOKEN',key['token'])
    workspace=tmp_path/'workspace';workspace.mkdir()
    source=workspace/'source';source.mkdir()
    md=source/'SKILL.md';md.write_text('---\nname: memo-summary\ndescription: Summarize notes\n---\n# Version one\n',encoding='utf-8')
    if as_folder:(source/'examples.txt').write_text('Example notes only.',encoding='utf-8')
    config=tmp_path/'private'/'config.json';save_config(config,server,[workspace],allow_http=True)
    runtime=Runtime(Settings(config),home=tmp_path/'fake-home')
    values=fields();input_path=str(source if as_folder else md)
    review=runtime.prepare_publish(values,input_path)
    assert review['targetSelectionRequired'] and not review['candidates']
    draft=runtime.prepare_publish(values,input_path,target='new')
    assert draft['status']=='pending'
    with app.app_context():assert db().tools.count_documents({})==0
    with pytest.raises(SquareError):runtime.publish_item(draft['id'])
    with app.app_context():assert db().tools.count_documents({})==0
    published=chat_publish(runtime,draft);tid=published['id']
    assert published['version']==1 and runtime.publish_item(draft['id'])['version']==1
    assert runtime.get_item(tid)['workflow']==values['workflow']
    assert runtime.search_items('업무 메모')['items'][0]['id']==tid
    assert runtime.connection_status()['user']['id']=='owner'
    plan=runtime.installer.prepare(tid,'project',str(workspace))
    installed=runtime.installer.install(plan['planId'],plan['approvalDigest'],True)
    target=workspace/'.claude/skills/mcp-e2e-memo/SKILL.md'
    assert target.read_bytes()==md.read_bytes() and installed['installed']
    if as_folder:assert (target.parent/'examples.txt').is_file()
    assert runtime.check_updates()['items'][0]['result']['status']=='current'
    first=md.read_bytes();md.write_text('# Version two\nSummarize notes and tasks.\n',encoding='utf-8')
    values['changes']='할 일 정리 추가'
    draft2=runtime.prepare_publish(values,input_path,target='update',tool_id=tid)
    assert draft2['toolId']==tid
    assert chat_publish(runtime,draft2)['version']==2
    assert runtime.check_updates()['items'][0]['result']['status']=='update_available'
    plan2=runtime.installer.prepare(tid,'project',str(workspace))
    updated=runtime.installer.install(plan2['planId'],plan2['approvalDigest'],True)
    assert target.read_bytes()==md.read_bytes()
    assert owner.get(f'/api/tools/{tid}').json['downloads']==1
    with app.app_context():
        assert db().activity_state.count_documents({'tool':tid,'kind':'download','user':'owner'})==1
        assert len(db().tools.find_one({'_id':tid})['versions'])==2
    runtime.installer.rollback(updated['installationId'],True)
    assert target.read_bytes()==first


def test_real_mcp_url_without_package_id_and_admin_key_owner_guard(app,server,tmp_path,monkeypatch):
    home=tmp_path/'fake-home';home.mkdir()
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:home))
    owner,h=ready(app); key,_=issue(owner,h);monkeypatch.setenv('PTAI_API_TOKEN',key['token'])
    workspace=tmp_path/'workspace';workspace.mkdir();config=tmp_path/'config.json'
    save_config(config,server,[workspace],allow_http=True);runtime=Runtime(Settings(config),home=tmp_path/'fake-home')
    metadata=fields();metadata.pop('packageId');metadata.pop('entryPoint');metadata.pop('installProfile')
    metadata.update(mode='url',url='https://example.test/docs')
    assert runtime.prepare_publish(metadata)['targetSelectionRequired']
    draft=runtime.prepare_publish(metadata,target='new')
    assert owner.post('/api/publish-drafts/'+draft['id']+'/approve',headers=h,json={'approval':True,'reviewDigest':draft['reviewDigest']}).status_code==200
    published=runtime.publish_item(draft['id']);tid=published['id']
    admin,ah=ready(app,'admin');admin_key,_=issue(admin,ah);monkeypatch.setenv('PTAI_API_TOKEN',admin_key['token'])
    with pytest.raises(SquareError,match='본인'):runtime.prepare_publish(metadata,target='update',tool_id=tid)
    with pytest.raises(SquareError):runtime.client.json('/api/admin/settings')


def test_real_mcp_http_url_chat_confirmation_publishes_new_and_update_without_creating_files(app,server,tmp_path,monkeypatch):
    no_web_approval(app,monkeypatch)
    home=tmp_path/'fake-home';home.mkdir();monkeypatch.setattr(Path,'home',classmethod(lambda cls:home))
    owner,h=ready(app);key,_=issue(owner,h);monkeypatch.setenv('PTAI_API_TOKEN',key['token'])
    workspace=tmp_path/'workspace';workspace.mkdir();config=tmp_path/'config.json'
    save_config(config,server,[workspace],allow_http=True);runtime=Runtime(Settings(config),home=home)
    before=config.read_bytes();values=fields()
    for name in ('packageId','entryPoint','installProfile'):values.pop(name)
    first_url='http://mcp.example.test:8080/mcp'
    next_url='http://api.example.test/v2/tools?format=json'
    values.update(type='MCP/Tool',mode='url',url=first_url,guide='등록된 주소의 연결 안내를 확인하세요.')
    review=runtime.prepare_publish(values)
    assert review['targetSelectionRequired'] and review['source'] is None
    with app.app_context():assert db().publish_drafts.count_documents({})==0
    first=runtime.prepare_publish(values,target='new')
    assert first['preparedFile'] is None and first['package'] is None
    with pytest.raises(SquareError):runtime.publish_item(first['id'])
    with app.app_context():assert db().tools.count_documents({})==0
    created=chat_publish(runtime,first);tid=created['id']
    assert created['version']==1 and runtime.get_item(tid)['url']==first_url
    assert runtime.publish_item(first['id'])['version']==1
    values.update(url=next_url,changes='새 API 주소 안내')
    review=runtime.prepare_publish(values)
    assert review['targetSelectionRequired'] and any(row['id']==tid for row in review['candidates'])
    second=runtime.prepare_publish(values,target='update',tool_id=tid)
    assert second['toolId']==tid and second['expectedRevision']==1 and second['preparedFile'] is None
    with pytest.raises(SquareError):runtime.publish_item(second['id'])
    assert runtime.get_item(tid)['url']==first_url
    updated=chat_publish(runtime,second);assert updated['id']==tid and updated['version']==2
    assert runtime.publish_item(second['id'])['version']==2
    detail=runtime.get_item(tid)
    assert detail['url']==next_url and {v['n']:v['url'] for v in detail['versions']}=={1:first_url,2:next_url}
    manifest=runtime.client.manifest(tid)
    assert manifest['url']==next_url and manifest['downloadUrl'] is None and manifest['bytes']==0
    assert runtime.installer.prepare(tid,'project',str(workspace))['canInstall'] is False
    with pytest.raises(SquareError):runtime.download_item(tid)
    assert config.read_bytes()==before and not (runtime.settings.state/'publish').exists()
    assert not any(workspace.iterdir())
    with app.app_context():
        row=db().tools.find_one({'_id':tid})
        assert db().tools.count_documents({})==1 and len(row['versions'])==2
        assert all(v['path'] is None and v['size']==0 and v['sha']=='' for v in row['versions'])


def test_real_mcp_url_credentials_are_rejected_before_draft_creation(app,server,tmp_path,monkeypatch):
    home=tmp_path/'fake-home';home.mkdir();monkeypatch.setattr(Path,'home',classmethod(lambda cls:home))
    owner,h=ready(app);key,_=issue(owner,h);monkeypatch.setenv('PTAI_API_TOKEN',key['token'])
    workspace=tmp_path/'workspace';workspace.mkdir();config=tmp_path/'config.json'
    save_config(config,server,[workspace],allow_http=True);runtime=Runtime(Settings(config),home=home)
    values=fields()
    for name in ('packageId','entryPoint','installProfile'):values.pop(name)
    values.update(type='MCP/Tool',mode='url',url='http://username:password@mcp.example.test/mcp')
    with pytest.raises(SquareError) as error:runtime.prepare_publish(values,target='new')
    assert 'password' not in str(error.value)
    with app.app_context():
        assert db().publish_drafts.count_documents({})==0 and db().tools.count_documents({})==0
    assert not any(workspace.iterdir())


def test_real_mcp_changed_zip_identity_requires_explicit_target_and_keeps_fixed_identity(app,server,tmp_path,monkeypatch):
    no_web_approval(app,monkeypatch)
    home=tmp_path/'fake-home';home.mkdir();monkeypatch.setattr(Path,'home',classmethod(lambda cls:home))
    owner,h=ready(app);key,_=issue(owner,h);monkeypatch.setenv('PTAI_API_TOKEN',key['token'])
    workspace=tmp_path/'workspace';workspace.mkdir();source=workspace/'source';source.mkdir()
    (source/'SKILL.md').write_text('# Original skill\n',encoding='utf-8')
    config=tmp_path/'config.json';save_config(config,server,[workspace],allow_http=True)
    runtime=Runtime(Settings(config),home=home);values=fields()
    first=runtime.prepare_publish(values,str(source),target='new')
    created=chat_publish(runtime,first);tid=created['id']
    assert runtime.get_item(tid)['packageId']=='test.memo-summary'
    # Build a different declaration in an independently named ZIP. The MCP may
    # inspect/copy it, but neither it nor the server may rewrite these bytes.
    original=Path(first['preparedFile']).read_bytes();buffer=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as old, zipfile.ZipFile(buffer,'w') as new:
        for entry in old.infolist():
            raw=old.read(entry.filename)
            if entry.filename=='ai-square.json':
                declaration=json.loads(raw);declaration['packageId']='new.source-identity'
                raw=json.dumps(declaration,ensure_ascii=False).encode('utf-8')
            elif entry.filename=='SKILL.md':raw=b'# New original source\n'
            new.writestr(entry.filename,raw)
    archive=workspace/'new-filename-and-identity.zip';raw=buffer.getvalue();archive.write_bytes(raw)
    values['packageId']='new.source-identity';values['changes']='원본 식별자가 다른 새 배포'
    with app.app_context():before=db().publish_drafts.count_documents({})
    review=runtime.prepare_publish(values,str(archive))
    assert review['targetSelectionRequired'] and review['candidateMatch']=='name'
    assert any(row['id']==tid for row in review['candidates'])
    with app.app_context():assert db().publish_drafts.count_documents({})==before
    second=runtime.prepare_publish(values,str(archive),target='update',tool_id=tid)
    assert second['toolId']==tid and second['expectedRevision']==1
    assert second['packageId']=='test.memo-summary' and second['sourcePackageId']=='new.source-identity'
    assert second['packageIdentityChanged'] is True and Path(second['preparedFile']).read_bytes()==raw
    with pytest.raises(SquareError):runtime.publish_item(second['id'])
    published=chat_publish(runtime,second);assert published['id']==tid and published['version']==2
    detail=runtime.get_item(tid)
    assert detail['packageId']=='test.memo-summary' and detail['sourcePackageId']=='new.source-identity'
    assert detail['packageIdentityChanged'] is True
    assert {v['n']:v['package']['packageId'] for v in detail['versions']}=={1:'test.memo-summary',2:'new.source-identity'}
    manifest=runtime.client.manifest(tid)
    assert manifest['packageId']=='test.memo-summary' and manifest['sourcePackageId']=='new.source-identity'
    assert manifest['package']['packageId']=='new.source-identity'
    downloaded=runtime.download_item(tid,update=True);assert Path(downloaded['file']).read_bytes()==raw==archive.read_bytes()
    plan=runtime.installer.prepare(tid,'project',str(workspace))
    assert Path(plan['destination'])==workspace/'.claude'/'skills'/'mcp-e2e-memo'
    installed=runtime.installer.install(plan['planId'],plan['approvalDigest'],True)
    assert (Path(installed['destination'])/'SKILL.md').read_bytes()==b'# New original source\n'
    assert (Path(installed['destination'])/'ai-square.json').read_bytes()==json.dumps(declaration,ensure_ascii=False).encode('utf-8')
    with app.app_context():
        row=db().tools.find_one({'_id':tid});assert row['packageId']=='test.memo-summary'
        assert row['versions'][1]['package']['packageId']=='new.source-identity'
        assert db().tools.count_documents({})==1


def test_actual_stdio_mcp_chat_publish_and_owned_update_without_browser(app,server,tmp_path,monkeypatch):
    pytest.importorskip('mcp')
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    no_web_approval(app,monkeypatch)
    home=tmp_path/'fake-home';home.mkdir()
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:home))
    owner,headers=ready(app);key,_=issue(owner,headers)
    workspace=tmp_path/'workspace';workspace.mkdir()
    config=tmp_path/'private'/'config.json';save_config(config,server,[workspace],allow_http=True)
    values=fields()
    for name in ('packageId','entryPoint','installProfile'):values.pop(name)
    values.update(type='MCP/Tool',mode='url',url='http://internal.example.test/mcp',approval=True)
    async def scenario():
        params=StdioServerParameters(command=sys.executable,
            args=['-X','utf8','-B',str(PACKAGE/'run_mcp.py'),'--config',str(config),'serve'],
            env=dict(os.environ,PTAI_API_TOKEN=key['token'],USERPROFILE=str(home),HOME=str(home)))
        with (tmp_path/'mcp-stderr.txt').open('w',encoding='utf-8') as errors:
            async with stdio_client(params,errlog=errors) as (reader,writer):
                async with ClientSession(reader,writer,read_timeout_seconds=timedelta(seconds=20)) as session:
                    await session.initialize()
                    async def call(name,arguments,*,error=False):
                        response=await session.call_tool(name,arguments)
                        assert key['token'] not in str(response.content)
                        assert bool(response.isError) is error,response.content
                        return None if error else json.loads(response.content[0].text)
                    choose=await call('prepare_publish',{'metadata':values,'target':'new'})
                    assert choose['organizationSelectionRequired'] and not choose['ready']
                    assert any(org['id']==values['orgId'] for org in choose['options']['organizations'])
                    with app.app_context(): assert db().publish_drafts.count_documents({})==0
                    first=await call('prepare_publish',{'metadata':values,'target':'new','organization_confirmed':True})
                    assert first['requiresConfirmation'] and first['approvalMethod']=='chat'
                    assert not first['serverReviewRequired']
                    await call('publish_item',{'draft_id':first['id']},error=True)
                    digest=first['reviewDigest']
                    wrong=('0' if digest[0]!='0' else '1')+digest[1:]
                    await call('publish_item',{'draft_id':first['id'],'review_digest':wrong,'confirmed':True},error=True)
                    with app.app_context():
                        assert db().tools.count_documents({})==0
                        assert db().publish_drafts.find_one({'_id':first['id']})['status']=='pending'
                    created=await call('publish_item',{'draft_id':first['id'],'review_digest':digest,'confirmed':True})
                    tid=created['id'];assert created['version']==1
                    again=await call('publish_item',{'draft_id':first['id']})
                    assert again['id']==tid and again['version']==1 and again['replayed']
                    member,_=ready(app,'member')
                    assert member.get(f'/api/tools/{tid}').status_code==403
                    values.update(url='http://internal.example.test/v2/mcp',changes='Second endpoint',approval=False)
                    choose=await call('prepare_publish',{'metadata':values,'target':'update','tool_id':tid})
                    assert choose['organizationSelectionRequired'] and not choose['ready']
                    assert choose['options']['currentOrganization']['id']==values['orgId']
                    with app.app_context(): assert db().publish_drafts.count_documents({})==1
                    second=await call('prepare_publish',{'metadata':values,'target':'update','tool_id':tid,'organization_confirmed':True})
                    assert second['toolId']==tid and second['expectedRevision']==1
                    updated=await call('publish_item',{'draft_id':second['id'],'review_digest':second['reviewDigest'],'confirmed':True})
                    assert updated['id']==tid and updated['version']==2
                    assert member.get(f'/api/tools/{tid}').status_code==200
                    with app.app_context():
                        assert db().tools.count_documents({})==1
                        row=db().tools.find_one({'_id':tid})
                        assert row['owner']=='owner' and len(row['versions'])==2
                    assert owner.get('/api/local-tokens').json['usage']['uploads']==2
    asyncio.run(scenario())
    assert key['token'] not in (tmp_path/'mcp-stderr.txt').read_text(encoding='utf-8')
