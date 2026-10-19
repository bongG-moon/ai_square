"""Reproduce direct-file execution outside the package, as in VS Code on Windows."""
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
    shutil.copytree(source/'demo',package/'demo')
    env={k:v for k,v in os.environ.items() if not k.startswith(('PTAI_','MONGODB_')) and k!='PYTHONPATH'}
    env.update(PTAI_AUTH_MODE='mock',PYTHONIOENCODING='utf-8')
    return package,env

def test_direct_file_starts_real_http_server_from_another_directory(deployment,tmp_path):
    package,env=deployment
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
    log=tmp_path/'process.log'
    with log.open('wb') as output:
        process=subprocess.Popen([sys.executable,str(package/'web_main.py'),'--port',str(port)],cwd=tmp_path,env=env,stdout=output,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+15;health=None
            while time.monotonic()<deadline and process.poll() is None:
                try:
                    with urlopen(f'http://127.0.0.1:{port}/health',timeout=.5) as response:health=json.load(response)
                    break
                except (URLError,OSError):time.sleep(.1)
            assert health and health['status']=='ok' and health['storage']=='demo',log.read_text(encoding='utf-8')
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)

@pytest.mark.parametrize('statement,cwd_kind',[
    ('from pt_ai_square.web_main import app','parent'),
    ('from web_main import app','package'),
])
def test_wsgi_import_still_exports_app(deployment,statement,cwd_kind):
    package,env=deployment
    result=subprocess.run([sys.executable,'-c',statement+"; assert app.test_client().get('/health').json['status']=='ok'"],cwd=package.parent if cwd_kind=='parent' else package,env=env,capture_output=True,text=True,encoding='utf-8',timeout=10)
    assert result.returncode==0,result.stderr

def test_direct_file_keeps_mock_loopback_guard(deployment):
    package,env=deployment
    result=subprocess.run([sys.executable,str(package/'web_main.py'),'--host','0.0.0.0'],cwd=package,env=env,capture_output=True,text=True,encoding='utf-8',timeout=10)
    assert result.returncode==2 and 'mock' in result.stderr
