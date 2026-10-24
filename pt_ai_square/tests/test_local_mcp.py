"""Local MCP tests touch only pytest-owned files, fake homes and fixture HTTP APIs."""
import asyncio
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import zipfile

import pytest

PACKAGE=Path(__file__).parents[1]/'integrations'/'pt-square-mcp'
sys.path.insert(0,str(PACKAGE))
from pt_square_mcp.config import Settings,SquareError,save_config,read_json,atomic_json,normalize_url,scoped_path,protect
from pt_square_mcp.client import Client
from pt_square_mcp.files import package,extract,inspect,safe_entries,sha256
from pt_square_mcp.profiles import validate_profile
from pt_square_mcp.runtime import Runtime
from pt_square_mcp.install import Installer

KEY='ptsq_'+'a'*43


def test_vendored_distribution_contract_matches_current_platform():
    canonical=Path(__file__).parents[1]/'static'/'guides'/'pt-file-distribution'/'scripts'/'package_contract.py'
    assert canonical.read_bytes()==(PACKAGE/'pt_square_mcp'/'_vendor'/'package_contract.py').read_bytes()


@pytest.fixture
def settings(tmp_path,monkeypatch):
    workspace=tmp_path/'workspace';workspace.mkdir()
    path=tmp_path/'private'/'config.json'
    save_config(path,'http://localhost:5000',[workspace],allow_http=True)
    monkeypatch.setenv('PTAI_API_TOKEN',KEY)
    return Settings(path)


def profile(kind='skill'):
    value={'schemaVersion':1,'kind':kind,'host':'claude','slug':'memo-summary','scopes':['project','user'],'entrypoint':'SKILL.md'}
    if kind=='mcp':
        value.update(entrypoint='server.py',command={'executable':'python','args':['{entrypoint}']})
    if kind=='installer':
        value.update(entrypoint='setup.exe',installerArgs={'project':['--target','{scopeDir}'],'user':['--user','{scopeDir}']})
    return value


