"""A private KEY form and explicit native folder selection. No local HTTP server."""
from pathlib import Path
from queue import Empty, Queue
import threading
import webbrowser

from .config import (DEFAULT_CONFIG, AuthenticationRequired, SquareError, Settings, atomic_json,
                     default_download_directory, no_links, normalize_url, operation_lock)
from .onboarding import connect, resolve_connection


def _tk():
    try:
        import tkinter as tk
        from tkinter import filedialog, ttk
        return tk, ttk, filedialog
    except ImportError:
        raise SquareError('연결 창을 열 수 없습니다. 터미널에서 python run_mcp.py setup을 실행하면 KEY만 입력하여 연결할 수 있습니다.') from None


class ConnectionWindow:
    def __init__(self, root, config_path=DEFAULT_CONFIG, *, url=None):
        tk, ttk, _ = _tk()
        self.root, self.config_path = root, config_path
        self.url = normalize_url(url) if url is not None else resolve_connection(config_path)
        self.busy = False
        self.completed = False
        self.results = Queue()
        self.key = tk.StringVar(root)
        self.http_ack = tk.BooleanVar(root, value=False)
        self.status = tk.StringVar(root, value='개인 KEY를 입력하면 계정과 연결 권한을 확인합니다.')
        root.title('P&T AI SQUARE · 개인 KEY 연결')
        root.geometry('610x520')
        root.minsize(560, 480)
        root.configure(bg='#f5f5f7')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('Square.TFrame', background='#f5f5f7')
        style.configure('Square.TLabel', background='#f5f5f7', foreground='#1d1d1f', font=('맑은 고딕', 10))
        style.configure('Title.Square.TLabel', font=('맑은 고딕', 22, 'bold'))
        style.configure('Muted.Square.TLabel', foreground='#66666e')
        style.configure('Square.TCheckbutton', background='#f5f5f7', font=('맑은 고딕', 9))
        style.configure('Primary.TButton', font=('맑은 고딕', 11, 'bold'), padding=(16, 10), background='#4b70db', foreground='white')
        style.map('Primary.TButton', background=[('disabled','#9ba9cf'),('active','#3d60c4')])
        frame = ttk.Frame(root, style='Square.TFrame', padding=28)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='P&T AI SQUARE', style='Muted.Square.TLabel').pack(anchor='w')
        ttk.Label(frame, text='KEY 하나로 연결하세요.', style='Title.Square.TLabel').pack(anchor='w', pady=(6, 18))
        ttk.Label(frame, text='연결할 사이트', style='Muted.Square.TLabel').pack(anchor='w')
        ttk.Label(frame, text=self.url, style='Square.TLabel', wraplength=550).pack(anchor='w', pady=(3, 12))
        ttk.Label(frame, text='자동 다운로드 위치', style='Muted.Square.TLabel').pack(anchor='w')
        ttk.Label(frame, text=str(default_download_directory()), style='Square.TLabel', wraplength=550).pack(anchor='w', pady=(3, 16))
        ttk.Label(frame, text='개인 KEY', style='Square.TLabel').pack(anchor='w')
        self.entry = ttk.Entry(frame, textvariable=self.key, show='●', font=('맑은 고딕', 11))
        self.entry.pack(fill='x', pady=(6, 8), ipady=7)
        if self.url.startswith('http:'):
            ttk.Checkbutton(frame, text='이 회사 사이트의 HTTP 연결은 전송이 암호화되지 않음을 확인했습니다.',
                            variable=self.http_ack, style='Square.TCheckbutton').pack(anchor='w', pady=(0, 10))
        ttk.Label(frame, textvariable=self.status, style='Muted.Square.TLabel', wraplength=550).pack(anchor='w', fill='x', pady=(8, 16))
        actions = ttk.Frame(frame, style='Square.TFrame')
        actions.pack(side='bottom', fill='x')
        ttk.Button(actions, text='KEY 발급·재발급 사이트 열기', command=lambda: webbrowser.open(self.url+'/local-access')).pack(side='left')
        self.button = ttk.Button(actions, text='연결하기', style='Primary.TButton', command=self.start_connect)
        self.button.pack(side='right')
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.entry.bind('<Return>', lambda _event: self.start_connect())
        self.entry.focus_set()

    def start_connect(self):
        if self.completed:
            self.close()
            return
        if self.busy:
            return
        if self.url.startswith('http:') and not self.http_ack.get():
            self.status.set('위에 표시된 사이트의 HTTP 연결 안내를 확인해 주세요.')
            return
        token = self.key.get().strip()
        if not token:
            self.status.set('웹에서 발급한 개인 KEY를 붙여넣어 주세요.')
            return
        self.busy = True
        self.key.set('')
        self.entry.configure(state='disabled')
        self.button.configure(state='disabled', text='연결 확인 중…')
        self.status.set('서버에서 본인 계정을 확인하고 있습니다…')
        accepted = self.http_ack.get()

        def worker():
            try:
                result = connect(self.config_path, self.url, token, allow_http=accepted)
                self.results.put((True, result))
            except AuthenticationRequired:
                self.results.put((False, 'KEY가 만료되었거나 취소·재발급되었을 수 있습니다. 아래 KEY 사이트 버튼에서 확인한 후 새 KEY를 입력하세요. 웹도 이용할 수 없다면 운영자에게 계정 상태를 확인해 주세요.'))
            except SquareError as error:
                self.results.put((False, str(error)))
            except Exception:
                # Never expose a raw HTTP error, KEY or filesystem content in the UI.
                self.results.put((False, '연결 정보를 저장하지 못했습니다. 연결 상태와 사용자 폴더 접근을 확인해 주세요.'))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(80, self.poll)

    def poll(self):
        try:
            success, result = self.results.get_nowait()
        except Empty:
            self.root.after(80, self.poll)
            return
        self.busy = False
        self.button.configure(state='normal')
        if success:
            user = result['user']
            identity = user['name'] + (' · '+user['dept'] if user.get('dept') else '')
            self.status.set(identity+'님, 연결되었습니다.\nKEY는 Windows 사용자 계정으로 암호화해 저장했습니다.')
            self.completed = True
            self.button.configure(text='완료')
        else:
            self.entry.configure(state='normal')
            self.entry.focus_set()
            self.button.configure(text='다시 연결')
            self.status.set(result)

    def close(self):
        if self.busy:
            self.status.set('연결 결과를 확인 중입니다. 확인이 끝나면 창을 닫을 수 있습니다.')
            return
        self.root.destroy()


