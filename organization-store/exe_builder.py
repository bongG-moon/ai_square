"""Build a standard NSIS handoff EXE offline; never execute a generated setup.

The compiler is an unmodified NSIS distribution, not a private installer helper.
All payload installation and confirmation remain owned by AX Workspace.
"""
from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import zipfile

MAX_TOOLCHAIN_ARCHIVE = 16 * 1024 * 1024
MAX_TOOLCHAIN_CONTENT = 32 * 1024 * 1024
TOOLCHAIN_ROOTS = {'Bin', 'Contrib', 'Include', 'Plugins', 'Stubs'}


def toolchain_files(compiler):
    """Select redistributable build files from an existing NSIS, without fetches."""
    compiler = Path(compiler).resolve()
    root = compiler.parent.parent if compiler.parent.name.lower() == 'bin' else compiler.parent
    if not (root / 'Bin/makensis.exe').is_file() or not (root / 'COPYING').is_file():
        raise ValueError('NSIS 3.12 빌드 도구를 찾지 못했습니다.')
    files = {}
    for item in sorted(root.rglob('*')):
        relative = item.relative_to(root)
        if relative.parts[0] not in TOOLCHAIN_ROOTS and relative.as_posix() != 'COPYING':
            continue
        if item.is_symlink() or getattr(item.stat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('NSIS 도구에 연결된 경로를 포함할 수 없습니다.')
        if item.is_file():
            files[relative.as_posix()] = item.read_bytes()
    _validate_toolchain(files)
    return files


def _validate_toolchain(files):
    if not 1 <= len(files) <= 512 or sum(map(len, files.values())) > MAX_TOOLCHAIN_CONTENT:
        raise ValueError('NSIS 빌드 도구의 파일 수 또는 크기가 올바르지 않습니다.')
    for required in ('Bin/makensis.exe', 'COPYING', 'Include/MUI2.nsh',
                     'Include/LogicLib.nsh'):
        if required not in files:
            raise ValueError('NSIS 빌드 도구 또는 라이선스가 누락되었습니다: ' + required)


def _toolchain(archive_path, checksum_path):
    archive_path, checksum_path = Path(archive_path), Path(checksum_path)
    if not 0 < archive_path.stat().st_size <= MAX_TOOLCHAIN_ARCHIVE or checksum_path.stat().st_size > 128:
        raise ValueError('NSIS 빌드 도구 파일 크기가 올바르지 않습니다.')
    digest = checksum_path.read_text('ascii').strip()
    data = archive_path.read_bytes()
    if not re.fullmatch(r'[0-9a-f]{64}', digest) or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('NSIS 빌드 도구 SHA256이 일치하지 않습니다. Distribution ZIP을 다시 받으세요.')
    files = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > 512 or sum(i.file_size for i in archive.infolist()) > MAX_TOOLCHAIN_CONTENT:
            raise ValueError('NSIS 빌드 도구의 파일 수 또는 크기 제한을 초과했습니다.')
        seen = set()
        for entry in archive.infolist():
            name = entry.filename
            parts = name.split('/')
            if (not name or len(name) > 220 or any(c in name for c in '\\:*?"<>|')
                    or any(ord(c) < 32 for c in name)
                    or any(not p or p in {'.', '..'} or p.rstrip(' .') != p for p in parts)
                    or any(re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])', p.split('.')[0]) for p in parts)
                    or (parts[0] not in TOOLCHAIN_ROOTS and name != 'COPYING')
                    or name.casefold() in seen or entry.is_dir() or entry.flag_bits & 1
                    or entry.external_attr & 0x400
                    or stat.S_IFMT(entry.external_attr >> 16) not in {0, stat.S_IFREG}
                    or entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}):
                raise ValueError('NSIS 빌드 도구에 안전하지 않은 경로가 있습니다.')
            seen.add(name.casefold())
            files[name] = archive.read(entry)
    _validate_toolchain(files)
    return files


def _literal(value):
    value = str(value)
    if '"' in value or any(ord(c) < 32 for c in value):
        raise ValueError('NSIS 경로에 따옴표나 제어 문자를 사용할 수 없습니다.')
    return value.replace('$', '$$')


def compile_installer(target, package_bytes, version, *, bundle_root=None,
                      compiler=None, host_exe_override=None):
    """Build, but never launch, setup. The host override is only for test builds."""
    if os.name != 'nt':
        raise ValueError('EXE 설치 파일 생성은 Windows에서 실행해 주세요.')
    target = Path(target).resolve()
    if target.suffix.lower() != '.exe':
        raise ValueError('설치 파일 이름은 .exe로 끝나야 합니다.')
    if target.exists():
        raise ValueError('출력 파일이 이미 있습니다. 새 파일 이름을 지정하세요.')
    if not re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}', version):
        raise ValueError('EXE 버전 형식이 올바르지 않습니다.')
    root = Path(bundle_root or Path(__file__).resolve().parent)
    script = (root / 'installer/ImportExtension.nsi').read_text('utf-8')
    if compiler is None:
        files = _toolchain(root / 'nsis-toolchain.zip', root / 'nsis-toolchain.zip.sha256')
    else:
        files = toolchain_files(compiler)
    # Work and output use fixed simple names: operator URLs never become script.
    with tempfile.TemporaryDirectory(prefix='ax-setup-build-') as temporary:
        work = Path(temporary)
        nsis = work / 'nsis'
        for name, data in files.items():
            path = nsis.joinpath(*PurePosixPath(name).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (work / 'package.zip').write_bytes(package_bytes)
        definitions = ('!define OUTPUT_FILE "result.exe"\n!define PACKAGE_ZIP "package.zip"\n'
                       '!define APP_VERSION "' + version + '"\n')
        if host_exe_override is not None:
            definitions += '!define IMPORT_TEST_HOST "' + _literal(Path(host_exe_override).resolve()) + '"\n'
        source = work / 'setup.nsi'
        source.write_text(definitions + script, encoding='utf-8-sig')
        environment = dict(os.environ, NSISDIR=str(nsis))
        try:
            result = subprocess.run([str(nsis / 'Bin/makensis.exe'), '/NOCONFIG', '/V2', str(source)],
                                    cwd=work, env=environment, capture_output=True, timeout=120,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError('NSIS 빌드 도구를 실행하지 못했습니다. Windows 보안 기록과 파일 접근 권한을 확인하세요.') from error
        output = work / 'result.exe'
        if result.returncode != 0 or not output.is_file():
            detail = (result.stdout + result.stderr).decode('utf-8', errors='replace')[-4000:]
            raise ValueError('EXE 생성에 실패했습니다.\n' + detail)
        built = output.read_bytes()
        if not built.startswith(b'MZ'):
            raise ValueError('NSIS 결과가 Windows 실행 파일이 아닙니다.')
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open('xb') as handle:
                handle.write(built)
        except FileExistsError:
            raise ValueError('출력 파일이 이미 있습니다. 새 파일 이름을 지정하세요.') from None
    return {'sha256': hashlib.sha256(built).hexdigest(), 'bytes': len(built),
            'installerExecutableIncluded': True, 'nativeHelperIncluded': False,
            'fileAssociationRequired': False, 'installerExecuted': False}
