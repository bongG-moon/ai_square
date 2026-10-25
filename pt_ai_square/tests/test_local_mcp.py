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
from urllib.parse import parse_qs, urlsplit

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
    home=tmp_path/'managed-home';home.mkdir()
    monkeypatch.setattr(Path,'home',classmethod(lambda cls:home))
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


@pytest.mark.parametrize('url',[
    'http://mcp.example.test:8080/mcp',
    'http://api.example.test/v1/tools?format=json',
    'https://mcp.example.test/mcp',
])
def test_url_publication_keeps_http_or_https_address_without_file_or_connection_changes(settings,url):
    client=FakeClient();runtime=Runtime(settings,client)
    values=metadata()
    values.pop('packageId');values.pop('entryPoint')
    values.update(type='MCP/Tool',mode='url',url=url)
    before=settings.path.read_bytes()
    review=runtime.prepare_publish(values)
    assert review['targetSelectionRequired'] and review['source'] is None
    assert review['metadata']['url']==url and not client.drafts
    for target,kwargs in [('new',{}),('update',{'tool_id':1})]:
        draft=runtime.prepare_publish(values,target=target,**kwargs)
        sent,artifact=client.drafts[-1]
        assert sent['mode']=='url' and sent['url']==url and artifact is None
        assert draft['preparedFile'] is None and draft['preparedSha256'] is None and draft['package'] is None
        assert draft['reviewUrl'].startswith(settings.url+'/publish-review/')
        assert '원격 MCP 자동 연결' in draft['notice']
        if target=='update':assert sent['toolId']==1 and sent['expectedRevision']==3
    assert settings.path.read_bytes()==before and settings.url=='http://localhost:5000'
    assert not (settings.state/'publish').exists()
    assert not any(path.startswith(('http:','https:')) or '/approve' in path for path,_,_ in client.calls)


@pytest.mark.parametrize('name,value',[('.env','TOKEN=private'),('runtime_config.py','secret'),('nested/credential.dpapi.json','value'),('readme.md',KEY)])
@pytest.mark.parametrize('suffix',['.zip','.axextension'])
def test_prebuilt_zip_inspects_compressed_names_and_content(settings,name,value,suffix):
    source=settings.roots[0]/('legacy'+suffix);source.write_bytes(zipped({name:value}))
    with pytest.raises(SquareError):package(source,metadata(),settings.roots,settings.state/'rejected')


def test_axextension_download_and_publication_preserve_format_without_install(settings,monkeypatch):
    raw=zipped({'extension.json':'{}','README.txt':'Open with AX Workspace.'})
    source=settings.roots[0]/'PNT-AI-Square.axextension';source.write_bytes(raw)
    prepared,declaration=package(source,metadata(),settings.roots,settings.state/'prepared')
    assert prepared.suffix=='.axextension' and prepared.read_bytes()==raw
    assert declaration is None
    manifest=FakeClient(raw,'.axextension').manifest(1)
    client=Client(settings)
    monkeypatch.setattr(client,'manifest',lambda _tid:copy.deepcopy(manifest))
    monkeypatch.setattr(client,'open',lambda *_args,**_kwargs:io.BytesIO(raw))
    downloaded=client.download(manifest,settings.state/'downloads')
    assert downloaded.name=='tool-1-v1.axextension' and downloaded.read_bytes()==raw


@pytest.mark.parametrize('kind',['skill','mcp','installer'])
def test_axextension_is_never_installed_as_claude_content(settings,tmp_path,kind):
    client=FakeClient(zipped({'extension.json':'{}'}),'.axextension',profile(kind))
    installer=Installer(settings,client,tmp_path)
    result=installer.prepare(1,'project',str(settings.roots[0]))
    assert result['canInstall'] is False and result['installed'] is False
    assert client.downloads==[]
    assert not (settings.roots[0]/'.claude').exists()


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


class IdentityClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.target_detail={'packageId':'fixed-platform-id'}
        self.exact_targets=[]
        self.name_targets=[{'id':1,'name':'메모 요약','revision':3,'packageId':'fixed-platform-id'}]
        self.draft_identity={}
    def json(self,path,method='GET',data=None):
        result=super().json(path,method,data)
        if path.startswith('/api/publish-targets'):
            query=parse_qs(urlsplit(path).query)
            return {'items':copy.deepcopy(self.exact_targets if 'packageId' in query else self.name_targets)}
        if path=='/api/tools/1':
            result.update(copy.deepcopy(self.target_detail))
        return result
    def draft(self,metadata,artifact):
        return dict(super().draft(metadata,artifact),**self.draft_identity)


def declared_archive(package_id):
    declaration={'schemaVersion':1,'packageId':package_id,'name':'메모 요약','desc':'메모를 요약합니다.',
                 'platform':'Claude','type':'Skill','entryPoint':'SKILL.md','guideFile':'INSTALL.md',
                 'requiredFiles':[],'requirements':[],'workTags':['메모'],'environment':'AI','changes':'갱신'}
    return zipped({'ai-square.json':json.dumps(declaration,ensure_ascii=False),
                   'SKILL.md':'# 원본 스킬\n','INSTALL.md':'설치 범위를 확인하세요.'})


@pytest.mark.parametrize('exact_match',[False,True])
def test_review_searches_exact_identity_then_name_separately_without_choosing_target(settings,exact_match):
    client=IdentityClient();runtime=Runtime(settings,client)
    if exact_match:client.exact_targets=copy.deepcopy(client.name_targets)
    result=runtime.prepare_publish(metadata())
    searches=[parse_qs(urlsplit(path).query) for path,_,_ in client.calls if path.startswith('/api/publish-targets')]
    assert searches==([{'packageId':['memo-summary']}] if exact_match else [{'packageId':['memo-summary']},{'q':['메모 요약']}])
    assert result['targetSelectionRequired'] and result['candidates'][0]['id']==1
    assert result['candidateMatch']==('packageId' if exact_match else 'name')
    assert not client.drafts and not (settings.state/'publish').exists()
    assert not any(path=='/api/tools/1' for path,_,_ in client.calls)


def test_review_without_any_match_still_requires_new_or_update_selection(settings):
    client=IdentityClient();client.name_targets=[]
    result=Runtime(settings,client).prepare_publish(metadata())
    assert result['targetSelectionRequired'] and result['candidates']==[] and result['candidateMatch']=='none'
    assert not client.drafts


def test_explicit_update_accepts_changed_source_id_preserving_zip_and_fixed_identity(settings):
    client=IdentityClient();runtime=Runtime(settings,client)
    source=settings.roots[0]/'renamed-upload.zip';raw=declared_archive('new-source-id');source.write_bytes(raw)
    values=metadata();values.update(packageId='metadata-is-not-the-zip',sourcePackageId='forged',packageIdentityChanged=False)
    result=runtime.prepare_publish(values,str(source),'update',1)
    assert result['packageId']=='fixed-platform-id' and result['sourcePackageId']=='new-source-id'
    assert result['packageIdentityChanged'] is True and result['package']['packageId']=='new-source-id'
    assert source.read_bytes()==raw==Path(result['preparedFile']).read_bytes()==client.drafts[0][1]
    posted=client.drafts[0][0]
    assert posted['toolId']==1 and posted['expectedRevision']==3
    assert 'sourcePackageId' not in posted and 'packageIdentityChanged' not in posted
    assert values['sourcePackageId']=='forged'  # Caller metadata was not mutated.


