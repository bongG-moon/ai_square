"""Private, DPI-aware location selection. This window never installs or reads a KEY."""
import argparse
import ctypes
import json
import math
import os
from pathlib import Path
from queue import Empty, Queue
import threading
import time
import uuid

from .config import SquareError, atomic_json, no_links

WAITING = '위치 선택 대기 · 설치나 업로드는 아직 실행하지 않았습니다. 선택 후 AI에 “선택했어”라고 알려주세요.'
CANCELLED = '위치 선택을 취소했습니다. 설치나 업로드는 실행하지 않았습니다.'
FAILED = '위치 선택 창을 완료하지 못했습니다. 창을 닫고 다시 요청해 주세요.'


def enable_dpi_awareness():
    """Call before creating any Tk window; older Windows versions use a fallback."""
    if os.name != 'nt':
        return
    try:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        function = user32.SetProcessDpiAwarenessContext
        function.argtypes = [ctypes.c_void_p]
        function.restype = ctypes.c_bool
        if function(ctypes.c_void_p(-4)):
            return
        # A host may have already set process awareness; the new UI thread can
        # still use per-monitor awareness before Tk creates its first HWND.
        function = user32.SetThreadDpiAwarenessContext
        function.argtypes = [ctypes.c_void_p]
        function.restype = ctypes.c_void_p
        if function(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.WinDLL('shcore').SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.WinDLL('user32').SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _directory(value):
    if not isinstance(value, str) or not value.strip() or not Path(value).is_absolute():
        raise SquareError('폴더를 먼저 선택해 주세요.')
    path = no_links(value)
    if not path.is_dir() or path == Path(path.anchor):
        raise SquareError('실제로 존재하는 작업 폴더를 선택해 주세요. 드라이브 전체는 선택할 수 없습니다.')
    return str(path)


def _candidate(row):
    if not isinstance(row, dict):
        return None
    try:
        path = _directory(row.get('path'))
    except (SquareError, OSError, ValueError):
        return None
    return {'path': path, 'name': str(row.get('name') or Path(path).name)[:120]}


def location_choices(locations=None):
    """Normalize only verified paths passed by the host; never guess its cwd."""
    locations = locations if isinstance(locations, dict) else {}
    user = next((_candidate(row) for row in locations.get('options', [])
                 if isinstance(row, dict) and row.get('scope') == 'user'), None)
    if user is None:
        user = _candidate({'path': str(Path.home()), 'name': '내 계정'})
    current = _candidate(locations.get('currentProject'))
    projects = []
    for row in locations.get('projectCandidates', []):
        candidate = _candidate(row)
        if candidate and all(x['path'] != candidate['path'] for x in projects):
            projects.append(candidate)
    if current and all(x['path'] != current['path'] for x in projects):
        projects.insert(0, current)
    confirmations = []
    for row in locations.get('confirmationCandidates', []):
        candidate = _candidate(row)
        if candidate and all(x['path'] != candidate['path'] for x in projects+confirmations):
            confirmations.append(candidate)
    return {'user': user, 'current': current, 'projects': projects, 'confirmations': confirmations}


def selection_result(selection, path, purpose):
    if purpose not in {'install', 'publish'} or selection not in {'user', 'current', 'confirmed-current', 'other'}:
        raise SquareError('위치 선택 항목을 확인해 주세요.')
    if purpose == 'publish' and selection == 'user':
        raise SquareError('등록할 원본 파일이 있는 프로젝트 폴더를 선택해 주세요.')
    return {'selected': True, 'scope': 'user' if selection == 'user' else 'project',
            'path': _directory(path), 'selection': selection,
            'notice': '위치만 선택했습니다. 설치나 업로드는 아직 실행하지 않았습니다.'}


def _windows_folder_picker(owner=0, initial_directory=None, cancel_event=None):
    """Windows Explorer's IFileOpenDialog, without Tk's legacy folder tree."""
    if os.name != 'nt':
        raise SquareError('이 폴더 선택 창은 Windows에서 사용할 수 있습니다.')
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [('a', wintypes.DWORD), ('b', wintypes.WORD),
                    ('c', wintypes.WORD), ('d', ctypes.c_ubyte * 8)]

    def guid(value):
        return GUID.from_buffer_copy(uuid.UUID(value).bytes_le)

    clsid = guid('DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7')
    iid = guid('D57C7288-D4AD-4768-BE02-9D969532D960')
    shell_iid = guid('43826D1E-E718-42EE-BC55-A1E261C37BFE')
    window_iid = guid('00000114-0000-0000-C000-000000000046')
    ole = ctypes.WinDLL('ole32')
    shell = ctypes.WinDLL('shell32')
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    pointer = ctypes.c_void_p
    ole.CoInitializeEx.argtypes = [pointer, wintypes.DWORD]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoCreateInstance.argtypes = [ctypes.POINTER(GUID), pointer, wintypes.DWORD, ctypes.POINTER(GUID), ctypes.POINTER(pointer)]
    ole.CoCreateInstance.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [pointer]
    shell.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, pointer, ctypes.POINTER(GUID), ctypes.POINTER(pointer)]
    shell.SHCreateItemFromParsingName.restype = ctypes.c_long
    timer_proc = ctypes.WINFUNCTYPE(None, wintypes.HWND, wintypes.UINT, ctypes.c_size_t, wintypes.DWORD)
    user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, timer_proc]
    user32.SetTimer.restype = ctypes.c_size_t
    user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
    user32.KillTimer.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
    user32.PostMessageW.restype = wintypes.BOOL

    def call(instance, index, types=(), args=(), result=ctypes.c_long):
        table = ctypes.cast(instance, ctypes.POINTER(ctypes.POINTER(pointer))).contents
        return ctypes.WINFUNCTYPE(result, pointer, *types)(table[index])(instance, *args)

    def checked(hr):
        if hr < 0:
            raise SquareError('Windows 폴더 선택 창을 열지 못했습니다. 다시 시도해 주세요.')

    if cancel_event is not None and cancel_event.is_set():
        return ''
    initialized = ole.CoInitializeEx(None, 2)
    checked(initialized)
    dialog, item, initial, native_window = pointer(), pointer(), pointer(), pointer()
    timer_id = 0
    callback = None  # Keep the native callback alive until KillTimer completes.
    try:
        checked(ole.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(dialog)))
        options = 0x20 | 0x40 | 0x800 | 0x8 | 0x02000000  # folders, filesystem, existing, no cwd/recent changes
        checked(call(dialog, 9, (wintypes.DWORD,), (options,)))
        checked(call(dialog, 17, (wintypes.LPCWSTR,), ('AI SQUARE · 사용할 폴더 선택',)))
        checked(call(dialog, 18, (wintypes.LPCWSTR,), ('이 폴더 선택',)))
        if initial_directory:
            # A missing initial folder is harmless; Windows opens its usual view.
            if shell.SHCreateItemFromParsingName(str(initial_directory), None, ctypes.byref(shell_iid), ctypes.byref(initial)) >= 0:
                call(dialog, 12, (pointer,), (initial,))
        if cancel_event is not None:
            checked(call(dialog, 0, (ctypes.POINTER(GUID), ctypes.POINTER(pointer)),
                         (ctypes.byref(window_iid), ctypes.byref(native_window))))
            def check_cancel(_window, _message, _timer, _tick):
                # Show pumps this STA's messages. Closing from its own timer
                # avoids a cross-apartment COM call that can wait indefinitely.
                if cancel_event.is_set():
                    hwnd = wintypes.HWND()
                    has_window = call(native_window, 3, (ctypes.POINTER(wintypes.HWND),), (ctypes.byref(hwnd),)) >= 0 and bool(hwnd.value)
                    call(dialog, 23, (ctypes.c_long,), (ctypes.c_long(0x800704C7).value,))
                    # Some Explorer builds report Close S_OK but leave Show's
                    # visible modal window alive. Post to this COM object's own
                    # window only; never find or close unrelated Explorer windows.
                    if has_window:
                        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE

            callback = timer_proc(check_cancel)
            timer_id = user32.SetTimer(None, 0, 100, callback)
            if not timer_id:
                raise SquareError('Windows 폴더 선택 창의 취소 기능을 준비하지 못했습니다. 다시 시도해 주세요.')
        if cancel_event is not None and cancel_event.is_set():
            return ''
        hr = call(dialog, 3, (wintypes.HWND,), (owner,))
        if hr == ctypes.c_long(0x800704C7).value or (cancel_event is not None and cancel_event.is_set()):
            return ''
        checked(hr)
        checked(call(dialog, 20, (ctypes.POINTER(pointer),), (ctypes.byref(item),)))
        display = pointer()
        checked(call(item, 5, (wintypes.DWORD, ctypes.POINTER(pointer)), (0x80058000, ctypes.byref(display))))
        try:
            return ctypes.wstring_at(display)
        finally:
            ole.CoTaskMemFree(display)
    finally:
        if timer_id:
            user32.KillTimer(None, timer_id)
        for instance in (item, initial, native_window, dialog):
            if instance:
                call(instance, 2, result=wintypes.ULONG)
        ole.CoUninitialize()


