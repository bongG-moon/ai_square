"""Private location chooser contracts, without touching a user's folders or GUI."""
import json
from pathlib import Path
from queue import Queue
import sys
import threading
from types import SimpleNamespace

import pytest

PACKAGE = Path(__file__).parents[1] / 'integrations' / 'pt-square-mcp'
sys.path.insert(0, str(PACKAGE))
from pt_square_mcp import workspace_ui as ui
from pt_square_mcp import connection_ui
from pt_square_mcp.config import SquareError, Settings, atomic_json, save_config


@pytest.fixture
def paths(tmp_path, monkeypatch):
    home = tmp_path / 'private-home'
    current = tmp_path / 'verified-project'
    other = tmp_path / 'selected-other'
    candidate = tmp_path / 'launch-candidate'
    for path in (home, current, other, candidate):
        path.mkdir()
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    return SimpleNamespace(home=home, current=current, other=other, candidate=candidate, base=tmp_path)


def locations(paths):
    return {'options':[{'scope':'user','label':'공통 (내 계정)','path':str(paths.home)}],
            'currentProject':{'path':str(paths.current),'name':'현재 프로젝트','source':'host-root'},
            'projectCandidates':[{'path':str(paths.current),'name':'현재 프로젝트','source':'host-root'}],
            'confirmationCandidates':[{'path':str(paths.candidate),'name':'확인할 프로젝트','source':'launch-cwd-unconfirmed','requiresUserSelection':True}],
            'rootsStatus':'available'}


def test_choices_keep_confirmed_host_roots_and_unconfirmed_launch_candidate_separate(paths):
    choices = ui.location_choices(locations(paths))
    assert choices['current']['path'] == str(paths.current)
    assert choices['projects'] == [{'path':str(paths.current),'name':'현재 프로젝트'}]
    assert choices['confirmations'] == [{'path':str(paths.candidate),'name':'확인할 프로젝트'}]
    assert choices['user']['path'] == str(paths.home)


def test_no_host_current_is_invented_from_candidates_or_python_cwd(paths, monkeypatch):
    monkeypatch.chdir(paths.other)
    data = locations(paths)
    data['currentProject'] = None
    choices = ui.location_choices(data)
    assert choices['current'] is None
    assert len(choices['projects']) == 1
    assert choices['projects'][0]['path'] != str(paths.other)
    choices = ui.location_choices({'confirmationCandidates':data['confirmationCandidates']})
    assert choices['current'] is None and choices['projects'] == []
    assert choices['confirmations'][0]['path'] == str(paths.candidate)


def test_bad_missing_and_drive_candidates_are_not_selectable(paths):
    file = paths.base / 'not-a-folder.txt'
    file.write_text('harmless', encoding='utf-8')
    rows = [{'path':str(path)} for path in (paths.base/'missing', file, Path(paths.base.anchor))]
    rows += [{'path':'relative-path'}, {'path':str(paths.current)}, {'path':str(paths.current)}]
    choices = ui.location_choices({'projectCandidates':rows})
    assert choices['projects'] == [{'path':str(paths.current),'name':paths.current.name}]


@pytest.mark.parametrize(('selection','attribute','scope'), [('user','home','user'),('current','current','project'),('confirmed-current','candidate','project'),('other','other','project')])
def test_selection_reports_exact_scope_without_installing_or_writing_settings(paths, selection, attribute, scope):
    before = set(paths.base.rglob('*'))
    result = ui.selection_result(selection, str(getattr(paths, attribute)), 'install')
    assert result == {'selected':True,'selection':selection,'scope':scope,'path':str(getattr(paths,attribute)),
                      'notice':'위치만 선택했습니다. 설치나 업로드는 아직 실행하지 않았습니다.'}
    assert set(paths.base.rglob('*')) == before


def test_publish_cannot_choose_account_home_scope(paths):
    with pytest.raises(SquareError):
        ui.selection_result('user', str(paths.home), 'publish')


def test_request_atomic_result_contains_selection_and_completion_time(paths):
    request = paths.base/'request.json'
    atomic_json(request, {'purpose':'install','locations':locations(paths),'initialDirectory':str(paths.other),'expiresAt':9999})
    calls = []
    def chooser(*args, **kwargs):
        calls.append((args,kwargs))
        return ui.selection_result('current', str(paths.current), 'install')
    result = ui.run_request(request, chooser=chooser, clock=lambda:1000)
    assert result['completedAt'] == 1000 and result['status'] == 'selected'
    assert json.loads((paths.base/'result.json').read_text(encoding='utf-8')) == result
    args, kwargs = calls[0]
    assert args[0] == 'install' and args[2] == str(paths.other)
    assert kwargs['expires_at'] == 1600
    assert kwargs['cancel_marker'] == paths.base/'cancel.marker'
    assert not list(paths.base.glob('*.tmp'))


