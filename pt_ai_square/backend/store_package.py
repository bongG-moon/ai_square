"""Download the optional desktop extension with a server-only connection preset.

The Windows installer is built ahead of deployment. Download requests never
compile or patch the executable, include user credentials, or change disk state.
"""
from io import BytesIO
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile, ZipInfo, ZIP_STORED

from flask import current_app, send_file
from werkzeug.exceptions import ServiceUnavailable

from .mcp_package import normalize_origin, service_origin


INSTALLER_NAME = 'PNT-AI-Square-Setup.exe'
MANIFEST = 'connection.json'
SOURCE_NAME = 'ax-workspace-extension-setup.exe'
MAX_INSTALLER_BYTES = 16 * 1024 * 1024
README = '''P&T AI Square — AX Workspace 선택 설치 확장

1. 확장 연결부를 지원하는 AX Workspace가 먼저 설치되어 있어야 합니다.
2. 이 ZIP의 모든 파일을 같은 폴더에 압축 해제하세요.
3. PNT-AI-Square-Setup.exe를 실행하세요. connection.json도 같은 폴더에 두세요.
4. AX Workspace를 완전히 종료한 뒤 다시 열고 P&T AI Square 메뉴를 선택하세요.
5. 서버 주소는 다운로드한 사이트로 자동 설정됩니다. 웹에서 발급받은 개인 KEY만 입력하세요.
   HTTP 사이트는 KEY가 암호화되지 않은 통신으로 전송된다는 안내를 한 번 확인해야 합니다.

이 설치 파일은 공통 AX Workspace 앱이나 로컬 MCP 설치 파일과 다릅니다.
사이트 주소만 포함하며 개인 KEY, 계정 정보, MongoDB 접속 정보는 포함하지 않습니다.
기존에 연결한 서버와 KEY는 자동 교체하지 않습니다. 연결 화면에서 주소를 확인하세요.
'''


def connection_origin(value):
    origin = normalize_origin(value)
    try:
        address = ipaddress.ip_address(urlsplit(origin).hostname)
    except ValueError:
        address = None
    if address is not None and address.is_unspecified:
        raise ValueError('A listening address is not a connection origin')
    return origin


def package_for_origin(source, origin):
    """Return a bounded request-local ZIP with the original installer bytes."""
    origin = connection_origin(origin)
    source = Path(source)
    try:
        if source.is_symlink() or not source.is_file():
            raise OSError('Missing installer')
        with source.open('rb') as stream:
            installer = stream.read(MAX_INSTALLER_BYTES + 1)
        if not 2 < len(installer) <= MAX_INSTALLER_BYTES or not installer.startswith(b'MZ'):
            raise ValueError('Invalid installer')
    except (OSError, ValueError):
        raise ServiceUnavailable('P&T AI Square 확장 설치 파일이 준비되지 않았습니다. 운영자에게 알려주세요.') from None
    output = BytesIO()
    entries = {
        INSTALLER_NAME: installer,
        MANIFEST: json.dumps({'schemaVersion': 1, 'baseUrl': origin}, ensure_ascii=False,
                             indent=2).encode('utf-8'),
        'README.txt': README.encode('utf-8'),
    }
    # The installer is already compressed. ZIP_STORED avoids repeating costly
    # compression for each download while keeping its signature/hash intact.
    with ZipFile(output, 'w', ZIP_STORED) as archive:
        for name, data in entries.items():
            info = ZipInfo(name, (2026, 10, 25, 0, 0, 0))
            info.compress_type = ZIP_STORED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    output.seek(0)
    return output


def download_package():
    try:
        origin = connection_origin(service_origin())
    except (ValueError, ServiceUnavailable):
        raise ServiceUnavailable('확장 연결 주소를 만들지 못했습니다. 운영자가 PTAI_PUBLIC_URL에 사용자가 접속하는 사이트 주소를 설정해 주세요.') from None
    source = Path(current_app.static_folder) / 'guides' / SOURCE_NAME
    output = package_for_origin(source, origin)
    response = send_file(output, mimetype='application/zip', as_attachment=True,
                         download_name='PNT-AI-Square-AX-Extension.zip',
                         conditional=False, etag=False)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Cookie'
    return response
