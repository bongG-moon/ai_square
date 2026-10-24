"""Explicit server origin / workspace configuration and Windows DPAPI credentials."""
import base64
import ctypes
import json
import os
from pathlib import Path
import re
import stat
from contextlib import contextmanager
from urllib.parse import urlsplit

DEFAULT_CONFIG = Path.home() / '.pt-ai-square' / 'mcp' / 'config.json'
TOKEN_RE = re.compile(r'ptsq_[A-Za-z0-9_-]{43}')
CREDENTIAL_FILE_RE = re.compile(r'credential(?:\.[a-f0-9]{32})?\.dpapi\.json')


def default_download_directory():
    """User-owned data survives replacing or moving the MCP program folder."""
    return no_links(Path.home() / 'AI_SQUARE' / 'downloads')


class SquareError(ValueError):
    """User-facing error that never contains a credential or raw server body."""


def normalize_url(value):
    if not isinstance(value, str) or any(ord(c) <= 32 for c in value) or '\\' in value:
        raise SquareError('서버 주소를 확인하세요.')
    try:
        p = urlsplit(value)
        port = p.port
    except ValueError:
        raise SquareError('서버 주소를 확인하세요.') from None
    if p.scheme not in {'http', 'https'} or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in {'', '/'}:
        raise SquareError('서버 주소는 인증정보·경로·쿼리 없는 HTTP(S) origin이어야 합니다.')
    host = p.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    return p.scheme + '://' + host + ((':' + str(port)) if port and port != (80 if p.scheme == 'http' else 443) else '')


def no_links(path):
    """Reject all existing symlink/reparse components, including Windows junctions."""
    path = Path(os.path.abspath(Path(path).expanduser()))
    for part in [path, *path.parents]:
        try:
            attrs = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(attrs.st_mode) or getattr(attrs, 'st_file_attributes', 0) & 0x400:
            raise SquareError('링크·junction 경로에는 접근할 수 없습니다.')
    return path.resolve()


def scoped_path(value, roots, *, existing=False):
    path = no_links(value)
    if not any(path == root or root in path.parents for root in roots):
        raise SquareError('허용된 작업 폴더 안의 경로만 사용할 수 있습니다. 다른 원본·프로젝트 폴더는 select_workspace에서 직접 선택하세요.')
    if existing and not path.exists():
        raise SquareError('선택한 파일 또는 폴더가 없습니다.')
    return path


def atomic_json(path, data):
    path = no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.new')
    no_links(temp)
    with temp.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


@contextmanager
def operation_lock(directory):
    """Serialize shared local state across multiple AI-host MCP processes."""
    directory=no_links(directory);directory.mkdir(parents=True,exist_ok=True)
    lockfile=no_links(directory/'operation.lock')
    with lockfile.open('a+b') as handle:
        handle.seek(0,os.SEEK_END)
        if handle.tell()==0:
            handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            raise SquareError('다른 AI 프로그램에서 로컬 작업을 처리 중입니다. 완료 후 다시 시도하세요.') from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name=='nt':
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def read_json(path):
    path = no_links(path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise SquareError('설정 파일이 너무 큽니다.')
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError, UnicodeError):
        raise SquareError('JSON 파일 형식을 확인하세요.') from None
    if not isinstance(value, dict):
        raise SquareError('JSON 객체가 필요합니다.')
    return value


def protect(data, decrypt=False):
    if os.name != 'nt':
        raise SquareError('영구 KEY 저장은 Windows DPAPI만 지원합니다. 다른 OS에서는 PTAI_API_TOKEN 환경변수를 사용하세요.')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    out = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.restype = wintypes.BOOL
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(out)):
        raise SquareError('현재 Windows 사용자로 KEY 보관함을 사용할 수 없습니다.')
    try:
        return ctypes.string_at(out.data, out.size)
    finally:
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(ctypes.cast(out.data, ctypes.c_void_p))


def save_config(path, url, roots, token=None, allow_http=False, *, download_directory=None,
                credential_name='credential.dpapi.json'):
    url = normalize_url(url)
    if url.startswith('http:') and not allow_http:
        raise SquareError('HTTP의 KEY·파일 전송이 암호화되지 않음을 확인하고 정확한 주소를 승인해야 합니다.')
    paths = [no_links(p) for p in roots]
    if not paths or any(not p.is_dir() or p == Path(p.anchor) for p in paths):
        raise SquareError('존재하는 작업 폴더를 하나 이상 지정하세요. 드라이브 전체는 허용하지 않습니다.')
    path = no_links(path)
    data = dict(schemaVersion=1, baseUrl=url, acceptedHttpOrigin=url if allow_http and url.startswith('http:') else None,
                trustedRoots=[str(p) for p in paths], credentialRef='environment:PTAI_API_TOKEN')
    if download_directory is not None:
        directory = scoped_path(download_directory, paths, existing=True)
        if not directory.is_dir():
            raise SquareError('다운로드 폴더를 확인하세요.')
        data['downloadDirectory'] = str(directory)
    if token:
        if not TOKEN_RE.fullmatch(token):
            raise SquareError('연결 KEY 형식을 확인하세요.')
        if not CREDENTIAL_FILE_RE.fullmatch(credential_name):
            raise SquareError('KEY 보관 파일 이름을 확인하세요.')
        # Binding inside the encrypted payload prevents accidental credential reuse after editing the URL.
        secret = protect(json.dumps(dict(origin=url, token=token)).encode())
        atomic_json(path.parent / credential_name, {'encrypted': base64.b64encode(secret).decode()})
        data['credentialRef'] = 'windows-dpapi:' + credential_name
    atomic_json(path, data)
    return data


class Settings:
    def __init__(self, path=DEFAULT_CONFIG):
        self.path = no_links(path)
        self.data = read_json(self.path)
        self.url = normalize_url(self.data.get('baseUrl'))
        if self.url.startswith('http:') and self.data.get('acceptedHttpOrigin') != self.url:
            raise SquareError('현재 HTTP 주소에 대한 사용자 확인이 없습니다. setup을 다시 실행하세요.')
        self.roots = [no_links(p) for p in self.data.get('trustedRoots', [])]
        if not self.roots or any(not p.is_dir() or p == Path(p.anchor) for p in self.roots):
            raise SquareError('허용된 작업 폴더 설정을 확인하세요.')
        self.downloads = (scoped_path(self.data['downloadDirectory'], self.roots)
                          if 'downloadDirectory' in self.data else default_download_directory())
        self.state = no_links(self.path.parent / 'state')

    def token(self):
        ref = self.data.get('credentialRef')
        if ref == 'environment:PTAI_API_TOKEN':
            token = os.environ.get('PTAI_API_TOKEN', '')
        elif isinstance(ref, str) and ref.startswith('windows-dpapi:') and CREDENTIAL_FILE_RE.fullmatch(ref.split(':', 1)[1]):
            try:
                raw = read_json(self.path.parent / ref.split(':', 1)[1])['encrypted']
                secret = json.loads(protect(base64.b64decode(raw, validate=True), decrypt=True))
                if secret.get('origin') != self.url:
                    raise SquareError('KEY가 연결된 서버와 설정 주소가 다릅니다. setup을 다시 실행하세요.')
                token = secret['token']
            except (KeyError, ValueError, UnicodeError):
                raise SquareError('KEY 보관함을 읽지 못했습니다. setup을 다시 실행하세요.') from None
        else:
            raise SquareError('알 수 없는 KEY 보관 방식입니다.')
        if not TOKEN_RE.fullmatch(token):
            raise SquareError('연결 KEY가 없습니다. setup으로 연결하고 웹 /local-access에서 발급하세요.')
        return token