class LocationWindow:
    def __init__(self, root, purpose, locations=None, initial_directory=None, *,
                 picker=None, cancel_marker=None, expires_at=None, clock=time.time):
        import tkinter as tk
        from tkinter import ttk
        self.root, self.purpose, self.clock = root, purpose, clock
        self.cancel_marker = Path(cancel_marker) if cancel_marker else None
        self.expires_at = min(clock() + 600 if expires_at is None else expires_at, clock() + 600)
        self.picker = picker or _windows_folder_picker
        self.choices = location_choices(locations)
        self.result = {'selected': False, 'notice': CANCELLED}
        self.closed = False
        self.busy = False
        self.after_ids = set()
        self.cancel_event = threading.Event()
        self.picker_results = Queue()
        self.other_path = ''
        self.initial_directory = initial_directory
        self.current_path = self.choices['current']['path'] if self.choices['current'] else ''
        self.current_selection = 'current'
        self.candidates = [dict(x, selection='current') for x in self.choices['projects']]+[dict(x, selection='confirmed-current') for x in self.choices['confirmations']]
        if not self.current_path and len(self.candidates) == 1:
            # The final button is the explicit confirmation; this does not
            # grant trust, install, or prepare anything on its own.
            self.current_path = self.candidates[0]['path']
            self.current_selection = self.candidates[0]['selection']
        self.selection = tk.StringVar(root, value='current' if self.current_path or self.candidates else 'user' if purpose == 'install' else 'other')
        self.status = tk.StringVar(root, value=WAITING)
        self.other_label = tk.StringVar(root, value='아직 선택한 폴더가 없습니다.')
        scale = max(1, root.winfo_fpixels('1i') / 96)
        self.px = lambda value: round(value * scale)
        p = self.px
        root.title('P&T AI SQUARE · '+('설치 위치 선택' if purpose == 'install' else '등록할 폴더 선택'))
        root.configure(bg='#f5f6fa')
        width, height = min(p(700), root.winfo_screenwidth()-p(32)), min(p(760), root.winfo_screenheight()-p(64))
        root.geometry(f'{width}x{height}+{max(0,(root.winfo_screenwidth()-width)//2)}+{max(0,(root.winfo_screenheight()-height)//2)}')
        root.minsize(min(p(600), width), min(p(580), height))
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('Location.TButton', font=('맑은 고딕', 10), padding=(p(14), p(9)))
        style.configure('Primary.Location.TButton', background='#4972df', foreground='#ffffff', font=('맑은 고딕', 10, 'bold'))
        style.map('Primary.Location.TButton', background=[('disabled','#acbce7'),('active','#3d62c9')])
        style.configure('Location.TCombobox', padding=p(7), font=('맑은 고딕', 10))
        outer = tk.Frame(root, bg='#f5f6fa', padx=p(28), pady=p(24))
        outer.pack(fill='both', expand=True)
        self.label(outer, 'P&T AI SQUARE', 10, '#77839b').pack(anchor='w')
        self.label(outer, '어디에서 사용할까요?' if purpose == 'install' else '어떤 폴더를 등록할까요?', 23, '#20232a', bold=True).pack(anchor='w', pady=(p(7),p(8)))
        self.label(outer, '사용 범위를 선택한 뒤 실제 경로를 확인해 주세요.' if purpose == 'install' else '등록할 원본 파일이 들어 있는 폴더만 선택해 주세요.', 10, '#697184').pack(anchor='w', pady=(0,p(18)))
        footer = tk.Frame(outer, bg='#f5f6fa')
        footer.pack(side='bottom', fill='x', pady=(p(14),0))
        self.label(footer, None, 10, '#64718b', variable=self.status, wrap=610).pack(anchor='w', fill='x', pady=(0,p(14)))
        self.confirm = ttk.Button(footer, text='이 위치 사용', style='Primary.Location.TButton', command=self.accept)
        self.confirm.pack(side='right')
        ttk.Button(footer, text='취소', style='Location.TButton', command=self.cancel).pack(side='right', padx=(0,p(8)))
        body = tk.Frame(outer, bg='#f5f6fa')
        body.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(body, bg='#f5f6fa', borderwidth=0, highlightthickness=0)
        scroll = ttk.Scrollbar(body, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        inner = tk.Frame(self.canvas, bg='#f5f6fa')
        window = self.canvas.create_window((0,0), window=inner, anchor='nw')
        inner.bind('<Configure>', lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(window, width=e.width))
        root.bind('<MouseWheel>', lambda e: self.canvas.yview_scroll(-int(e.delta/120),'units'))
        self.cards = {}
        if purpose == 'install':
            frame = self.card(inner, 'user', '공통 (내 계정)', '이 PC에서 내 계정으로 사용하는 여러 프로젝트에 적용합니다. 모든 사용자에게 설치하지 않습니다.')
            self.label(frame, self.choices['user']['path'] if self.choices['user'] else '사용자 폴더를 확인할 수 없습니다.', 10, '#47556e', wrap=560, bg='white').pack(anchor='w', fill='x', pady=(p(8),0))
        frame = self.card(inner, 'current', '현재 프로젝트 폴더', '선택한 프로젝트에서만 사용합니다.' if purpose == 'install' else '이 프로젝트의 원본 파일을 등록합니다.')
        if self.current_path:
            self.label(frame, self.current_path, 10, '#47556e', wrap=560, bg='white').pack(anchor='w', fill='x', pady=(p(8),0))
            if self.current_selection == 'confirmed-current':
                self.label(frame, '확인 필요 · 이 프로그램이 시작된 폴더입니다. 프로젝트 경로가 맞는지 확인한 뒤 ‘이 위치 사용’을 눌러주세요.', 10, '#94734e', wrap=560, bg='white').pack(anchor='w', fill='x', pady=(p(8),0))
        elif self.candidates:
            self.project_combo = ttk.Combobox(frame, state='readonly', style='Location.TCombobox', values=[('확인 필요 · ' if x['selection']=='confirmed-current' else '')+x['name']+' · '+x['path'] for x in self.candidates])
            self.project_combo.set('사용할 프로젝트를 선택하세요')
            self.project_combo.pack(fill='x', pady=(p(10),0))
            self.project_combo.bind('<<ComboboxSelected>>', self.project_selected)
            self.project_path_label = tk.StringVar(root, value='폴더를 선택하면 전체 경로가 여기에 표시됩니다.')
            self.label(frame, None, 10, '#47556e', variable=self.project_path_label, wrap=560, bg='white').pack(anchor='w', fill='x', pady=(p(8),0))
            if self.choices['confirmations']:
                self.label(frame, '‘확인 필요’ 경로는 이 프로그램이 시작된 폴더입니다. 프로젝트 경로가 맞는지 확인해 주세요.', 10, '#94734e', wrap=560, bg='white').pack(anchor='w', fill='x', pady=(p(8),0))
        else:
            self.label(frame, '현재 프로젝트를 확인하지 못했어요. 아래에서 폴더를 선택해 주세요.', 10, '#7a8497', wrap=560, bg='white').pack(anchor='w', fill='x', pady=(p(8),0))
        frame = self.card(inner, 'other', '기타 경로' if purpose == 'install' else '다른 원본 폴더', '파일 탐색기에서 사용할 폴더를 직접 선택합니다.')
        self.label(frame, None, 10, '#47556e', variable=self.other_label, wrap=560, bg='white').pack(anchor='w', fill='x', pady=(p(8),p(10)))
        self.browse = ttk.Button(frame, text='폴더 찾아보기', style='Location.TButton', command=self.browse_folder)
        self.browse.pack(anchor='w')
        for value, card in self.cards.items():
            for child in card.winfo_children():
                if child.winfo_class() == 'Label':
                    child.bind('<Button-1>', lambda _e, selected=value: self.selection.set(selected))
        self.selection.trace_add('write', lambda *_: self.refresh_selection())
        self.refresh_selection()
        root.protocol('WM_DELETE_WINDOW', self.cancel)
        root.bind('<Escape>', lambda _e: self.cancel())
        self.schedule(100, self.poll)

    def schedule(self, delay, callback):
        if self.closed:
            return
        def invoke():
            self.after_ids.discard(identifier)
            if not self.closed:
                callback()
        identifier = self.root.after(delay, invoke)
        self.after_ids.add(identifier)

    def label(self, parent, text, size, color, *, bold=False, variable=None, wrap=None, bg='#f5f6fa'):
        import tkinter as tk
        return tk.Label(parent, text=text, textvariable=variable, bg=bg, fg=color,
                        font=('맑은 고딕',size,'bold' if bold else 'normal'), anchor='w', justify='left',
                        wraplength=self.px(wrap) if wrap else 0)

    def card(self, parent, value, title, explanation):
        import tkinter as tk
        p = self.px
        shell = tk.Frame(parent, bg='white', highlightthickness=p(1), highlightbackground='#e0e5ef', padx=p(18), pady=p(16))
        shell.pack(fill='x', pady=(0,p(12)), padx=(0,p(8)))
        radio = tk.Radiobutton(shell, text=title, variable=self.selection, value=value, bg='white', activebackground='white',
                               fg='#252a36', activeforeground='#252a36', selectcolor='#eef3ff', font=('맑은 고딕',12,'bold'),
                               anchor='w', padx=0, pady=0, highlightthickness=0)
        radio.pack(anchor='w')
        self.label(shell, explanation, 10, '#758096', wrap=560, bg='white').pack(anchor='w', fill='x', pady=(p(6),0))
        shell.bind('<Button-1>', lambda _e: self.selection.set(value))
        self.cards[value] = shell
        return shell

    def project_selected(self, _event=None):
        index = self.project_combo.current()
        self.current_path = self.candidates[index]['path'] if index >= 0 else ''
        self.current_selection = self.candidates[index]['selection'] if index >= 0 else 'current'
        self.project_path_label.set(self.current_path or '사용할 프로젝트를 선택해 주세요.')
        self.selection.set('current')

    def refresh_selection(self):
        for value, card in self.cards.items():
            card.configure(highlightbackground='#4972df' if self.selection.get()==value else '#e0e5ef')
        self.status.set(WAITING)

    def browse_folder(self):
        if self.closed or self.busy:
            return
        self.busy = True
        self.selection.set('other')
        self.browse.configure(state='disabled')
        self.confirm.configure(state='disabled')
        self.status.set('열린 파일 탐색기에서 폴더를 선택해 주세요. 설치나 업로드는 아직 실행하지 않았습니다.')
        owner = self.root.winfo_id()
        initial = self.other_path or self.initial_directory or self.current_path or (self.choices['user'] or {}).get('path')
        def worker():
            try:
                chosen = self.picker(owner, initial, self.cancel_event)
                self.picker_results.put((True, _directory(chosen) if chosen else ''))
            except Exception:
                self.picker_results.put((False, '폴더 선택을 완료하지 못했습니다. 다른 폴더를 선택하거나 다시 시도해 주세요.'))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        if self.closed:
            return
        if self.clock() >= self.expires_at or (self.cancel_marker and self.cancel_marker.exists()):
            expired = self.clock() >= self.expires_at
            self.finish({'selected':False, 'status':'expired' if expired else 'cancelled', 'notice':'선택 시간이 지나 창을 닫았습니다. 설치나 업로드는 실행하지 않았습니다.' if expired else CANCELLED})
            return
        try:
            ok, value = self.picker_results.get_nowait()
        except Empty:
            pass
        else:
            self.busy = False
            self.browse.configure(state='normal')
            self.confirm.configure(state='normal')
            if ok and value:
                self.other_path = value
                self.other_label.set(value)
                self.status.set(WAITING)
            elif not ok:
                self.status.set(value)
            else:
                self.status.set('폴더 선택을 취소했습니다. 다시 선택하거나 이 창을 닫을 수 있습니다.')
        self.schedule(100, self.poll)

    def accept(self):
        if self.closed or self.busy:
            return
        if self.clock() >= self.expires_at or (self.cancel_marker and self.cancel_marker.exists()):
            self.poll()
            return
        selection = self.selection.get()
        path = (self.choices['user'] or {}).get('path') if selection == 'user' else self.current_path if selection == 'current' else self.other_path
        try:
            result = selection_result(self.current_selection if selection == 'current' else selection, path, self.purpose)
        except (SquareError, OSError, ValueError):
            self.status.set('사용할 폴더를 선택한 뒤 다시 눌러주세요. 드라이브 전체나 존재하지 않는 폴더는 사용할 수 없습니다.')
            return
        self.finish(result)

    def cancel(self, notice=CANCELLED):
        self.finish({'selected':False, 'notice':notice})

    def finish(self, result):
        if self.closed:
            return
        self.closed = True
        self.result = result
        self.cancel_event.set()
        import tkinter as tk
        for identifier in self.after_ids:
            try:
                self.root.after_cancel(identifier)
            except (tk.TclError, RuntimeError):
                pass
        self.after_ids.clear()
        self.root.destroy()


def choose_location(purpose, locations=None, initial_directory=None, *, cancel_marker=None, expires_at=None):
    if purpose not in {'install', 'publish'}:
        raise SquareError('위치 선택 용도는 install 또는 publish이어야 합니다.')
    enable_dpi_awareness()
    try:
        import tkinter as tk
    except ImportError:
        raise SquareError('위치 선택 창을 열 수 없습니다. Windows Python의 Tcl/Tk 설치를 확인해 주세요.') from None
    root = tk.Tk()
    try:
        window = LocationWindow(root, purpose, locations, initial_directory, cancel_marker=cancel_marker, expires_at=expires_at)
        root.lift()
        root.attributes('-topmost', True)
        window.schedule(300, lambda: root.attributes('-topmost', False))
        root.mainloop()
        return window.result
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def run_request(request_path, *, chooser=choose_location, clock=time.time):
    """No config or credential input/output; one atomic response next to the request."""
    request_path = no_links(request_path)
    destination = request_path.parent / 'result.json'
    try:
        raw = json.loads(request_path.read_text(encoding='utf-8-sig'))
        if not isinstance(raw, dict) or raw.get('purpose') not in {'install','publish'}:
            raise ValueError('invalid request')
        expires = raw.get('expiresAt')
        if not isinstance(expires, (int,float)) or isinstance(expires, bool) or not math.isfinite(expires):
            raise ValueError('invalid expiry')
        marker = request_path.parent / 'cancel.marker'
        if marker.exists() or clock() >= expires:
            result = {'selected':False, 'status':'expired' if clock() >= expires else 'cancelled', 'notice':CANCELLED}
        else:
            result = chooser(raw['purpose'], raw.get('locations'), raw.get('initialDirectory'), cancel_marker=marker, expires_at=min(expires,clock()+600))
            if not isinstance(result, dict) or type(result.get('selected')) is not bool:
                raise ValueError('invalid chooser result')
            result = dict(result, status='selected' if result['selected'] else result.get('status','cancelled'))
    except Exception:
        result = {'selected':False, 'status':'failed', 'notice':FAILED}
    result['completedAt'] = clock()
    atomic_json(destination, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='AI SQUARE private location chooser')
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_request(args.request)
    except Exception:
        return 1
    return 1 if result.get('status') == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
