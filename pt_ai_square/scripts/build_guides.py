"""Build the downloadable distribution Skill from its maintained source folder."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import shutil

base=Path(__file__).resolve().parents[1]/'static'/'guides'
shutil.copy2(Path(__file__).resolve().parents[1]/'backend/package_contract.py',base/'pt-file-distribution/scripts/package_contract.py')
shutil.copy2(Path(__file__).resolve().parents[1]/'receiver/pt-square-receiver/scripts/square_client.py',base/'pt-file-distribution/scripts/square_client.py')
with ZipFile(base/'PT_AI_SQUARE_파일배포_Skill.zip','w',ZIP_DEFLATED) as archive:
    for path in sorted((base/'pt-file-distribution').rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':archive.write(path,path.relative_to(base).as_posix())
print('Distribution Skill ZIP updated.')