@pytest.mark.parametrize('cancelled', [False, True])
def test_expired_or_cancelled_request_does_not_open_a_window(paths, cancelled):
    request = paths.base/'request.json'
    atomic_json(request, {'purpose':'install','expiresAt':2000 if cancelled else 999})
    if cancelled:
        (paths.base/'cancel.marker').write_text('cancel', encoding='utf-8')
    result = ui.run_request(request, chooser=lambda *_a,**_kw:pytest.fail('must not open'), clock=lambda:1000)
    assert result['status'] == ('cancelled' if cancelled else 'expired')
    assert result['selected'] is False and result['completedAt'] == 1000


@pytest.mark.parametrize('expires', [None, True, '2000', float('nan'), float('inf')])
def test_invalid_expiry_is_sanitized(paths, expires):
    request = paths.base/'request.json'
    request.write_text(json.dumps({'purpose':'install','expiresAt':expires}), encoding='utf-8')
    result = ui.run_request(request, chooser=lambda *_a,**_kw:pytest.fail('must not open'), clock=lambda:1000)
    assert result['status'] == 'failed' and result['notice'] == ui.FAILED


def test_exception_text_and_private_data_never_reach_result_or_console(paths, capsys):
    request = paths.base/'request.json'
    atomic_json(request, {'purpose':'publish','expiresAt':2000})
    def failure(*_a, **_kw):
        raise RuntimeError('PRIVATE-KEY-DO-NOT-LOG')
    result = ui.run_request(request, chooser=failure, clock=lambda:1000)
    assert result['status'] == 'failed'
    assert 'PRIVATE' not in (paths.base/'result.json').read_text(encoding='utf-8')
    captured = capsys.readouterr()
    assert captured.out == captured.err == ''


class Variable:
    def __init__(self, value=''):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class Root:
    def __init__(self):
        self.destroyed = False
        self.callbacks = []
        self.cancelled_callbacks = []
    def destroy(self):
        self.destroyed = True
    def after(self, delay, callback):
        self.callbacks.append((delay,callback))
        return len(self.callbacks)
    def after_cancel(self, identifier):
        self.cancelled_callbacks.append(identifier)


def controller(paths):
    window = ui.LocationWindow.__new__(ui.LocationWindow)
    window.root = Root()
    window.purpose = 'install'
    window.clock = lambda:1000
    window.expires_at = 1600
    window.cancel_marker = paths.base/'cancel.marker'
    window.closed = window.busy = False
    window.after_ids = set()
    window.cancel_event = threading.Event()
    window.result = {'selected':False}
    window.choices = ui.location_choices(locations(paths))
    window.selection = Variable('current')
    window.current_path = str(paths.current)
    window.current_selection = 'current'
    window.status = Variable()
    window.other_path = ''
    window.other_label = Variable()
    window.picker_results = Queue()
    window.browse = SimpleNamespace(configure=lambda **_kw:None)
    window.confirm = SimpleNamespace(configure=lambda **_kw:None)
    return window


def test_expiry_and_marker_close_even_while_native_picker_is_busy(paths):
    for expired in (False,True):
        window = controller(paths)
        window.busy = True
        if expired:
            window.expires_at = 999
        else:
            window.cancel_marker.write_text('cancel', encoding='utf-8')
        window.poll()
        assert window.closed and window.root.destroyed and window.cancel_event.is_set()
        assert not window.result['selected']
        assert window.result['status'] == ('expired' if expired else 'cancelled')


def test_confirmed_launch_path_requires_combo_selection_then_explicit_accept(paths):
    window = controller(paths)
    window.current_path = ''
    window.accept()
    assert not window.closed
    window.candidates = [{'path':str(paths.candidate),'name':'후보','selection':'confirmed-current'}]
    window.project_combo = SimpleNamespace(current=lambda:0)
    window.project_path_label = Variable()
    window.project_selected()
    assert window.project_path_label.get() == str(paths.candidate)
    assert not window.closed
    window.accept()
    assert window.result['selection'] == 'confirmed-current' and window.result['scope'] == 'project'
    assert window.result['path'] == str(paths.candidate)


