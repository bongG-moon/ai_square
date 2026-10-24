"""Build the reviewed local MCP source ZIP without credentials or environments."""
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
import hashlib

ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'integrations/pt-square-mcp'
target=ROOT/'static/guides/pt-square-mcp.zip'
allowed={'README.md','requirements.txt','pyproject.toml','run_mcp.py'}
paths=sorted(p for p in source.rglob('*') if p.is_file()
             and (p.relative_to(source).as_posix() in allowed or p.relative_to(source).parts[0]=='pt_square_mcp')
             and '__pycache__' not in p.parts and p.suffix not in {'.pyc','.pyo'})
assert all((source/name).is_file() for name in allowed), 'MCP source is incomplete'
assert not any(p.is_symlink() for p in paths), 'MCP sources must be regular files'
target.parent.mkdir(parents=True,exist_ok=True)
with ZipFile(target,'w',ZIP_DEFLATED) as archive:
    for p in paths:
        info=ZipInfo('pt-square-mcp/'+p.relative_to(source).as_posix(),(2026,10,24,0,0,0))
        info.compress_type=ZIP_DEFLATED;info.external_attr=0o100644<<16
        archive.writestr(info,p.read_bytes())
print(f'Local MCP ZIP: {len(paths)} files · sha256={hashlib.sha256(target.read_bytes()).hexdigest()}')
