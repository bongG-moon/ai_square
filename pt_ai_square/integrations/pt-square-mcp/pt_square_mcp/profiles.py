"""Typed install declarations. No free-form shell command execution."""
import re
from pathlib import PurePosixPath
from .config import SquareError


def relative(value):
    if (not isinstance(value, str) or not value or len(value) > 240 or '\\' in value or ':' in value
            or value.startswith('/') or any(ord(c) < 32 for c in value)
            or any(p in {'', '.', '..'} or p.endswith((' ', '.')) for p in value.split('/'))):
        raise SquareError('파일 경로는 안전한 / 구분 상대 경로여야 합니다.')
    for part in value.split('/'):
        if part.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
            raise SquareError('Windows 예약 파일명은 사용할 수 없습니다.')
    return value


def arguments(value):
    if not isinstance(value, list) or len(value) > 40:
        raise SquareError('실행 인자는 최대 40개 문자열 목록이어야 합니다.')
    for arg in value:
        if not isinstance(arg, str) or len(arg) > 2000 or any(ord(c) < 32 for c in arg):
            raise SquareError('실행 인자 형식을 확인하세요.')
        plain = arg
        for name in ('{installDir}', '{scopeDir}', '{entrypoint}'):
            plain = plain.replace(name, '')
        if '{' in plain or '}' in plain:
            raise SquareError('지원하지 않는 설치 변수입니다.')
    return value


def validate_profile(raw):
    if raw is None:
        return None
    keys = {'schemaVersion','kind','host','slug','scopes','entrypoint','command','installerArgs','verification'}
    if not isinstance(raw, dict) or set(raw) - keys or type(raw.get('schemaVersion')) is not int or raw.get('schemaVersion') != 1:
        raise SquareError('installProfile v1 형식을 확인하세요.')
    if raw.get('kind') not in {'skill','mcp','installer','manual'} or raw.get('host') not in {'claude','other'}:
        raise SquareError('설치 유형·호스트를 확인하세요.')
    if not isinstance(raw.get('slug'), str) or not re.fullmatch('[a-z][a-z0-9-]{1,63}', raw['slug']):
        raise SquareError('설치 이름(slug)을 확인하세요.')
    scopes = raw.get('scopes')
    if not isinstance(scopes, list) or not scopes or any(not isinstance(s,str) or s not in {'project','user'} for s in scopes) or len(scopes) != len(set(scopes)):
        raise SquareError('설치 범위를 명시하세요.')
    if raw['kind'] != 'manual' or 'entrypoint' in raw:
        relative(raw.get('entrypoint'))
    if raw['kind'] == 'mcp':
        cmd = raw.get('command')
        if not isinstance(cmd, dict) or set(cmd) != {'executable','args'} or cmd.get('executable') not in {'python','node'}:
            raise SquareError('MCP 실행 정보는 python 또는 node와 args만 지원합니다.')
        arguments(cmd['args'])
    elif 'command' in raw:
        raise SquareError('command는 MCP에만 사용할 수 있습니다.')
    if raw['kind'] == 'installer':
        args = raw.get('installerArgs')
        if not isinstance(args, dict) or set(args) != set(scopes):
            raise SquareError('선언한 범위별 설치 인자가 필요합니다.')
        for values in args.values():
            arguments(values)
        if PurePosixPath(raw['entrypoint']).suffix.lower() not in {'.exe','.msi','.ps1'}:
            raise SquareError('설치기는 EXE·MSI·PS1이어야 합니다.')
    elif 'installerArgs' in raw:
        raise SquareError('installerArgs는 설치기에만 사용할 수 있습니다.')
    if 'verification' in raw:
        value = raw['verification']
        if not isinstance(value, dict) or set(value) != {'relativePath'}:
            raise SquareError('설치 확인 상대 경로를 지정하세요.')
        relative(value['relativePath'])
    return raw
