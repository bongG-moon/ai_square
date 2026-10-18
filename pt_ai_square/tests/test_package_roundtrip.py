"""Verify bundled MD/Python resources survive publish, release and rollback."""
import hashlib
import io
import json
import zipfile
import pytest
from .conftest import ready

@pytest.mark.parametrize('kind',['Skill','MCP'])
def test_md_python_package_roundtrip(app,kind):
    client,headers=ready(app)
    metadata=dict(name=kind+' 공유 검증',desc='파일 묶음 배포 검증',owner='예시 담당자',org='공통',category='공통 업무',platform='Claude',type=kind,guide='INSTALL_GUIDE.md를 확인하세요.',environment='Python',approval=False,workTags=['문서 정리'],changes='첫 등록',mode='file')
    blobs=[]
    for version in [1,2]:
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            archive.writestr('SKILL.md' if kind=='Skill' else 'README.md',f'# {kind}\nRelease {version}\n')
            archive.writestr('scripts/processor.py',f'VERSION = {version}\n')
            archive.writestr('INSTALL_GUIDE.md','샘플 배포 검증용. 실제 시스템 호출 없음.')
        blob=buffer.getvalue();blobs.append(blob)
        if version==2:metadata['expectedRevision']=1
        result=client.post('/api/tools' if version==1 else '/api/tools/1/versions',data={'metadata':json.dumps(metadata),'artifact':(io.BytesIO(blob),'package.zip')},headers=headers)
        assert result.status_code==201 and result.json['version']==version
        manifest=client.get('/api/tools/1/manifest').json
        assert manifest['release']==version and manifest['sha256']==hashlib.sha256(blob).hexdigest()
        assert manifest['managedInstall'] is False
        downloaded=client.get(manifest['downloadUrl'])
        assert downloaded.status_code==200 and downloaded.data==blob
        with zipfile.ZipFile(io.BytesIO(downloaded.data)) as archive:assert f'VERSION = {version}' in archive.read('scripts/processor.py').decode()
    assert client.post('/api/tools/1/rollback',json={'version':1,'expectedRevision':2},headers=headers).status_code==200
    manifest=client.get('/api/tools/1/manifest').json
    assert manifest['release']==1 and manifest['updatePaused']
    assert client.get(manifest['downloadUrl']).data==blobs[0]
    assert client.get('/download/1/2').status_code==404
