"""KEY-only UI and managed downloads, using private test folders and fake widgets."""
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


def test_folder_cancel_keeps_configuration(settings):
    before = settings.path.read_bytes()
    result = ui.choose_workspace(settings.path, chooser=lambda: '')
    assert not result['selected']
    assert settings.path.read_bytes() == before


def test_native_folder_selection_adds_only_chosen_root_and_preserves_credential(settings, tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    data = read_json(settings.path)
    ref = 'windows-dpapi:credential.' + 'a' * 32 + '.dpapi.json'
    data['credentialRef'] = ref
    atomic_json(settings.path, data)
    secret = settings.path.parent / ref.split(':')[1]
    secret.write_text('{"encrypted":"placeholder"}', encoding='utf-8')
    secret_before = secret.read_bytes()
    with pytest.raises(SquareError):
        scoped_path(source, settings.roots)
    result = ui.choose_workspace(settings.path, 'publish', chooser=lambda: str(source))
    updated = Settings(settings.path)
    assert result['selected'] and result['purpose'] == 'publish'
    assert updated.roots == [settings.downloads, source]
    assert updated.data['credentialRef'] == ref
    assert updated.downloads == settings.downloads
    assert secret.read_bytes() == secret_before
    assert scoped_path(source, updated.roots) == source
    with pytest.raises(SquareError):
        scoped_path(tmp_path / 'unselected', updated.roots)
    ui.choose_workspace(settings.path, 'install', chooser=lambda: str(source))
    assert Settings(settings.path).roots == updated.roots


@pytest.mark.parametrize('kind', ['drive', 'missing', 'file'])
def test_native_folder_rejects_unusable_targets(settings, tmp_path, kind):
    path = {'drive': Path(tmp_path.anchor), 'missing': tmp_path / 'missing', 'file': tmp_path / 'file.txt'}[kind]
    if kind == 'file':
        path.write_text('not a directory')
    before = settings.path.read_bytes()
    with pytest.raises(SquareError):
        ui.choose_workspace(settings.path, chooser=lambda: str(path))
    assert settings.path.read_bytes() == before


def test_native_folder_rejects_unknown_purpose_without_opening_dialog(settings):
    def unexpected():
        pytest.fail('Invalid purpose must not open a picker')
    with pytest.raises(SquareError):
        ui.choose_workspace(settings.path, 'arbitrary', chooser=unexpected)


def test_native_folder_does_not_grant_to_a_connection_changed_during_picker(settings, tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    def switch_connection():
        data = read_json(settings.path)
        data.update(baseUrl='https://other.example', acceptedHttpOrigin=None)
        atomic_json(settings.path, data)
        return str(source)
    with pytest.raises(SquareError, match='사이트가 바뀌'):
        ui.choose_workspace(settings.path, chooser=switch_connection)
    current = Settings(settings.path)
    assert current.url == 'https://other.example'
    assert source not in current.roots


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


class Variable:
    def __init__(self, root=None, value=''):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class Widget:
    def __init__(self, parent=None, **options):
        self.options = options
        self.bindings = {}
        self.children = []
        if parent is not None:
            parent.children.append(self)
    def pack(self, **options):
        pass
    def configure(self, **options):
        self.options.update(options)
    def bind(self, event, callback):
        self.bindings[event] = callback
    def focus_set(self):
        pass


class Root(Widget):
    def __init__(self):
        super().__init__()
        self.destroyed = False
        self.callbacks = []
    def title(self, value):
        self.window_title = value
    def geometry(self, value):
        pass
    def minsize(self, *args):
        pass
    def protocol(self, *args):
        pass
    def after(self, delay, callback):
        self.callbacks.append(callback)
    def destroy(self):
        self.destroyed = True


class Style:
    def __init__(self, root):
        pass
    def theme_use(self, *args):
        pass
    def configure(self, *args, **kwargs):
        pass
    def map(self, *args, **kwargs):
        pass


class InlineThread:
    def __init__(self, target, **kwargs):
        self.target = target
    def start(self):
        self.target()


@pytest.fixture
def window(settings, monkeypatch):
    tk = SimpleNamespace(StringVar=Variable, BooleanVar=Variable)
    ttk = SimpleNamespace(Style=Style, Frame=Widget, Label=Widget, Entry=Widget, Checkbutton=Widget, Button=Widget)
    monkeypatch.setattr(ui, '_tk', lambda: (tk, ttk, None))
    monkeypatch.setattr(ui, 'resolve_connection', lambda config: settings.url)
    monkeypatch.setattr(ui.threading, 'Thread', InlineThread)
    root = Root()
    view = ui.ConnectionWindow(root, settings.path)
    return view


def test_key_form_masks_input_and_requires_http_ack_before_contact(window, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Unconfirmed HTTP must not send a KEY')
    monkeypatch.setattr(ui, 'connect', forbidden)
    window.key.set(KEY)
    window.start_connect()
    assert window.entry.options['show']
    assert not window.busy and not window.completed
    assert 'HTTP' in window.status.get()
    assert not window.root.callbacks


def test_key_form_requires_key_after_http_ack(window, monkeypatch):
    monkeypatch.setattr(ui, 'connect', lambda *a, **k: pytest.fail('Empty KEY must not connect'))
    window.http_ack.set(True)
    window.start_connect()
    assert not window.busy and not window.completed
    assert 'KEY' in window.status.get()


def test_key_form_success_requires_verified_account_and_clears_input(window, monkeypatch):
    calls = []
    def verified(*args, **kwargs):
        calls.append((args, kwargs))
        return {'connected': True, 'user': {'id': 'E1', 'name': '홍길동', 'dept': '융합기술'}}
    monkeypatch.setattr(ui, 'connect', verified)
    window.http_ack.set(True)
    window.key.set(KEY)
    window.start_connect()
    assert window.busy and not window.completed
    assert window.key.get() == ''
    assert window.entry.options['state'] == 'disabled'
    assert calls[0][0][2] == KEY and calls[0][1] == {'allow_http': True}
    window.poll()
    assert window.completed and not window.busy
    assert '홍길동 · 융합기술' in window.status.get()
    assert KEY not in window.status.get()
    assert window.button.options['text'] == '완료'
    window.start_connect()
    assert window.root.destroyed and len(calls) == 1


@pytest.mark.parametrize('raw', [False, True])
def test_key_form_failed_connection_keeps_no_success_and_sanitizes_raw_error(window, monkeypatch, raw):
    def fail(*args, **kwargs):
        if raw:
            raise RuntimeError('unexpected secret=' + KEY)
        raise SquareError('KEY를 확인하세요.')
    monkeypatch.setattr(ui, 'connect', fail)
    window.http_ack.set(True)
    window.key.set(KEY)
    window.start_connect()
    window.poll()
    assert not window.completed and not window.busy
    assert window.key.get() == ''
    assert window.entry.options['state'] == 'normal'
    assert window.button.options['text'] == '다시 연결'
    assert KEY not in window.status.get()


def test_key_form_prevents_duplicate_connect_and_close_while_busy(window, monkeypatch):
    started = []
    class DeferredThread(InlineThread):
        def start(self):
            started.append(self.target)
    monkeypatch.setattr(ui.threading, 'Thread', DeferredThread)
    window.http_ack.set(True)
    window.key.set(KEY)
    window.start_connect()
    window.start_connect()
    window.close()
    assert len(started) == 1
    assert window.busy and not window.root.destroyed
    assert window.key.get() == ''
