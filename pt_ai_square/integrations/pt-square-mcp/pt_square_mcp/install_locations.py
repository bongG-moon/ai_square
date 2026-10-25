"""Discover install locations from the MCP host, never from an AI-supplied grant."""
import asyncio
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import url2pathname

from .config import SquareError, no_links, scoped_path


ROOTS_TIMEOUT_SECONDS = 2.0
MAX_HOST_ROOTS = 128
PACKAGE_DIRECTORY = Path(__file__).resolve().parents[1]


def _directory(value, settings):
    """Exclude broad/private/program locations and reject links before resolving."""
    path = no_links(value)
    home = no_links(Path.home())
    if (not path.is_dir() or path == Path(path.anchor)
            or path == home or path in home.parents):
        raise SquareError('프로젝트로 사용할 작업 폴더를 선택하세요.')
    system_directories = tuple(Path(os.path.abspath(value)) for name in
                               ('SystemRoot', 'WINDIR', 'ProgramFiles', 'ProgramFiles(x86)', 'ProgramData')
                               if (value := os.environ.get(name)))
    excluded = (settings.downloads, settings.path.parent, PACKAGE_DIRECTORY, *system_directories)
    if any(path == root or root in path.parents for root in excluded):
        raise SquareError('다운로드·연결 설정·프로그램·시스템 폴더는 현재 프로젝트가 아닙니다.')
    return path


def _file_root(uri, settings):
    if (not isinstance(uri, str) or len(uri) > 8192 or '\\' in uri or uri != uri.strip()
            or any(ord(character) < 32 for character in uri)
            or re.search(r'%(?![0-9a-fA-F]{2})', uri)):
        raise SquareError('호스트의 프로젝트 주소를 확인할 수 없습니다.')
    parsed = urlsplit(uri)
    if (parsed.scheme != 'file' or parsed.netloc.lower() not in {'', 'localhost'}
            or parsed.query or parsed.fragment or not parsed.path):
        raise SquareError('호스트가 제공한 로컬 파일 주소만 사용할 수 있습니다.')
    decoded = url2pathname(parsed.path)
    if (any(ord(character) < 32 for character in decoded)
            or decoded.startswith(('//', '\\\\')) or not os.path.isabs(decoded)):
        raise SquareError('호스트의 프로젝트 주소를 확인할 수 없습니다.')
    return _directory(decoded, settings)


def _candidate(path, source, name=''):
    # Names are display data only. Never interpret them as paths/instructions.
    label = ' '.join(str(name or path.name).split())[:120]
    return {'path': str(path), 'name': label or str(path), 'source': source}


async def discover_locations(settings, context, *, launch_cwd=None, timeout=ROOTS_TIMEOUT_SECONDS):
    """Read a bounded host response and return only independently valid folders."""
    candidates, confirmations, roots_status = [], [], 'unsupported'
    try:
        session = context.session
        params = session.client_params
        supported = params is not None and params.capabilities.roots is not None
    except (AttributeError, LookupError, RuntimeError, ValueError):
        supported = False
    if supported:
        try:
            result = await asyncio.wait_for(session.list_roots(), timeout=timeout)
            rows = result.roots
            if not isinstance(rows, list) or len(rows) > MAX_HOST_ROOTS:
                raise ValueError('Invalid root list')
            seen = set()
            for row in rows:
                try:
                    path = _file_root(str(row.uri), settings)
                except (AttributeError, OSError, ValueError, TypeError):
                    continue
                if path not in seen:
                    candidates.append(_candidate(path, 'mcp-roots', getattr(row, 'name', '')))
                    seen.add(path)
            roots_status = 'available' if candidates else 'empty'
        except asyncio.TimeoutError:
            roots_status = 'timeout'
        except asyncio.CancelledError:
            raise
        except Exception:
            # Host errors must not leak arbitrary client content or hang the MCP.
            roots_status = 'unavailable'
    # An explicit multi-root workspace is ambiguous; do not infer a preferred
    # project from cwd. Fallback is limited to an already user-authorized root.
    if not candidates and launch_cwd is not None:
        try:
            cwd = _directory(launch_cwd, settings)
            try:
                scoped_path(cwd, settings.roots, existing=True)
                candidates.append(_candidate(cwd, 'launch-cwd'))
            except SquareError:
                confirmations.append({**_candidate(cwd, 'launch-cwd-unconfirmed'),
                                      'requiresUserSelection': True})
        except (OSError, ValueError, TypeError):
            pass
    current = candidates[0] if len(candidates) == 1 else None
    return {
        'options': [
            {'scope': 'user', 'label': '공통 (내 계정)', 'available': True, 'path': str(no_links(Path.home()))},
            {'scope': 'project', 'label': '현재 프로젝트', 'available': bool(candidates or confirmations),
             'path': current['path'] if current else None, 'candidates': candidates},
            {'scope': 'other', 'label': '기타 경로', 'available': True, 'requiresChatSelection': True},
        ],
        'currentProject': current, 'projectCandidates': candidates, 'rootsStatus': roots_status,
        'confirmationCandidates': confirmations,
        'requiresProjectSelection': len(candidates) != 1,
        'notice': ('현재 프로젝트를 확인했습니다. 설치 범위와 준비안을 확인한 뒤 설치하세요.' if current else
                   '프로젝트가 여러 개입니다. 표시된 후보 중 설치할 프로젝트를 선택하세요.' if candidates else
                   '시작 폴더 후보를 채팅에서 확인해 주세요. 선택을 확인하기 전에는 폴더 접근 권한이 추가되지 않습니다.' if confirmations else
                   '현재 프로젝트를 확인하지 못했습니다. 공통 (내 계정) 또는 기타 경로를 선택하세요.'),
    }


def project_roots(locations):
    """Private call argument, created only from a freshly validated host result."""
    return tuple(Path(row['path']) for row in locations['projectCandidates'])


def project_path(locations, requested=''):
    if requested:
        return requested
    current = locations['currentProject']
    if current is None:
        raise SquareError(locations['notice'] + ' select_workspace(purpose="install")에서 선택할 수 있습니다.')
    return current['path']
