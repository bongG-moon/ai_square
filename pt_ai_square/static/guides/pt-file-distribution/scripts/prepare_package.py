"""Build a declared ZIP from a dedicated distribution directory. No code execution."""
import argparse
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from package_contract import read_package


def prepare(source,output):
    source=Path(source).resolve();output=Path(output).resolve()
    if not source.is_dir(): raise ValueError('준비 폴더가 없습니다.')
    if output==source or source in output.parents: raise ValueError('ZIP 출력은 준비 폴더 바깥에 지정하세요.')
    if output.exists(): raise ValueError('같은 이름의 출력 파일이 있습니다. 새 이름을 지정하세요.')
    files=sorted(source.rglob('*'))
    for p in files:
        rel=p.relative_to(source)
        if p.is_symlink() or p.resolve()!=p.absolute(): raise ValueError(f'링크는 포함할 수 없습니다: {rel}')
        if any(part in {'.git','.venv','venv','node_modules','__pycache__'} for part in rel.parts) or p.name=='.env' or p.name.startswith('.env.'):
            raise ValueError(f'공유 준비 폴더에서 제외하세요: {rel}')
    output.parent.mkdir(parents=True,exist_ok=True)
    created=False
    try:
        with ZipFile(output,'x',ZIP_DEFLATED) as z:
            created=True
            for p in files:
                if p.is_file():z.write(p,p.relative_to(source).as_posix())
        with ZipFile(output) as z:
            package=read_package(z)
            if package is None: raise ValueError('준비 폴더 최상위에 ai-square.json이 필요합니다.')
        return package
    except Exception:
        if created: output.unlink(missing_ok=True)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='P&T AI SQUARE 배포 ZIP 준비')
    parser.add_argument('source',help='ai-square.json과 공유 파일만 넣은 준비 폴더')
    parser.add_argument('output',help='준비 폴더 바깥의 새 ZIP 파일 경로')
    args=parser.parse_args()
    try:package=prepare(args.source,args.output)
    except (ValueError,OSError) as error:parser.error(str(error))
    print(f"배포 준비 완료: {args.output} ({package['packageId']})")
    print('파일 구성만 확인했습니다. 코드 실행·의존성 설치·악성코드 검사는 하지 않았습니다.')
