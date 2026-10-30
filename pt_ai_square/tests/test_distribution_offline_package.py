"""The distribution Skill packages local sources without a platform account."""
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile


SKILL = Path(__file__).resolve().parents[1] / 'static/guides/pt-file-distribution'


def run_offline(source, output, home):
    # Exercise the shipped entry point with no stdin and forbid network calls,
    # even if a future helper accidentally adds account/bootstrap behavior.
    bootstrap = '''
import os, runpy, socket, sys
def forbidden(*args, **kwargs):
    raise AssertionError('Distribution preparation must stay offline')
socket.create_connection = forbidden
socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
os.environ['HOME'] = os.environ['USERPROFILE'] = sys.argv.pop(1)
for name in ('PTAI_API_TOKEN', 'PTAI_READ_TOKEN', 'PTAI_SERVER_URL'):
    os.environ.pop(name, None)
script = sys.argv[1]
sys.path.insert(0, os.path.dirname(script))
sys.argv = sys.argv[1:]
runpy.run_path(script, run_name='__main__')
'''
    return subprocess.run(
        [sys.executable, '-X', 'utf8', '-B', '-c', bootstrap, str(home),
         str(SKILL / 'scripts/prepare_package.py'), str(source), str(output)],
        input='', capture_output=True, text=True, encoding='utf-8', timeout=20)


def source_files(tmp_path):
    source = tmp_path / 'prepared'
    source.mkdir()
    declaration = json.loads((SKILL / 'assets/ai-square.example.json').read_text(encoding='utf-8'))
    data = {
        'ai-square.json': json.dumps(declaration, ensure_ascii=False).encode('utf-8'),
        'SKILL.md': b'---\nname: weekly-report\ndescription: Turn notes into a report.\n---\n# Report\n',
        'INSTALL_GUIDE.md': '선택한 프로젝트에 파일을 복사합니다.'.encode('utf-8'),
        # Packaging must inspect bytes, never execute source files.
        'scripts/report.py': b'raise AssertionError("Do not execute packaging input")\n',
    }
    for name, raw in data.items():
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return source, data


def test_declared_zip_is_ready_without_credentials_network_or_installation(tmp_path):
    source, original = source_files(tmp_path)
    home = tmp_path / 'empty-home'
    home.mkdir()
    output = tmp_path / 'release.zip'
    result = run_offline(source, output, home)
    assert result.returncode == 0, result.stderr
    assert list(home.iterdir()) == []
    assert {p.relative_to(source).as_posix(): p.read_bytes()
            for p in source.rglob('*') if p.is_file()} == original
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == set(original)
        assert {name: archive.read(name) for name in archive.namelist()} == original
    assert set(p.name for p in tmp_path.iterdir()) == {'prepared', 'empty-home', 'release.zip'}


def test_invalid_package_never_leaves_a_ready_archive_or_connection_state(tmp_path):
    source, _ = source_files(tmp_path)
    (source / 'scripts/report.py').unlink()
    home = tmp_path / 'empty-home'
    home.mkdir()
    output = tmp_path / 'release.zip'
    result = run_offline(source, output, home)
    assert result.returncode != 0
    assert not output.exists()
    assert list(home.iterdir()) == []
