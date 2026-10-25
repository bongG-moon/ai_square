"""Connect using the website-bound package and a single privately entered KEY."""
import os
from pathlib import Path
from types import SimpleNamespace
import uuid

from .client import Client
from .config import (DEFAULT_CONFIG, TOKEN_RE, SquareError, ConnectionCancelled, ConnectionChanged, UNSET_CONNECTION_STATE,
                     connection_fingerprint, default_download_directory,
                     no_links, normalize_url, operation_lock, read_json, save_config)


PACKAGE_MANIFEST = Path(__file__).resolve().parent.parent / 'connection.json'


def resolve_connection(config_path=DEFAULT_CONFIG, override_url=None, *, manifest_path=None):
    """Explicit advanced override, then this package's origin, then saved settings.

    A present but malformed package must never silently select a different site.
    Only the small public origin manifest is read; there is no network discovery.
    """
    if override_url is not None:
        return normalize_url(override_url)
    manifest_path = no_links(PACKAGE_MANIFEST if manifest_path is None else manifest_path)
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if (type(manifest.get('schemaVersion')) is not int or manifest['schemaVersion'] != 1
                or set(manifest) != {'schemaVersion', 'baseUrl'}):
            raise SquareError('MCP 연결 정보가 올바르지 않습니다. 웹사이트에서 MCP를 다시 받으세요.')
        return normalize_url(manifest.get('baseUrl'))
    config_path = no_links(config_path)
    if config_path.exists():
        return normalize_url(read_json(config_path).get('baseUrl'))
    raise SquareError('서버 주소가 포함되지 않은 공용 ZIP입니다. AI SQUARE 웹의 로컬 MCP 받기에서 다시 받으세요. 고급 설정에서는 --url을 지정할 수 있습니다.')


def _identity(response):
    """Reject unrelated 200 pages and emit only actual account/key metadata."""
    if not isinstance(response, dict):
        raise SquareError('계정 연결 응답을 확인하지 못했습니다.')
    user, key = response.get('user'), response.get('key')
    if not isinstance(user, dict) or not isinstance(key, dict):
        raise SquareError('계정 연결 응답을 확인하지 못했습니다.')
    if key.get('scope') not in {'read', 'publish'}:
        raise SquareError('KEY의 허용 작업을 확인하지 못했습니다.')
    def field(source, name, limit, required=False):
        value = source.get(name, '')
        if (not isinstance(value, str) or len(value) > limit or (required and not value.strip())
                or TOKEN_RE.search(value) or any(ord(c) < 32 for c in value)):
            raise SquareError('계정 연결 응답을 확인하지 못했습니다.')
        return value
    safe_user = {name: field(user, name, limit, required)
                 for name, limit, required in [('id',100,True),('name',100,True),
                                              ('dept',200,False),('dept_cd',100,False)]}
    safe_key = {'id': field(key, 'id', 100, True), 'scope': key['scope']}
    return safe_user, safe_key


def connect(config_path, url, token=None, roots=None, *, allow_http=False,
            token_from_env=False, client_factory=None,
            expected_state=UNSET_CONNECTION_STATE, cancel_event=None):
    """Authenticate first, then create managed downloads and commit private settings.

    A wrong KEY, unreachable server or invalid identity never replaces a working
    configuration or credential. New encrypted files use generation names; the
    final atomic config replacement is the credential cutover.
    """
    url = normalize_url(url)
    if url.startswith('http:') and not allow_http:
        raise SquareError('HTTP 연결은 전송이 암호화되지 않음을 먼저 확인하세요.')
    if token_from_env:
        if token is not None:
            raise SquareError('KEY 입력과 환경변수 방식 중 하나만 선택하세요.')
        candidate = os.environ.get('PTAI_API_TOKEN', '')
    else:
        candidate = token
    if not isinstance(candidate, str) or not TOKEN_RE.fullmatch(candidate):
        raise SquareError('연결 KEY 형식을 확인하세요.')
    if roots is not None and not isinstance(roots, (list, tuple)):
        raise SquareError('추가 작업 폴더 목록을 확인하세요.')
    config_path = no_links(config_path)
    def check_pending_connection():
        if cancel_event is not None and cancel_event.is_set():
            raise ConnectionCancelled('개인 KEY 연결 요청이 취소되었습니다. 기존 연결 설정은 유지됩니다.')
        if (expected_state is not UNSET_CONNECTION_STATE
                and connection_fingerprint(config_path) != expected_state):
            raise ConnectionChanged('연결을 확인하는 동안 설정이 변경되었습니다. 기존 설정을 덮어쓰지 않았습니다. 연결 상태를 확인한 뒤 다시 요청하세요.')
    check_pending_connection()
    # This transient object contains no persisted values and cannot print the KEY.
    candidate_settings = SimpleNamespace(url=url, token=lambda: candidate)
    user, key = _identity((client_factory or Client)(candidate_settings).json('/api/integration/me'))
    downloads = default_download_directory()
    with operation_lock(config_path.parent):
        check_pending_connection()
        retained = []
        if config_path.exists():
            old = read_json(config_path)
            if normalize_url(old.get('baseUrl')) == url:
                retained = old.get('trustedRoots', [])
                if not isinstance(retained, list):
                    raise SquareError('기존 작업 폴더 설정을 확인하세요.')
        chosen = []
        for value in [*retained, *(roots or [])]:
            if not isinstance(value, (str, Path)):
                raise SquareError('작업 폴더 경로를 확인하세요.')
            path = no_links(value)
            if path == downloads:
                # The managed directory is recreated below if the user removed
                # it between connections; no extra source access is introduced.
                continue
            if path == Path(path.anchor) or not path.is_dir():
                raise SquareError('기존 또는 추가 작업 폴더를 확인하세요. 드라이브 전체는 허용하지 않습니다.')
            if path not in chosen:
                chosen.append(path)
        downloads.mkdir(parents=True, exist_ok=True)
        downloads = no_links(downloads)
        if downloads not in chosen:
            chosen.append(downloads)
        credential_name = 'credential.' + uuid.uuid4().hex + '.dpapi.json'
        try:
            check_pending_connection()
            data = save_config(config_path, url, chosen, None if token_from_env else candidate,
                               allow_http=allow_http, download_directory=downloads,
                               credential_name=credential_name,
                               before_commit=check_pending_connection)
        except Exception:
            # Only this new, unreferenced generation may be removed. The previous
            # credential/config remains authoritative if the config write failed.
            (config_path.parent / credential_name).unlink(missing_ok=True)
            raise
    return {'connected': True, 'configured': True, 'baseUrl': url,
            'user': user, 'key': key, 'downloadDirectory': str(downloads),
            'config': str(config_path), 'credentialStored': data['credentialRef'].split(':')[0],
            'encryptedTransport': url.startswith('https:')}
