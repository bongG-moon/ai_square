"""Bind the public service origin to a downloaded MCP, never a user's credential."""
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile, ZipInfo, ZIP_DEFLATED

from flask import current_app, request, send_file
from werkzeug.exceptions import ServiceUnavailable


MANIFEST = 'pt-square-mcp/connection.json'


def normalize_origin(value):
    """Match the MCP client's origin contract without loading its SDK on the web."""
    if not isinstance(value, str) or any(ord(c) <= 32 for c in value) or '\\' in value:
        raise ValueError('Invalid service origin')
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError('Invalid service origin') from None
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {'', '/'}):
        raise ValueError('Invalid service origin')
    host = parsed.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    default = 80 if parsed.scheme == 'http' else 443
    return parsed.scheme + '://' + host + (':' + str(port) if port and port != default else '')


def service_origin():
    # Forwarded headers and download query parameters are intentionally ignored.
    # A reverse proxy can use the operator-owned canonical PUBLIC_URL setting.
    configured = current_app.config.get('PUBLIC_URL', '')
    try:
        return normalize_origin(configured or request.host_url)
    except ValueError:
        raise ServiceUnavailable('MCP 연결 주소를 만들지 못했습니다. 운영자가 PTAI_PUBLIC_URL 설정을 확인해 주세요.') from None


def package_for_origin(source, origin):
    """Return a request-local ZIP; leave the generic package on disk unchanged."""
    origin = normalize_origin(origin)
    source = Path(source)
    if not source.is_file() or source.stat().st_size > 16 * 1024 * 1024:
        raise ServiceUnavailable('MCP 배포 파일이 준비되지 않았습니다. 운영자에게 알려주세요.')
    output = BytesIO()
    try:
        with ZipFile(source) as original, ZipFile(output, 'w', ZIP_DEFLATED) as result:
            entries = original.infolist()
            if (not entries or len(entries) > 500
                    or sum(entry.file_size for entry in entries) > 32 * 1024 * 1024):
                raise ValueError('Invalid MCP package')
            names = set()
            for entry in entries:
                name = entry.filename
                if (not name.startswith('pt-square-mcp/') or '\\' in name
                        or '..' in PurePosixPath(name).parts or ':' in name
                        or name in names or entry.flag_bits & 1):
                    raise ValueError('Invalid MCP package')
                names.add(name)
                if name != MANIFEST:
                    result.writestr(entry, original.read(entry))
            info = ZipInfo(MANIFEST, (2026, 10, 24, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            result.writestr(info, json.dumps({'schemaVersion': 1, 'baseUrl': origin},
                                            ensure_ascii=False, indent=2).encode('utf-8'))
    except (BadZipFile, OSError, ValueError, RuntimeError, NotImplementedError):
        raise ServiceUnavailable('MCP 배포 파일을 읽지 못했습니다. 운영자에게 알려주세요.') from None
    output.seek(0)
    return output


def download_package():
    source = Path(current_app.static_folder) / 'guides' / 'pt-square-mcp.zip'
    output = package_for_origin(source, service_origin())
    response = send_file(output, mimetype='application/zip', as_attachment=True,
                         download_name='pt-square-mcp.zip', conditional=False, etag=False)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Cookie'
    return response
