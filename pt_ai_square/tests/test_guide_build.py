"""Public guide artifacts must remain usable through ASCII-only proxy paths."""
from pathlib import Path
import shutil
import subprocess
import sys


def test_public_guide_build_keeps_ascii_and_legacy_copies_identical(tmp_path):
    source = Path(__file__).resolve().parents[1]
    app = tmp_path / 'app'
    (app / 'scripts').mkdir(parents=True)
    (app / 'docs').mkdir()
    (app / 'static' / 'fonts').mkdir(parents=True)
    (app / 'static' / 'guides').mkdir()
    shutil.copyfile(source / 'scripts' / 'build_docs.py', app / 'scripts' / 'build_docs.py')
    (app / 'static' / 'fonts' / 'PretendardVariable.woff2').write_bytes(b'test-font')
    (app / 'docs' / 'USER_GUIDE.md').write_text('# 사용자 가이드\n\n## 한글 파일\n\n우리 팀 도구.zip\n', encoding='utf-8')

    subprocess.run([sys.executable, '-X', 'utf8', '-B', str(app / 'scripts' / 'build_docs.py'),
                    '--only', 'USER_GUIDE.md'], check=True, capture_output=True, text=True)

    public = app / 'static' / 'guides' / 'pt-ai-square-user-guide.html'
    legacy = app / 'static' / 'guides' / 'PT_AI_SQUARE_등록가이드.html'
    assert public.read_bytes() == legacy.read_bytes()
    html = public.read_text(encoding='utf-8')
    assert '우리 팀 도구.zip' in html
    assert 'data:font/woff2;base64,' in html
    assert set(path.name for path in public.parent.iterdir()) == {public.name, legacy.name}
