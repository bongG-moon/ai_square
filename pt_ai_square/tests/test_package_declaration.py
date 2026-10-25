import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest
from pt_ai_square.backend.storage import db
from .conftest import ready

BASE=Path(__file__).resolve().parents[1]


def declaration(**changes):
    return dict(schemaVersion=1,packageId='sample-tool',name='선언한 도구',desc='선언에서 읽은 설명',
        platform='Claude',type='MCP/Tool',entryPoint='main.py',guideFile='INSTALL.md',
        requiredFiles=['requirements.txt'],requirements=['Python 3.11'],workTags=['분석'],
        environment='Python',changes='첫 배포',**changes)


def bundle(raw=None,missing=None,manifest_path='ai-square.json'):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr(manifest_path,json.dumps(declaration() if raw is None else raw,ensure_ascii=False))
        for name,value in {'main.py':'raise RuntimeError("MUST NEVER EXECUTE")',
                           'INSTALL.md':'압축을 풀고 Python 환경을 준비하세요.',
                           'requirements.txt':'# dependencies'}.items():
            if name!=missing:z.writestr(name,value)
    return b.getvalue()


def post(c,h,blob,url='/api/tools',file_name='tool.zip',**extra):
    meta=dict(org='공통',category='공통 업무',owner='등록자',approval=False,mode='file')
    meta.update(extra)
    return c.post(url,headers=h,data={'metadata':json.dumps(meta),'artifact':(io.BytesIO(blob),file_name)})


@pytest.mark.parametrize('file_name', ['tool.zip', 'PNT-AI-Square.axextension'])
def test_inspect_publish_original_bytes_versions_and_rollback(app,file_name):
    c,h=ready(app);v1=bundle()
    before=list((Path(app.config['DATA_DIR'])/'artifacts').iterdir())
    inspected=c.post('/api/packages/inspect',headers=h,data={'artifact':(io.BytesIO(v1),file_name)})
    assert inspected.status_code==200 and inspected.json['recognized']
    assert inspected.json['metadata']['guide']=='압축을 풀고 Python 환경을 준비하세요.'
    assert inspected.json['sha256']==hashlib.sha256(v1).hexdigest()
    assert list((Path(app.config['DATA_DIR'])/'artifacts').iterdir())==before
    with app.app_context():assert db().tools.count_documents({})==0
    published=post(c,h,v1,file_name=file_name);assert published.status_code==201,published.json
    tid=published.json['id'];url=published.json['deploymentUrl']
    info=c.get(url);assert info.status_code==200
    assert info.json['toolId']==tid and info.json['release']==1
    assert info.json['package']['entryPoint']=='main.py'
    assert info.json['managedInstall'] is False
    assert info.json['filename']==file_name
    assert info.json['installProfile'] is None
    assert 'attachment;' in info.headers['Content-Disposition']
    downloaded=c.get(info.json['downloadUrl'])
    assert downloaded.data==v1
    assert file_name in downloaded.headers['Content-Disposition']
    downloaded.close()
    assert c.get(info.json['versionCheckUrl']).json['status']=='current'
    updated=declaration();updated.update(changes='두 번째',entryPoint='requirements.txt')
    v2=bundle(updated)
    result=post(c,h,v2,f'/api/tools/{tid}/versions',file_name=file_name,expectedRevision=1)
    assert result.status_code==201,result.json
    assert c.get(result.json['deploymentUrl']).json['release']==2
    assert c.get(f'/api/tools/{tid}/manifest').json['package']['entryPoint']=='requirements.txt'
    assert c.get(info.json['versionCheckUrl']).json['status']=='update_available'
    assert c.post(f'/api/tools/{tid}/rollback',headers=h,json={'version':1,'expectedRevision':2}).status_code==200
    assert c.get(f'/api/tools/{tid}/manifest').json['package']['entryPoint']=='main.py'
    assert c.get(result.json['deploymentUrl']).status_code==404
    assert c.get(url).json['release']==1
    assert c.get(f'/download/{tid}/1').data==v1


