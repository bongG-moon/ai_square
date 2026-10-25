"""Build a separate optional store package and per-user Windows installer.

No profile, common-app executable, registry, or network is changed by this build.
The platform's canonical Python installer sources are copied verbatim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# The web repository ships this extension and the sibling platform, not the
# common AX application. Host integration tests may point to a separate checkout.
HOST = Path(os.environ.get('AX_WORKSPACE_SOURCE') or ROOT / 'build' / 'workspace-local-repository')
CANONICAL = ROOT / 'pt_ai_square' / 'integrations' / 'pt-square-mcp' / 'pt_square_mcp'


def host_source_available(path=None):
    path = Path(path or HOST)
    return all((path / name).is_file() for name in (
        'local_app/extensions.py', 'local_app/web/extensions.js'))


def nsis_compiler(value=None):
    """Resolve an explicit compiler first; never download build dependencies."""
    configured = value or os.environ.get('NSIS_MAKENSIS')
    if configured:
        return Path(configured)
    installed = shutil.which('makensis')
    return Path(installed) if installed else HOST / 'build/nsis/portable-3.12/nsis-3.12/makensis.exe'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def source_bytes(path):
    if path.is_symlink() or getattr(path.stat(), 'st_file_attributes', 0) & 0x400:
        raise ValueError(f'Linked source is not packaged: {path}')
    return path.read_bytes()


def zip_bytes(path, files):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)


def package(output, *, source=HERE, vendor=CANONICAL):
    template = json.loads(source_bytes(source / 'extension.template.json'))
    html = source_bytes(source / 'ui' / 'index.html').decode('utf-8')
    css = source_bytes(source / 'ui' / 'store.css').decode('utf-8')
    script = source_bytes(source / 'ui' / 'store.js').decode('utf-8')
    if html.count('<!--STORE_STYLE-->') != 1 or html.count('<!--STORE_SCRIPT-->') != 1:
        raise ValueError('UI embedding placeholders must occur exactly once')
    if '</style' in css.lower() or '</script' in script.lower():
        raise ValueError('Inline UI source contains an unexpected closing element')
    html = html.replace('<!--STORE_STYLE-->', '<style>\n' + css + '\n</style>')
    html = html.replace('<!--STORE_SCRIPT-->', '<script>\n' + script + '\n</script>')
    files = {'worker.py': source_bytes(source / 'worker.py'),
             'zip_install.py': source_bytes(source / 'zip_install.py'), 'ui.html': html.encode('utf-8'),
             'package-meta.json': encoded({'format': 1, 'extension': template})}
    for path in sorted(vendor.rglob('*.py')):
        if '__pycache__' not in path.parts:
            files['vendor/pt_square_mcp/' + path.relative_to(vendor).as_posix()] = source_bytes(path)
    if 'vendor/pt_square_mcp/install.py' not in files or len(files) > 512:
        raise ValueError('Canonical platform installer sources are missing or exceed the file limit')
    hashes = {name: digest(value) for name, value in files.items()}
    fingerprint = ''.join(name + '\t' + hashes[name] + '\n' for name in sorted(hashes))
    build_id = digest(fingerprint.encode('utf-8'))
    prefix = 'packages/' + build_id + '/'
    manifest = dict(template, entrypoint=prefix + 'worker.py', ui=prefix + 'ui.html',
                    files={prefix + name: hashes[name] for name in sorted(hashes)})
    archive_files = {prefix + name: value for name, value in files.items()}
    archive_files['extension.json'] = encoded(manifest)
    output.mkdir(parents=True, exist_ok=True)
    target = output / 'store-package.zip'
    zip_bytes(target, archive_files)
    return {'id': template['id'], 'version': template['version'], 'build': build_id,
            'package': target, 'packageSha256': digest(target.read_bytes()), 'files': len(files),
            'uncompressedBytes': sum(map(len, archive_files.values()))}


def build(output, *, source=HERE, vendor=CANONICAL, make_exe=True, nsis=None):
    output = output.resolve()
    if output == Path(output.anchor):
        raise ValueError('Output must be a dedicated directory')
    result = package(output, source=source, vendor=vendor)
    compiler = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.is_file():
        raise RuntimeError('Building the standalone installer requires the Windows .NET Framework C# compiler')
    support = output / 'StoreInstaller.exe'
    with tempfile.TemporaryDirectory(prefix='store-build-', dir=output) as staging:
        compiled_source = Path(staging) / 'StoreInstaller.cs'
        compiled_source.write_text(source_bytes(HERE / 'installer/StoreInstaller.cs').decode('utf-8')
                                   .replace('__PACKAGE_SHA256__', result['packageSha256']), encoding='utf-8')
        command = [str(compiler), '/nologo', '/target:exe', '/platform:anycpu', '/optimize+', '/codepage:65001',
                   '/win32manifest:' + str(HERE / 'installer/StoreInstaller.manifest'),
                   '/reference:System.Core.dll', '/reference:System.Web.Extensions.dll',
                   '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
                   '/out:' + str(support), str(compiled_source)]
        subprocess.run(command, check=True, capture_output=True, text=True)
    wrapper = source_bytes(HERE / 'install_extension.py')
    notices = {'NSIS-COPYING.txt': source_bytes(HERE / 'installer/licenses/NSIS-COPYING.txt'),
               'NSIS-Modern-UI-2.txt': source_bytes(HERE / 'installer/licenses/NSIS-Modern-UI-2.txt'),
               'THIRD_PARTY_NOTICES.md': source_bytes(HERE / 'installer/THIRD_PARTY_NOTICES.md')}
    instructions = ('P&T AI Square 0.1.0 — AX Workspace 추가 기능\n\n'
                    '권장: AX-Organization-Store-0.1.0-setup.exe를 실행하세요. 별도 Python 설치는 필요하지 않습니다.\n'
                    '확장 연결부가 포함된 AX Workspace가 먼저 설치되어 있어야 합니다.\n'
                    '기본 앱을 완전히 종료하고 다시 열면 P&T AI Square 메뉴가 표시됩니다.\n\n'
                    'ZIP 수동 설치: 모든 파일을 같은 폴더에 풀고 install.cmd를 실행하세요.\n'
                    '웹에서 받은 connection.json은 설치 파일 옆에 그대로 두세요. 서버 주소가 자동으로 채워져 개인 KEY만 입력하면 됩니다.\n'
                    'ZIP 수동 제거: AX Workspace를 완전히 종료한 뒤 uninstall.cmd를 실행하세요.\n'
                    '연결 설정, 다운로드, 스토어에서 설치한 스킬/플러그인은 제거하지 않습니다.\n'
                    '기존 기능의 제거·변경은 해당 기능의 관리 화면에서 별도로 진행하세요.\n'
                    '사용자 지정 상태/소스 실행: python install_extension.py --help\n').encode('utf-8')
    common = '"%LOCALAPPDATA%\\Programs\\AX Workspace\\AX-Workspace.exe"'
    install_call = '"%~dp0StoreInstaller.exe" install "%LOCALAPPDATA%\\CompanyAgent" "%~dp0store-package.zip" ' + common
    install_cmd = ('@echo off\r\ncd /d "%~dp0"\r\nif exist "%~dp0connection.json" (\r\n  ' + install_call + ' "%~dp0connection.json"\r\n) else (\r\n  ' + install_call + '\r\n)\r\npause\r\n').encode('ascii')
    uninstall_cmd = b'@echo off\r\ncd /d "%~dp0"\r\n"%~dp0StoreInstaller.exe" uninstall "%LOCALAPPDATA%\\CompanyAgent"\r\npause\r\n'
    portable = output / f"AX-Organization-Store-{result['version']}-portable.zip"
    zip_bytes(portable, dict(notices, **{'StoreInstaller.exe': support.read_bytes(), 'store-package.zip': result['package'].read_bytes(),
                         'install_extension.py': wrapper, 'install.cmd': install_cmd, 'uninstall.cmd': uninstall_cmd,
                         'README.txt': instructions}))
    result['portableZip'] = portable
    if make_exe:
        nsis = nsis_compiler(nsis)
        if not nsis.is_file():
            raise RuntimeError('NSIS 3.12 is required: pass --nsis <makensis.exe> or set NSIS_MAKENSIS; --without-nsis builds the portable ZIP only')
        target = output / f"AX-Organization-Store-{result['version']}-setup.exe"
        command = [str(nsis), '/V2', '/INPUTCHARSET', 'UTF8', '/DOUTPUT_FILE=' + str(target), '/DSUPPORT_EXE=' + str(support),
                   '/DPACKAGE_ZIP=' + str(result['package']), '/DAPP_VERSION=' + result['version'],
                   '/DLICENSE_DIR=' + str(HERE / 'installer/licenses'), '/DNOTICE_FILE=' + str(HERE / 'installer/THIRD_PARTY_NOTICES.md'),
                   str(HERE / 'installer/Store.nsi')]
        subprocess.run(command, check=True, capture_output=True, text=True)
        result['installerExe'] = target
    result['supportExe'] = support
    result['pythonBundled'] = False
    result['installerRequiresPython'] = False
    result['profileModified'] = False
    result['canonicalVendor'] = str(vendor)
    result['artifacts'] = {path.name: {'sha256': digest(path.read_bytes()), 'bytes': path.stat().st_size}
                           for path in [result['package'], support, portable] + ([result['installerExe']] if make_exe else [])}
    report = {key: str(value) if isinstance(value, Path) else value for key, value in result.items()}
    (output / 'build-report.json').write_bytes(encoded(report))
    (output / 'SHA256SUMS.txt').write_text(''.join(f"{value['sha256']}  {name}\n" for name, value in report['artifacts'].items()), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/organization-store-preview')
    parser.add_argument('--without-nsis', action='store_true', help='Build the same standalone helper and portable ZIP only')
    parser.add_argument('--nsis', type=Path, help='Path to an existing NSIS 3.12 makensis.exe; alternatively set NSIS_MAKENSIS')
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.output, make_exe=not args.without_nsis, nsis=args.nsis), ensure_ascii=False, indent=2))
    except subprocess.CalledProcessError as error:
        raise SystemExit((error.stdout or '') + (error.stderr or '')) from error


if __name__ == '__main__':
    main()
