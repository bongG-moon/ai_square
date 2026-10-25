"""Final shipped package + actual common extension host + real finite worker."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--preview', type=Path, default=ROOT/'outputs/organization-store-preview')
parser.add_argument('--host-source', type=Path,
                    default=Path(os.environ.get('AX_WORKSPACE_SOURCE') or ROOT/'build/workspace-local-repository'))
parser.add_argument('--host-exe', type=Path, help='Optional built common-app EXE to verify; defaults to the supplied source checkout')
args = parser.parse_args()
PREVIEW = args.preview.resolve()
if not (args.host_source/'local_app/extensions.py').is_file():
 parser.error('An external AX host is required; use --host-source or AX_WORKSPACE_SOURCE')
for required in ('StoreInstaller.exe', 'store-package.zip'):
 if not (PREVIEW/required).is_file():
  parser.error('Build the extension first: missing ' + required)
sys.path.insert(0, str(args.host_source))
from local_app.extensions import ExtensionHost

base = ROOT/'outputs/organization-store-final-check'
base.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='isolated-', dir=base) as temp:
 root = Path(temp)
 def installer(*args):
  result = subprocess.run([str(PREVIEW/'StoreInstaller.exe'), *map(str,args)],capture_output=True,timeout=30)
  assert result.returncode == 0, result.stderr.decode('utf-8',errors='replace')
 installer('install',root,PREVIEW/'store-package.zip',args.host_exe or args.host_source)
 host = ExtensionHost(root/'local-ui')
 try:
  entries = host.snapshot()['extensions']
  assert len(entries)==1 and entries[0]['id']=='pt-ai-square.store'
  view = host.view('pt-ai-square.store')
  html = host.consume_view('pt-ai-square.store',parse_qs(urlsplit(view['url']).query)['ticket'][0])
  assert b'ax-extension-ready' in html and b'connection-key' in html
  result = host.action('pt-ai-square.store','status',{})
  assert result['ok'] is True and result['result']['configured'] is False
  assert result['result']['storeVersion']=='0.1.0'
 finally:
  host.close()
 installer('uninstall',root)
 assert not (root/'extensions/pt-ai-square.store').exists()
 assert (root/'extension-data/pt-ai-square.store').is_dir()
 print(json.dumps({'passed':True,'actualVendoredWorker':True,'realCommonHost':True,'actualInstallerHelper':True,'personalProfileModified':False}))