@pytest.mark.parametrize('explicit_id',[None,'chosen-source-id'])
def test_folder_declaration_uses_fixed_identity_only_when_input_is_missing(settings,explicit_id):
    client=IdentityClient();folder=settings.roots[0]/'source';folder.mkdir();(folder/'SKILL.md').write_text('# source')
    values=metadata()
    if explicit_id is None:values.pop('packageId')
    else:values['packageId']=explicit_id
    result=Runtime(settings,client).prepare_publish(values,str(folder),'update',1)
    expected=explicit_id or 'fixed-platform-id'
    assert result['packageId']=='fixed-platform-id' and result['sourcePackageId']==expected
    assert result['packageIdentityChanged']==bool(explicit_id)
    with zipfile.ZipFile(result['preparedFile']) as z:assert json.loads(z.read('ai-square.json'))['packageId']==expected
    assert not (folder/'ai-square.json').exists()
    assert client.drafts[0][0]['packageId']==expected


def test_existing_folder_declaration_is_never_rewritten_for_an_update(settings):
    client=IdentityClient();folder=settings.roots[0]/'source';folder.mkdir()
    with zipfile.ZipFile(io.BytesIO(declared_archive('retained-source-id'))) as z:z.extractall(folder)
    before=(folder/'ai-square.json').read_bytes();values=metadata();values.pop('packageId')
    result=Runtime(settings,client).prepare_publish(values,str(folder),'update',1)
    assert result['packageId']=='fixed-platform-id' and result['sourcePackageId']=='retained-source-id'
    with zipfile.ZipFile(result['preparedFile']) as z:assert z.read('ai-square.json')==before
    assert (folder/'ai-square.json').read_bytes()==before and 'packageId' not in client.drafts[0][0]


def test_old_server_fallback_uses_first_recognized_identity_not_latest(settings):
    client=IdentityClient();client.target_detail={'versions':[{'n':3,'package':{'packageId':'latest-id'}},
        {'n':1,'package':None},{'n':2,'package':{'packageId':'first-fixed-id'},'withdrawn':True}]}
    source=settings.roots[0]/'later.zip';source.write_bytes(declared_archive('current-source-id'))
    result=Runtime(settings,client).prepare_publish(metadata(),str(source),'update',1)
    assert result['packageId']=='first-fixed-id' and result['sourcePackageId']=='current-source-id'


def test_server_identity_response_wins_over_local_legacy_hints(settings):
    client=IdentityClient();client.draft_identity={'packageId':'server-fixed-id','sourcePackageId':'server-source-id','packageIdentityChanged':True}
    source=settings.roots[0]/'SKILL.md';source.write_text('# source')
    result=Runtime(settings,client).prepare_publish(metadata(),str(source),'update',1)
    assert all(result[key]==value for key,value in client.draft_identity.items())


@pytest.mark.parametrize('field,value',[('slug','../unsafe'),('entrypoint','../SKILL.md')])
def test_changed_package_identity_does_not_bypass_install_profile_checks(settings,field,value):
    client=IdentityClient();source=settings.roots[0]/'different.zip';source.write_bytes(declared_archive('different-source'))
    values=metadata();values['installProfile']=dict(profile(),**{field:value})
    with pytest.raises(SquareError):Runtime(settings,client).prepare_publish(values,str(source),'update',1)
    assert not client.drafts


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


