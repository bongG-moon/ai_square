"""Build the downloadable distribution Skill from its maintained source folder."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import shutil

base=Path(__file__).resolve().parents[1]/'static'/'guides'
shutil.copy2(Path(__file__).resolve().parents[1]/'backend/package_contract.py',base/'pt-file-distribution/scripts/package_contract.py')
# The compatibility CLI sources remain in the repository for existing clients.
# The downloadable Skill only prepares local distribution files; connected
# catalog, download, install and publish operations belong to the MCP.
legacy_clients = {'scripts/square_client.py', 'scripts/publish_client.py'}
target=base/'pt-file-distribution.zip'
with ZipFile(target,'w',ZIP_DEFLATED) as archive:
    for path in sorted((base/'pt-file-distribution').rglob('*')):
        relative = path.relative_to(base/'pt-file-distribution').as_posix()
        if (path.is_file() and relative not in legacy_clients
                and '__pycache__' not in path.parts and path.suffix not in {'.pyc', '.pyo'}):
            archive.write(path,path.relative_to(base).as_posix())
shutil.copyfile(target,base/'PT_AI_SQUARE_파일배포_Skill.zip')
print('Distribution Skill ZIP updated.')
