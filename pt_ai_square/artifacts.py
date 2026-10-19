import hashlib
import stat
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from flask import current_app
from werkzeug.exceptions import BadRequest

def stage_upload(upload):
    if not upload or not upload.filename: raise BadRequest('공유 파일을 선택해 주세요.')
    name=upload.filename.replace('\\','/').split('/')[-1]
    if not name or len(name)>180 or any(ord(c)<32 for c in name): raise BadRequest('파일 이름을 확인해 주세요.')
    ext=Path(name).suffix.lower()
    if ext not in {'.zip','.exe','.msi','.ps1'}: raise BadRequest('ZIP, EXE, MSI, PS1 파일을 등록해 주세요.')
    directory=Path(current_app.config['DATA_DIR'])/'artifacts'
    path=directory/(uuid.uuid4().hex+ext)
    try:
        upload.save(path)
        size=path.stat().st_size
        if not size: raise BadRequest('빈 파일은 등록할 수 없습니다.')
        with path.open('rb') as f: prefix=f.read(8)
        if ext=='.exe' and not prefix.startswith(b'MZ'): raise BadRequest('EXE 파일 형식을 확인해 주세요.')
        if ext=='.msi' and prefix!=bytes.fromhex('d0cf11e0a1b11ae1'): raise BadRequest('MSI 파일 형식을 확인해 주세요.')
        if ext=='.ps1':
            raw=path.read_bytes()
            try: raw.decode('utf-16' if raw[:2] in (b'\xff\xfe',b'\xfe\xff') else 'utf-8-sig')
            except UnicodeError: raise BadRequest('PS1은 UTF-8 또는 BOM이 있는 UTF-16으로 저장해 주세요.')
        if ext=='.zip':
            try:
                with zipfile.ZipFile(path) as z:
                    entries=z.infolist()
                    if not entries or len(entries)>5000 or sum(i.file_size for i in entries)>512*1024*1024:
                        raise BadRequest('ZIP 파일 수 또는 압축 해제 용량 제한을 초과했습니다.')
                    for entry in entries:
                        n=entry.filename.replace('\\','/')
                        if n.startswith('/') or '..' in PurePosixPath(n).parts or ':' in n or stat.S_ISLNK(entry.external_attr>>16) or entry.flag_bits&1:
                            raise BadRequest('ZIP의 경로·링크·암호화 항목을 확인해 주세요.')
                        if entry.file_size>max(entry.compress_size,1)*200: raise BadRequest('ZIP 압축률이 허용 범위를 초과했습니다.')
                    if z.testzip(): raise BadRequest('손상된 ZIP 파일입니다.')
            except (zipfile.BadZipFile,RuntimeError,NotImplementedError): raise BadRequest('읽을 수 없는 ZIP 파일입니다.')
        with path.open('rb') as f: sha=hashlib.file_digest(f,'sha256').hexdigest()
        return dict(path=path.name,name=name,size=size,sha=sha,url='',ext=ext)
    except Exception:
        path.unlink(missing_ok=True)
        raise

def artifact_path(name):
    root=(Path(current_app.config['DATA_DIR'])/'artifacts').resolve()
    path=(root/name).resolve()
    if path.parent!=root: raise BadRequest('유효하지 않은 파일 경로입니다.')
    return path

def used_bytes():
    root=Path(current_app.config['DATA_DIR'])
    return sum(p.stat().st_size for folder in ['artifacts','request_attachments'] for p in (root/folder).glob('*') if p.is_file())
