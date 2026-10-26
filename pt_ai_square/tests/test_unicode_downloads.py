"""Korean uploaded names stay metadata; every server download uses an ASCII ID."""
import hashlib
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from werkzeug.http import parse_options_header

from pt_ai_square.backend.storage import db
from .conftest import ready
from .test_ax_workspace import upload as workspace_upload
from .test_personal_api_usage import issue
from .test_request_files import body as request_body


def archive(release=1):
    output = BytesIO()
    with ZipFile(output, 'w') as zipped:
        zipped.writestr('SKILL.md', f'# 도구\n배포 {release}')
        zipped.writestr('참고 자료/사용 안내.md', '# 사용 안내\n한글 파일을 보존합니다.')
    return output.getvalue()


def assert_download(client, url, name, content, headers=None):
    assert url.isascii() and '%' not in url and name not in url
    response = client.get(url, headers=headers or {})
    assert response.status_code == 200, response.json
    assert response.data == content
    disposition = response.headers['Content-Disposition']
    assert disposition.isascii()
    assert parse_options_header(disposition) == ('attachment', {'filename': name})
    response.close()


@pytest.mark.parametrize('kind', ['Skill', 'MCP/Tool', '플러그인/하네스'])
def test_tool_korean_zip_versions_keep_ascii_web_and_key_download_urls(app, kind):
    owner, csrf = ready(app)
    member, _ = ready(app, 'member')
    _, bearer = issue(owner, csrf)
    api = app.test_client()
    metadata = dict(name='한글 배포 검증', desc='원본 이름과 다운로드 경로를 분리합니다.',
                    owner='등록자', org='공통', category='공통 업무', platform='Claude',
                    type=kind, guide='동봉된 사용 안내를 확인하세요.', environment='Python',
                    approval=True, workTags=['파일'], changes='배포', mode='file')
    releases = []
    tool_id = None
    for number in (1, 2):
        name = f'한글 도구 100% #최종 {number}.zip'
        content = archive(number)
        endpoint = '/api/tools' if tool_id is None else f'/api/tools/{tool_id}/versions'
        if number == 2:
            metadata['expectedRevision'] = 1
        saved = owner.post(endpoint, headers=csrf,
                           data={'metadata': json.dumps(metadata),
                                 'artifact': (BytesIO(content), name)})
        assert saved.status_code == 201, saved.json
        tool_id = saved.json['id']
        manifest = api.get(f'/api/tools/{tool_id}/manifest', headers=bearer).json
        assert manifest['filename'] == name
        assert manifest['sha256'] == hashlib.sha256(content).hexdigest()
        url = manifest['downloadUrl']
        assert url == f'/download/{tool_id}/{number}'
        assert_download(owner, url, name, content)
        assert_download(api, url, name, content, bearer)
        assert app.test_client().get(url).status_code == 401
        assert member.get(url).status_code == 403
        releases.append((url, name, content))
    for url, name, content in releases:
        assert_download(owner, url, name, content)
    with app.app_context():
        versions = db().tools.find_one({'_id': tool_id})['versions']
        for version, (_, name, content) in zip(versions, releases):
            assert version['name'] == name and version['path'].isascii()
            assert (Path(app.config['DATA_DIR']) / 'artifacts' / version['path']).read_bytes() == content


@pytest.mark.parametrize('extension', ['zip', 'axextension', 'md'])
def test_workspace_korean_installers_extensions_and_guides_use_stable_ascii_ids(app, extension):
    admin, csrf = ready(app, 'admin')
    member, _ = ready(app, 'member')
    file_id = None
    for number in (1, 2):
        name = f'확장 프로그램 및 안내 {number}.{extension}'
        content = f'# 한글 안내 {number}'.encode() if extension == 'md' else archive(number)
        options = {'expectedRevision': 1} if number == 2 else {}
        saved = workspace_upload(admin, csrf, file_name=name, content=content,
                                 file_id=file_id, category='plugin', **options)
        assert saved.status_code == 201, saved.json
        public = saved.json['file']
        if file_id is not None:
            assert public['id'] == file_id
        file_id = public['id']
        assert public['fileName'] == name
        assert public['downloadUrl'] == f'/api/ax-workspace/{file_id}/download'
        assert_download(member, public['downloadUrl'], name, content)
        assert app.test_client().get(public['downloadUrl']).status_code == 401
        with app.app_context():
            stored = db().workspace_files.find_one({'_id': file_id})
            assert stored['path'].isascii() and stored['fileName'] == name
            assert (Path(app.config['DATA_DIR']) / 'artifacts' / stored['path']).read_bytes() == content


@pytest.mark.parametrize('name,content', [
    ('한글 첨부.zip', archive()),
    ('업무 안내.pdf', b'%PDF-1.7\nexample'),
    ('등록 안내.docx', archive()),
])
def test_request_korean_zip_and_document_attachments_use_ascii_ids(app, name, content):
    owner, csrf = ready(app)
    saved = owner.post('/api/ideas', headers=csrf, data=request_body([(name, content)]))
    assert saved.status_code == 201, saved.json
    idea = next(row for row in owner.get('/api/ideas').json['ideas'] if row['id'] == saved.json['id'])
    attachment = idea['attachments'][0]
    assert attachment['name'] == name
    assert attachment['url'] == f"/api/ideas/{saved.json['id']}/attachments/{attachment['id']}"
    assert_download(owner, attachment['url'], name, content)
    assert app.test_client().get(attachment['url']).status_code == 401
    with app.app_context():
        stored = db().ideas.find_one({'_id': saved.json['id']})['attachments'][0]
        assert stored['path'].isascii() and stored['name'] == name
        assert (Path(app.config['DATA_DIR']) / 'request_attachments' / stored['path']).read_bytes() == content
