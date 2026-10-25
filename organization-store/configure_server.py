"""Build an operator-configured EXE using the bundled standard NSIS compiler.

Payload code and the generated installer are never executed. No network, KEY,
profile, registry or personal configuration is accessed during this build.
"""
from __future__ import annotations

# ── 여기 두 항목만 수정한 뒤 `python configure_server.py`로 실행하세요. ──
# 1. 사용자가 브라우저로 접속하는 웹 서버 주소를 따옴표 안에 입력하세요.
#    예: "https://square.company.example" 또는 로컬 시험용 "http://127.0.0.1:8000"
#    서버 실행 주소인 0.0.0.0, 개인 KEY, 비밀번호, /뒤의 페이지 경로는 넣지 않습니다.
#    HTTP 주소도 가능하지만, 연결 시 KEY가 암호화되지 않으므로 앱에서 확인합니다.
SERVER_URL = ""

# 2. 완성될 확장 설치 파일 이름입니다. 아래 이름을 그대로 사용하면 됩니다.
#    이 Python 파일과 같은 폴더에 생성됩니다. 기존 파일은 덮어쓰지 않습니다.
#    생성된 Setup.exe 파일만 웹에 올리세요. 사용자는 받아서 더블클릭합니다.
#    변수명 OUTPUT_ZIP은 이전 설정 호환용입니다. 기본 출력은 이제 EXE입니다.
#    관리자 PC는 Windows와 Python이 필요하며 NSIS 빌드 도구는 ZIP에 포함됩니다.
OUTPUT_ZIP = "PNT-AI-Square-0.1.0-Setup.exe"
# ── 아래 코드는 수정하지 않아도 됩니다. ──

import argparse
import hashlib
import importlib.util
import io
import ipaddress
import json
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import urlsplit
import zipfile


def server_origin(value):
    if not isinstance(value, str) or not value or len(value) > 500:
        raise ValueError('서버 기본 주소를 입력하세요.')
    if any(character.isspace() or ord(character) < 32 for character in value) or '\\' in value:
        raise ValueError('공백과 역슬래시가 없는 서버 주소를 입력하세요.')
    parsed = urlsplit(value)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
        raise ValueError('계정·경로·쿼리가 없는 HTTP(S) 서버 기본 주소를 입력하세요.')
    port = parsed.port
    if port == 0:
        raise ValueError('서버 포트는 1~65535 범위여야 합니다.')
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and address.is_unspecified:
        raise ValueError('0.0.0.0 같은 실행 주소 대신 사용자가 접속하는 서버 주소를 입력하세요.')
    host = parsed.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    if port and port != (443 if parsed.scheme == 'https' else 80):
        host += ':' + str(port)
    return parsed.scheme + '://' + host


