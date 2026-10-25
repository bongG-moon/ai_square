"""Small allowlisted HTTP client. Redirects never receive the personal KEY."""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import AuthenticationRequired, SquareError, no_links

MAX_FILE_BYTES = 128 * 1024 * 1024
ENDPOINTS = re.compile(r'^/(?:api/integration/me|api/catalog(?:/options)?|api/publish-targets|api/tools/[1-9][0-9]*(?:/manifest|/version-check)?|api/publish-drafts(?:/[a-f0-9-]+(?:/commit)?)?|download/[1-9][0-9]*/[1-9][0-9]*)$')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def positive(value):
    if type(value) is not int or not 1 <= value <= 999999999:
        raise SquareError('도구 ID와 배포 번호는 양의 정수여야 합니다.')
    return value


def automatic_download_directory(settings, manifest):
    """Separate the same tool/version IDs on different company/test servers."""
    server = hashlib.sha256(settings.url.encode('utf-8')).hexdigest()[:12]
    return no_links(settings.downloads / ('server-' + server)
                    / f'tool-{positive(manifest.get("toolId"))}'
                    / f'v{positive(manifest.get("release"))}')


class Client:
    def __init__(self, settings, opener=None):
        self.settings = settings
        self.url = settings.url
        self.opener = opener or build_opener(NoRedirect())

    def open(self, path, method='GET', body=None, content_type=None):
        parsed = urlsplit(path)
        if (parsed.scheme or parsed.netloc or parsed.fragment or '\\' in path
                or any(ord(c) < 32 for c in path) or not ENDPOINTS.fullmatch(parsed.path)):
            raise SquareError('허용되지 않은 API 경로입니다.')
        if method not in {'GET', 'POST'} or (method == 'POST' and not parsed.path.startswith('/api/publish-drafts')):
            raise SquareError('허용되지 않은 API 작업입니다.')
        headers = {'Authorization': 'Bearer ' + self.settings.token(), 'Accept': 'application/json,application/octet-stream',
                   'User-Agent': 'PT-AI-SQUARE-MCP/1'}
        if content_type:
            headers['Content-Type'] = content_type
        try:
            return self.opener.open(Request(self.url + path, body, headers, method=method), timeout=30)
        except HTTPError as error:
            code = error.code
            error.close()
            if code == 401:
                raise AuthenticationRequired(self.url) from None
            messages = {403: '이 KEY의 권한 또는 본인 도구 여부를 확인하세요. KEY 재발급 전의 게시 초안은 새 KEY로 다시 준비하고 웹에서 승인하세요.',
                        404: '도구·버전·게시 초안을 찾을 수 없습니다.',
                        409: '승인 대기·내용 변경·버전 충돌입니다. 초안 상태와 웹 확인 화면을 확인하세요.',
                        413: '파일이 서버 업로드 한도를 초과했습니다.',
                        429: '요청이 많습니다. 잠시 후 다시 시도하세요.'}
            if 300 <= code < 400:
                raise SquareError('서버가 다른 주소로 이동하라고 응답했습니다. KEY 보호를 위해 이동하지 않았습니다.') from None
            raise SquareError(messages.get(code, f'서버 요청 실패 (HTTP {code}). KEY나 원문 오류는 출력하지 않습니다.')) from None
        except (URLError, OSError, TimeoutError):
            raise SquareError('서버에 연결하지 못했습니다. 주소·사내망·인증서를 확인하세요.') from None

    def json(self, path, method='GET', data=None):
        body = json.dumps(data, ensure_ascii=False).encode() if data is not None else None
        with self.open(path, method, body, 'application/json' if body is not None else None) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise SquareError('서버 응답이 너무 큽니다.')
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise SquareError('서버 JSON 응답을 읽지 못했습니다.') from None
        if not isinstance(value, dict):
            raise SquareError('서버 응답은 JSON 객체여야 합니다.')
        return value

    def draft(self, metadata, artifact=None):
        boundary = 'square-' + uuid.uuid4().hex
        body = bytearray((f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n'
                          + json.dumps(metadata, ensure_ascii=False) + '\r\n').encode())
        if artifact:
            artifact = no_links(artifact)
            if artifact.stat().st_size > MAX_FILE_BYTES:
                raise SquareError('MCP 파일 준비 한도는 128 MiB입니다. 더 큰 파일은 웹을 사용하세요.')
            # User supplied filenames cannot inject multipart headers.
            filename = 'artifact' + artifact.suffix.lower()
            body.extend((f'--{boundary}\r\nContent-Disposition: form-data; name="artifact"; filename="{filename}"\r\n'
                         'Content-Type: application/octet-stream\r\n\r\n').encode())
            body.extend(artifact.read_bytes())
            body.extend(b'\r\n')
        body.extend(f'--{boundary}--\r\n'.encode())
        with self.open('/api/publish-drafts', 'POST', bytes(body), 'multipart/form-data; boundary=' + boundary) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise SquareError('게시 초안 응답이 너무 큽니다.')
        try:
            result = json.loads(raw)
        except ValueError:
            raise SquareError('게시 초안 응답을 읽지 못했습니다.') from None
        if not isinstance(result, dict):
            raise SquareError('게시 초안 응답을 읽지 못했습니다.')
        return result

    def manifest(self, tool_id):
        tool_id = positive(tool_id)
        manifest = self.json(f'/api/tools/{tool_id}/manifest')
        if manifest.get('toolId') != tool_id:
            raise SquareError('배포 정보의 도구 ID가 다릅니다.')
        positive(manifest.get('release'))
        return manifest

    def download(self, manifest, directory, *, update=False):
        tool_id, release = positive(manifest.get('toolId')), positive(manifest.get('release'))
        url = f'/download/{tool_id}/{release}'
        if not manifest.get('downloadUrl'):
            raise SquareError('파일이 없는 항목입니다. 상세의 연결·설치 안내를 확인하세요.')
        if manifest['downloadUrl'] != url:
            raise SquareError('배포 파일 경로가 올바르지 않습니다.')
        size, sha = manifest.get('bytes'), manifest.get('sha256')
        if type(size) is not int or not 0 < size <= MAX_FILE_BYTES or not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
            raise SquareError('파일의 크기·무결성 정보를 확인할 수 없거나 128 MiB 한도를 초과합니다.')
        suffix = Path(str(manifest.get('filename', ''))).suffix.lower()
        if suffix not in {'.md', '.zip', '.axextension', '.exe', '.msi', '.ps1'}:
            raise SquareError('지원하지 않는 배포 파일 형식입니다.')
        directory = no_links(directory)
        directory.mkdir(parents=True, exist_ok=True)
        target = no_links(directory / f'tool-{tool_id}-v{release}{suffix}')
        if target.exists():
            # Reuse a verified already downloaded file; do not count an artificial second transfer.
            if target.stat().st_size == size and hashlib.sha256(target.read_bytes()).hexdigest() == sha:
                return target
            raise SquareError('대상에 다른 내용의 파일이 있습니다. 새 폴더를 선택하세요.')
        part = no_links(directory / (uuid.uuid4().hex + '.part'))
        try:
            received, digest = 0, hashlib.sha256()
            with part.open('xb') as f, self.open(url + ('?purpose=update' if update else '')) as response:
                while chunk := response.read(1024 * 1024):
                    received += len(chunk)
                    if received > size:
                        raise SquareError('수신 파일이 선언된 크기를 초과합니다.')
                    f.write(chunk)
                    digest.update(chunk)
                f.flush()
                os.fsync(f.fileno())
            if received != size or digest.hexdigest() != sha:
                raise SquareError('파일 SHA-256 또는 크기가 다릅니다. 설치하지 않았습니다.')
            current = self.manifest(tool_id)
            if (current.get('release'), current.get('sha256'), current.get('installProfile')) != (release, sha, manifest.get('installProfile')):
                raise SquareError('다운로드 중 배포 정보가 바뀌었습니다. 다시 준비하세요.')
            if os.name == 'nt':
                os.rename(part, target)
            else:
                os.link(part, target)
        finally:
            part.unlink(missing_ok=True)
        return target
