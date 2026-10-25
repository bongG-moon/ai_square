"""Create an operator-uploaded AX extension EXE; no installer is run.

The server origin is supplied at packaging time, never embedded in this source.
This does not publish, connect, request credentials, or change a user profile.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

from build import CANONICAL, HERE, encoded, nsis_compiler, package
from configure_server import configure, read_template, server_origin, write_zip
from exe_builder import toolchain_files


def create_upload(output, origin, *, source=HERE, vendor=CANONICAL, file_extension='.exe', compiler=None):
    origin = server_origin(origin)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if file_extension not in {'.exe', '.zip', '.axextension'}:
        raise ValueError('지원하지 않는 배포 파일 형식입니다.')
    # Reuse the deterministic source packager, never build()/native helper.
    with tempfile.TemporaryDirectory(prefix='upload-package-', dir=output) as directory:
        details = package(Path(directory), source=Path(source), vendor=Path(vendor))
        files, manifest, _ = read_template(details['package'])
        version = manifest['version']
        suffix = '-Setup.exe' if file_extension == '.exe' else file_extension
        target = output / f'PNT-AI-Square-{version}{suffix}'
        prepared = configure(details['package'], target, origin,
                             compiler=compiler or nsis_compiler())
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    report = {'id': details['id'], 'version': version, 'build': details['build'],
              'baseUrl': origin, 'archive': target.name, 'bytes': target.stat().st_size,
              'sha256': sha, 'files': prepared['files'], 'installerExecutableIncluded': file_extension == '.exe',
              'nativeHelperIncluded': False, 'fileAssociationRequired': file_extension == '.axextension',
              'profileModified': False, 'published': False, 'serverConnectionTested': False,
              'antivirusCleared': False}
    (output / 'SHA256SUMS.txt').write_text(sha + '  ' + target.name + '\n', encoding='utf-8')
    (output / 'package-report.json').write_bytes(encoded(report))
    instructions = (
        '설명: Setup.exe를 실행하면 AX Workspace 설치 확인창이 열립니다. 앱에서 설치 후 개인 KEY로 연결합니다. 서버 주소는 포함되어 있습니다.\n\n'
        'EXE는 ZIP 메타데이터 자동 불러오기 대상이 아닙니다. 위 설명과 분류를 직접 입력하세요.\n'
        if file_extension == '.exe' else
        '설명: AX Workspace 설정 → 추가 기능 → 확장 ZIP 가져오기에서 파일을 선택해 설치한 뒤 개인 KEY로 연결합니다. 서버 주소는 포함되어 있습니다.\n\n'
        '일반 도구 등록에서는 ZIP의 ai-square.json을 읽어 설명과 설치 안내를 가져올 수 있습니다.\n'
    )
    (output / '등록안내.txt').write_text(
        '직접 등록할 파일: ' + target.name + '\n\n'
        '권장: 웹 AX Workspace → 파일 등록\n'
        '이름: P&T AI Square 확장\n분류: 플러그인\n버전: ' + version + '\n'
        + instructions +
        '업로드나 게시를 자동 수행하지 않았습니다. 공개 Git에는 서버 주소가 포함된 배포 파일을 올리지 마세요.\n', encoding='utf-8')
    return report


def create_distribution(output, *, source=HERE, vendor=CANONICAL, compiler=None):
    """Public bundle: neutral template and licensed standard NSIS compiler."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='distribution-package-', dir=output) as directory:
        details = package(Path(directory), source=Path(source), vendor=Path(vendor))
        read_template(details['package'], details['packageSha256'])
        template = Path(details['package']).read_bytes()
        nsis_zip = Path(directory) / 'nsis-toolchain.zip'
        write_zip(nsis_zip, toolchain_files(compiler or nsis_compiler()))
        nsis_data = nsis_zip.read_bytes()
    version = details['version']
    files = {
        'extension-template.zip': template,
        'extension-template.zip.sha256': (details['packageSha256'] + '\n').encode('ascii'),
        'configure_server.py': (Path(source) / 'configure_server.py').read_bytes(),
        'exe_builder.py': (Path(source) / 'exe_builder.py').read_bytes(),
        'installer/ImportExtension.nsi': (Path(source) / 'installer/ImportExtension.nsi').read_bytes(),
        'nsis-toolchain.zip': nsis_data,
        'nsis-toolchain.zip.sha256': (hashlib.sha256(nsis_data).hexdigest() + '\n').encode('ascii'),
        'licenses/NSIS-COPYING.txt': (Path(source) / 'installer/licenses/NSIS-COPYING.txt').read_bytes(),
        'licenses/NSIS-Modern-UI-2.txt': (Path(source) / 'installer/licenses/NSIS-Modern-UI-2.txt').read_bytes(),
        'README.txt': (Path(source) / 'DISTRIBUTION_README.txt').read_bytes(),
    }
    target = output / f'PNT-AI-Square-{version}-Distribution.zip'
    write_zip(target, files)
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    report = {'id': details['id'], 'version': version, 'build': details['build'],
              'archive': target.name, 'bytes': target.stat().st_size, 'sha256': sha,
              'templateSha256': details['packageSha256'], 'serverPresetIncluded': False,
              'installerExecutableIncluded': False, 'standardCompilerIncluded': True,
              'nativeHelperIncluded': False, 'profileModified': False,
              'published': False, 'serverConnectionTested': False, 'antivirusCleared': False}
    (output / 'SHA256SUMS.txt').write_text(sha + '  ' + target.name + '\n', encoding='utf-8')
    (output / 'distribution-report.json').write_bytes(encoded(report))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--server-url')
    mode.add_argument('--distribution', action='store_true', help='서버 주소 없는 공개 관리자용 ZIP')
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--format', choices=['exe', 'zip', 'axextension'], default='exe', help='사용자 배포 파일 형식. 기본 exe')
    parser.add_argument('--nsis', type=Path, help='개발 빌드에 사용할 기존 NSIS makensis.exe 위치')
    args = parser.parse_args()
    try:
        result = (create_distribution(args.output_directory, compiler=args.nsis) if args.distribution
                  else create_upload(args.output_directory, args.server_url, file_extension='.' + args.format, compiler=args.nsis))
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.exit(2, str(error) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
