"""Nonblocking, connection-bound native location choices. Never installs a tool."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from .config import (DEFAULT_CONFIG, Settings, SquareError, atomic_json, no_links,
                     operation_lock, read_json)

LIFETIME_SECONDS = 600
_ID = re.compile(r'[a-f0-9]{32}')
_children = {}


def _binding(settings):
    return hashlib.sha256(json.dumps(settings.data, sort_keys=True,
                                    ensure_ascii=False).encode()).hexdigest()


def _base(settings):
    return no_links(settings.state / 'workspace-selections')


def _directory(settings, request_id):
    if not isinstance(request_id, str) or not _ID.fullmatch(request_id):
        raise SquareError('위치 선택 요청 번호를 확인하세요.')
    return no_links(_base(settings) / request_id)


def _folder(value):
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise SquareError('존재하는 폴더의 전체 경로를 선택해 주세요.')
    path = no_links(value)
    if not path.is_dir() or path == Path(path.anchor):
        raise SquareError('존재하는 작업 폴더만 선택할 수 있습니다. 드라이브 전체는 허용하지 않습니다.')
    return path


def _identity(path):
    value = path.stat()
    return [value.st_dev, value.st_ino]


def _launch(request_file):
    # The child has no server address, KEY, credential reference or token environment.
    env = dict(os.environ)
    env.pop('PTAI_API_TOKEN', None)
    return subprocess.Popen(
        [sys.executable, '-B', '-m', 'pt_square_mcp.workspace_ui', '--request', str(request_file)],
        cwd=str(Path(__file__).resolve().parent.parent), env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )


def _answer(record):
    result = dict(record['result']) if record.get('result') else {}
    result.update(requestId=record['requestId'], status=record['status'], purpose=record['purpose'])
    if record['status'] == 'pending':
        result.update(selected=False, waitingForUser=True, pollAfterSeconds=3,
                      nextTool='get_workspace_selection', cancelTool='cancel_workspace_selection',
                      notice='설치 위치 선택 창을 열었습니다.' if record['purpose'] == 'install' else '원본 폴더 선택 창을 열었습니다.')
        result['notice'] += ' 사용자 선택을 기다리는 중이며 설치·업로드는 아직 실행하지 않았습니다. 선택 후 AI에 “선택했어”라고 알려주세요.'
        result['guidance'] = '사용자에게 대기 상태를 알리세요. 선택 완료 후 상태를 확인하고, 대기 중이면 반복 조회하지 말고 사용자의 응답을 기다리세요.'
    return result


def _finish(directory, record, status, notice, **result):
    record.update(status=status, result=dict(selected=False, notice=notice, **result))
    atomic_json(directory / 'record.json', record)
    if status != 'selected':
        atomic_json(directory / 'cancel.marker', {'cancelled': True})
    return _answer(record)


def _status(settings, directory, record):
    if record['binding'] != _binding(settings):
        return _finish(directory, record, 'cancelled', '선택 중 연결 설정이 바뀌었습니다. 새 위치 선택 요청을 열어 주세요.')
    if record['status'] != 'pending':
        child = _children.get(record['requestId'])
        if child is not None and child.poll() is not None:
            _children.pop(record['requestId'], None)
        return _answer(record)
    request = read_json(directory / 'request.json')
    result_file = no_links(directory / 'result.json')
    if result_file.exists():
        result = read_json(result_file)
        completed = result.get('completedAt', time.time())
        if (type(completed) not in (int, float) or not math.isfinite(completed)
                or completed > request['expiresAt']):
            return _finish(directory, record, 'expired', '위치 선택 시간이 지났습니다. 필요하면 선택 창을 다시 열어 주세요.')
        if not result.get('selected'):
            if result.get('status') == 'expired':
                return _finish(directory, record, 'expired', '위치 선택 시간이 지났습니다. 필요하면 선택 창을 다시 열어 주세요.')
            failed = result.get('status') == 'failed'
            return _finish(directory, record, 'failed' if failed else 'cancelled',
                           '위치 선택 창을 열거나 처리하지 못했습니다. 선택 창을 다시 열어 주세요.' if failed else
                           '위치 선택을 취소했습니다. 파일 접근 범위는 변경되지 않았습니다.')
        try:
            path = _folder(result.get('path'))
            selection, scope = result.get('selection'), result.get('scope')
            if selection == 'user' and record['purpose'] == 'install':
                if scope != 'user' or path != no_links(Path.home()):
                    raise SquareError('공통 설치는 현재 사용자 계정의 경로만 사용할 수 있습니다.')
            elif selection in {'current', 'confirmed-current'} and record['purpose'] == 'install':
                candidates = record['candidates'] if selection == 'current' else record.get('confirmationCandidates', {})
                if scope != 'project' or str(path) not in candidates or candidates[str(path)] != _identity(path):
                    raise SquareError('현재 프로젝트 폴더가 바뀌었습니다. 위치를 다시 확인해 주세요.')
            elif selection == 'other':
                if scope != 'project':
                    raise SquareError('선택한 폴더의 설치 범위를 확인해 주세요.')
            else:
                raise SquareError('위치 선택 결과를 확인하지 못했습니다. 선택 창을 다시 열어 주세요.')
            if selection in {'other', 'confirmed-current'}:
                roots = [str(root) for root in settings.roots]
                if str(path) not in roots:
                    settings.data['trustedRoots'] = [*roots, str(path)]
                    atomic_json(settings.path, settings.data)
                    record['binding'] = _binding(settings)
        except (OSError, SquareError):
            return _finish(directory, record, 'failed', '선택한 위치를 확인하지 못했습니다. 존재하는 폴더를 다시 선택해 주세요.')
        record.update(status='selected', result=dict(selected=True, scope=scope, path=str(path),
                      selection=selection, notice='위치를 선택했습니다. 설치·업로드는 아직 실행하지 않았습니다. 실제 설치 준비안의 범위와 경로를 확인해 주세요.'))
        atomic_json(directory / 'record.json', record)
        return _answer(record)
    if time.time() >= request['expiresAt']:
        return _finish(directory, record, 'expired', '위치 선택 시간이 지났습니다. 필요하면 선택 창을 다시 열어 주세요.')
    child = _children.get(record['requestId'])
    if child is not None and child.poll() is not None:
        _children.pop(record['requestId'], None)
        # The child writes result.json before exit; recheck on the next call if it
        # appeared between the existence check and process exit.
        if result_file.exists():
            return _status(settings, directory, record)
        return _finish(directory, record, 'failed', '위치 선택 창이 종료되었습니다. 필요하면 선택 창을 다시 열어 주세요.')
    return _answer(record)


def start_selection(config_path=DEFAULT_CONFIG, purpose='publish', locations=None):
    if purpose not in {'install', 'publish'}:
        raise SquareError('폴더 선택 용도는 publish 또는 install이어야 합니다.')
    settings = Settings(config_path)
    with operation_lock(settings.path.parent):
        settings = Settings(config_path)
        base = _base(settings)
        pointer = no_links(base / (purpose + '.json'))
        if pointer.exists():
            previous = read_json(pointer)['requestId']
            directory = _directory(settings, previous)
            record = read_json(directory / 'record.json')
            result = _status(settings, directory, record)
            if result['status'] == 'pending':
                return result
        request_id = uuid.uuid4().hex
        directory = _directory(settings, request_id)
        locations = locations or {}
        candidates = {}
        for candidate in locations.get('projectCandidates', []):
            path = _folder(candidate.get('path'))
            candidates[str(path)] = _identity(path)
        confirmation_candidates = {}
        for candidate in locations.get('confirmationCandidates', []):
            path = _folder(candidate.get('path'))
            confirmation_candidates[str(path)] = _identity(path)
        current = locations.get('currentProject')
        initial = current.get('path') if isinstance(current, dict) else str(settings.downloads)
        request = dict(purpose=purpose, locations=locations, initialDirectory=initial,
                       expiresAt=time.time() + LIFETIME_SECONDS)
        record = dict(requestId=request_id, purpose=purpose, binding=_binding(settings),
                      status='pending', candidates=candidates, confirmationCandidates=confirmation_candidates)
        atomic_json(directory / 'request.json', request)
        atomic_json(directory / 'record.json', record)
        atomic_json(pointer, {'requestId': request_id})
        try:
            _children[request_id] = _launch(directory / 'request.json')
        except (OSError, subprocess.SubprocessError):
            return _finish(directory, record, 'failed', '위치 선택 창을 열지 못했습니다. MCP가 실행되는 PC에서 다시 시도해 주세요.')
        return _answer(record)


def selection_status(config_path, request_id):
    settings = Settings(config_path)
    with operation_lock(settings.path.parent):
        settings = Settings(config_path)
        directory = _directory(settings, request_id)
        try:
            record = read_json(directory / 'record.json')
        except FileNotFoundError:
            raise SquareError('위치 선택 요청을 찾지 못했습니다. 선택 창을 다시 열어 주세요.') from None
        return _status(settings, directory, record)


def cancel_selection(config_path, request_id):
    settings = Settings(config_path)
    with operation_lock(settings.path.parent):
        directory = _directory(settings, request_id)
        try:
            record = read_json(directory / 'record.json')
        except FileNotFoundError:
            raise SquareError('위치 선택 요청을 찾지 못했습니다.') from None
        if record['status'] != 'pending':
            return _answer(record)
        return _finish(directory, record, 'cancelled', '위치 선택을 취소했습니다. 파일 접근 범위는 변경되지 않았습니다.')
