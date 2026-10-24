"""An uploaded ZIP must not look like a code edit to Werkzeug's watchdog."""
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pt_ai_square.backend.dev_reload import upload_reload_excludes


BASE = Path(__file__).resolve().parents[1]


def watchdog_loop(monkeypatch, patterns=()):
    pytest.importorskip('watchdog')
    from werkzeug._reloader import WatchdogReloaderLoop
    monkeypatch.setattr(WatchdogReloaderLoop, 'log_reload', lambda *args: None)
    return WatchdogReloaderLoop(exclude_patterns=patterns)


@pytest.mark.parametrize('folder', ['artifacts', 'request_attachments'])
@pytest.mark.parametrize('event_name', ['FileCreatedEvent', 'FileModifiedEvent', 'FileDeletedEvent'])
def test_uploaded_zip_no_longer_triggers_watchdog_restart(tmp_path, monkeypatch, folder, event_name):
    pytest.importorskip('watchdog')
    import watchdog.events
    # Includes Unicode, whitespace and bracket characters found in real paths.
    data = tmp_path / '회사 자료 [운영]'
    uploaded = data / folder / 'deployment.zip'
    event = getattr(watchdog.events, event_name)(str(uploaded))
    original = watchdog_loop(monkeypatch)
    original.event_handler.dispatch(event)
    assert original.should_reload.is_set(), 'The old default must reproduce the restart trigger'
    fixed = watchdog_loop(monkeypatch, upload_reload_excludes(data))
    fixed.event_handler.dispatch(event)
    assert not fixed.should_reload.is_set()


@pytest.mark.parametrize('filename', ['backend/routes.py', 'dependencies/library.zip'])
def test_source_edits_outside_uploads_still_reload(tmp_path, monkeypatch, filename):
    pytest.importorskip('watchdog')
    from watchdog.events import FileModifiedEvent
    # DATA_DIR can equal the application directory; do not ignore all code.
    fixed = watchdog_loop(monkeypatch, upload_reload_excludes(tmp_path))
    fixed.event_handler.dispatch(FileModifiedEvent(str(tmp_path / filename)))
    assert fixed.should_reload.is_set()


def test_relative_store_is_resolved_at_launch_without_changing_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert upload_reload_excludes('instance') == upload_reload_excludes(tmp_path / 'instance')
    assert Path.cwd() == tmp_path
    assert not (tmp_path / 'instance').exists(), 'Building watch patterns does not create data'


def test_company_launcher_keeps_application_host_debug_and_default_port(tmp_path, monkeypatch):
    calls = []
    app = SimpleNamespace(config={'DATA_DIR': str(tmp_path)}, run=lambda **kwargs: calls.append(kwargs))
    monkeypatch.setitem(sys.modules, 'web_main', SimpleNamespace(app=app))
    monkeypatch.syspath_prepend(str(BASE))
    namespace = runpy.run_path(str(BASE / 'index.py'), run_name='__main__')
    assert namespace['application'] is app
    assert calls == [{'debug': True, 'host': '0.0.0.0',
                      'exclude_patterns': upload_reload_excludes(tmp_path)}]


def test_wsgi_import_does_not_run_a_server_or_modify_flask_config(tmp_path, monkeypatch):
    config = {'DATA_DIR': str(tmp_path)}
    app = SimpleNamespace(config=config, run=lambda **kwargs: pytest.fail('WSGI import must not start server'))
    monkeypatch.setitem(sys.modules, 'web_main', SimpleNamespace(app=app))
    namespace = runpy.run_path(str(BASE / 'index.py'), run_name='company_index')
    assert namespace['application'] is app
    assert config == {'DATA_DIR': str(tmp_path)}