def guide(origin, version):
    transport = ('HTTP 연결에서는 KEY가 암호화되지 않은 통신으로 전송됩니다. 앱에 표시된 주소와 안내를 확인한 뒤 연결하세요.'
                 if origin.startswith('http:') else 'HTTPS 연결 시 회사 인증서와 네트워크 정책을 확인하세요.')
    return f'''P&T AI Square {version} — AX Workspace 선택 확장

연결할 서버: {origin}

설치 조건
- 확장 파일 가져오기를 지원하는 최신 AX Workspace가 필요합니다.
- 이전 0.23.32 설치본은 가져오기 연결이 없을 수 있습니다. 함께 제공된 최신 공통 앱 설치본을 먼저 설치하세요.
- 확장은 현재 Windows 계정의 AX Workspace에 설치됩니다. 프로젝트별 설치는 지원하지 않습니다.
- 앱의 Python 실행 환경을 사용하므로 확장용 Python을 따로 설치하지 않습니다.

설치와 연결
1. 내려받은 Setup.exe 파일을 더블클릭하세요. Windows 파일 연결 설정은 필요하지 않습니다.
2. AX Workspace가 열리며 설치 확인창을 표시합니다. 열리지 않으면 최신 공통 앱을 설치하세요.
3. 확장 이름·버전·설치 위치·서버 주소를 확인하고 설치를 누르세요.
4. 왼쪽 P&T AI Square 메뉴를 열고 웹에서 발급받은 유효한 개인 KEY를 입력하세요.
5. {transport}
6. 연결 후 기능 검색·상세 확인·좋아요·다운로드를 사용할 수 있습니다.

별도로 .axextension 파일을 받은 경우에는 최신 AX Workspace의 파일 연결로 더블클릭합니다. Windows 앱 선택 창이 뜨거나 .zip 파일을 받은 경우에는 AX Workspace → 설정 → 추가 기능 → 확장 ZIP 가져오기에서 파일을 선택할 수도 있습니다.

사용 범위
- 기존 대화·업무·작성 중인 입력과 개인 Claude 설정은 유지됩니다.
- 기존에 인증된 연결이 있으면 그 주소와 KEY를 유지합니다. 다른 서버로 바꾸려면 연결 화면에서 직접 변경하세요.
- 스토어 안에서 Skill/MCP를 설치할 때 내 계정·현재 업무·특정 폴더 범위와 실제 변경 경로를 따로 확인합니다.
- 파일 다운로드와 실제 설치는 서로 다른 동작입니다. EXE/MSI 등을 자동 실행하지 않습니다.

배포와 신뢰
- 내장 확장 패키지에는 개인 KEY·MongoDB 접속 정보·설치 도우미 EXE가 없습니다.
- 확장의 Python 코드는 설치 후 사용자 권한으로 실행됩니다. 확인한 배포자의 패키지만 설치하세요.
- 파일 해시는 무결성 확인 수단이며 게시자 전자서명이나 백신 안전 판정이 아닙니다.
- 이전 V3가 탐지한 StoreInstaller.exe는 이 배포 방식에서 사용하지 않습니다. V3 오탐 해제 또는 무탐지를 보장하지 않습니다.

업데이트와 제거
- 새 확장 파일도 더블클릭한 뒤 변경 내용을 확인하고 설치합니다. 자동 업데이트하지 않습니다.
- 제거가 필요하면 앱을 완전히 종료한 뒤 설치 확인 화면에 표시된 extensions/pt-ai-square.store 폴더만 제거하세요.
- extension-data/pt-ai-square.store는 연결 설정·다운로드 기록이므로 임의로 지우지 마세요.
'''


def declaration():
    return {
        'schemaVersion': 1, 'packageId': 'pt-ai-square.store', 'name': 'P&T AI Square 확장',
        'desc': 'AX Workspace에서 P&T AI Square의 기능을 검색하고 상세 확인·좋아요·다운로드·지원되는 설치를 진행합니다.',
        'platform': '기타', 'type': '플러그인/하네스', 'entryPoint': 'extension.json',
        'guideFile': 'README.txt', 'requiredFiles': ['connection.json'],
        'requirements': ['확장 가져오기를 지원하는 최신 AX Workspace', 'P&T AI Square 개인 연결 KEY', '지정된 서버에 접근할 수 있는 네트워크'],
        'environment': 'Windows · AX Workspace 확장 가져오기 지원 빌드',
        'changes': '표준 NSIS EXE에서 AX Workspace 설치 확인창을 엽니다. 파일 연결 없이 서버 주소를 사전 설정합니다.',
        'workTags': ['기능 검색', '업무 도구 공유'],
        'workflow': {'steps': [
            {'title': '확장 파일 더블클릭', 'description': '설치 확인창에서 이름·서버·설치 위치를 확인하고 설치합니다.'},
            {'title': '개인 KEY 연결', 'description': '미리 설정된 서버 주소를 확인하고 KEY를 입력합니다.'},
            {'title': '기능 찾아 활용', 'description': '상세·좋아요·다운로드와 지원되는 Skill/MCP 설치를 진행합니다.'},
        ]},
    }


MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_CONTENT_BYTES = 64 * 1024 * 1024
WRAPPER_FILES = {'README.txt', 'ai-square.json', 'connection.json', 'SHA256SUMS.txt'}
FORBIDDEN_SUFFIXES = {'.exe', '.dll', '.msi', '.ps1', '.bat', '.cmd', '.vbs'}


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('중복 JSON 키가 있습니다.')
        result[key] = value
    return result


def _path(name):
    if not isinstance(name, str) or not name or len(name) > 240:
        raise ValueError('ZIP 상대 경로가 올바르지 않습니다.')
    if any(character in name for character in '\\:*?"<>|') or any(ord(c) < 32 for c in name):
        raise ValueError('ZIP 경로에 허용하지 않는 문자가 있습니다.')
    parts = name.split('/')
    for part in parts:
        if not part or part in {'.', '..'} or part.rstrip(' .') != part:
            raise ValueError('ZIP 경로에 빈 경로 또는 상위 경로가 있습니다.')
        if re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])', part.split('.')[0]):
            raise ValueError('ZIP 경로에 예약된 파일 이름이 있습니다.')
    if Path(name).suffix.lower() in FORBIDDEN_SUFFIXES:
        raise ValueError('이 배포 방식에는 실행 설치 파일을 포함하지 않습니다.')
    return name