class FakeClient:
    def __init__(self,raw=b'# memo\n',suffix='.md',install_profile=None):
        self.raw=raw;self.downloads=[];self.calls=[];self.drafts=[];self.owner='E1'
        self.value={'toolId':1,'release':1,'filename':'source'+suffix,'downloadUrl':'/download/1/1',
                    'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'installProfile':profile() if install_profile is None else install_profile}
    def manifest(self,tool_id):
        return copy.deepcopy(self.value)
    def json(self,path,method='GET',data=None):
        self.calls.append((path,method,data))
        if path=='/api/catalog/options':
            return {'organizations':[{'id':'org','name':'공통'}],'categories':[{'id':'cat','name':'공통 업무'}]}
        if path=='/api/integration/me':
            return {'user':{'id':'E1','name':'홍길동','dept':'공통','dept_cd':'D1'},'key':{'id':'K1','scope':'publish'}}
        if path.startswith('/api/publish-targets'):
            return {'items':[{'id':1,'name':'메모 요약','revision':3}]}
        if path=='/api/tools/1':
            return {'ownerId':self.owner,'revision':3,'name':'메모 요약'}
        if 'version-check' in path:
            return {'latest':False,'release':2}
        if '/commit' in path:
            return {'id':1,'version':2}
        return {'items':[]}
    def download(self,manifest,directory,update=False):
        directory.mkdir(parents=True,exist_ok=True)
        p=directory/manifest['filename'];p.write_bytes(self.raw)
        self.downloads.append(update)
        return p
    def draft(self,metadata,artifact):
        self.drafts.append((copy.deepcopy(metadata),artifact.read_bytes() if artifact else None))
        return {'id':'12345678-1234-1234-1234-123456789abc','status':'pending','reviewUrl':'/publish-review/12345678-1234-1234-1234-123456789abc'}


def metadata():
    return {'name':'메모 요약','desc':'메모를 요약합니다.','platform':'Claude','type':'Skill','guide':'프로젝트 또는 내 계정을 선택해 설치하세요.',
            'orgId':'org','categoryId':'cat','approval':False,'packageId':'memo-summary','entryPoint':'SKILL.md','workflow':{'steps':[{'title':'메모 읽기'}]}}


@pytest.mark.parametrize('url',['http://example.com/other','https://name:pass@example.com','//example.com','file:///tmp/a','http://example.com?token=x','http://example.com\\evil'])
def test_config_rejects_ambiguous_origins(url):
    with pytest.raises(SquareError):normalize_url(url)


def test_http_ack_exactorigin_and_key_not_in_config(settings):
    data=read_json(settings.path)
    assert KEY not in settings.path.read_text()
    data['baseUrl']='http://another-company-server'
    atomic_json(settings.path,data)
    with pytest.raises(SquareError,match='확인'):Settings(settings.path)


def test_http_requires_setup_ack(tmp_path):
    with pytest.raises(SquareError):save_config(tmp_path/'config.json','http://example.com',[tmp_path])


@pytest.mark.skipif(os.name!='nt',reason='Windows DPAPI')
def test_dpapi_roundtrip_origin_binding(settings,monkeypatch):
    save_config(settings.path,settings.url,settings.roots,KEY,allow_http=True)
    monkeypatch.delenv('PTAI_API_TOKEN')
    assert Settings(settings.path).token()==KEY
    secret=settings.path.parent/'credential.dpapi.json'
    assert KEY not in secret.read_text()
    data=read_json(settings.path);data.update(baseUrl='http://elsewhere',acceptedHttpOrigin='http://elsewhere');atomic_json(settings.path,data)
    with pytest.raises(SquareError):Settings(settings.path).token()


def test_source_scope_and_secret_deny(settings,tmp_path):
    outside=tmp_path/'outside.md';outside.write_text('no')
    with pytest.raises(SquareError):inspect(outside,settings.roots)
    source=settings.roots[0]/'source';source.mkdir()
    (source/'.env').write_text('secret')
    with pytest.raises(SquareError):inspect(source,settings.roots)
    (source/'.env').unlink();(source/'a.md').write_text(KEY)
    with pytest.raises(SquareError):inspect(source,settings.roots)


def test_single_md_preserved_and_folder_zip_generated(settings):
    md=settings.roots[0]/'single.md';raw='# 메모 요약\n'.encode();md.write_bytes(raw)
    artifact,decl=package(md,metadata(),settings.roots,settings.state/'out1')
    assert artifact.suffix=='.md' and artifact.read_bytes()==raw and decl is None
    folder=settings.roots[0]/'source';folder.mkdir();(folder/'SKILL.md').write_bytes(raw)
    artifact,decl=package(folder,metadata(),settings.roots,settings.state/'out2')
    assert artifact.suffix=='.zip' and decl['packageId']=='memo-summary'
    with zipfile.ZipFile(artifact) as z:
        assert z.read('SKILL.md')==raw
        assert json.loads(z.read('ai-square.json'))['workflow']['steps'][0]['title']=='메모 읽기'
        assert 'installProfile' not in json.loads(z.read('ai-square.json'))


@pytest.mark.parametrize('name',['../x','/abs','C:/bad','bad\\path','x:ads','CON.txt','a./bad','a/../b'])
def test_zip_path_rejected(tmp_path,name):
    raw=io.BytesIO()
    with zipfile.ZipFile(raw,'w') as z:z.writestr(name,b'x')
    if name=='bad\\path':
        raw=io.BytesIO(raw.getvalue().replace(b'bad/path',b'bad\\path'))
    with zipfile.ZipFile(raw) as z:
        with pytest.raises(SquareError):safe_entries(z)


def test_zip_symlink_and_duplicate_and_bomb_rejected():
    for mode in ['link','duplicate','bomb']:
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w',zipfile.ZIP_DEFLATED) as z:
            if mode=='link':
                e=zipfile.ZipInfo('link');e.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(e,'outside')
            elif mode=='duplicate':
                z.writestr('a.txt','x');z.writestr('A.txt','y')
            else:z.writestr('bomb',b'0'*(2*1024*1024))
        with zipfile.ZipFile(raw) as z:
            with pytest.raises(SquareError):safe_entries(z)


def test_prepare_does_not_auto_choose_update_and_requires_visibility(settings):
    source=settings.roots[0]/'SKILL.md';source.write_text('# demo')
    client=FakeClient();runtime=Runtime(settings,client)
    result=runtime.prepare_publish(metadata(),str(source))
    assert result['targetSelectionRequired'] and not client.drafts
    values=metadata();values.pop('approval')
    result=runtime.prepare_publish(values,str(source),'new')
    assert not result['ready'] and not client.drafts


@pytest.mark.parametrize('name,value',[('.env','TOKEN=private'),('runtime_config.py','secret'),('nested/credential.dpapi.json','value'),('readme.md',KEY)])
def test_prebuilt_zip_inspects_compressed_names_and_content(settings,name,value):
    source=settings.roots[0]/'legacy.zip';source.write_bytes(zipped({name:value}))
    with pytest.raises(SquareError):package(source,metadata(),settings.roots,settings.state/'rejected')


def test_missing_previous_backup_never_deletes_current_installation(settings,tmp_path):
    client=FakeClient();installer=Installer(settings,client,tmp_path)
    plan=installer.prepare(1,'project',str(settings.roots[0]));first=installer.install(plan['planId'],plan['approvalDigest'],True)
    client.raw=b'# v2';client.value.update(release=2,sha256=hashlib.sha256(client.raw).hexdigest(),bytes=len(client.raw))
    plan=installer.prepare(1,'project',str(settings.roots[0]));second=installer.install(plan['planId'],plan['approvalDigest'],True)
    record=installer.records()[second['installationId']]
    missing=Path(record['backup'])/'files'/'SKILL.md';missing.unlink()
    with pytest.raises(SquareError,match='백업'):installer.rollback(second['installationId'],True)
    assert (Path(second['destination'])/'SKILL.md').read_bytes()==b'# v2'
    assert installer.records()[second['installationId']]['release']==2


def test_plan_cleanup_failure_keeps_successful_install_record(settings,tmp_path,monkeypatch):
    import pt_square_mcp.install as module
    client=FakeClient();installer=Installer(settings,client,tmp_path)
    plan=installer.prepare(1,'project',str(settings.roots[0]));original=module.atomic_json
    def fail_plan(path,data):
        if path.parent.name=='plans':raise OSError('fixture postcommit failure')
        original(path,data)
    monkeypatch.setattr(module,'atomic_json',fail_plan)
    result=installer.install(plan['planId'],plan['approvalDigest'],True)
    assert result['installed'] and result['planCleanupPending']
    assert (Path(result['destination'])/'SKILL.md').exists()
    assert result['installationId'] in installer.records()
    with pytest.raises(SquareError):installer.install(plan['planId'],plan['approvalDigest'],True)


def test_download_time_external_config_edit_is_preserved(settings,tmp_path):
    client=FakeClient(zipped({'server.py':'# code'}),'.zip',profile('mcp'));installer=Installer(settings,client,tmp_path)
    plan=installer.prepare(1,'project',str(settings.roots[0]));original=client.download
    def changed(*args,**kwargs):
        result=original(*args,**kwargs)
        atomic_json(settings.roots[0]/'.mcp.json',{'mcpServers':{'concurrent':{'command':'keep'}}})
        return result
    client.download=changed
    with pytest.raises(SquareError,match='받는 동안'):installer.install(plan['planId'],plan['approvalDigest'],True)
    assert read_json(settings.roots[0]/'.mcp.json')['mcpServers']['concurrent']['command']=='keep'


def test_rollback_state_save_failure_restores_current_files(settings,tmp_path,monkeypatch):
    import pt_square_mcp.install as module
    client=FakeClient();installer=Installer(settings,client,tmp_path)
    plan=installer.prepare(1,'project',str(settings.roots[0]));result=installer.install(plan['planId'],plan['approvalDigest'],True)
    original=module.atomic_json
    def fail_record(path,data):
        if path.name=='installations.json':raise OSError('fixture')
        original(path,data)
    monkeypatch.setattr(module,'atomic_json',fail_record)
    with pytest.raises(OSError):installer.rollback(result['installationId'],True)
    assert (Path(result['destination'])/'SKILL.md').read_bytes()==b'# memo\n'
    assert result['installationId'] in installer.records()


def test_new_draft_keeps_md_sanitizes_update_target_and_absolute_review(settings):
    source=settings.roots[0]/'SKILL.md';source.write_bytes(b'# demo')
    client=FakeClient();runtime=Runtime(settings,client)
    values=metadata();values.update(toolId=99,expectedRevision=9)
    result=runtime.prepare_publish(values,str(source),'new')
    assert result['status']=='pending' and result['reviewUrl'].startswith(settings.url+'/publish-review/')
    posted,raw=client.drafts[0]
    assert raw==b'# demo' and 'toolId' not in posted and 'expectedRevision' not in posted
    assert result['preparedFile'].endswith('.md')


def test_update_requires_owner_and_uses_current_revision(settings):
    source=settings.roots[0]/'SKILL.md';source.write_text('# demo')
    client=FakeClient();runtime=Runtime(settings,client)
    client.owner='E2'
    with pytest.raises(SquareError):runtime.prepare_publish(metadata(),str(source),'update',1)
    client.owner='E1';runtime.prepare_publish(metadata(),str(source),'update',1)
    assert client.drafts[-1][0]['toolId']==1 and client.drafts[-1][0]['expectedRevision']==3


def test_commit_only_calls_draft_commit(settings):
    client=FakeClient();runtime=Runtime(settings,client)
    result=runtime.publish_item('12345678-1234-1234-1234-123456789abc')
    assert result['version']==2
    assert client.calls==[('/api/publish-drafts/12345678-1234-1234-1234-123456789abc/commit','POST',{})]


def test_skill_install_scope_confirm_update_rollback(settings,tmp_path):
    client=FakeClient();home=tmp_path/'fake-home';home.mkdir();installer=Installer(settings,client,home)
    with pytest.raises(SquareError):installer.prepare(1,'')
    plan=installer.prepare(1,'project',str(settings.roots[0]))
    with pytest.raises(SquareError):installer.install(plan['planId'],plan['approvalDigest'])
    result=installer.install(plan['planId'],plan['approvalDigest'],True)
    target=Path(result['destination'])
    assert result['installed'] and (target/'SKILL.md').read_bytes()==client.raw
    with pytest.raises(SquareError):installer.install(plan['planId'],plan['approvalDigest'],True)
    client.raw=b'# newer';client.value.update(release=2,downloadUrl='/download/1/2',sha256=hashlib.sha256(client.raw).hexdigest(),bytes=len(client.raw))
    plan2=installer.prepare(1,'project',str(settings.roots[0]));result2=installer.install(plan2['planId'],plan2['approvalDigest'],True)
    assert client.downloads==[False,True]
    assert installer.rollback(result2['installationId'],True)['release']==1
    assert (target/'SKILL.md').read_bytes()==b'# memo\n'
    assert not list(home.iterdir())


def test_user_install_uses_fake_user_home_and_preserves_other_skill(settings,tmp_path):
    home=tmp_path/'fake-home';home.mkdir();other=home/'.claude'/'skills'/'other';other.mkdir(parents=True);(other/'SKILL.md').write_text('keep')
    installer=Installer(settings,FakeClient(),home)
    plan=installer.prepare(1,'user');result=installer.install(plan['planId'],plan['approvalDigest'],True)
    assert Path(result['destination']).is_relative_to(home)
    installer.rollback(result['installationId'],True)
    assert (other/'SKILL.md').read_text()=='keep'


def test_no_overwrite_unowned_and_modified_files(settings,tmp_path):
    target=settings.roots[0]/'.claude'/'skills'/'memo-summary';target.mkdir(parents=True);(target/'SKILL.md').write_text('mine')
    installer=Installer(settings,FakeClient(),tmp_path)
    with pytest.raises(SquareError):installer.prepare(1,'project',str(settings.roots[0]))
    (target/'SKILL.md').unlink();target.rmdir()
    plan=installer.prepare(1,'project',str(settings.roots[0]));result=installer.install(plan['planId'],plan['approvalDigest'],True)
    (target/'SKILL.md').write_text('edited')
    with pytest.raises(SquareError):installer.rollback(result['installationId'],True)
    with pytest.raises(SquareError):installer.prepare(1,'project',str(settings.roots[0]))


def test_changed_release_or_profile_requires_fresh_approval(settings,tmp_path):
    client=FakeClient();installer=Installer(settings,client,tmp_path)
    plan=installer.prepare(1,'project',str(settings.roots[0]))
    client.value['release']=2
    with pytest.raises(SquareError,match='변경'):installer.install(plan['planId'],plan['approvalDigest'],True)
    assert not client.downloads


def zipped(files):
    raw=io.BytesIO()
    with zipfile.ZipFile(raw,'w') as z:
        for name,value in files.items():z.writestr(name,value)
    return raw.getvalue()


def test_skill_zip_files_and_mcp_merge_without_erasing_other_entries(settings,tmp_path):
    raw=zipped({'server.py':'print("not executed")','helper.py':'# helper'})
    client=FakeClient(raw,'.zip',profile('mcp'));installer=Installer(settings,client,tmp_path)
    config=settings.roots[0]/'.mcp.json';atomic_json(config,{'mcpServers':{'existing':{'command':'keep'}},'unrelated':42})
    plan=installer.prepare(1,'project',str(settings.roots[0]));result=installer.install(plan['planId'],plan['approvalDigest'],True)
    values=read_json(config)
    assert values['mcpServers']['existing']=={'command':'keep'} and values['unrelated']==42
    assert result['status']=='configured' and not result['connectionVerified']
    values['another']='user change';atomic_json(config,values)
    installer.rollback(result['installationId'],True)
    assert read_json(config)=={'mcpServers':{'existing':{'command':'keep'}},'unrelated':42,'another':'user change'}


def test_config_change_between_prepare_execute_is_not_overwritten(settings,tmp_path):
    client=FakeClient(zipped({'server.py':'# never run'}),'.zip',profile('mcp'));installer=Installer(settings,client,tmp_path)
    plan=installer.prepare(1,'project',str(settings.roots[0]));atomic_json(settings.roots[0]/'.mcp.json',{'mcpServers':{'new':{}}})
    with pytest.raises(SquareError,match='설정'):installer.install(plan['planId'],plan['approvalDigest'],True)


@pytest.mark.skipif(os.name!='nt',reason='Windows installer')
def test_installer_launch_is_not_reported_installed_and_does_not_inherit_key(settings,tmp_path,monkeypatch):
    p=profile('installer');p['verification']={'relativePath':'installed/result.txt'}
    client=FakeClient(b'MZ-TEST','.exe',p);installer=Installer(settings,client,tmp_path)
    captured=[]
    class Process:pid=123
    monkeypatch.setattr('pt_square_mcp.install.subprocess.Popen',lambda command,**kwargs:captured.append((command,kwargs)) or Process())
    plan=installer.prepare(1,'project',str(settings.roots[0]));result=installer.install(plan['planId'],plan['approvalDigest'],True)
    assert result['status']=='launched' and not result['installed'] and not result['rollbackAvailable']
    assert captured and not captured[0][1]['shell'] and 'PTAI_API_TOKEN' not in captured[0][1]['env']
    assert not installer.verify(result['installationId'])['installed']
    target=settings.roots[0]/'installed'/'result.txt';target.parent.mkdir();target.write_text('fixture only')
    assert installer.verify(result['installationId'])['installed']
    assert installer.verify(result['installationId'])['installed']


def test_search_sorts_and_version_check_do_not_install(settings,tmp_path):
    client=FakeClient();runtime=Runtime(settings,client,tmp_path)
    runtime.search_items('메일',sort='realtime')
    assert 'sort=realtime' in client.calls[-1][0]
    assert runtime.check_updates()=={'items':[],'automaticallyUpdated':False,'notice':'버전 확인만 수행했습니다. 실제 교체는 새 설치 준비안과 범위 확인 후 진행합니다.'}


@pytest.fixture
def api_server():
    calls=[];payload=b'# downloaded Skill\n'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            calls.append((self.path,self.headers.get('Authorization')))
            if self.path.startswith('/api/catalog'):
                value={'items':[{'id':1,'name':'메일 조회','reasons':['업무 일치']}],'sort':'recommended'}
            elif self.path=='/api/integration/me':value={'user':{'id':'E1'},'key':{'scope':'publish'}}
            elif self.path=='/api/tools/1/manifest':
                value={'toolId':1,'release':1,'filename':'demo.md','downloadUrl':'/download/1/1','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),'installProfile':profile()}
            elif self.path.startswith('/download/1/1'):
                self.send_response(200);self.end_headers();self.wfile.write(payload);return
            elif self.path=='/api/tools/2':
                self.send_response(302);self.send_header('Location','/api/integration/me');self.end_headers();return
            else:
                self.send_response(401);self.end_headers();self.wfile.write(b'private secret never expose');return
            raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield 'http://127.0.0.1:'+str(server.server_address[1]),calls,payload
    server.shutdown();server.server_close();thread.join()


def test_real_http_download_and_redirect_block(settings,api_server):
    url,calls,payload=api_server;save_config(settings.path,url,settings.roots,allow_http=True);settings=Settings(settings.path);client=Client(settings)
    manifest=client.manifest(1);target=client.download(manifest,settings.roots[0]/'downloads',update=True)
    assert target.read_bytes()==payload
    assert any(path=='/download/1/1?purpose=update' for path,key in calls)
    before=len(calls)
    with pytest.raises(SquareError,match='이동'):client.json('/api/tools/2')
    assert len(calls)==before+1
    with pytest.raises(SquareError):client.json('https://evil.example/api/catalog')
    with pytest.raises(SquareError):client.json('/api/tools/1/purge','POST',{})
    assert all(key=='Bearer '+KEY for _,key in calls)


def test_http_error_does_not_echo_server_body(settings,api_server):
    url,_,_=api_server;save_config(settings.path,url,settings.roots,allow_http=True)
    with pytest.raises(SquareError) as error:Client(Settings(settings.path)).json('/api/tools/999')
    assert 'private secret' not in str(error.value) and KEY not in str(error.value)


def test_stdio_initialize_list_and_call_actual_sdk(settings,api_server):
    pytest.importorskip('mcp')
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    url,_,_=api_server;save_config(settings.path,url,settings.roots,allow_http=True)
    async def scenario():
        params=StdioServerParameters(command=sys.executable,args=['-X','utf8','-B',str(PACKAGE/'run_mcp.py'),'--config',str(settings.path),'serve'],env=dict(os.environ,PTAI_API_TOKEN=KEY))
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:
                initialized=await session.initialize();assert initialized.serverInfo.name=='P&T AI SQUARE'
                listing=await session.list_tools();names={t.name for t in listing.tools}
                assert {'connection_status','search_items','download_item','prepare_install','install_item','prepare_publish','publish_item','get_publish_status','rollback_install'}<=names
                for tool in listing.tools:
                    assert 'token' not in tool.inputSchema.get('properties',{}) and 'key' not in tool.inputSchema.get('properties',{})
                result=await session.call_tool('connection_status',{})
                assert not result.isError and 'E1' in result.content[0].text and KEY not in result.content[0].text
                result=await session.call_tool('search_items',{'query':'메일'})
                assert not result.isError and '메일 조회' in result.content[0].text
    asyncio.run(scenario())
