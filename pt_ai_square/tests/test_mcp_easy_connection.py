"""Retired native entry points and managed downloads in isolated test folders."""
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

PACKAGE = Path(__file__).parents[1] / 'integrations' / 'pt-square-mcp'
sys.path.insert(0, str(PACKAGE))
from pt_square_mcp import connection_ui as ui
from pt_square_mcp.client import automatic_download_directory
from pt_square_mcp.config import Settings, SquareError, atomic_json, read_json, save_config, scoped_path
from pt_square_mcp.runtime import Runtime
from .test_local_mcp import FakeClient, KEY


@pytest.fixture
def settings(tmp_path, monkeypatch):
    home = tmp_path / 'fake-home'
    downloads = home / 'AI_SQUARE' / 'downloads'
    downloads.mkdir(parents=True)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    path = tmp_path / 'private' / 'config.json'
    save_config(path, 'http://company.example', [downloads], allow_http=True,
                download_directory=downloads)
    monkeypatch.setenv('PTAI_API_TOKEN', KEY)
    return Settings(path)


@pytest.mark.parametrize('purpose', ['publish', 'install'])
def test_legacy_folder_entry_never_opens_picker_or_grants_access(settings, purpose):
    before = settings.path.read_bytes()
    def forbidden():
        pytest.fail('Legacy folder entry must not invoke a native callback')
    result = ui.choose_workspace(settings.path, purpose, chooser=forbidden)
    assert result['selected'] is False and result['chatRequired'] is True
    assert result['selectTool'] == 'select_workspace' and result['purpose'] == purpose
    assert settings.path.read_bytes() == before


def test_legacy_folder_entry_rejects_unknown_purpose_without_opening_dialog(settings):
    with pytest.raises(SquareError):
        ui.choose_workspace(settings.path, 'arbitrary', chooser=lambda: pytest.fail('No picker'))


def test_legacy_folder_guidance_does_not_need_connection_config(tmp_path):
    path = tmp_path / 'absent.json'
    result = ui.choose_workspace(path)
    assert result['chatRequired'] is True
    assert not path.exists()


def test_download_without_folder_uses_managed_server_tool_release_path(settings):
    client = FakeClient()
    runtime = Runtime(settings, client=client, home=Path.home())
    result = runtime.download_item(1)
    artifact = Path(result['file'])
    assert artifact.read_bytes() == client.raw
    assert artifact.parent == automatic_download_directory(settings, client.value)
    assert artifact.parent.parts[-2:] == ('tool-1', 'v1')
    assert artifact.parent.parent.parent.name.startswith('server-')
    assert settings.downloads in artifact.parents
    assert not result['installed']
    assert client.downloads == [False]
    runtime.download_item(1, update=True)
    assert client.downloads == [False, True]


def test_managed_downloads_isolate_origins_tools_and_releases(settings):
    value = FakeClient().value
    baseline = automatic_download_directory(settings, value)
    assert automatic_download_directory(settings, dict(value, toolId=2)) != baseline
    assert automatic_download_directory(settings, dict(value, release=2)) != baseline
    second = SimpleNamespace(url='https://other.example', downloads=settings.downloads)
    assert automatic_download_directory(second, value) != baseline
    assert not baseline.exists()


@pytest.mark.parametrize('field,value', [('toolId', '../private'), ('release', '../private'), ('release', 0)])
def test_managed_downloads_reject_invalid_server_identifiers(settings, field, value):
    manifest = dict(FakeClient().value, **{field: value})
    with pytest.raises(SquareError):
        automatic_download_directory(settings, manifest)


def test_explicit_download_directory_still_requires_selected_root(settings, tmp_path):
    client = FakeClient()
    runtime = Runtime(settings, client=client, home=Path.home())
    with pytest.raises(SquareError):
        runtime.download_item(1, str(tmp_path / 'outside'))
    assert not client.downloads
    chosen = settings.downloads / 'manual'
    result = runtime.download_item(1, str(chosen))
    assert Path(result['file']).parent == chosen


def test_retired_key_dialog_returns_without_importing_gui_or_touching_config(settings, monkeypatch):
    before = settings.path.read_bytes()
    monkeypatch.setitem(sys.modules, 'tkinter', None)
    assert ui._show_connection(settings.path, settings.url) is False
    assert settings.path.read_bytes() == before
    assert not hasattr(ui, 'ConnectionWindow')


def test_legacy_open_connection_only_prints_chat_guidance(settings, monkeypatch, capsys):
    import json
    before = settings.path.read_bytes()
    monkeypatch.setitem(sys.modules, 'tkinter', None)
    assert ui.open_connection(settings.path) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result['connected'] is False and result['keyRequired'] is True
    assert result['connectTool'] == 'connect_account'
    assert result['baseUrl'] == settings.url
    assert KEY not in output and settings.path.read_bytes() == before
