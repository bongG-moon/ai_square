"""Run the real application/host with a synthetic extension backend in isolated state."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
APP = Path(os.environ.get('AX_WORKSPACE_SOURCE') or ROOT/'build/workspace-local-repository')
if not (APP/'local_app/server.py').is_file() or not (APP/'local_app/extensions.py').is_file():
 raise SystemExit('This browser integration fixture needs the external AX host. Set AX_WORKSPACE_SOURCE to its compatible source checkout.')
sys.path.insert(0, str(APP))
from local_app.server import LocalApp, Server

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True, type=Path)
parser.add_argument('--without-extension', action='store_true')
args = parser.parse_args()
out = args.output.resolve()
if not out.is_relative_to(ROOT/'outputs'):
 raise SystemExit('Use an isolated outputs subdirectory')
out.mkdir(parents=True, exist_ok=True)
work = out/'sample-work'; work.mkdir(exist_ok=True)
other_work = out/'other-work'; other_work.mkdir(exist_ok=True)
selected = out/'selected-folder'; selected.mkdir(exist_ok=True)
if not args.without_extension:
 package = out/'extensions/pt-ai-square.store'; package.mkdir(parents=True, exist_ok=True)
 template = ROOT/'organization-store'
 ui = (template/'ui/index.html').read_text(encoding='utf-8').replace('<!--STORE_STYLE-->', '<style>'+(template/'ui/store.css').read_text(encoding='utf-8')+'</style>').replace('<!--STORE_SCRIPT-->', '<script>'+(template/'ui/store.js').read_text(encoding='utf-8')+'</script>')
 (package/'ui.html').write_text(ui, encoding='utf-8')
 (package/'worker.py').write_bytes((template/'tests/browser_worker_fixture.py').read_bytes())
 manifest = json.loads((template/'extension.template.json').read_text(encoding='utf-8'))
 manifest['files'] = {name: hashlib.sha256((package/name).read_bytes()).hexdigest() for name in ('ui.html', 'worker.py')}
 (package/'extension.json').write_text(json.dumps(manifest), encoding='utf-8')
app = LocalApp(out/'state', demo=True, command=['never-start'], managed_workspace_root=out/'managed')
# The real route/token boundary is exercised, without opening a human's native picker.
def fixture_pick(kind, initial_directory=None):
 if (out/'cancel-picker').exists(): return {'status': 'cancel', 'paths': []}
 return {'status': 'success', 'paths': [str(selected)]}
app.pick = fixture_pick
sid = app.create(str(work), True)['id']
app.sessions[sid]['title'] = '스토어 기능 검증 · 예시 업무'
other_sid = app.create(str(other_work), True)['id']
app.sessions[other_sid]['title'] = '품질 개선 보고서'
server = Server(app, 0)
(out/'runtime.json').write_text(json.dumps({'url': server.origin+'/#token='+app.token, 'origin': server.origin, 'session': sid, 'otherSession': other_sid}), encoding='utf-8')
print('Fixture ready', flush=True)
# Explicitly bounded test-only service, never a persistent app/service.
timer = threading.Timer(1200, server.shutdown); timer.daemon = True; timer.start()
try:
 server.serve_forever(.1)
finally:
 app.close(); server.server_close()
 timer.cancel()
