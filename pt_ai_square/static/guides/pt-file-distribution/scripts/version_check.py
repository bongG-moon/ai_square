"""Optional startup check. Does not install, download artifacts, or modify files.

The caller supplies its own authenticated HTTP opener when the site uses SSO/local
login. Browser login is NOT automatically inherited by a Python process.
"""
import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener


def check_version(base_url, tool_id, installed_release, *, opener=None, timeout=2.0):
    """Return a notice for the host UI; never write to stdout (MCP uses stdout)."""
    parsed=urlsplit(base_url)
    if (parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment
            or (parsed.scheme=='http' and parsed.hostname not in {'localhost','127.0.0.1','::1'})):
        raise ValueError('Use HTTPS (HTTP is allowed only on loopback), without credentials/query/fragment.')
    if any(type(n) is not int or not 0<n<1000000000 for n in [tool_id,installed_release]):
        raise ValueError('tool_id and installed_release must be positive release identifiers.')
    if not 0<timeout<=10:raise ValueError('Use a bounded timeout of 0–10 seconds.')
    url=f'{base_url.rstrip("/")}/api/tools/{tool_id}/version-check?release={installed_release}'
    try:
        with (opener or build_opener()).open(Request(url,headers={'Accept':'application/json'}),timeout=timeout) as response:
            raw=response.read(65537)
        if len(raw)>65536:raise ValueError('Oversized response')
        data=json.loads(raw)
        if (not isinstance(data,dict) or data.get('schemaVersion')!=1
                or data.get('toolId')!=tool_id or data.get('installedRelease')!=installed_release
                or data.get('status') not in {'current','update_available','rollback_available','unknown_release'}
                or type(data.get('activeRelease')) is not int or data['activeRelease']<1
                or not isinstance(data.get('message'),str) or data.get('checkOnly') is not True):
            raise ValueError('Invalid version response')
        return data
    except HTTPError as error:
        status={401:'authentication_required',403:'permission_required',404:'not_found'}.get(error.code,'unavailable')
        messages={'authentication_required':'버전 확인을 위한 로그인이 필요합니다. 실행 프로그램의 인증 연결을 확인해 주세요.',
                  'permission_required':'이 도구의 조회 권한이 필요합니다.',
                  'not_found':'공유 목록에서 도구를 찾을 수 없습니다.',
                  'unavailable':'서버에서 버전을 확인하지 못했습니다. 최신 버전 여부는 알 수 없습니다.'}
        return dict(status=status,message=messages[status],checkOnly=True)
    except (URLError,OSError,ValueError,HTTPException):
        return dict(status='unavailable',message='지금은 버전을 확인할 수 없습니다. 최신 버전 여부는 알 수 없습니다.',checkOnly=True)
