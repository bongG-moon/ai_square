"""Legacy entry points now provide chat guidance; no native windows are opened."""
import json

from .config import DEFAULT_CONFIG, SquareError, UNSET_CONNECTION_STATE, no_links, read_json, normalize_url
from .onboarding import resolve_connection


def connection_origin(config_path=DEFAULT_CONFIG):
    """Keep an existing connection's origin; use the package only for first use."""
    path = no_links(config_path)
    # KEY recovery must still be possible when a previously selected folder was
    # removed. Origin validation is independent of filesystem access grants.
    return normalize_url(read_json(path).get('baseUrl')) if path.exists() else resolve_connection(path)


def connection_instructions(config_path=DEFAULT_CONFIG):
    """Safe instructions for old launchers; authentication runs in the MCP tool."""
    url = connection_origin(config_path)
    return {
        'connected': False, 'keyRequired': True, 'chatRequired': True,
        'connectTool': 'connect_account', 'baseUrl': url, 'authUrl': url + '/local-access',
        'message': 'Claude Code 등 MCP를 등록한 AI 채팅에서 "AI SQUARE 연결해줘"라고 요청한 뒤 개인 KEY를 입력하세요. 별도 KEY 입력창은 열리지 않습니다.',
        'notice': '채팅에 입력한 KEY는 AI 서비스의 대화 및 도구 호출 기록에 남을 수 있습니다. KEY를 답변에 다시 표시하지 마세요.',
    }


def _show_connection(config_path, url, *, expected_state=UNSET_CONNECTION_STATE, cancel_event=None):
    """Compatibility only: retired native dialogs must never reappear."""
    return False


def open_connection(config_path=DEFAULT_CONFIG):
    print(json.dumps(connection_instructions(config_path), ensure_ascii=False, indent=2))
    return 0


def reconnect_key(config_path=DEFAULT_CONFIG, *, show_dialog=None, cancel_event=None):
    """Old callers receive instructions; their dialog callbacks are not invoked."""
    result = {'reconnected': False, **connection_instructions(config_path)}
    if cancel_event is not None and cancel_event.is_set():
        result['cancelled'] = True
    return result


def choose_workspace(config_path=DEFAULT_CONFIG, purpose='publish', *, chooser=None):
    """Old callers cannot launch a picker or grant paths outside chat approval."""
    if purpose not in {'publish', 'install'}:
        raise SquareError('폴더 선택 용도는 publish 또는 install이어야 합니다.')
    return {
        'selected': False, 'chatRequired': True, 'selectTool': 'select_workspace',
        'purpose': purpose,
        'notice': 'AI 채팅에서 현재 프로젝트 폴더 또는 사용할 경로를 선택해 주세요. 별도 폴더 창은 열리지 않으며 아직 파일 접근 범위를 변경하지 않았습니다.',
    }
