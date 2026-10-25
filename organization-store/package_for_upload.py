"""Create an operator-uploaded AX extension ZIP; no EXE or installer is run.

The server origin is supplied at packaging time, never embedded in this source.
This does not publish, connect, request credentials, or change a user profile.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
import zipfile

from build import CANONICAL, HERE, encoded, package, zip_bytes


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
- 설정에 “확장 ZIP 가져오기”가 있는 AX Workspace가 필요합니다.
- 이전 0.23.32 설치본은 이 기능이 없을 수 있습니다. 함께 제공된 ZIP 가져오기 지원 설치본을 사용하세요.
- 확장은 현재 Windows 계정의 AX Workspace에 설치됩니다. 프로젝트별 설치는 지원하지 않습니다.
- 앱의 Python 실행 환경을 사용하므로 확장용 Python을 따로 설치하지 않습니다.

설치와 연결
1. 이 ZIP은 압축을 풀거나 더블클릭으로 실행하지 않습니다.
2. AX Workspace → 설정 → 추가 기능 → 확장 ZIP 가져오기에서 이 ZIP을 선택하세요.
3. 확장 이름·버전·설치 위치·서버 주소를 확인하고 설치를 누르세요.
4. 왼쪽 P&T AI Square 메뉴를 열고 웹에서 발급받은 유효한 개인 KEY를 입력하세요.
5. {transport}
6. 연결 후 기능 검색·상세 확인·좋아요·다운로드를 사용할 수 있습니다.

사용 범위
- 기존 대화·업무·작성 중인 입력과 개인 Claude 설정은 유지됩니다.
- 기존에 인증된 연결이 있으면 그 주소와 KEY를 유지합니다. 다른 서버로 바꾸려면 연결 화면에서 직접 변경하세요.
- 스토어 안에서 Skill/MCP를 설치할 때 내 계정·현재 업무·특정 폴더 범위와 실제 변경 경로를 따로 확인합니다.
- 파일 다운로드와 실제 설치는 서로 다른 동작입니다. EXE/MSI 등을 자동 실행하지 않습니다.

배포와 신뢰
- 이 ZIP에는 개인 KEY·MongoDB 접속 정보·설치 도우미 EXE가 없습니다.
- 확장의 Python 코드는 설치 후 사용자 권한으로 실행됩니다. 확인한 배포자의 패키지만 설치하세요.
- 파일 해시는 무결성 확인 수단이며 게시자 전자서명이나 백신 안전 판정이 아닙니다.
- 이전 V3가 탐지한 StoreInstaller.exe는 이 배포 방식에서 사용하지 않습니다. V3 오탐 해제 또는 무탐지를 보장하지 않습니다.

업데이트와 제거
- 새 ZIP도 같은 가져오기 메뉴에서 변경 내용을 확인한 뒤 설치합니다. 자동 업데이트하지 않습니다.
- 제거가 필요하면 앱을 완전히 종료한 뒤 설치 확인 화면에 표시된 extensions/pt-ai-square.store 폴더만 제거하세요.
- extension-data/pt-ai-square.store는 연결 설정·다운로드 기록이므로 임의로 지우지 마세요.
'''


def create_upload(output, origin, *, source=HERE, vendor=CANONICAL):
    origin = server_origin(origin)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # Reuse the deterministic source packager, never build()/native helper.
    with tempfile.TemporaryDirectory(prefix='upload-package-', dir=output) as directory:
        details = package(Path(directory), source=Path(source), vendor=Path(vendor))
        with zipfile.ZipFile(details['package']) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
    version = details['version']
    instructions = guide(origin, version)
    files['connection.json'] = encoded({'schemaVersion': 1, 'baseUrl': origin})
    files['README.txt'] = instructions.encode('utf-8')
    declaration = {
        'schemaVersion': 1, 'packageId': 'pt-ai-square.store', 'name': 'P&T AI Square 확장',
        'desc': 'AX Workspace에서 P&T AI Square의 기능을 검색하고 상세 확인·좋아요·다운로드·지원되는 설치를 진행합니다.',
        'platform': '기타', 'type': '플러그인/하네스', 'entryPoint': 'extension.json',
        'guideFile': 'README.txt', 'requiredFiles': ['connection.json'],
        'requirements': ['확장 ZIP 가져오기를 지원하는 AX Workspace', 'P&T AI Square 개인 연결 KEY', '지정된 서버에 접근할 수 있는 네트워크'],
        'environment': 'Windows · AX Workspace 확장 ZIP 가져오기 지원 빌드',
        'changes': '독립 ZIP 배포와 서버 주소 사전 설정. 별도 설치 도우미 EXE 없이 앱에서 검증 후 가져옵니다.',
        'workTags': ['기능 검색', '업무 도구 공유'],
        'workflow': {'steps': [
            {'title': '확장 ZIP 가져오기', 'description': '앱 설정에서 배포 ZIP과 설치 위치를 확인합니다.'},
            {'title': '개인 KEY 연결', 'description': '미리 설정된 서버 주소를 확인하고 KEY를 입력합니다.'},
            {'title': '기능 찾아 활용', 'description': '상세·좋아요·다운로드와 지원되는 Skill/MCP 설치를 진행합니다.'},
        ]},
    }
    files['ai-square.json'] = encoded(declaration)
    forbidden = {'.exe', '.dll', '.msi', '.ps1', '.bat', '.cmd', '.vbs'}
    if any(Path(name).suffix.lower() in forbidden for name in files):
        raise ValueError('이 배포 방식에는 실행 설치 파일을 포함하지 않습니다.')
    target = output / f'PNT-AI-Square-{version}-Extension.zip'
    if target.exists():
        raise ValueError('출력 ZIP이 이미 있습니다. 새 출력 폴더를 선택하세요.')
    zip_bytes(target, files)
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    report = {'id': details['id'], 'version': version, 'build': details['build'],
              'baseUrl': origin, 'archive': target.name, 'bytes': target.stat().st_size,
              'sha256': sha, 'files': len(files), 'installerExecutableIncluded': False,
              'profileModified': False, 'published': False, 'serverConnectionTested': False,
              'antivirusCleared': False}
    (output / 'SHA256SUMS.txt').write_text(sha + '  ' + target.name + '\n', encoding='utf-8')
    (output / 'package-report.json').write_bytes(encoded(report))
    (output / '등록안내.txt').write_text(
        '직접 등록할 파일: ' + target.name + '\n\n'
        '권장: 웹 AX Workspace → 파일 등록\n'
        '이름: P&T AI Square 확장\n분류: 플러그인\n버전: ' + version + '\n'
        '설명: AX Workspace 설정에서 이 ZIP을 가져와 설치하고 개인 KEY로 연결합니다. 서버 주소는 포함되어 있습니다.\n\n'
        '일반 도구 목록에 등록하려면 ZIP에서 불러오기로 ai-square.json을 읽을 수 있습니다.\n'
        '업로드나 게시를 자동 수행하지 않았습니다. 공개 Git에는 서버 주소가 포함된 ZIP을 올리지 마세요.\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-url', required=True)
    parser.add_argument('--output-directory', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = create_upload(args.output_directory, args.server_url)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.exit(2, str(error) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
