"""Optional workflow stays plain data, authorized and tied to a release."""
import io
import json
import zipfile

import pytest

from pt_ai_square.backend.package_contract import normalize_workflow, read_package
from pt_ai_square.backend.storage import db
from .conftest import ready, publish
from .test_package_declaration import bundle, declaration, post


def flow(title='자료 입력'):
    return {'steps': [{'title': title, 'description': '사용자가 자료를 선택합니다.'},
                      {'title': '결과 확인', 'description': '정리된 결과를 검토합니다.'}]}


@pytest.mark.parametrize('value', [
    [], {}, {'steps': []}, {'steps': [{}]}, {'steps': [{'title': ' '}]},
    {'steps': [{'title': 'x'*61}]}, {'steps': [{'title': 'a', 'description': 'x'*241}]},
    {'steps': [{'title': 'a', 'script': 'alert(1)'}]},
    {'steps': [{'title': 'a'}]*9}, {'steps': [{'title': 'bad\x00'}]},
    {'steps': [{'title': 'a'}], 'html': '<script>alert(1)</script>'},
])
def test_rejects_unsupported_workflow_shapes(value):
    with pytest.raises(ValueError): normalize_workflow(value)


def test_old_packages_optional_and_text_not_interpreted():
    with zipfile.ZipFile(io.BytesIO(bundle())) as z:
        assert read_package(z)['workflow'] is None
    assert normalize_workflow(None) is None
    assert normalize_workflow({'steps': [{'title': ' Input ', 'description': ' result '}]}) == {
        'steps': [{'title': 'Input', 'description': 'result'}]}
    # Renderers must escape this text; it is not executable HTML or Mermaid.
    text='<img src=x onerror=alert(1)>'
    assert normalize_workflow({'steps': [{'title': text}]})['steps'][0]['title']==text


def test_workflow_inspection_release_authorization_and_rollback(app):
    owner,h=ready(app); first=flow(); second=flow('새 자료 입력')
    one=bundle(declaration(workflow=first))
    inspected=post(owner,h,one,'/api/packages/inspect')
    assert inspected.status_code==200
    assert inspected.json['metadata']['workflow']==first
    created=post(owner,h,one,approval=True)
    assert created.status_code==201,created.json
    tid=created.json['id']
    member,_=ready(app,'member')
    card=next(x for x in member.get('/api/bootstrap').json['items'] if x['id']==tid)
    assert 'workflow' not in card and card['versions']==[]
    assert member.get(f'/api/tools/{tid}').status_code==403
    assert member.get(f'/api/tools/{tid}/manifest').status_code==403
    assert owner.get(f'/api/tools/{tid}').json['workflow']==first
    assert owner.get(created.json['deploymentUrl']).json['workflow']==first
    # An inherited stale draft cannot replace the new ZIP's declared flow.
    update=post(owner,h,bundle(declaration(workflow=second)),f'/api/tools/{tid}/versions',
                expectedRevision=1,approval=True,workflow=first)
    assert update.status_code==201,update.json
    current=owner.get(f'/api/tools/{tid}').json
    assert current['workflow']==second and current['versions'][0]['workflow']==second
    assert current['versions'][1]['workflow']==first
    assert owner.get(f'/api/tools/{tid}/manifest').json['workflow']==second
    with app.app_context():
        row=db().tools.find_one({'_id':tid})
        assert row['versions'][0]['data']['workflow']==first
        assert row['versions'][1]['data']['workflow']==second
    assert owner.post(f'/api/tools/{tid}/rollback',headers=h,
                      json={'version':1,'expectedRevision':2}).status_code==200
    assert owner.get(f'/api/tools/{tid}').json['workflow']==first
    assert owner.get(f'/api/tools/{tid}/manifest').json['workflow']==first


def test_new_package_without_workflow_clears_previous_and_legacy_rollback(app):
    owner,h=ready(app)
    tid=post(owner,h,bundle(declaration(workflow=flow()))).json['id']
    assert post(owner,h,bundle(),f'/api/tools/{tid}/versions',expectedRevision=1,
                workflow=flow('이전 화면의 초안')).status_code==201
    assert owner.get(f'/api/tools/{tid}').json['workflow'] is None
    # Pre-workflow versions have no field; restoring them must not retain v3's flow.
    with app.app_context():
        db().tools.update_one({'_id':tid},{'$unset':{'versions.1.data.workflow':''}})
    assert post(owner,h,bundle(declaration(workflow=flow('세 번째'))),
                f'/api/tools/{tid}/versions',expectedRevision=2).status_code==201
    assert owner.post(f'/api/tools/{tid}/rollback',headers=h,
                      json={'version':2,'expectedRevision':3}).status_code==200
    assert owner.get(f'/api/tools/{tid}').json['workflow'] is None


def test_invalid_workflow_declaration_warns_and_plain_file_still_publishes(app):
    owner,h=ready(app)
    bad=bundle(declaration(workflow={'steps':[]}))
    inspected=post(owner,h,bad,'/api/packages/inspect')
    assert inspected.status_code==200 and not inspected.json['recognized']
    assert 'workflow' in inspected.json['warning']
    created=post(owner,h,bad,name='수동 도구',desc='수동 소개',platform='Claude',
                 type='Skill',guide='직접 작성 안내')
    assert created.status_code==201 and created.json['packageWarning']
    assert owner.get(f'/api/tools/{created.json["id"]}').json['workflow'] is None
    assert owner.get(f'/download/{created.json["id"]}/1').data==bad


def test_manual_metadata_flow_for_md_and_no_retroactive_release_edits(app):
    owner,h=ready(app)
    metadata=dict(name='단일 MD',desc='자료를 정리합니다.',owner='등록자',org='공통',
        category='공통 업무',platform='Claude',type='Skill',guide='MD 사용 안내',
        approval=False,mode='file',workflow=flow())
    raw=b'# Skill\n'
    created=owner.post('/api/tools',headers=h,data={'metadata':json.dumps(metadata),
                           'artifact':(io.BytesIO(raw),'SKILL.md')})
    assert created.status_code==201,created.json
    tid=created.json['id']
    assert owner.get(f'/download/{tid}/1').data==raw
    assert owner.get(f'/api/tools/{tid}').json['workflow']==flow()
    assert owner.patch(f'/api/tools/{tid}',headers=h,
        json={'expectedRevision':1,'workflow':flow('바뀐 흐름')}).status_code==400
    assert owner.patch(f'/api/tools/{tid}',headers=h,
        json={'expectedRevision':1,'desc':'설명만 수정'}).status_code==200
    assert owner.get(f'/api/tools/{tid}/manifest').json['workflow']==flow()
    failed=publish(owner,h,workflow={'steps':[{'title':'a','url':'javascript:alert(1)'}]})
    assert failed.status_code==400
