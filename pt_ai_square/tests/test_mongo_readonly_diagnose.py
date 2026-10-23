"""Diagnostics exercise the same client factory without creating app data."""
from types import SimpleNamespace
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
from pymongo.errors import OperationFailure
from pt_ai_square.scripts import diagnose_mongo as diagnostic
from .test_entrypoint import deployment


def test_allowlisted_readonly_commands_and_no_private_fields(monkeypatch):
    calls=[]
    class Client:
        options=SimpleNamespace(retry_writes=False)
        @property
        def admin(self):return self
        def command(self,command):
            calls.append(command)
            return {'ok':1,'maxWireVersion':13,'logicalSessionTimeoutMinutes':30,
                    'setName':'private-replica','hosts':['private-host'],'version':'5.0.11-10'}
        def close(self):calls.append('close')
    config={'MONGODB_RETRY_WRITES':False}
    def factory(value): assert value is config;return Client()
    monkeypatch.setattr(diagnostic,'mongo_client',factory)
    r=diagnostic.diagnose(config)
    assert calls==['ping','hello','buildInfo','close']
    assert r==dict(retryWrites=False,ping='ok',maxWireVersion=13,sessionsSupported=True,
                   replicaSet=True,router=False,version='5.0.11-10',errors=[])
    assert 'private' not in str(r)


@pytest.mark.parametrize('failed_command',['ping','hello','buildInfo'])
def test_diagnostic_errors_are_redacted_and_remaining_checks_run(monkeypatch,failed_command):
    calls=[]
    class Client:
        options=SimpleNamespace(retry_writes=False)
        @property
        def admin(self):return self
        def command(self,command):
            calls.append(command)
            if command==failed_command:raise OperationFailure('private-password-and-host',13,{'errmsg':'private'})
            return {'ok':1}
        def close(self):calls.append('close')
    monkeypatch.setattr(diagnostic,'mongo_client',lambda _:Client())
    result=diagnostic.diagnose({})
    assert result['errors']==[{'command':failed_command,'code':'DB-PERMISSION','mongoCode':13}]
    assert 'private' not in str(result)
    assert calls==['ping','hello','buildInfo','close']


def test_configuration_failure_has_no_traceback_or_credentials(monkeypatch,capsys):
    def fail():raise ValueError('private connection string')
    monkeypatch.setattr(diagnostic,'settings',fail)
    assert diagnostic.main()==2
    output=capsys.readouterr()
    assert 'private' not in output.out+output.err and not output.err


def test_actual_diagnostic_is_readonly_and_uses_existing_app_options(app):
    client=app.extensions['square_mongo_client']
    database=client[app.config['MONGODB_DATABASE']]
    before={name:database[name].count_documents({}) for name in database.list_collection_names()}
    result=diagnostic.diagnose(app.config)
    assert result['ping']=='ok' and result['retryWrites'] is False
    assert result['sessionsSupported'] is True and result['replicaSet'] is True
    after={name:database[name].count_documents({}) for name in database.list_collection_names()}
    assert before==after


def test_diagnostic_script_runs_from_a_renamed_standalone_folder(deployment,tmp_path,app):
    package,env=deployment
    source=Path(diagnostic.__file__).parent
    (package/'scripts').mkdir()
    for name in ('__init__.py','diagnose_mongo.py'):
        shutil.copy2(source/name,package/'scripts'/name)
    renamed=package.with_name('회사 웹 운영 복사본');package.rename(renamed)
    env.update(MONGODB_URI=app.config['MONGODB_URI'],MONGODB_DATABASE=app.config['MONGODB_DATABASE'],
               PTAI_MONGODB_RETRY_WRITES='false')
    result=subprocess.run([sys.executable,str(renamed/'scripts/diagnose_mongo.py')],
                           cwd=tmp_path,env=env,capture_output=True,text=True,encoding='utf-8',timeout=15)
    assert result.returncode==0,result.stderr
    payload=json.loads(result.stdout)
    assert payload['ping']=='ok' and payload['retryWrites'] is False
    assert app.config['MONGODB_URI'] not in result.stdout+result.stderr