def read_template(path, expected_sha256=None):
    """Verify files in memory, without extracting or importing payload code."""
    path = Path(path)
    if not 0 < path.stat().st_size <= MAX_ARCHIVE_BYTES:
        raise ValueError('확장 ZIP은 16MB 이하여야 합니다.')
    with path.open('rb') as source:
        data = source.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError('확장 ZIP은 16MB 이하여야 합니다.')
    if expected_sha256 is not None:
        if (not re.fullmatch(r'[0-9a-fA-F]{64}', expected_sha256)
                or hashlib.sha256(data).hexdigest() != expected_sha256.lower()):
            raise ValueError('확장 template ZIP의 SHA256이 일치하지 않습니다.')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if not 1 <= len(entries) <= 517 or sum(item.file_size for item in entries) > MAX_CONTENT_BYTES:
            raise ValueError('확장 ZIP의 파일 수 또는 전체 크기 제한을 초과했습니다.')
        names = set()
        files = {}
        for item in entries:
            name = _path(item.filename)
            mode = item.external_attr >> 16
            if (name.casefold() in names or item.is_dir() or item.flag_bits & 1 or item.external_attr & 0x400
                    or item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                    or stat.S_IFMT(mode) not in {0, stat.S_IFREG}):
                raise ValueError('중복 경로·폴더·링크·암호화 파일은 허용하지 않습니다.')
            names.add(name.casefold())
            files[name] = archive.read(item)
    manifest_data = files.get('extension.json', b'')
    if not 0 < len(manifest_data) <= 256 * 1024:
        raise ValueError('확장 선언이 없거나 너무 큽니다.')
    manifest = json.loads(manifest_data.decode('utf-8'), object_pairs_hook=_unique_object)
    if (not isinstance(manifest, dict) or manifest.get('id') != 'pt-ai-square.store'
            or type(manifest.get('schemaVersion')) is not int or manifest['schemaVersion'] != 1
            or type(manifest.get('hostApi')) is not int or manifest['hostApi'] != 1
            or not isinstance(manifest.get('version'), str) or len(manifest['version']) > 50
            or not re.fullmatch(r'\d+\.\d+\.\d+', manifest['version'])
            or not isinstance(manifest.get('name'), str) or not 1 <= len(manifest['name']) <= 60
            or any(ord(character) < 32 for character in manifest['name'])):
        raise ValueError('지원하는 P&T AI Square 확장 선언이 아닙니다.')
    hashes = manifest.get('files')
    if not isinstance(hashes, dict) or not 1 <= len(hashes) <= 512:
        raise ValueError('확장 파일 해시 목록이 올바르지 않습니다.')
    prefix = None
    relative_hashes = {}
    for name, digest in hashes.items():
        _path(name)
        match = re.fullmatch(r'packages/([0-9a-f]{64})/(.+)', name)
        if not match or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('확장 payload 경로 또는 해시가 올바르지 않습니다.')
        current_prefix = 'packages/' + match[1] + '/'
        if prefix is not None and current_prefix != prefix:
            raise ValueError('확장 payload가 여러 빌드에 분산되어 있습니다.')
        prefix = current_prefix
        if name not in files or hashlib.sha256(files[name]).hexdigest() != digest:
            raise ValueError('확장 payload 파일이 누락되었거나 해시가 일치하지 않습니다.')
        relative_hashes[match[2]] = digest
    fingerprint = ''.join(name + '\t' + relative_hashes[name] + '\n' for name in sorted(relative_hashes))
    build_id = hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()
    if prefix != 'packages/' + build_id + '/':
        raise ValueError('확장 payload 빌드 해시가 일치하지 않습니다.')
    if (manifest.get('entrypoint') != prefix + 'worker.py' or manifest.get('ui') != prefix + 'ui.html'
            or manifest['entrypoint'] not in hashes or manifest['ui'] not in hashes):
        raise ValueError('확장의 실행 또는 화면 파일이 올바르지 않습니다.')
    if len(files[manifest['ui']]) > 1024 * 1024:
        raise ValueError('확장 화면 파일이 너무 큽니다.')
    files[manifest['ui']].decode('utf-8')
    actions = manifest.get('actions')
    if (not isinstance(actions, list) or not 1 <= len(actions) <= 48
            or any(not isinstance(action, str) or not re.fullmatch(r'[a-z][a-zA-Z0-9_.-]{0,63}', action) for action in actions)
            or len(set(actions)) != len(actions)):
        raise ValueError('확장의 작업 목록이 올바르지 않습니다.')
    if set(files) - set(hashes) - {'extension.json'} - WRAPPER_FILES:
        raise ValueError('확장에 선언되지 않은 파일이 있습니다.')
    for name in files:
        parts = name.split('/')
        if any('/'.join(parts[:index]).casefold() in names for index in range(1, len(parts))):
            raise ValueError('확장 파일과 폴더 경로가 겹칩니다.')
    # Drop all prior wrapper metadata, including any prior connection preset.
    return {name: files[name] for name in [*hashes, 'extension.json']}, manifest, build_id