@pytest.mark.parametrize('suffix', ['.zip', '.ZIP', '.Zip'])
def test_skill_zip_files_and_mcp_merge_without_erasing_other_entries(settings,tmp_path,suffix):
    raw=zipped({'server.py':'print("not executed")','helper.py':'# helper'})
    client=FakeClient(raw,suffix,profile('mcp'));installer=Installer(settings,client,tmp_path)
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
        params=StdioServerParameters(command=sys.executable,args=['-X','utf8','-B',str(PACKAGE/'run_mcp.py'),'--config',str(settings.path),'serve'],env=dict(os.environ,PTAI_API_TOKEN=KEY,USERPROFILE=str(Path.home())))
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:
                initialized=await session.initialize();assert initialized.serverInfo.name=='P&T AI SQUARE'
                listing=await session.list_tools();names={t.name for t in listing.tools}
                assert {'connection_status','search_items','download_item','prepare_install','install_item','prepare_publish','publish_item','get_publish_status','rollback_install',
                        'list_install_locations','get_workspace_selection','cancel_workspace_selection'}<=names
                for tool in listing.tools:
                    assert 'token' not in tool.inputSchema.get('properties',{}) and 'key' not in tool.inputSchema.get('properties',{})
                    assert not {'ctx','project_roots'} & set(tool.inputSchema.get('properties',{}))
                download=next(t for t in listing.tools if t.name=='download_item')
                assert download.inputSchema['required']==['tool_id']
                picker=next(t for t in listing.tools if t.name=='select_workspace')
                assert set(picker.inputSchema['properties'])=={'purpose'}
                result=await session.call_tool('list_install_locations',{})
                assert not result.isError
                locations=json.loads(result.content[0].text)
                assert [row['scope'] for row in locations['options']]==['user','project','other']
                assert locations['rootsStatus']=='unsupported'
                result=await session.call_tool('connection_status',{})
                assert not result.isError and 'E1' in result.content[0].text and KEY not in result.content[0].text
                result=await session.call_tool('search_items',{'query':'메일'})
                assert not result.isError and '메일 조회' in result.content[0].text
                # An already-running host notices a folder selected after setup.
                extra=settings.path.parent/'selected-project';extra.mkdir()
                save_config(settings.path,url,[*settings.roots,extra],allow_http=True)
                result=await session.call_tool('connection_status',{})
                assert not result.isError and 'selected-project' in result.content[0].text
    asyncio.run(scenario())


def test_stdio_host_root_prepares_without_folder_reselection_and_rechecks_on_install(settings,api_server,tmp_path):
    pytest.importorskip('mcp')
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import ListRootsResult,Root
    url,calls,payload=api_server
    save_config(settings.path,url,settings.roots,allow_http=True)
    host=tmp_path/'host-current-project';host.mkdir()
    second=tmp_path/'second-project';second.mkdir()
    arbitrary=tmp_path/'unapproved-project';arbitrary.mkdir()
    roots=[host]
    before=settings.path.read_bytes()
    async def host_roots(_ctx):
        return ListRootsResult(roots=[Root(uri=path.as_uri(),name=path.name) for path in roots])
    async def scenario():
        params=StdioServerParameters(command=sys.executable,args=['-X','utf8','-B',str(PACKAGE/'run_mcp.py'),'--config',str(settings.path),'serve'],
                                     env=dict(os.environ,PTAI_API_TOKEN=KEY,USERPROFILE=str(Path.home())))
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write,list_roots_callback=host_roots) as session:
                await session.initialize()
                result=await session.call_tool('list_install_locations',{})
                locations=json.loads(result.content[0].text)
                assert locations['currentProject']['path']==str(host)
                result=await session.call_tool('prepare_install',{'tool_id':1,'scope':'project','project_path':str(arbitrary)})
                assert result.isError and not (arbitrary/'.claude').exists()
                roots.append(second)
                result=await session.call_tool('prepare_install',{'tool_id':1,'scope':'project'})
                assert result.isError and '여러 개' in result.content[0].text
                roots.pop()
                result=await session.call_tool('prepare_install',{'tool_id':1,'scope':'project'})
                assert not result.isError,result.content
                plan=json.loads(result.content[0].text)
                assert plan['scopeDir']==str(host) and plan['requiresConfirmation']
                assert settings.path.read_bytes()==before and not (host/'.claude').exists()
                roots[:]=[second]
                result=await session.call_tool('install_item',{'plan_id':plan['planId'],'approval_digest':plan['approvalDigest'],'confirmed':True})
                assert result.isError and not any(path.startswith('/download/') for path,_ in calls)
                roots[:]=[host]
                result=await session.call_tool('install_item',{'plan_id':plan['planId'],'approval_digest':plan['approvalDigest'],'confirmed':True})
                assert not result.isError,result.content
                assert json.loads(result.content[0].text)['installed']
    asyncio.run(scenario())
    assert (host/'.claude'/'skills'/'memo-summary'/'SKILL.md').read_bytes()==payload
    assert settings.path.read_bytes()==before
