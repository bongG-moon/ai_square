"""Company entry contract and optional local CLI, without a production database."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import pytest

@pytest.fixture
def deployment(tmp_path):
    source=Path(__file__).resolve().parents[1]
    package=tmp_path/'pt_ai_square';package.mkdir()
    for path in source.glob('*.py'):
        if path.name!='runtime_config.py':shutil.copy2(path,package/path.name)
    shutil.copytree(source/'templates',package/'templates')
    shutil.copytree(source/'backend',package/'backend',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(source/'dummy',package/'dummy')
    (package/'static').mkdir()
    (package/'static'/'probe.txt').write_text('standalone asset',encoding='utf-8')
    env={k:v for k,v in os.environ.items() if not k.startswith(('PTAI_','MONGODB_')) and k!='PYTHONPATH'}
    env.update(PYTHONIOENCODING='utf-8',PTAI_AUTH_MODE='mock',PTAI_DATA_MODE='dummy')
    return package,env

@pytest.mark.parametrize('missing_waitress', [False, True])
def test_optional_local_cli_starts_http_server_from_another_directory(deployment,tmp_path,missing_waitress):
    package,env=deployment
    renamed=package.with_name('회사 웹 독립 실행');package.rename(renamed);package=renamed
    if missing_waitress:
        blocker=tmp_path/'blocker';blocker.mkdir()
        (blocker/'sitecustomize.py').write_text(
            "import sys\nclass BlockWaitress:\n"
            "    def find_spec(self, fullname, path=None, target=None):\n"
            "        if fullname == 'waitress': raise ModuleNotFoundError('waitress absent for test')\n"
            "sys.meta_path.insert(0, BlockWaitress())\n",encoding='utf-8')
        env['PYTHONPATH']=str(blocker)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    log=tmp_path/'process.log'
    with log.open('wb') as output:
        command=[sys.executable,str(package/'__main__.py'),'run']
        process=subprocess.Popen([*command,'--port',str(port)],cwd=tmp_path,env=env,stdout=output,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+15;health=None
            while time.monotonic()<deadline and process.poll() is None:
                try:
                    with urlopen(f'http://127.0.0.1:{port}/health',timeout=.5) as response:health=json.load(response)
                    break
                except (URLError,OSError):time.sleep(.1)
            assert health and health['status']=='ok' and health['storage']=='dummy',log.read_text(encoding='utf-8')
            with urlopen(f'http://127.0.0.1:{port}/',timeout=10) as response:
                assert b'<html' in response.read().lower()
            with urlopen(f'http://127.0.0.1:{port}/static/probe.txt',timeout=10) as response:
                assert response.read()==b'standalone asset'
            if missing_waitress:
                assert 'Waitress가 없어' in log.read_text(encoding='utf-8')
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)

@pytest.mark.parametrize('statement,cwd_kind',[
    ('from pt_ai_square.web_main import app','parent'),
    ('from web_main import app','package'),
    ('from web_main import app','renamed'),
    ('from index import application as app; from web_main import app as original; assert app is original','package'),
    ('from index import application as app; from web_main import app as original; assert app is original','renamed'),
])
def test_wsgi_import_still_exports_app(deployment,statement,cwd_kind):
    package,env=deployment
    if cwd_kind=='renamed':
        renamed=package.with_name('standalone_app');package.rename(renamed);package=renamed
    code=("from flask import Flask\n"
          "def forbidden_run(*args, **kwargs): raise AssertionError('Import must not start a server')\n"
          "Flask.run=forbidden_run\n"+statement+"\n"
          "assert isinstance(app, Flask)\n"
          "assert app.test_client().get('/health').json['status']=='ok'\n"
          "assert app.test_client().get('/static/probe.txt').data==b'standalone asset'\n")
    result=subprocess.run([sys.executable,'-c',code],cwd=package.parent if cwd_kind=='parent' else package,env=env,capture_output=True,text=True,encoding='utf-8',timeout=10)
    assert result.returncode==0,result.stderr

def test_optional_local_cli_keeps_mock_loopback_guard(deployment):
    package,env=deployment
    result=subprocess.run([sys.executable,str(package/'__main__.py'),'run','--host','0.0.0.0'],cwd=package,env=env,capture_output=True,text=True,encoding='utf-8',timeout=10)
    assert result.returncode==2 and 'mock' in result.stderr


def test_sso_does_not_fallback_when_waitress_missing(deployment):
    package,env=deployment
    code=("import sys, runpy\nfrom flask import Flask\n"
          "from _square_bootstrap import load_package\n"
          "package=load_package()\napp=Flask('sso-cli-test')\n"
          "app.config.update(AUTH_MODE='sso',DATA_MODE='mongodb',HOST='127.0.0.1',PORT=5080)\n"
          "package.create_app=lambda:app\n"
          "class BlockWaitress:\n"
          "    def find_spec(self, fullname, path=None, target=None):\n"
          "        if fullname == 'waitress': raise ModuleNotFoundError('missing')\n"
          "sys.meta_path.insert(0, BlockWaitress())\n"
          "sys.argv=['__main__.py','run']\nrunpy.run_path('__main__.py',run_name='__main__')\n")
    result=subprocess.run([sys.executable,'-c',code],cwd=package,env=env,capture_output=True,text=True,encoding='utf-8',timeout=10)
    assert result.returncode==2
    assert '-m pip install -r' in result.stderr
    assert str(package/'requirements.txt') in result.stderr
    assert 'Waitress가 없어' not in result.stdout


@pytest.mark.parametrize('configured_port', [None, '9876'])
def test_company_index_uses_base_run_arguments_without_port_override(deployment,configured_port):
    package,env=deployment
    renamed=package.with_name('회사 웹 독립 실행');package.rename(renamed);package=renamed
    if configured_port:env['PTAI_PORT']=configured_port
    env['PTAI_HOST']='127.0.0.1'
    code=("import runpy\nfrom flask import Flask\n"
          "calls=[]\n"
          "Flask.run=lambda self,*args,**kwargs:calls.append((self,args,kwargs))\n"
          "namespace=runpy.run_path('index.py',run_name='__main__')\n"
          "from web_main import app\n"
          "assert namespace['application'] is app\n"
          "assert len(calls)==1\n"
          "assert calls[0][0] is app\n"
          "assert calls[0][1]==()\n"
          "assert calls[0][2]=={'debug':True,'host':'0.0.0.0'},calls[0][2]\n")
    result=subprocess.run([sys.executable,'-c',code],cwd=package,env=env,capture_output=True,text=True,encoding='utf-8',timeout=10)
    assert result.returncode==0,result.stderr


def test_direct_web_main_only_constructs_app_and_never_starts_listener(deployment):
    package,env=deployment
    code=("import os, runpy\nfrom flask import Flask\n"
          "def forbidden_run(*args,**kwargs):raise AssertionError('web_main must not start a server')\n"
          "Flask.run=forbidden_run\n"
          "namespace=runpy.run_path('web_main.py',run_name='__main__')\n"
          "assert isinstance(namespace['app'],Flask)\n"
          "assert namespace['app'].test_client().get('/health').json['status']=='ok'\n"
          "assert namespace['url_path']==''\n"
          "assert os.environ['NLS_LANG']=='.UTF8'\n")
    result=subprocess.run([sys.executable,'-c',code],cwd=package,env=env,capture_output=True,text=True,encoding='utf-8',timeout=10)
    assert result.returncode==0,result.stderr