@pytest.mark.parametrize('case',['missing','path','nested','schema','duplicate','unknown','wrong-kind','empty-guide'])
@pytest.mark.parametrize('file_name',['tool.zip','tool.axextension'])
def test_invalid_declaration_warns_but_manual_publish_succeeds(app,case,file_name):
    c,h=ready(app);raw=declaration()
    if case=='path':raw['entryPoint']='../private.py'
    if case=='schema':raw['schemaVersion']=2
    if case=='unknown':raw['toolId']=1
    if case=='wrong-kind':raw['type']='MCP'
    blob=bundle(raw,missing='main.py' if case=='missing' else None,manifest_path='folder/ai-square.json' if case=='nested' else 'ai-square.json')
    if case in {'duplicate','empty-guide'}:
        b=io.BytesIO(blob)
        with zipfile.ZipFile(b,'a') as z:
            z.writestr('MAIN.py' if case=='duplicate' else 'EMPTY.md','x' if case=='duplicate' else '')
        if case=='empty-guide':
            raw['guideFile']='EMPTY.md'
            b=io.BytesIO()
            with zipfile.ZipFile(b,'w') as z:
                z.writestr('ai-square.json',json.dumps(raw));z.writestr('EMPTY.md','')
                z.writestr('main.py','x');z.writestr('requirements.txt','x')
        blob=b.getvalue()
    result=post(c,h,blob,'/api/packages/inspect',file_name=file_name)
    assert result.status_code==200 and not result.json['recognized'],(case,result.json)
    assert result.json['warning']
    assert not list((Path(app.config['DATA_DIR'])/'artifacts').iterdir())
    result=post(c,h,blob,file_name=file_name,name='직접 작성',desc='수동 등록',platform='Claude',type='Skill',guide='수동 설치 안내')
    assert result.status_code==201 and result.json['packageWarning'],(case,result.json)
    assert c.get(f'/download/{result.json["id"]}/1').data==blob
    with app.app_context():assert db().tools.count_documents({})==1


def test_declaration_cannot_grant_access_or_skip_actual_validation(app):
    c,h=ready(app);blob=bundle()
    assert c.post('/api/packages/inspect',data={'artifact':(io.BytesIO(blob),'x.zip')}).status_code==403
    assert app.test_client().post('/api/packages/inspect',headers=h,data={'artifact':(io.BytesIO(blob),'x.zip')}).status_code in {401,403}
    r=post(c,h,blob,approval=True);tid=r.json['id']
    member,_=ready(app,'member')
    assert member.get(r.json['deploymentUrl']).status_code==403
    card=next(x for x in member.get('/api/bootstrap').json['items'] if x['id']==tid)
    assert card['versions']==[] and 'package' not in card
    assert member.get(f'/api/tools/{tid}/manifest').status_code==403
    different=declaration();different['packageId']='different-tool'
    assert post(c,h,bundle(different),f'/api/tools/{tid}/versions',expectedRevision=1).status_code==400
    assert post(c,h,blob,f'/api/tools/{tid}/versions',expectedRevision=1,type='Skill').status_code==400
    no_manifest=io.BytesIO()
    with zipfile.ZipFile(no_manifest,'w') as z:z.writestr('README.md','# legacy')
    assert len(list((Path(app.config['DATA_DIR'])/'artifacts').iterdir()))==1
    assert c.get(r.json['deploymentUrl']).json['release']==1
    assert c.patch(f'/api/tools/{tid}',headers=h,json={'type':'Skill','expectedRevision':1}).status_code==400
    forged=declaration();forged['entryPoint']='absent.py'
    updated=post(c,h,bundle(forged),f'/api/tools/{tid}/versions',expectedRevision=1,packageInspection={'recognized':True},name='수동 업데이트',desc='설명',platform='Claude',type='MCP/Tool',guide='수동 안내')
    assert updated.status_code==201 and not updated.json['packageRecognized']
    assert updated.json['packageWarning']
    assert post(c,h,no_manifest.getvalue(),f'/api/tools/{tid}/versions',expectedRevision=2,name='수동 업데이트',desc='설명',platform='Claude',type='MCP/Tool',guide='수동 안내').status_code==201


def test_legacy_inspection_remains_supported(app):
    c,h=ready(app);blob=io.BytesIO()
    with zipfile.ZipFile(blob,'w') as z:z.writestr('README.md','# old package')
    r=c.post('/api/packages/inspect',headers=h,data={'artifact':(io.BytesIO(blob.getvalue()),'legacy.zip')})
    assert r.status_code==200 and r.json['recognized'] is False
    assert not list((Path(app.config['DATA_DIR'])/'artifacts').iterdir())


def test_downloadable_skill_builds_accepted_package(app,tmp_path):
    skill=BASE/'static/guides/pt-file-distribution'
    assert (skill/'scripts/package_contract.py').read_bytes()==(BASE/'backend/package_contract.py').read_bytes()
    source=tmp_path/'prepared';source.mkdir()
    workflow={'steps':[{'title':'입력 확인','description':'선택한 자료를 확인합니다.'},
                       {'title':'결과 제공','description':'처리한 결과를 제공합니다.'}]}
    with zipfile.ZipFile(io.BytesIO(bundle(declaration(workflow=workflow)))) as z:z.extractall(source)
    output=tmp_path/'release.zip'
    built=subprocess.run([sys.executable,str(skill/'scripts/prepare_package.py'),str(source),str(output)],capture_output=True)
    assert built.returncode==0,built.stderr
    c,h=ready(app);r=post(c,h,output.read_bytes())
    assert r.status_code==201,r.json
    assert c.get(f'/api/tools/{r.json["id"]}').json['workflow']==workflow
    assert c.get(f'/download/{r.json["id"]}/1').data==output.read_bytes()
    again=subprocess.run([sys.executable,str(skill/'scripts/prepare_package.py'),str(source),str(output)],capture_output=True)
    assert again.returncode!=0 and output.exists()
