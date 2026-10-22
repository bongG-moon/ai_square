"""File-store capacity policy. MongoDB holds settings; the DATA_DIR volume holds bytes."""
import errno
import shutil
import threading
import time
from pathlib import Path
from flask import current_app
from werkzeug.exceptions import Conflict, ServiceUnavailable, HTTPException


class InsufficientStorage(HTTPException):
    code = 507
    description = '서버 저장 공간이 부족합니다.'

# The normal Waitress deployment uses one process with multiple threads.
# This lock prevents competing in-process writes from using the same allowance.
# Multiple processes/servers need a filesystem quota for an exact shared hard cap.
WRITE_LOCK = threading.RLock()


def policy():
    row = current_app.extensions['square_mongo'].settings.find_one({'_id': 'storage_limits'}) or {}
    return dict(mode=row.get('mode', 'manual'),
                quotaBytes=row.get('quotaBytes', current_app.config['STORAGE_QUOTA']),
                reserveBytes=row.get('reserveBytes', current_app.config.get('STORAGE_RESERVE', 1024**3)),
                revision=row.get('revision', 0),
                source='admin' if row else 'config')


def disk_status():
    try:
        disk = shutil.disk_usage(Path(current_app.config['DATA_DIR']).resolve())
        return dict(diskKnown=True, diskTotal=disk.total, diskFree=disk.free, diskUsed=disk.used)
    except OSError:
        return dict(diskKnown=False, diskTotal=None, diskFree=None, diskUsed=None)


def snapshot():
    from .artifacts import used_bytes
    p = policy()
    used = used_bytes()
    disk = disk_status()
    disk_available = max(0, disk['diskFree'] - p['reserveBytes']) if disk['diskKnown'] else None
    quota = p['quotaBytes'] if p['mode'] == 'manual' else used + disk_available if disk_available is not None else None
    available = min(max(0, quota-used), disk_available) if disk_available is not None else None
    return dict(used=used, quota=quota, available=available, mode=p['mode'],
                configuredQuota=p['quotaBytes'], reserve=p['reserveBytes'],
                limitRevision=p['revision'], source=p['source'], checkedAt=time.time(),
                overLimit=bool((p['mode']=='manual' and used>p['quotaBytes']) or
                               (disk['diskKnown'] and disk['diskFree']<p['reserveBytes'])),
                **disk)


def save_upload(upload, path, max_bytes=None):
    """Check the allowance before storing bytes; callers remove partial files on error."""
    from werkzeug.exceptions import RequestEntityTooLarge
    with WRITE_LOCK:
        state = snapshot()
        if not state['diskKnown']:
            raise ServiceUnavailable('서버 디스크의 여유 공간을 확인할 수 없습니다. 관리자에게 알려주세요.')
        budget = state['available']
        size = 0
        try:
            with path.open('xb') as output:
                while chunk := upload.stream.read(1024*1024):
                    size += len(chunk)
                    if max_bytes and size > max_bytes:
                        raise RequestEntityTooLarge('첨부파일 하나당 최대 20MB입니다.')
                    if size > budget:
                        raise Conflict('저장 한도 또는 서버의 확보할 여유 공간에 도달했습니다. 관리자에게 용량 조정·파일 정리를 요청하세요.')
                    disk = disk_status()
                    if not disk['diskKnown']:
                        raise ServiceUnavailable('서버 디스크 여유 공간을 확인할 수 없어 업로드를 중단했습니다.')
                    if disk['diskFree']-len(chunk) < state['reserve']:
                        raise InsufficientStorage('서버에 남겨둘 여유 공간이 부족합니다.')
                    output.write(chunk)
        except OSError as error:
            if error.errno in {errno.ENOSPC, errno.EDQUOT}:
                raise InsufficientStorage('서버 디스크가 가득 찼거나 파일시스템 용량 한도에 도달했습니다.') from None
            raise
        # Apply settings changed while an upload was in flight, too.
        latest = snapshot()
        if not latest['diskKnown']:
            raise ServiceUnavailable('서버 디스크 상태를 확인할 수 없습니다.')
        if latest['overLimit']:
            raise Conflict('현재 저장 한도 또는 여유 공간 기준을 초과했습니다. 설정을 확인해 주세요.')
        return size
