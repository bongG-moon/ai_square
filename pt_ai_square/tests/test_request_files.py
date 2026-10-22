import io
import json
from pathlib import Path
from .conftest import ready, publish
from pt_ai_square.backend.storage import db


def body(files):
    return {'metadata':json.dumps({'name':'첨부 요청','desc':'비교 자료입니다.','category':'공통 업무'}),
            'attachments':[(io.BytesIO(data),name) for name,data in files]}


def test_request_attachment_roundtrip_and_auth(app):
    c,h=ready(app)
    result=c.post('/api/ideas',data=body([('한글 자료.txt',b'input example')]),headers=h)
    assert result.status_code==201
    idea=c.get('/api/ideas').json['ideas'][0]
    file=idea['attachments'][0]
    assert 'path' not in file
    response=c.get(file['url'])
    assert response.status_code==200 and response.data==b'input example'
    assert 'attachment;' in response.headers['Content-Disposition']
    assert app.test_client().get(file['url']).status_code==401
    with app.app_context():
        stored=db().ideas.find_one({'_id':result.json['id']})['attachments'][0]
    assert (Path(app.config['DATA_DIR'])/'request_attachments'/stored['path']).read_bytes()==b'input example'


def test_bad_attachments_leave_no_files_or_requests(app):
    c,h=ready(app)
    for files in [[('a.txt',b'ok'),('bad.exe',b'MZ')],[('a.txt',b'')],[(f'{i}.txt',b'x') for i in range(6)], [('large.txt',b'x'*(20*1024*1024+1))]]:
        response=c.post('/api/ideas',data=body(files),headers=h)
        assert response.status_code in (400,413)
    assert not list((Path(app.config['DATA_DIR'])/'request_attachments').glob('*'))
    assert c.get('/api/ideas').json['ideas']==[]


def test_grouped_types_accept_legacy_and_new_values(app):
    c,h=ready(app)
    for old,new in [('MCP','MCP/Tool'),('Tool','MCP/Tool'),('하네스','플러그인/하네스'),('플러그인/하네스','플러그인/하네스')]:
        r=publish(c,h,type=old)
        assert r.status_code==201
        assert c.get(f"/api/tools/{r.json['id']}").json['type']==new
