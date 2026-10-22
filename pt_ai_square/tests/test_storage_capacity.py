import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from pt_ai_square.backend.storage_capacity import snapshot
from .conftest import ready, publish

GB=1024**3
MB=1024**2

def limits(c,h,**overrides):
    raw=dict(mode='manual',quotaBytes=5*GB,reserveBytes=GB,expectedRevision=0)
    raw.update(overrides)
    return c.put('/api/storage/limits',headers=h,json=raw)

def test_admin_policy_persists_precedes_config_and_conflicts(app):
    c,h=ready(app,'admin')
    with patch('pt_ai_square.backend.storage_capacity.shutil.disk_usage',return_value=SimpleNamespace(total=100*GB,used=60*GB,free=40*GB)):
        assert c.get('/api/storage/limits').json['storage']['source']=='config'
        result=limits(c,h,quotaBytes=20*GB,reserveBytes=10*GB)
        assert result.status_code==200,result.json
        assert result.json['storage']['available']==20*GB
        app.config['STORAGE_QUOTA']=GB
        assert c.get('/api/bootstrap').json['storage']['quota']==20*GB
        assert limits(c,h,expectedRevision=0).status_code==409
        result=limits(c,h,mode='auto',expectedRevision=1,reserveBytes=10*GB)
        assert result.json['storage']['quota']==30*GB
        assert result.json['storage']['source']=='admin'
        assert c.get('/api/bootstrap').json['storage']['limitRevision']==2
    member,mh=ready(app,'member')
    assert member.get('/api/storage/limits').status_code==403
    assert limits(member,mh).status_code==403
    assert member.get('/api/bootstrap').json['storage'] is None
    assert c.put('/api/storage/limits',json={}).status_code==403

@pytest.mark.parametrize('override',[
    {'mode':'unlimited'},{'quotaBytes':0},{'quotaBytes':True},
    {'reserveBytes':-1},{'reserveBytes':'100'},{'expectedRevision':False},
    {'quotaBytes':2**53}
])
def test_invalid_policy(app,override):
    c,h=ready(app,'admin')
    assert limits(c,h,**override).status_code==400

def test_both_upload_paths_enforce_limit_and_keep_existing_files(app):
    c,h=ready(app,'admin')
    original=publish(c,h);assert original.status_code==201
    tid=original.json['id']
    original_bytes=c.get(f'/download/{tid}/1').data
    assert limits(c,h,quotaBytes=MB,reserveBytes=0).status_code==200
    # Fill space using a fixture file; saving a lower limit must not delete it.
    artifacts=Path(app.config['DATA_DIR'])/'artifacts'
    filler=artifacts/'fixture.bin';filler.write_bytes(b'x'*MB)
    result=limits(c,h,quotaBytes=MB,reserveBytes=0,expectedRevision=1)
    assert result.status_code==200 and result.json['storage']['overLimit']
    before=set(artifacts.iterdir())
    assert publish(c,h).status_code==409
    assert set(artifacts.iterdir())==before
    r=c.post('/api/ideas',headers=h,data={'metadata':'{"name":"첨부 검증","desc":"내용","category":"공통 업무"}','attachments':(io.BytesIO(b'example'),'example.txt')})
    assert r.status_code==409,r.json
    assert not list((Path(app.config['DATA_DIR'])/'request_attachments').glob('*'))
    assert filler.is_file() and c.get(f'/download/{tid}/1').data==original_bytes
    # Connections and commands do not consume file capacity.
    assert publish(c,h,mode='url',url='https://example.com/tool').status_code==201
    assert publish(c,h,mode='command',commandProject='tool install .').status_code==201

def test_auto_recalculates_and_disk_failure_does_not_fake_free_space(app):
    c,h=ready(app,'admin')
    assert limits(c,h,mode='auto',reserveBytes=GB).status_code==200
    with patch('pt_ai_square.backend.storage_capacity.shutil.disk_usage',return_value=SimpleNamespace(total=100*GB,used=90*GB,free=10*GB)):
        assert c.get('/api/storage/limits').json['storage']['available']==9*GB
    with patch('pt_ai_square.backend.storage_capacity.shutil.disk_usage',return_value=SimpleNamespace(total=100*GB,used=100*GB,free=GB//2)):
        assert c.get('/api/storage/limits').json['storage']['available']==0
        assert publish(c,h).status_code==409
    with patch('pt_ai_square.backend.storage_capacity.shutil.disk_usage',side_effect=OSError('unavailable')):
        s=c.get('/api/storage/limits').json['storage']
        assert s['diskKnown'] is False and s['available'] is None and s['quota'] is None
        assert publish(c,h).status_code==503
    assert not list((Path(app.config['DATA_DIR'])/'artifacts').iterdir())

def test_mid_upload_disk_exhaustion_cleans_partial_file(app):
    c,h=ready(app,'admin')
    # Snapshot succeeds, then another application consumes the reserved space.
    ample=SimpleNamespace(total=100*GB,used=50*GB,free=50*GB)
    low=SimpleNamespace(total=100*GB,used=100*GB,free=1)
    with patch('pt_ai_square.backend.storage_capacity.shutil.disk_usage',side_effect=[ample,low]):
        assert publish(c,h).status_code==507
    assert not list((Path(app.config['DATA_DIR'])/'artifacts').iterdir())
