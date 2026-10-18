"""Build the downloadable distribution Skill from its maintained source folder."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

base=Path(__file__).resolve().parent/'static'/'guides'
with ZipFile(base/'PT_AI_SQUARE_파일배포_Skill.zip','w',ZIP_DEFLATED) as archive:
    for path in sorted((base/'pt-file-distribution').rglob('*')):
        if path.is_file():archive.write(path,path.relative_to(base).as_posix())
print('Distribution Skill ZIP updated.')
