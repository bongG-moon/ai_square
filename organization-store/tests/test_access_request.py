"""Permission requests use the current KEY, never approve or download a tool."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'worker.py'
spec = importlib.util.spec_from_file_location('store_access_worker', SCRIPT)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
TOKEN = 'ptsq_' + 'R' * 43
REVISION = 'a' * 32


def settings():
    return type('Settings', (), {'url': 'https://fixture.test', 'token': lambda _: TOKEN})()


@pytest.mark.parametrize('value', [True, False, 0, -1, 1000000000, '7', '../7', None])
def test_request_rejects_non_tool_ids_before_network(value):
    class Opener:
        def open(self, *args, **kwargs): pytest.fail('invalid tool must not reach the network')
    client = worker.StoreClient(settings(), Opener())
    for action in (client.request_access, client.access_status):
        with pytest.raises(worker.SquareError): action(value)


@pytest.mark.parametrize('access,requested', [('pending', True), ('pending', False), ('approved', False)])
def test_request_is_exact_same_origin_single_post(access, requested):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, request.method))
            assert request.full_url == 'https://fixture.test/api/tools/7/requests'
            assert request.method == 'POST' and timeout == 10
            assert request.get_header('Authorization') == 'Bearer ' + TOKEN
            assert json.loads(request.data) == {'reason': worker.ACCESS_REQUEST_REASON}
            return io.BytesIO(json.dumps(dict(ok=True, toolId=7, access=access, requested=requested, pending=False)).encode())
    result = worker.StoreClient(settings(), Opener()).request_access(7)
    assert result['status'] == access and result['requested'] is requested
    assert len(calls) == 1 and TOKEN not in json.dumps(result)


@pytest.mark.parametrize('failure', ['timeout', 'broken', 'oversize', 'invalid', 'wrong-tool', 'false-ok', 409, 500, 302])
def test_uncertain_mutation_never_retries_or_claims_success(failure):
    calls = []
    class Broken:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size): raise worker.HTTPException('private response ' + TOKEN)
    class Opener:
        def open(self, request, timeout):
            calls.append(request.method)
            if failure == 'timeout': raise TimeoutError(TOKEN)
            if failure == 'broken': return Broken()
            if type(failure) is int: raise HTTPError(request.full_url, failure, TOKEN, {}, io.BytesIO(TOKEN.encode()))
            raw = {'oversize': b'x' * (512 * 1024 + 1), 'invalid': b'not json',
                   'wrong-tool': b'{"ok":true,"toolId":8,"access":"pending","requested":true}',
                   'false-ok': b'{"ok":false,"toolId":7,"access":"pending","requested":true}'}[failure]
            return io.BytesIO(raw)
    result = worker.StoreClient(settings(), Opener()).request_access(7)
    assert result == {'toolId': 7, 'status': 'uncertain', 'notice': worker.ACCESS_REQUEST_UNCERTAIN}
    assert calls == ['POST'] and TOKEN not in json.dumps(result)


@pytest.mark.parametrize('code', [400, 401, 403, 404, 405, 413, 429])
def test_rejected_request_is_sanitized_and_not_retried(code):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(request.method)
            raise HTTPError(request.full_url, code, TOKEN, {}, io.BytesIO(TOKEN.encode()))
    result = worker.StoreClient(settings(), Opener()).request_access(7)
    assert result['status'] == 'rejected' and result['toolId'] == 7 and result['notice']
    assert calls == ['POST'] and TOKEN not in json.dumps(result)


@pytest.mark.parametrize('revision', [None, True, 2, '', 'a'*31, 'a'*33, 'A'*32, '../cancel', 'a'*65])
def test_cancel_rejects_invalid_attempt_revision_before_network(revision):
    class Opener:
        def open(self, *args, **kwargs): pytest.fail('invalid revision reached network')
    with pytest.raises(worker.SquareError):
        worker.StoreClient(settings(), Opener()).cancel_access_request(7, revision)


@pytest.mark.parametrize('access,cancelled,request_status,status', [
    ('none', True, 'cancelled', 'cancelled'), ('approved', False, 'approved', 'approved'),
    ('none', False, 'rejected', 'none'), ('pending', False, 'pending', 'pending'),
])
def test_cancel_is_exact_same_origin_single_post(access, cancelled, request_status, status):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, request.method))
            assert request.full_url == 'https://fixture.test/api/tools/7/requests/cancel'
            assert request.method == 'POST' and timeout == 10
            assert request.get_header('Authorization') == 'Bearer ' + TOKEN
            assert json.loads(request.data) == {'expectedRevision': REVISION}
            return io.BytesIO(json.dumps(dict(ok=True, toolId=7, access=access, cancelled=cancelled,
                                               requestRevision=REVISION, requestStatus=request_status,
                                               canCancel=access=='pending', pending=False)).encode())
    result = worker.StoreClient(settings(), Opener()).cancel_access_request(7, REVISION)
    assert result['status'] == status and result['cancelled'] is cancelled
    assert result['requestRevision'] == REVISION and result['canCancel'] is (access=='pending')
    assert len(calls) == 1 and TOKEN not in json.dumps(result)


@pytest.mark.parametrize('failure', ['timeout', 'broken-json', 'wrong-attempt', 'inconsistent-state', 500, 302])
def test_uncertain_cancel_never_retries_or_claims_success(failure):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(request.method)
            if failure == 'timeout': raise TimeoutError(TOKEN)
            if type(failure) is int: raise HTTPError(request.full_url, failure, TOKEN, {}, io.BytesIO(TOKEN.encode()))
            raw = b'not-json' if failure=='broken-json' else json.dumps(dict(
                ok=True,toolId=7,access='pending' if failure=='inconsistent-state' else 'none',cancelled=True,
                requestStatus='cancelled',requestRevision=('b'*32 if failure=='wrong-attempt' else REVISION))).encode()
            return io.BytesIO(raw)
    result = worker.StoreClient(settings(), Opener()).cancel_access_request(7, REVISION)
    assert result == {'toolId': 7, 'status': 'uncertain', 'notice': worker.ACCESS_CANCEL_UNCERTAIN}
    assert calls == ['POST'] and TOKEN not in json.dumps(result)


@pytest.mark.parametrize('code', [400, 401, 403, 404, 405, 409, 413, 429])
def test_rejected_cancel_is_sanitized_without_mutation_retry(code):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(request.method)
            raise HTTPError(request.full_url, code, TOKEN, {}, io.BytesIO(TOKEN.encode()))
    result = worker.StoreClient(settings(), Opener()).cancel_access_request(7, REVISION)
    assert result['status']=='rejected' and result['notice']
    assert calls == ['POST'] and TOKEN not in json.dumps(result)


def test_attempt_fields_require_valid_pending_revision_for_cancel():
    valid = dict(access='pending', requestStatus='pending', requestRevision=REVISION, canCancel=True)
    assert worker.StoreClient.access_fields(valid)['canCancel'] is True
    for changed in ({'requestRevision': None}, {'requestRevision': 'unsafe'}, {'access': 'approved'},
                    {'requestStatus': 'cancelled'}, {'canCancel': 1}):
        assert worker.StoreClient.access_fields(dict(valid, **changed))['canCancel'] is False


@pytest.mark.parametrize('payload', [b'[]', b'not-json', b'{"toolId":8,"access":"pending"}',
                                    b'{"toolId":7,"access":"unknown"}', b'x' * (512 * 1024 + 1)],
                         ids=['array', 'non-json', 'wrong-tool', 'invalid-status', 'oversize'])
def test_access_status_rejects_invalid_read_without_mutation(payload):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append((request.method, request.full_url))
            assert request.data is None
            return io.BytesIO(payload)
    with pytest.raises(worker.SquareError):
        worker.StoreClient(settings(), Opener()).access_status(7)
    assert calls == [('GET', 'https://fixture.test/api/tools/7/access-status')]


@pytest.fixture
def service():
    state = {'access': 'none', 'posts': 0, 'requests': [], 'failAfterCommit': False,
             'approvedManifest': False, 'requestRevision': None, 'requestStatus': 'none',
             'cancelPosts': 0, 'failCancelAfterCommit': False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def reply(self, value, status=200):
            content = json.dumps(value).encode()
            self.send_response(status); self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(content))); self.end_headers(); self.wfile.write(content)
        def auth(self):
            state['requests'].append((self.command, self.path))
            if self.headers.get('Authorization') != 'Bearer ' + TOKEN:
                self.reply({'error': 'key'}, 401); return False
            return True
        def access_fields(self):
            return dict(toolId=7,access=state['access'],requestRevision=state['requestRevision'],
                        requestStatus='approved' if state['access']=='approved' else state['requestStatus'],
                        canCancel=state['access']=='pending' and state['requestStatus']=='pending')
        def do_GET(self):
            if not self.auth(): return
            if self.path == '/api/integration/me':
                return self.reply({'user': {'id': 'user', 'name': '사용자'}, 'capabilities': {'accessRequest': True}})
            if self.path == '/api/tools/7':
                if state['access'] != 'approved': return self.reply({'error': 'private ' + TOKEN}, 403)
                return self.reply({'id': 7, 'name': '도구', 'access': 'approved', 'guide': '설치 안내'})
            if self.path == '/api/tools/7/access-status':
                return self.reply(dict(**self.access_fields(), canRequest=state['access']=='none',
                                       accessDecision='', item={'id': 7, 'name': '도구', 'approval': True}))
            if self.path == '/api/tools/7/manifest':
                if not state['approvedManifest']:
                    state['access'] = 'none'
                    return self.reply({'error': 'revoked'}, 403)
                return self.reply({'toolId': 7, 'release': 1})
            return self.reply({'error': 'unexpected'}, 404)
        def do_POST(self):
            if not self.auth(): return
            if self.path == '/api/tools/7/requests/cancel':
                raw=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert set(raw)=={'expectedRevision'}
                state['cancelPosts'] += 1
                if raw['expectedRevision'] != state['requestRevision']:
                    return self.reply({'error': 'stale ' + TOKEN},409)
                if state['access']=='pending':
                    state['access']='none';state['requestStatus']='cancelled'
                if state['failCancelAfterCommit']:
                    state['failCancelAfterCommit']=False
                    return self.reply({'error':'uncertain '+TOKEN},500)
                return self.reply(dict(ok=True,**self.access_fields(),
                                       cancelled=state['requestStatus']=='cancelled',pending=False))
            assert self.path == '/api/tools/7/requests'
            assert json.loads(self.rfile.read(int(self.headers['Content-Length']))) == {'reason': worker.ACCESS_REQUEST_REASON}
            state['posts'] += 1
            requested = state['access'] == 'none'
            if requested:
                state['access'] = 'pending';state['requestStatus']='pending'
                state['requestRevision']=f'{state["posts"]:032x}'
            if state['failAfterCommit']:
                state['failAfterCommit'] = False
                return self.reply({'error': 'private ' + TOKEN}, 500)
            self.reply(dict(ok=True, **self.access_fields(), requested=requested, pending=False))
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}', state
    finally: server.shutdown(); server.server_close(); thread.join(timeout=3)


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI connection persistence')
def test_stdio_restricted_detail_request_pending_recheck_and_revocation(service, tmp_path):
    url, state = service
    data = tmp_path / 'data'
    def call(action, payload):
        request = dict(protocol=1, action=action, payload=payload, dataDirectory=str(data), context={})
        env = {k: v for k, v in os.environ.items() if k not in {'PTAI_API_TOKEN', 'CLAUDE_CONFIG_DIR'}}
        result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(SCRIPT)],
                                input=json.dumps(request).encode(), capture_output=True, timeout=20, env=env)
        assert result.returncode == 0 and not result.stderr and TOKEN.encode() not in result.stdout
        message = json.loads(result.stdout)
        assert message['ok'], message
        return message['result']
    assert call('connect', dict(url=url, key=TOKEN, allowHttp=True))['configured']
    state['requests'].clear()
    detail = call('detail', dict(toolId=7, recordView=True))
    assert detail['item']['access'] == 'none' and detail['canRequestAccess'] is True
    assert detail['manifest'] == {} and not detail['canInstall']
    assert 'guide' not in detail['item'] and state['posts'] == 0
    assert state['requests'] == [('GET', '/api/tools/7'), ('GET', '/api/tools/7/access-status')]
    result = call('requestAccess', {'toolId': 7})
    assert result['status'] == 'pending' and result['requested'] is True
    assert result['requestRevision'] and result['canCancel'] is True
    assert state['posts'] == 1
    result = call('requestAccess', {'toolId': 7})
    assert result['status'] == 'pending' and result['requested'] is False
    detail = call('detail', dict(toolId=7, recordView=False))
    assert detail['item']['access'] == 'pending' and detail['canRequestAccess'] is False
    assert detail['canCancelAccessRequest'] is True and detail['item']['requestRevision']==result['requestRevision']
    assert state['posts'] == 2
    state['access'] = 'none'; state['failAfterCommit'] = True
    result = call('requestAccess', {'toolId': 7})
    assert result['status'] == 'uncertain' and state['posts'] == 3
    assert call('detail', dict(toolId=7, recordView=False))['item']['access'] == 'pending'
    assert state['posts'] == 3
    state['access'] = 'approved'; state['requests'].clear()
    detail = call('detail', dict(toolId=7, recordView=False))
    assert detail['item']['access'] == 'none' and detail['manifest'] == {}
    assert 'guide' not in detail['item']
    assert state['requests'] == [('GET', '/api/tools/7'), ('GET', '/api/tools/7/manifest'), ('GET', '/api/tools/7/access-status')]
    state['access'] = 'approved'; state['approvedManifest'] = True; state['requests'].clear()
    detail = call('detail', dict(toolId=7, recordView=False))
    assert detail['item']['access'] == 'approved' and detail['item']['guide'] == '설치 안내'
    assert state['requests'] == [('GET', '/api/tools/7'), ('GET', '/api/tools/7/manifest')]
    assert not any('/download/' in path or '/decision' in path for _, path in state['requests'])


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI connection persistence')
def test_stdio_cancel_uncertain_recheck_reapply_and_stale_attempt(service,tmp_path):
    url,state=service
    data=tmp_path/'data'
    def call(action,payload):
        request=dict(protocol=1,action=action,payload=payload,dataDirectory=str(data),context={})
        env={k:v for k,v in os.environ.items() if k not in {'PTAI_API_TOKEN','CLAUDE_CONFIG_DIR'}}
        result=subprocess.run([sys.executable,'-I','-B','-X','utf8',str(SCRIPT)],input=json.dumps(request).encode(),capture_output=True,timeout=20,env=env)
        assert result.returncode==0 and not result.stderr and TOKEN.encode() not in result.stdout
        message=json.loads(result.stdout)
        assert message['ok'],message
        return message['result']
    assert call('connect',dict(url=url,key=TOKEN,allowHttp=True))['configured']
    first=call('requestAccess',{'toolId':7})
    revision=first['requestRevision']
    assert first['canCancel'] is True
    state['failCancelAfterCommit']=True
    result=call('cancelAccessRequest',dict(toolId=7,expectedRevision=revision))
    assert result['status']=='uncertain' and state['cancelPosts']==1
    current=call('detail',dict(toolId=7,recordView=False))
    assert current['item']['access']=='none' and current['item']['requestStatus']=='cancelled'
    assert current['canCancelAccessRequest'] is False and state['cancelPosts']==1
    duplicate=call('cancelAccessRequest',dict(toolId=7,expectedRevision=revision))
    assert duplicate['status']=='cancelled' and duplicate['cancelled'] is True
    second=call('requestAccess',{'toolId':7})
    assert second['requestRevision']!=revision
    stale=call('cancelAccessRequest',dict(toolId=7,expectedRevision=revision))
    assert stale['status']=='rejected' and state['access']=='pending'
    current=call('detail',dict(toolId=7,recordView=False))
    assert current['item']['requestRevision']==second['requestRevision'] and current['canCancelAccessRequest'] is True
    state['access']='approved'
    already=call('cancelAccessRequest',dict(toolId=7,expectedRevision=second['requestRevision']))
    assert already['status']=='approved' and already['cancelled'] is False and state['access']=='approved'
    assert state['posts']==2 and state['cancelPosts']==4
    assert not any('/download/' in path or '/decision' in path for _,path in state['requests'])