def _show_connection(config_path, url):
    url = normalize_url(url)
    from .workspace_ui import enable_dpi_awareness
    enable_dpi_awareness()
    tk, _, _ = _tk()
    root = tk.Tk()
    try:
        window = ConnectionWindow(root, config_path, url=url)
        root.mainloop()
        return window.completed
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass

def open_connection(config_path=DEFAULT_CONFIG):
    # First connection respects the server bound into the downloaded ZIP.
    _show_connection(config_path, resolve_connection(config_path))
    return 0


def reconnect_key(config_path=DEFAULT_CONFIG, *, show_dialog=None):
    # Renew the failing connection, even if the ZIP was originally downloaded
    # from a different server. No KEY or user-supplied URL is an MCP argument.
    url = Settings(config_path).url
    completed = (show_dialog or _show_connection)(config_path, url)
    return {'reconnected': bool(completed), 'baseUrl': url, 'authUrl': url+'/local-access'}


def choose_workspace(config_path=DEFAULT_CONFIG, purpose='publish', *, chooser=None):
    """The native picker, not an AI-supplied string, authorizes an extra root."""
    labels = {'publish':'등록할 원본 파일이 있는 폴더 선택', 'install':'설치할 프로젝트 폴더 선택'}
    if purpose not in labels:
        raise SquareError('폴더 선택 용도는 publish 또는 install이어야 합니다.')
    before = Settings(config_path)
    selection = None
    if chooser is None:
        from .workspace_ui import choose_location
        selection = choose_location(purpose)
        chosen = selection.get('path') if selection.get('selected') else None
    else:
        chosen = chooser()
    if not chosen:
        return {'selected': False, 'notice':'폴더 선택을 취소했습니다. 파일 접근 범위는 변경되지 않았습니다.'}
    path = no_links(chosen)
    if not path.is_dir() or path == Path(path.anchor):
        raise SquareError('존재하는 작업 폴더만 선택할 수 있습니다. 드라이브 전체는 허용하지 않습니다.')
    if selection and selection.get('scope') == 'user':
        # Account-wide install scope is not permission to upload the whole home.
        if Settings(config_path).url != before.url:
            raise SquareError('폴더를 선택하는 동안 연결 사이트가 바뀌었습니다. 다시 선택해 주세요.')
        return {**selection, 'purpose':purpose}
    with operation_lock(before.path.parent):
        current = Settings(config_path)
        if current.url != before.url:
            raise SquareError('폴더를 선택하는 동안 연결 사이트가 바뀌었습니다. 다시 선택해 주세요.')
        roots = [str(p) for p in current.roots]
        if str(path) not in roots:
            current.data['trustedRoots'] = [*roots, str(path)]
            atomic_json(current.path, current.data)
    return {'selected':True, 'path':str(path), 'purpose':purpose,
            'notice':'선택한 폴더만 추가했습니다. 도구 설치나 업로드는 아직 실행하지 않았습니다.'}
