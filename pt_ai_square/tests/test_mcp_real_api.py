"""End-to-end local MCP orchestration against the actual Flask+Mongo contracts."""
import sys
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


@pytest.mark.parametrize('as_folder',[False,True])
def test_real_mcp_new_update_install_counts_and_rollback(app,server,tmp_path,monkeypatch,as_folder):
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
    approved=owner.post('/api/publish-drafts/'+draft['id']+'/approve',headers=h,json={'approval':False,'reviewDigest':draft['reviewDigest']})
    assert approved.status_code==200,approved.json
    published=runtime.publish_item(draft['id']);tid=published['id']
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
    approved=owner.post('/api/publish-drafts/'+draft2['id']+'/approve',headers=h,json={'approval':False,'reviewDigest':draft2['reviewDigest']})
    assert approved.status_code==200
    assert runtime.publish_item(draft2['id'])['version']==2
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