def test_accept_cannot_win_over_existing_cancel_marker(paths):
    window = controller(paths)
    window.cancel_marker.write_text('cancel', encoding='utf-8')
    window.accept()
    assert not window.result['selected'] and window.result['status'] == 'cancelled'


def test_cancelled_native_picker_keeps_previous_confirmed_path_and_allows_retry(paths):
    window = controller(paths)
    window.busy = True
    window.other_path = str(paths.other)
    window.picker_results.put((True,''))
    window.poll()
    assert not window.busy and not window.closed
    assert window.other_path == str(paths.other)
    assert '취소' in window.status.get()


def test_finish_cancels_poll_and_foreground_callbacks_before_destroy(paths):
    window = controller(paths)
    invoked = []
    window.schedule(100, window.poll)
    window.schedule(300, lambda:invoked.append('foreground'))
    assert len(window.after_ids) == 2
    window.cancel()
    assert sorted(window.root.cancelled_callbacks) == [1,2]
    assert not window.after_ids and window.root.destroyed
    # A callback already queued by Tcl must also be harmless after closing.
    for _, callback in window.root.callbacks:
        callback()
    assert invoked == [] and len(window.root.callbacks) == 2


def test_poll_consumes_its_callback_and_schedules_only_one_next_poll(paths):
    window = controller(paths)
    window.schedule(100, window.poll)
    window.root.callbacks[0][1]()
    assert window.after_ids == {2}
    window.cancel()
    assert window.root.cancelled_callbacks == [2]


@pytest.fixture
def withdrawn_root():
    tk = pytest.importorskip('tkinter', reason='Native widget contract requires Python Tcl/Tk')
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip('Native widget contract requires a display')
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


def test_one_unconfirmed_candidate_is_visible_but_requires_final_confirmation(paths, withdrawn_root):
    data = {'options':locations(paths)['options'], 'confirmationCandidates':locations(paths)['confirmationCandidates']}
    window = ui.LocationWindow(withdrawn_root, 'install', data)
    assert window.current_path == str(paths.candidate)
    assert window.current_selection == 'confirmed-current'
    assert not hasattr(window, 'project_combo')
    assert window.result['selected'] is False
    before = list(paths.candidate.iterdir())
    window.accept()
    assert window.result['selected'] and window.result['selection'] == 'confirmed-current'
    assert list(paths.candidate.iterdir()) == before
    assert not window.after_ids


def test_multiple_candidates_need_explicit_combo_selection_before_confirm(paths, withdrawn_root):
    data = locations(paths)
    data['currentProject'] = None
    window = ui.LocationWindow(withdrawn_root, 'install', data)
    assert window.project_combo.current() == -1 and window.current_path == ''
    window.accept()
    assert not window.closed and not window.result['selected']
    window.project_combo.current(1)
    window.project_selected()
    window.accept()
    assert window.result['selection'] == 'confirmed-current'
    assert window.result['path'] == str(paths.candidate)


def test_choose_location_sets_dpi_before_creating_tk_root(paths, monkeypatch):
    events = []
    root = SimpleNamespace(mainloop=lambda:events.append('loop'), destroy=lambda:events.append('destroy'),
                           lift=lambda:events.append('lift'), attributes=lambda *_a:events.append('foreground'),
                           after=lambda *_a:events.append('release-foreground'))
    monkeypatch.setattr(ui, 'enable_dpi_awareness', lambda:events.append('dpi'))
    monkeypatch.setitem(sys.modules, 'tkinter', SimpleNamespace(Tk=lambda:(events.append('tk') or root),TclError=RuntimeError))
    monkeypatch.setattr(ui, 'LocationWindow', lambda *_a,**_kw:SimpleNamespace(result={'selected':False},schedule=root.after))
    assert not ui.choose_location('install')['selected']
    assert events[:2] == ['dpi','tk']


def test_default_legacy_account_selection_does_not_trust_entire_home(paths, monkeypatch):
    downloads = paths.home/'AI_SQUARE'/'downloads'
    downloads.mkdir(parents=True)
    config = paths.base/'config.json'
    save_config(config, 'http://company.example', [downloads], allow_http=True, download_directory=downloads)
    before = config.read_bytes()
    monkeypatch.setattr(ui, 'choose_location', lambda _purpose:ui.selection_result('user',str(paths.home),'install'))
    result = connection_ui.choose_workspace(config, 'install')
    assert result['scope'] == 'user' and result['selected']
    assert config.read_bytes() == before and Settings(config).roots == [downloads]
