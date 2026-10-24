"""Declarative local installation metadata. The server never executes it."""
import copy
import re
from pathlib import PurePosixPath
from werkzeug.exceptions import BadRequest


def relative_path(value):
    if (not isinstance(value, str) or not value or len(value) > 240
            or value.startswith('/') or '\\' in value or ':' in value
            or any(p in {'', '.', '..'} for p in value.split('/'))
            or any(ord(c) < 32 for c in value)):
        raise BadRequest('installProfile: 안전한 상대 파일 경로를 입력하세요.')
    return str(PurePosixPath(value))


def arguments(value):
    if (not isinstance(value, list) or len(value) > 40
            or any(not isinstance(x, str) or len(x) > 2000 or any(ord(c) < 32 for c in x) for x in value)):
        raise BadRequest('installProfile: 실행 인수는 최대 40개 문자열입니다.')
    for arg in value:
        remainder = re.sub(r'\{(?:installDir|scopeDir|entrypoint)\}', '', arg)
        if '{' in remainder or '}' in remainder:
            raise BadRequest('installProfile: 지원하지 않는 실행 인수 자리표시자입니다.')
    return value


def normalize_install_profile(raw):
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - {'schemaVersion', 'kind', 'host', 'slug', 'scopes', 'entrypoint', 'command', 'installerArgs', 'verification'}:
        raise BadRequest('installProfile: 지원하는 설치 정보 필드만 입력하세요.')
    if type(raw.get('schemaVersion')) is not int or raw['schemaVersion'] != 1:
        raise BadRequest('installProfile: schemaVersion은 1입니다.')
    if (not isinstance(raw.get('kind'), str) or not isinstance(raw.get('host'), str)
            or raw['kind'] not in {'skill', 'mcp', 'installer', 'manual'} or raw['host'] not in {'claude', 'other'}):
        raise BadRequest('installProfile: 설치 유형·프로그램을 확인하세요.')
    if not isinstance(raw.get('slug'), str) or not re.fullmatch(r'[a-z][a-z0-9-]{1,63}', raw['slug']):
        raise BadRequest('installProfile: slug는 소문자·숫자·하이픈 2~64자입니다.')
    scopes = raw.get('scopes')
    if (not isinstance(scopes, list) or not scopes or any(x not in ('project', 'user') for x in scopes)
            or len(set(scopes)) != len(scopes)):
        raise BadRequest('installProfile: 지원하는 설치 범위를 선택하세요.')
    result = copy.deepcopy(raw)
    if raw['kind'] != 'manual' or 'entrypoint' in raw:
        result['entrypoint'] = relative_path(raw.get('entrypoint'))
    if raw['kind'] == 'mcp':
        command = raw.get('command')
        if (not isinstance(command, dict) or set(command) != {'executable', 'args'}
                or not isinstance(command['executable'], str) or command['executable'] not in {'python', 'node'}):
            raise BadRequest('installProfile: MCP 실행은 python 또는 node와 인수로 선언하세요.')
        arguments(command['args'])
    elif 'command' in raw:
        raise BadRequest('installProfile: command는 MCP에만 사용할 수 있습니다.')
    if raw['kind'] == 'installer':
        mapping = raw.get('installerArgs')
        if not isinstance(mapping, dict) or set(mapping) != set(scopes):
            raise BadRequest('installProfile: 지원하는 각 범위의 설치 인수를 선언하세요.')
        if PurePosixPath(result['entrypoint']).suffix.lower() not in {'.exe', '.msi', '.ps1'}:
            raise BadRequest('installProfile: 설치기는 EXE·MSI·PS1입니다.')
        for args in mapping.values():
            arguments(args)
    elif 'installerArgs' in raw:
        raise BadRequest('installProfile: installerArgs는 설치기에만 사용할 수 있습니다.')
    if 'verification' in raw:
        value = raw['verification']
        if not isinstance(value, dict) or set(value) != {'relativePath'}:
            raise BadRequest('installProfile: 확인할 상대 파일만 선언하세요.')
        relative_path(value['relativePath'])
    return result
