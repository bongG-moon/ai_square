import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile
import pytest
from .conftest import ready, publish

SKILL=Path(__file__).parents[1]/'static/guides/pt-file-distribution'

def test_markdown_original_download_and_version(app):
    c,h=ready(app)
    raw=b'---\nname: simple\ndescription: single file\n---\n# Skill\n'
    m=dict(name='MD 도구',desc='단일 파일',owner='작성자',org='공통',category='공통 업무',platform='Claude',type='Skill',guide='먼저 범위를 고르고 해당 위치로 복사합니다.',mode='file')
    r=c.post('/api/tools',headers=h,data={'metadata':json.dumps(m),'artifact':(io.BytesIO(raw),'SKILL.md')})
    assert r.status_code==201,r.json
    tid=r.json['id'];assert c.get(f'/download/{tid}/1').data==raw
    r=c.post(f'/api/tools/{tid}/versions',headers=h,data={'metadata':json.dumps(dict(m,expectedRevision=1)),'artifact':(io.BytesIO(raw+b'updated'),'SKILL.md')})
    assert r.status_code==201
    assert c.get(f'/api/tools/{tid}/version-check?release=1').json['status']=='update_available'
    assert c.get(f'/download/{tid}/2').data==raw+b'updated'

def test_command_permissions_versions_rollback(app):
    c,h=ready(app)
    r=publish(c,h,mode='command',commandProject='tool setup --project .',commandUser='tool setup --user',approval=True)
    assert r.status_code==201,r.json
    tid=r.json['id'];url=f'/api/tools/{tid}'
    item=c.get(url).json
    assert item['mode']=='command' and item['versions'][0]['commands']['project']=='tool setup --project .'
    assert c.get(url+'/manifest').json['downloadUrl'] is None
    assert c.get(f'/download/{tid}/1').status_code==400
    member,_=ready(app,'member')
    assert member.get(url).status_code==403
    assert member.get(url+'/manifest').status_code==403
    card=member.get('/api/bootstrap').json['items'][0]
    assert card['versions']==[] and 'commands' not in card
    r=publish(c,h,tid,1,mode='command',commandProject='tool setup --project . --new',commandUser='',approval=True)
    assert r.status_code==201,r.json
    assert c.get(url+'/manifest').json['commands']['user']==''
    assert c.post(url+'/rollback',headers=h,json={'version':1,'expectedRevision':2}).status_code==200
    assert c.get(url+'/manifest').json['commands']['user']=='tool setup --user'
    withdrawn=next(v for v in c.get(url).json['versions'] if v['n']==2)
    assert withdrawn['commands']=={} and withdrawn['withdrawn']

def test_empty_commands_rejected_and_zip_traversal_still_blocked(app):
    c,h=ready(app)
    assert publish(c,h,mode='command',commandProject='',commandUser='').status_code==400
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr('ai-square.json','broken');z.writestr('../escape.txt','x')
    b.seek(0)
    assert c.post('/api/packages/inspect',headers=h,data={'artifact':(b,'bad.zip')}).status_code==400

def test_skill_preserves_single_md_and_requires_scope(tmp_path):
    source=tmp_path/'source.md';source.write_bytes(b'# One markdown\r\n')
    target=tmp_path/'SKILL.md'
    script=SKILL/'scripts/prepare_package.py'
    r=subprocess.run([sys.executable,str(script),str(source),str(target)],capture_output=True)
    assert r.returncode==0,r.stderr
    assert target.read_bytes()==source.read_bytes()
    r=subprocess.run([sys.executable,str(script),str(source),str(tmp_path/'forced.zip')],capture_output=True)
    assert r.returncode!=0 and not (tmp_path/'forced.zip').exists()
    helper=SKILL/'scripts/install_scope.py'
    r=subprocess.run([sys.executable,'-X','utf8',str(helper)],input='',capture_output=True,text=True,encoding='utf-8')
    assert r.returncode!=0  # no terminal input: never silently choose global
    spec=importlib.util.spec_from_file_location('install_scope',helper)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    answers=iter(['','invalid','1'])
    choice=module.select_scope(project_dir=tmp_path,interactive=True,ask=lambda _:next(answers))
    assert choice=={'scope':'project','baseDirectory':str(tmp_path.resolve())}
    assert module.select_scope('user')['baseDirectory']==str(Path.home().resolve())
    with pytest.raises(ValueError):module.select_scope(interactive=True,ask=lambda _:'q')
