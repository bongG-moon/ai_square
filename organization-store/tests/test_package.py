"""Build and exercise the production standalone verifier in isolated folders.

These tests never execute NSIS setup, write uninstall registry keys, install to
the current user's profile, or run the common app/Claude. Windows .NET is needed.
"""
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
spec = importlib.util.spec_from_file_location('organization_store_build', HERE / 'build.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
CSC = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'


@unittest.skipUnless(os.name == 'nt' and CSC.is_file(), 'Windows .NET compiler required for standalone installer validation')
class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch = ROOT / 'build/os-tests'
        scratch.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='isolated-', dir=scratch)
        cls.base = Path(cls.temp.name).resolve()
        cls.source = cls.base / 'source'
        cls.source.mkdir()
        shutil.copy2(HERE / 'extension.template.json', cls.source)
        shutil.copy2(HERE / 'worker.py', cls.source)
        shutil.copytree(HERE / 'ui', cls.source / 'ui')
        cls.first = builder.build(cls.base / 'v1', source=cls.source, make_exe=False)
        with (cls.source / 'ui/store.css').open('a', encoding='utf-8') as target:
            target.write('\n/* isolated second build */\n')
        cls.second = builder.build(cls.base / 'v2', source=cls.source, make_exe=False)
        # Installer safety tests need only the host's declared on-disk contract.
        # Keep them runnable without shipping/importing the common application.
        # Its actual runtime verification is a separate optional test below.
        cls.host = cls.base / 'host-fixture'
        web = cls.host / 'local_app/web'
        web.mkdir(parents=True)
        (web.parent / 'extensions.py').write_text('HOST_API = 1\n', encoding='utf-8')
        (web / 'extensions.js').write_text('// WorkspaceExtensions fixture\n', encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        if not cls.base.is_relative_to((ROOT / 'build/os-tests').resolve()):
            raise RuntimeError('Refusing cleanup outside isolated test workspace')
        cls.temp._finalizer.detach()
        shutil.rmtree('\\\\?\\' + str(cls.base))

    def setUp(self):
        self.case = Path(tempfile.mkdtemp(prefix='case-', dir=self.base))
        self.state = self.case / 'CompanyAgent'

    def run_helper(self, *args, build=None, ok=True):
        build = build or self.first
        result = subprocess.run([build['supportExe'], *map(str, args)], capture_output=True, timeout=15)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def install(self, build=None, ok=True):
        build = build or self.first
        return self.run_helper('install', self.state, build['package'], self.host, build=build, ok=ok)

    @property
    def extension(self):
        return self.state / 'extensions/pt-ai-square.store'

    def test_package_is_self_contained_exact_canonical_vendor_and_hashed(self):
        with zipfile.ZipFile(self.first['package']) as archive:
            manifest = json.loads(archive.read('extension.json'))
            self.assertEqual(manifest['version'], '0.1.0')
            self.assertEqual(set(archive.namelist()), set(manifest['files']) | {'extension.json'})
            for name, checksum in manifest['files'].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), checksum)
                self.assertNotIn('__pycache__', name)
                self.assertTrue(name.startswith('packages/' + self.first['build'] + '/'))
            html = archive.read(manifest['ui']).decode('utf-8')
            self.assertNotIn('<!--STORE_STYLE-->', html)
            self.assertNotIn('<!--STORE_SCRIPT-->', html)
            for path in builder.CANONICAL.rglob('*.py'):
                if '__pycache__' not in path.parts:
                    name = 'packages/' + self.first['build'] + '/vendor/pt_square_mcp/' + path.relative_to(builder.CANONICAL).as_posix()
                    self.assertEqual(archive.read(name), path.read_bytes())

    def test_install_is_idempotent(self):
        self.install()
        before = (self.extension / 'extension.json').read_bytes()
        self.install()
        self.assertEqual((self.extension / 'extension.json').read_bytes(), before)

    @unittest.skipUnless(builder.host_source_available(),
                         'Actual AX host test: set AX_WORKSPACE_SOURCE to a compatible common-app source checkout')
    def test_real_host_can_verify_installed_package(self):
        self.run_helper('install', self.state, self.first['package'], builder.HOST)
        sys.path.insert(0, str(builder.HOST))
        try:
            from local_app.extensions import ExtensionHost
            host = ExtensionHost(self.state / 'local-ui')
            self.assertEqual(host.snapshot()['extensions'][0]['id'], 'pt-ai-square.store')
            view = host.view('pt-ai-square.store')
            self.assertTrue(view['url'].startswith('/extension-ui/pt-ai-square.store?ticket='))
        finally:
            sys.path.remove(str(builder.HOST))

    def test_downloaded_origin_is_installed_without_importing_credentials(self):
        supplied = self.case / 'connection.json'
        supplied.write_text(json.dumps({'schemaVersion': 1, 'baseUrl': 'HTTP://PntAiSquare.Example:80/'}), encoding='utf-8')
        before = supplied.read_bytes()
        self.run_helper('install', self.state, self.first['package'], self.host, supplied)
        data = self.state / 'extension-data/pt-ai-square.store'
        preset = data / 'connection.json'
        self.assertEqual(json.loads(preset.read_text('utf-8')), {'schemaVersion': 1, 'baseUrl': 'http://pntaisquare.example'})
        self.assertEqual(supplied.read_bytes(), before)
        self.assertFalse((data / 'connection/config.json').exists())
        self.run_helper('uninstall', self.state)
        self.assertTrue(preset.is_file())

    def test_generic_install_does_not_create_or_change_connection_preset(self):
        self.install()
        data = self.state / 'extension-data/pt-ai-square.store'
        self.assertFalse(data.exists())
        data.mkdir(parents=True)
        preset = data / 'connection.json'
        preset.write_text('user data', encoding='utf-8')
        self.install(self.second)
        self.assertEqual(preset.read_text('utf-8'), 'user data')

    def test_new_preset_does_not_rebind_existing_saved_key_or_settings(self):
        data = self.state / 'extension-data/pt-ai-square.store'
        (data / 'connection').mkdir(parents=True)
        config = data / 'connection/config.json'
        selection = data / 'connection-selection.json'
        config.write_text('existing encrypted key config', encoding='utf-8')
        selection.write_text('existing selection', encoding='utf-8')
        supplied = self.case / 'connection.json'
        for origin in ('https://first.example', 'https://second.example:8443'):
            supplied.write_text(json.dumps({'schemaVersion': 1, 'baseUrl': origin}), encoding='utf-8')
            self.run_helper('install', self.state, self.first['package'], self.host, supplied)
            self.assertEqual(json.loads((data / 'connection.json').read_text('utf-8'))['baseUrl'], origin)
            self.assertEqual(config.read_text('utf-8'), 'existing encrypted key config')
            self.assertEqual(selection.read_text('utf-8'), 'existing selection')

    def test_invalid_preset_aborts_before_any_install_files_and_does_not_echo_secret(self):
        invalid = [
            {'schemaVersion': 1, 'baseUrl': 'https://user:private-secret@example.com'},
            {'schemaVersion': 1, 'baseUrl': 'https://example.com/path'},
            {'schemaVersion': 1, 'baseUrl': 'https://example.com?token=private-secret'},
            {'schemaVersion': 1, 'baseUrl': 'https://example.com#private-secret'},
            {'schemaVersion': 1, 'baseUrl': 'https://example.com', 'token': 'private-secret'},
            {'schemaVersion': True, 'baseUrl': 'https://example.com'},
            {'schemaVersion': 2, 'baseUrl': 'https://example.com'},
            {'schemaVersion': 1, 'baseUrl': 'file:///C:/private-secret'},
            {'schemaVersion': 1, 'baseUrl': 'https://example.com\\private-secret'},
            {'schemaVersion': 1, 'baseUrl': 'https://example.com\nprivate-secret'},
            {'schemaVersion': 1, 'baseUrl': 'https://example.com:bad'},
            {'schemaVersion': 1, 'baseUrl': 'https://example.com:65536'},
        ]
        supplied = self.case / 'connection.json'
        payloads = [json.dumps(value).encode('utf-8') for value in invalid] + [
            b'{"schemaVersion":1,"baseUrl":"https://example.com","baseUrl":"https://private-secret.example"}',
            b'{"schemaVersion":1,"baseUrl":"https://example.com"}' + b' ' * 4096,
            b'\xffprivate-secret', b'private-secret', b'[]',
        ]
        for payload in payloads:
            with self.subTest(payload=payload[:100]):
                supplied.write_bytes(payload)
                result = self.run_helper('install', self.state, self.first['package'], self.host, supplied, ok=False)
                self.assertNotIn(b'private-secret', result.stderr + result.stdout)
                self.assertFalse(self.state.exists())

    def test_preset_source_and_destination_junctions_are_rejected_before_install(self):
        outside = self.case / 'outside'
        outside.mkdir()
        (outside / 'connection.json').write_text(json.dumps({'schemaVersion': 1, 'baseUrl': 'https://example.com'}), encoding='utf-8')
        link = self.case / 'linked'
        result = subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True)
        if result.returncode:
            self.skipTest('Junction creation unavailable in this Windows environment')
        try:
            self.run_helper('install', self.state, self.first['package'], self.host, link / 'connection.json', ok=False)
            self.assertFalse(self.state.exists())
        finally:
            os.rmdir(link)
        self.state.mkdir()
        destination = self.state / 'extension-data'
        result = subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(destination), str(outside)], capture_output=True)
        self.assertEqual(result.returncode, 0)
        try:
            self.run_helper('install', self.state, self.first['package'], self.host, outside / 'connection.json', ok=False)
            self.assertFalse(self.extension.exists())
            self.assertEqual([path.name for path in outside.iterdir()], ['connection.json'])
        finally:
            os.rmdir(destination)

    def test_python_portable_wrapper_uses_sibling_connection_file(self):
        wrapper = self.case / 'install_extension.py'
        shutil.copy2(HERE / 'install_extension.py', wrapper)
        (self.case / 'connection.json').write_text(json.dumps({'schemaVersion': 1, 'baseUrl': 'http://pntaisquare.example'}), encoding='utf-8')
        result = subprocess.run([sys.executable, str(wrapper), 'install', '--root', str(self.state),
                                 '--host', str(self.host), '--package', self.first['package'], '--helper', self.first['supportExe']],
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        preset = self.state / 'extension-data/pt-ai-square.store/connection.json'
        self.assertEqual(json.loads(preset.read_text('utf-8'))['baseUrl'], 'http://pntaisquare.example')

    def test_update_keeps_previous_immutable_package_and_uninstall_preserves_user_data(self):
        self.install()
        old = self.extension / 'packages' / self.first['build'] / 'worker.py'
        content = old.read_bytes()
        saved = self.state / 'extension-data/pt-ai-square.store/connection.json'
        saved.parent.mkdir(parents=True)
        saved.write_text('private data', encoding='utf-8')
        outside = self.case / '.claude/skills/example/SKILL.md'
        outside.parent.mkdir(parents=True)
        outside.write_text('user skill', encoding='utf-8')
        self.install(self.second)
        manifest = json.loads((self.extension / 'extension.json').read_text('utf-8'))
        self.assertIn(self.second['build'], manifest['entrypoint'])
        self.assertEqual(old.read_bytes(), content)
        self.run_helper('uninstall', self.state, build=self.second)
        self.assertFalse(self.extension.exists())
        self.assertEqual(saved.read_text('utf-8'), 'private data')
        self.assertEqual(outside.read_text('utf-8'), 'user skill')

    def test_tampered_archive_does_not_create_install_target(self):
        path = self.case / 'tampered.zip'
        path.write_bytes(Path(self.first['package']).read_bytes() + b'tamper')
        self.run_helper('install', self.state, path, self.host, ok=False)
        self.assertFalse(self.state.exists())

    def test_existing_unowned_directory_is_never_adopted(self):
        self.extension.mkdir(parents=True)
        sentinel = self.extension / 'important.txt'
        sentinel.write_text('keep', encoding='utf-8')
        self.install(ok=False)
        self.assertEqual(sentinel.read_text('utf-8'), 'keep')
        self.assertEqual(list(self.extension.iterdir()), [sentinel])

    def test_tampered_or_extra_installed_files_abort_uninstall_before_any_deletion(self):
        self.install()
        manifest = (self.extension / 'extension.json').read_bytes()
        worker = self.extension / 'packages' / self.first['build'] / 'worker.py'
        original = worker.read_bytes()
        worker.write_bytes(original + b'\n# changed\n')
        self.run_helper('uninstall', self.state, ok=False)
        self.assertEqual((self.extension / 'extension.json').read_bytes(), manifest)
        self.install(self.second, ok=False)
        worker.write_bytes(original)
        extra = self.extension / 'do-not-delete.txt'
        extra.write_text('keep', encoding='utf-8')
        self.run_helper('uninstall', self.state, ok=False)
        self.assertEqual(extra.read_text('utf-8'), 'keep')
        self.assertTrue(worker.exists())

    def test_failed_atomic_activation_keeps_previous_version_and_can_resume(self):
        self.install()
        manifest = self.extension / 'extension.json'
        before = manifest.read_bytes()
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                      ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        # Allow reads for initial verification, but deny delete/replace during activation.
        handle = kernel.CreateFileW(str(manifest), 0x80000000, 1, None, 3, 0, None)
        self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
        try:
            self.install(self.second, ok=False)
            self.assertEqual(manifest.read_bytes(), before)
        finally:
            kernel.CloseHandle(handle)
        self.install(self.second)
        self.assertIn(self.second['build'], json.loads(manifest.read_text('utf-8'))['entrypoint'])

    def test_process_killed_after_package_move_recovers_only_exact_trusted_build(self):
        self.install()
        before = (self.extension / 'extension.json').read_bytes()
        # Kill the real verifier exactly at the durable rename boundary. This
        # bypasses every catch/finally block, unlike an injected exception.
        source = self.case / 'KillVerifier.cs'
        code = (HERE / 'installer/StoreInstaller.cs').read_text('utf-8').replace(
            '__PACKAGE_SHA256__', self.second['packageSha256'])
        needle = 'NoLinks(destination);Directory.Move(stage,destination);'
        self.assertEqual(code.count(needle), 1)
        code = code.replace(needle, needle + 'System.Diagnostics.Process.GetCurrentProcess().Kill();System.Threading.Thread.Sleep(10000);')
        source.write_text(code, encoding='utf-8')
        helper = self.case / 'KillVerifier.exe'
        subprocess.run([str(CSC), '/nologo', '/target:exe', '/out:' + str(helper),
                        '/reference:System.Core.dll', '/reference:System.Web.Extensions.dll',
                        '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
                        str(source)], check=True, capture_output=True)
        self.run_helper('install', self.state, self.second['package'], self.host,
                        build={'supportExe': str(helper)}, ok=False)
        self.assertEqual((self.extension / 'extension.json').read_bytes(), before)
        marker = json.loads((self.extension / '.ax-extension-owner.json').read_text('utf-8'))
        self.assertNotIn(self.second['build'], marker['packages'])
        self.assertTrue((self.extension / 'packages' / self.second['build']).is_dir())
        self.install(self.second)
        marker = json.loads((self.extension / '.ax-extension-owner.json').read_text('utf-8'))
        self.assertIn(self.second['build'], marker['packages'])
        self.assertIn(self.second['build'], json.loads((self.extension / 'extension.json').read_text('utf-8'))['entrypoint'])

    def test_orphan_recovery_never_adopts_modified_or_unrelated_files(self):
        self.install()
        manifest = (self.extension / 'extension.json').read_bytes()
        with zipfile.ZipFile(self.second['package']) as archive:
            for name in archive.namelist():
                if name != 'extension.json':
                    target = self.extension / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(name))
        changed = self.extension / 'packages' / self.second['build'] / 'worker.py'
        changed.write_bytes(changed.read_bytes() + b'\n# changed\n')
        self.install(self.second, ok=False)
        self.assertEqual((self.extension / 'extension.json').read_bytes(), manifest)
        self.assertTrue(changed.exists())
        marker = json.loads((self.extension / '.ax-extension-owner.json').read_text('utf-8'))
        self.assertNotIn(self.second['build'], marker['packages'])

    def test_junction_parent_is_rejected_without_touching_target(self):
        outside = self.case / 'outside'
        outside.mkdir()
        self.state.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(self.state), str(outside)], capture_output=True)
        if result.returncode:
            self.skipTest('Junction creation unavailable in this Windows environment')
        try:
            self.install(ok=False)
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            os.rmdir(self.state)

    def test_running_common_app_blocks_removal(self):
        self.install()
        runtime = self.state / 'local-ui/runtime.json'
        runtime.parent.mkdir()
        runtime.write_text(json.dumps({'pid': os.getpid()}), encoding='utf-8')
        self.run_helper('uninstall', self.state, ok=False)
        self.assertTrue((self.extension / 'extension.json').exists())

    def test_long_custom_state_path_installs_and_removes_without_machine_policy_change(self):
        self.state = self.case / ('long-user-path-' * 6) / 'CompanyAgent'
        self.install()
        extended = Path('\\\\?\\' + str(self.extension))
        self.assertTrue((extended / 'extension.json').is_file())
        self.run_helper('uninstall', self.state)
        self.assertFalse(extended.exists())

    def test_embedded_host_check_reads_metadata_without_executing_host(self):
        source = self.case / 'fake.cs'
        sentinel = self.case / 'must-not-exist.txt'
        source.write_text('class Host { static void Main(){System.IO.File.WriteAllText(@"' + str(sentinel) + '","bad");} }', encoding='utf-8')
        manifest = self.case / 'manifest.tsv'
        manifest.write_text('0\tCompany-Workspace/local_app/extensions.py\n0\tCompany-Workspace/local_app/web/extensions.js\n', encoding='utf-8')
        host = self.case / 'AX-Workspace.exe'
        subprocess.run([str(CSC), '/nologo', '/target:exe', '/out:' + str(host),
                        '/resource:' + str(manifest) + ',WorkspacePayload.manifest.tsv', str(source)], check=True, capture_output=True)
        self.run_helper('check-host', host)
        self.assertFalse(sentinel.exists())

    def test_old_host_and_control_folders_are_rejected(self):
        old = self.case / 'old/local_app/web'
        old.mkdir(parents=True)
        (old.parent / 'extensions.py').write_text('HOST_API = 0', encoding='utf-8')
        (old / 'extensions.js').write_text('WorkspaceExtensions', encoding='utf-8')
        self.run_helper('check-host', old.parent.parent, ok=False)
        control = self.case / 'control'
        control.mkdir()
        (control / 'store.install-id').write_text('another product', encoding='utf-8')
        self.run_helper('check-control', control, ok=False)
        self.assertTrue((control / 'store.install-id').exists())

    def test_path_traversal_is_rejected_even_with_matching_outer_archive_hash(self):
        # Recompile the verifier for this controlled corrupt fixture to exercise
        # inner path validation beyond the production outer checksum gate.
        path = self.case / 'malicious.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('../escape.txt', b'bad')
            archive.writestr('extension.json', b'{}')
            archive.writestr('worker.py', b'pass')
        source = self.case / 'Verifier.cs'
        source.write_text((HERE / 'installer/StoreInstaller.cs').read_text('utf-8').replace(
            '__PACKAGE_SHA256__', hashlib.sha256(path.read_bytes()).hexdigest()), encoding='utf-8')
        helper = self.case / 'Verifier.exe'
        subprocess.run([str(CSC), '/nologo', '/target:exe', '/out:' + str(helper),
                        '/reference:System.Core.dll', '/reference:System.Web.Extensions.dll',
                        '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
                        str(source)], check=True, capture_output=True)
        self.run_helper('install', self.state, path, self.host, build={'supportExe': str(helper)}, ok=False)
        self.assertFalse(self.state.exists())
        self.assertFalse((self.case / 'escape.txt').exists())


if __name__ == '__main__':
    unittest.main()
