"""Syntax-only validation for user-published links; never resolves or fetches."""
import ipaddress
import re
from urllib.parse import urlsplit

from werkzeug.exceptions import BadRequest


def publication_url(value):
    message = '인증정보 없는 올바른 HTTP 또는 HTTPS 주소를 입력해 주세요.'
    if not isinstance(value, str) or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
        raise BadRequest(message)
    value = value.strip()
    if not value or len(value) > 2048 or '\\' in value or any(c.isspace() for c in value):
        raise BadRequest(message)
    try:
        value.encode('utf-8')  # Invalid surrogate text must not reach BSON storage.
        parts = urlsplit(value)
        host = parts.hostname
        if (parts.scheme not in {'http', 'https'} or not parts.netloc or not host
                or '@' in parts.netloc or parts.username is not None or parts.password is not None):
            raise ValueError('scheme, authority, or credentials')
        port = parts.port
        if parts.netloc.endswith(':') or (port is not None and not 1 <= port <= 65535):
            raise ValueError('port')
        if parts.netloc.startswith('['):
            if not re.fullmatch(r'\[[^\]]+\](?::[0-9]+)?', parts.netloc) or '%' in host:
                raise ValueError('IPv6 authority')
            ipaddress.IPv6Address(host)
        else:
            ascii_host = host.encode('idna').decode('ascii').removesuffix('.')
            if len(ascii_host) > 253 or not all(
                    re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label)
                    for label in ascii_host.split('.')):
                raise ValueError('hostname')
            if re.fullmatch(r'[0-9.]+', ascii_host):
                ipaddress.IPv4Address(ascii_host)
    except (ValueError, UnicodeError):
        # urlsplit itself can raise for broken brackets or Unicode authority.
        # Never expose the supplied URL, credentials, or parser exception.
        raise BadRequest(message) from None
    return value
