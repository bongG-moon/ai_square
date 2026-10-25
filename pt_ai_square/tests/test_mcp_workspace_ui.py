"""Legacy native chooser entrypoint safely directs callers back to chat."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

PACKAGE = Path(__file__).parents[1] / 'integrations' / 'pt-square-mcp'
sys.path.insert(0, str(PACKAGE))
from pt_square_mcp import workspace_ui as ui
from pt_square_mcp.config import atomic_json


@pytest.fixture
def no_native_ui(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Legacy location helper must not launch a process or native UI')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setitem(sys.modules, 'tkinter', None)


def test_legacy_entrypoint_returns_chat_guidance_without_native_ui(no_native_ui, capsys):
    assert ui.main([]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['chatRequired'] is True
    assert result['nextTool'] == 'select_workspace'
    assert not result.get('selected')


def test_legacy_request_file_is_not_processed_or_completed(no_native_ui, tmp_path, capsys):
    chosen = tmp_path / 'chosen-project'
    chosen.mkdir()
    request = tmp_path / 'request.json'
    atomic_json(request, {'purpose': 'install',
                         'locations': {'currentProject': {'path': str(chosen)}},
                         'initialDirectory': str(chosen), 'expiresAt': 9999999999})
    before = request.read_bytes()
    assert ui.main(['--request', str(request)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['chatRequired'] and result['nextTool'] == 'select_workspace'
    assert request.read_bytes() == before
    assert not (tmp_path / 'result.json').exists()
    assert not (chosen / '.claude').exists()


def test_missing_legacy_request_does_not_make_a_native_or_file_fallback(no_native_ui, tmp_path, capsys):
    missing = tmp_path / 'missing.json'
    assert ui.main(['--request', str(missing)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['chatRequired'] and not result.get('selected')
    assert not missing.exists() and not (tmp_path / 'result.json').exists()


def test_legacy_module_cli_returns_same_chat_contract(tmp_path):
    request = tmp_path / 'request.json'
    atomic_json(request, {'purpose': 'publish', 'initialDirectory': str(tmp_path)})
    completed = subprocess.run(
        [sys.executable, '-X', 'utf8', '-B', '-m', 'pt_square_mcp.workspace_ui',
         '--request', str(request)],
        cwd=PACKAGE, text=True, capture_output=True, encoding='utf-8', timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result['chatRequired'] and result['nextTool'] == 'select_workspace'
    assert not (tmp_path / 'result.json').exists()
