"""Create an operator-uploaded AX extension ZIP; no EXE or installer is run.

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

from build import CANONICAL, HERE, encoded, package
from configure_server import configured_files, read_template, server_origin, write_zip


def create_upload(output, origin, *, source=HERE, vendor=CANONICAL):
    origin = server_origin(origin)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # Reuse the deterministic source packager, never build()/native helper.
    with tempfile.TemporaryDirectory(prefix='upload-package-', dir=output) as directory:
        details = package(Path(directory), source=Path(source), vendor=Path(vendor))
        files, manifest, _ = read_template(details['package'])
    version = manifest['version']
    files = configured_files(files, origin, version)
    target = output / f'PNT-AI-Square-{version}.axextension'
    if target.exists():
        raise ValueError('출력 ZIP이 이미 있습니다. 새 출력 폴더를 선택하세요.')
    write_zip(target, files)
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
        '설명: 파일을 더블클릭하면 AX Workspace 설치 확인창이 열립니다. 설치 후 개인 KEY로 연결합니다. 서버 주소는 포함되어 있습니다.\n\n'
        '일반 도구 목록에 등록하려면 ZIP에서 불러오기로 ai-square.json을 읽을 수 있습니다.\n'
        '업로드나 게시를 자동 수행하지 않았습니다. 공개 Git에는 서버 주소가 포함된 ZIP을 올리지 마세요.\n', encoding='utf-8')
    return report


def create_distribution(output, *, source=HERE, vendor=CANONICAL):
    """Public operator bundle: no preset address, personal KEY or native helper."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='distribution-package-', dir=output) as directory:
        details = package(Path(directory), source=Path(source), vendor=Path(vendor))
        read_template(details['package'], details['packageSha256'])
        template = Path(details['package']).read_bytes()
    version = details['version']
    files = {
        'extension-template.zip': template,
        'extension-template.zip.sha256': (details['packageSha256'] + '\n').encode('ascii'),
        'configure_server.py': (Path(source) / 'configure_server.py').read_bytes(),
        'README.txt': (Path(source) / 'DISTRIBUTION_README.txt').read_bytes(),
    }
    target = output / f'PNT-AI-Square-{version}-Distribution.zip'
    write_zip(target, files)
    sha = hashlib.sha256(target.read_bytes()).hexdigest()
    report = {'id': details['id'], 'version': version, 'build': details['build'],
              'archive': target.name, 'bytes': target.stat().st_size, 'sha256': sha,
              'templateSha256': details['packageSha256'], 'serverPresetIncluded': False,
              'installerExecutableIncluded': False, 'profileModified': False,
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
    args = parser.parse_args()
    try:
        result = (create_distribution(args.output_directory) if args.distribution
                  else create_upload(args.output_directory, args.server_url))
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        parser.exit(2, str(error) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