def configured_files(files, origin, version):
    origin = server_origin(origin)
    return dict(files, **{
        'connection.json': encoded({'schemaVersion': 1, 'baseUrl': origin}),
        'README.txt': guide(origin, version).encode('utf-8'),
        'ai-square.json': encoded(declaration()),
    })


def write_zip(target, files):
    """Compress before creating the output, then exclusively create a new file."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, data)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open('xb') as output:
            output.write(buffer.getvalue())
    except FileExistsError:
        raise ValueError('출력 ZIP이 이미 있습니다. 새 파일 이름을 지정하세요.') from None


def configure(template, target, origin, *, expected_sha256=None, compiler=None):
    origin = server_origin(origin)
    target = Path(target)
    if target.suffix.lower() not in {'.exe', '.zip', '.axextension'}:
        raise ValueError('출력 파일 이름은 .exe, .axextension 또는 .zip으로 끝나야 합니다.')
    if target.exists():
        raise ValueError('출력 파일이 이미 있습니다. 새 파일 이름을 지정하세요.')
    files, manifest, build_id = read_template(template, expected_sha256)
    files = configured_files(files, origin, manifest['version'])
    installer = {'installerExecutableIncluded': False}
    if target.suffix.lower() == '.exe':
        # -I mode excludes the script directory. Load only the adjacent reviewed
        # builder, never a module from the caller's working directory or PATH.
        module_path = Path(__file__).resolve().with_name('exe_builder.py')
        spec = importlib.util.spec_from_file_location('ax_extension_exe_builder', module_path)
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory(prefix='ax-package-build-') as temporary:
            package = Path(temporary) / 'package.zip'
            write_zip(package, files)
            installer = builder.compile_installer(target, package.read_bytes(), manifest['version'],
                                                  bundle_root=module_path.parent, compiler=compiler)
    else:
        write_zip(target, files)
    return {'archive': target.name, 'version': manifest['version'], 'build': build_id,
            'baseUrl': origin, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
            'files': len(files), 'bytes': target.stat().st_size,
            'profileModified': False, 'published': False, 'serverConnectionTested': False, **installer}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-url', default=SERVER_URL, help='생략하면 파일 상단의 SERVER_URL 사용')
    parser.add_argument('--output', type=Path, help='생략하면 이 파일 옆에 OUTPUT_ZIP 이름으로 생성')
    parser.add_argument('--template', type=Path, default=Path(__file__).resolve().with_name('extension-template.zip'))
    args = parser.parse_args()
    try:
        if not args.server_url:
            raise ValueError('파일 상단의 SERVER_URL = ""에 웹 서버 주소를 입력한 뒤 다시 실행하세요. 예: https://square.company.example')
        # 명령행 옵션을 쓸 때는 기존 동작을 유지하고, 옵션이 없으면 위 설정을 씁니다.
        target = args.output if args.output is not None else Path(__file__).resolve().parent / OUTPUT_ZIP
        checksum_path = args.template.with_suffix(args.template.suffix + '.sha256')
        if checksum_path.stat().st_size > 128:
            raise ValueError('template SHA256 파일이 올바르지 않습니다.')
        checksum = checksum_path.read_text(encoding='ascii').strip()
        result = configure(args.template, target, args.server_url, expected_sha256=checksum)
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
        parser.exit(2, str(error) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print('생성된 확장 설치 파일: ' + str(target.resolve()))
    if result['baseUrl'].startswith('http:'):
        print('주의: HTTP에서는 개인 KEY가 암호화되지 않은 통신으로 전송됩니다. 사용자가 앱에서 확인해야 합니다.')
    print('지정한 서버에 접속하거나 업로드하지 않았습니다. 생성된 설치 파일을 직접 등록하세요.')


if __name__ == '__main__':
    main()
