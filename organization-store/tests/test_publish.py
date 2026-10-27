"""Registration runs canonical preparation without touching real profiles/servers."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import uuid
import zipfile

import pytest

spec = importlib.util.spec_from_file_location('store_publish_worker', Path(__file__).resolve().parents[1] / 'worker.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def metadata(**changes):
    return dict(dict(name='메모 요약', desc='업무 메모를 요약합니다.', platform='Claude', type='Skill',
                     guide='파일을 원하는 공간에 설치하세요.', orgId='org', categoryId='work',
                     approval=False, mode='file', workTags=['메모']), **changes)


class Platform:
    def __init__(self):
        self.identity = dict(user={'id': 'owner', 'name': '등록자'}, key={'id': 'key-one', 'scope': 'publish'},
                             capabilities={'publishDraft': True})
        self.options = dict(organizations=[{'id': 'org', 'name': '조직'}], categories=[{'id': 'work', 'name': '업무'}])
        self.drafts, self.calls, self.draft_calls, self.commits = {}, [], [], 0
        self.lost_response = False
        self.item = dict(id=7, ownerId='owner', revision=2, name='기존 도구', active=1, mode='zip',
                         versions=[dict(n=1, installProfile={'schemaVersion': 1, 'kind': 'skill', 'host': 'claude',
                                      'slug': 'memo-skill', 'entrypoint': 'SKILL.md', 'scopes': ['user']})])

    def json(self, path, method='GET', data=None):
        self.calls.append((path, method, data))
        if path == '/api/integration/me':
            return copy.deepcopy(self.identity)
        if path == '/api/catalog/options':
            return copy.deepcopy(self.options)
        if path.startswith('/api/publish-targets?'):
            return {'items': [{'id': 7, 'name': '기존 도구'}]}
        if path == '/api/tools/7':
            return copy.deepcopy(self.item)
        if path.startswith('/api/publish-drafts/'):
            draft_id = path.split('/')[3]
            draft = self.drafts[draft_id]
            if method == 'POST':
                assert path.endswith('/commit')
                if draft['status'] not in {'approved', 'committed'}:
                    raise worker.SquareError('approval required')
                if draft['status'] != 'committed':
                    self.commits += 1
                draft['status'] = 'committed'
                draft['result'] = {'id': draft.get('toolId') or 100, 'version': 2 if draft.get('toolId') else 1}
                return copy.deepcopy(draft['result'])
            return copy.deepcopy(draft)
        raise AssertionError(path)

    def draft(self, values, artifact=None):
        content = artifact.read_bytes() if artifact else b''
        self.draft_calls.append((copy.deepcopy(values), content))
        draft_id = str(uuid.uuid5(uuid.NAMESPACE_URL, values['clientRequestId']))
        self.drafts.setdefault(draft_id, dict(id=draft_id, status='pending', metadata=copy.deepcopy(values),
                                            toolId=values.get('toolId'), reviewDigest='digest',
                                            reviewUrl='/publish-review/' + draft_id,
                                            artifact={'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}))
        if self.lost_response:
            self.lost_response = False
            raise worker.SquareError('network response lost')
        return copy.deepcopy(self.drafts[draft_id])


@pytest.fixture
def ready(tmp_path):
    data, home = tmp_path / 'data', tmp_path / 'home'
    data.mkdir(); home.mkdir()
    source = tmp_path / 'SKILL.md'
    source.write_text('---\nname: memo-skill\ndescription: Memo\n---\n# Memo\n', encoding='utf-8')
    store = worker.Store(data, home=home, existing_config=tmp_path / 'absent')
    worker.save_config(store.config_path, 'https://fixture.test', [data], download_directory=data)
    worker.atomic_json(store.selection_path, {'mode': 'local'})
    client = Platform()
    store.client_factory = lambda settings: client
    select(store, source)
    return store, client, source


def select(store, path):
    info = path.stat()
    store.context = {'selectedFile': str(path), 'selectedFileIdentity': [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]}


def prepare(store, **changes):
    return store.dispatch('preparePublish', dict(dict(target='new', metadata=metadata(), requestId=str(uuid.uuid4())), **changes))


def test_file_preparation_browser_approval_commit_and_retry(ready):
    store, client, source = ready
    options = store.dispatch('publishOptions')
    assert options['canPublish'] and options['candidates'][0]['id'] == 7
    inspected = store.dispatch('inspectPublishSource')
    assert inspected['metadata'] == {'type': 'Skill'} and inspected['source']['name'] == 'SKILL.md'
    request_id = str(uuid.uuid4())
    pending = prepare(store, requestId=request_id)
    assert pending['status'] == 'pending' and pending['reviewUrl'].startswith('https://fixture.test/publish-review/')
    assert not any((store.directory / 'publish-staging').iterdir())
    assert client.draft_calls[0][1] == source.read_bytes()
    assert 'preparedFile' not in pending
    with pytest.raises(worker.SquareError, match='등록 내용'):
        store.dispatch('publish', {'draftId': pending['id'], 'confirmed': True})
    assert not client.commits
    # Only the test server's browser-side approval changes status.
    client.drafts[pending['id']]['status'] = 'approved'
    assert store.dispatch('publishStatus', {'draftId': pending['id']})['status'] == 'approved'
    result = store.dispatch('publish', {'draftId': pending['id']})
    assert result['published'] and result['version'] == 1
    assert store.dispatch('publish', {'draftId': pending['id']}) == result
    assert client.commits == 1
    assert prepare(store, requestId=request_id)['status'] == 'committed'
    assert len(client.draft_calls) == 1
    assert not any('/approve' in call[0] for call in client.calls)


def test_read_only_key_never_uploads_and_offers_reconnect(ready):
    store, client, _ = ready
    client.identity['capabilities']['publishDraft'] = False
    assert store.dispatch('publishOptions')['canPublish'] is False
    assert store.dispatch('publishOptions')['keyGuideUrl'].endswith('/local-access')
    for action in ('inspectPublishSource', 'preparePublish', 'publishStatus', 'publish'):
        with pytest.raises(worker.SquareError, match='업로드 포함'):
            store.dispatch(action, {})
    assert not client.draft_calls


@pytest.mark.parametrize('context', [{}, {'selectedFile': 'C:/secret.md'}, {'selectedFileIdentity': [1, 2, 3, 4]}])
def test_payload_cannot_grant_file_access(ready, context):
    store, client, source = ready
    store.context = context
    with pytest.raises(worker.SquareError, match='선택'):
        store.dispatch('inspectPublishSource', {'path': str(source), 'selectedFile': str(source), 'fileToken': 'invented'})
    assert not client.draft_calls


def test_changed_file_rejected_before_upload(ready):
    store, client, source = ready
    source.write_text('# changed', encoding='utf-8')
    with pytest.raises(worker.SquareError, match='변경'):
        prepare(store)
    assert not client.draft_calls


@pytest.mark.parametrize('suffix', ['.json', '.py', '.cmd'])
def test_only_canonical_distribution_formats_can_publish(ready, suffix):
    store, client, source = ready
    other = source.with_suffix(suffix); other.write_bytes(b'no execution')
    select(store, other)
    with pytest.raises(worker.SquareError, match='지원 범위'):
        prepare(store)
    assert not client.draft_calls


@pytest.mark.parametrize('suffix', ['.exe', '.msi', '.ps1'])
def test_executable_artifacts_upload_unchanged_without_running(ready, suffix):
    store, client, source = ready
    artifact = source.with_suffix(suffix); artifact.write_bytes(b'not executed fixture')
    select(store, artifact)
    assert store.dispatch('inspectPublishSource')['metadata'] == {}
    assert prepare(store)['status'] == 'pending'
    assert client.draft_calls[0][1] == b'not executed fixture'


@pytest.mark.parametrize('identity_change', ['user', 'key', 'origin'])
def test_saved_draft_bound_to_connection_user_and_key(ready, identity_change):
    store, client, _ = ready
    pending = prepare(store)
    if identity_change == 'user':
        client.identity['user']['id'] = 'other'
    elif identity_change == 'key':
        client.identity['key']['id'] = 'replacement-key'
    else:
        config = worker.read_json(store.config_path); config['baseUrl'] = 'https://other.test'
        worker.atomic_json(store.config_path, config)
    with pytest.raises(worker.SquareError, match='현재 연결'):
        store.dispatch('publish', {'draftId': pending['id']})
    assert not client.commits


def test_lost_prepare_response_reuses_id_and_cleans_staging(ready):
    store, client, _ = ready
    request_id = str(uuid.uuid4()); client.lost_response = True
    with pytest.raises(worker.SquareError, match='network'):
        prepare(store, requestId=request_id)
    assert not any((store.directory / 'publish-staging').iterdir())
    pending = prepare(store, requestId=request_id)
    assert len(client.drafts) == 1 and pending['id'] in client.drafts
    assert len(client.draft_calls) == 2
    assert client.draft_calls[0] == client.draft_calls[1]


def test_same_retry_id_cannot_publish_modified_metadata(ready):
    store, client, _ = ready
    request_id = str(uuid.uuid4())
    prepare(store, requestId=request_id)
    with pytest.raises(worker.SquareError, match='내용이나 연결'):
        prepare(store, requestId=request_id, metadata=metadata(desc='다른 내용'))
    assert len(client.draft_calls) == 1


def test_explicit_owned_update_preserves_profile_in_form_and_revision(ready):
    store, client, _ = ready
    existing = store.dispatch('publishOptions', {'toolId': 7})['existing']
    profile = existing['metadata']['installProfile']
    assert profile['slug'] == 'memo-skill'
    pending = prepare(store, target='update', toolId=7, metadata=metadata(installProfile=profile))
    assert pending['metadata']['expectedRevision'] == 2 and pending['toolId'] == 7
    assert pending['metadata']['installProfile'] == profile
    client.item['ownerId'] = 'other'
    for action, payload in [('publishOptions', {'toolId': 7}), ('preparePublish', {'target': 'update', 'toolId': 7, 'metadata': metadata()})]:
        with pytest.raises(worker.SquareError, match='본인'):
            store.dispatch(action, payload)


@pytest.mark.parametrize('values', [metadata(mode='url', url='https://service.test'),
                                   metadata(mode='command', commandProject='python setup.py')])
def test_url_and_commands_are_metadata_only_never_executed(ready, values, monkeypatch):
    store, client, _ = ready
    store.context = {}
    monkeypatch.setattr(worker.Store, 'selected_file', lambda self: pytest.fail('not a file request'))
    pending = prepare(store, metadata=values)
    assert pending['status'] == 'pending' and client.draft_calls[0][1] == b''
    assert client.draft_calls[0][0]['mode'] == values['mode']


def test_zip_declaration_prefills_without_execution(ready):
    store, client, source = ready
    package = dict(schemaVersion=1, packageId='memo.skill', name='메모', desc='정리', platform='Claude', type='Skill',
                   entryPoint='SKILL.md', guideFile='GUIDE.md', workTags=['메모'])
    archive = source.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w') as zip_file:
        zip_file.writestr('ai-square.json', json.dumps(package)); zip_file.writestr('SKILL.md', '# memo')
        zip_file.writestr('GUIDE.md', '설치 안내')
    select(store, archive)
    inspected = store.dispatch('inspectPublishSource')
    assert inspected['metadata']['guide'] == '설치 안내'
    assert inspected['metadata']['packageId'] == 'memo.skill'
    assert not client.draft_calls


@pytest.mark.parametrize('artifact_name', ['html-report.zip', 'web-interface.zip'])
def test_real_distribution_packages_supply_all_registration_fields(ready, artifact_name):
    """The app imports the same declared data and guide text as web registration."""
    store, client, _ = ready
    archive = Path(__file__).resolve().parents[2] / 'skills_zip' / artifact_name
    before = archive.read_bytes()
    with zipfile.ZipFile(archive) as zipped:
        declared = json.loads(zipped.read('ai-square.json').decode('utf-8-sig'))
        guide = zipped.read(declared['guideFile']).decode('utf-8-sig').strip()
    select(store, archive)

    result = store.dispatch('inspectPublishSource')

    expected = {key: declared[key] for key in ('name', 'desc', 'platform', 'type', 'workTags',
                                               'environment', 'changes', 'workflow', 'packageId')}
    expected['guide'] = guide
    assert result['metadata'] == expected
    assert result['packageWarning'] == ''
    assert result['source'] == {'name': artifact_name, 'bytes': len(before),
                                'sha256': hashlib.sha256(before).hexdigest()}
    assert result['options'] == client.options
    assert any(call[0] == '/api/publish-targets?packageId=' + declared['packageId'] for call in client.calls)
    assert all(call[1] == 'GET' for call in client.calls)
    assert not client.draft_calls and not client.commits
    assert archive.read_bytes() == before
    assert not set(result['metadata']) & {'approval', 'orgId', 'categoryId', 'owner'}


@pytest.mark.parametrize('kind', ['Skill', 'MCP/Tool', '플러그인/하네스'])
def test_distribution_skill_builder_output_is_readable_by_app(ready, kind):
    store, client, source = ready
    root = Path(__file__).resolve().parents[2]
    prepared = source.parent / 'prepared'
    prepared.mkdir()
    (prepared / 'guides').mkdir()
    declaration = dict(schemaVersion=1, packageId='fixture.distribution', name='배포 도구',
                       desc='배포 스킬로 만든 파일을 자동 입력합니다.', platform='Claude', type=kind,
                       entryPoint='SKILL.md', guideFile='guides/INSTALL.md', requiredFiles=['SKILL.md'],
                       requirements=['Python 3.13'], workTags=['배포', '업무'], environment='Windows',
                       changes='자동 입력 정보 확인', workflow={'steps': [{'title': '파일 선택'},
                                   {'title': '내용 확인', 'description': '입력된 정보를 검토합니다.'}]})
    (prepared / 'ai-square.json').write_text(json.dumps(declaration, ensure_ascii=False), encoding='utf-8-sig')
    (prepared / 'SKILL.md').write_text('# 배포 도구\n', encoding='utf-8')
    (prepared / 'guides' / 'INSTALL.md').write_bytes('  # 설치 안내\n\n업무를 선택하세요.\n'.encode('utf-8-sig'))
    archive = source.parent / 'from-distribution-skill.zip'
    built = subprocess.run([sys.executable, '-X', 'utf8', '-B',
                            str(root / 'pt_ai_square/static/guides/pt-file-distribution/scripts/prepare_package.py'),
                            str(prepared), str(archive)], capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert built.returncode == 0, built.stderr
    select(store, archive)

    result = store.dispatch('inspectPublishSource')

    assert result['packageWarning'] == ''
    assert result['metadata'] == dict(name=declaration['name'], desc=declaration['desc'],
        platform='Claude', type=kind, guide='# 설치 안내\n\n업무를 선택하세요.', packageId='fixture.distribution',
        workTags=['배포', '업무'], environment='Windows', changes='자동 입력 정보 확인',
        workflow={'steps': [{'title': '파일 선택', 'description': ''},
                            {'title': '내용 확인', 'description': '입력된 정보를 검토합니다.'}]})
    assert all(call[1] == 'GET' for call in client.calls) and not client.draft_calls


@pytest.mark.parametrize('invalid', ['missing-guide', 'non-utf8-guide', 'nested-manifest',
                                    'duplicate-json-key', 'permission-field', 'type-alias'])
def test_invalid_declaration_is_manual_entry_warning_without_partial_autofill(ready, invalid):
    store, client, source = ready
    declaration = dict(schemaVersion=1, packageId='fixture.invalid', name='배포 도구', desc='정리',
                       platform='Claude', type='Skill', entryPoint='SKILL.md', guideFile='GUIDE.md')
    if invalid == 'permission-field':
        declaration['approval'] = True
    if invalid == 'type-alias':
        declaration['type'] = 'skill'
    manifest = json.dumps(declaration, ensure_ascii=False)
    if invalid == 'duplicate-json-key':
        manifest = manifest.replace('"schemaVersion": 1', '"schemaVersion": 1, "schemaVersion": 1')
    archive = source.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w') as zipped:
        zipped.writestr('nested/ai-square.json' if invalid == 'nested-manifest' else 'ai-square.json', manifest)
        zipped.writestr('SKILL.md', '# skill')
        if invalid != 'missing-guide':
            zipped.writestr('GUIDE.md', b'\xff\xfeinvalid' if invalid == 'non-utf8-guide' else '설치 안내')
    select(store, archive)

    result = store.dispatch('inspectPublishSource')

    assert result['metadata'] == {}
    assert result['packageWarning'].startswith('배포 정보: ')
    assert all(call[1] == 'GET' for call in client.calls) and not client.draft_calls


@pytest.mark.parametrize('unsafe', ['path-traversal', 'duplicate-entry', 'secret-in-compressed-file'])
def test_zip_autofill_never_accepts_unsafe_archive_contents(ready, unsafe):
    store, client, source = ready
    archive = source.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr('SKILL.md', '# skill')
        if unsafe == 'path-traversal':
            zipped.writestr('../outside.md', '# outside')
        elif unsafe == 'duplicate-entry':
            zipped.writestr('skill.MD', '# duplicate case-insensitive path')
        else:
            zipped.writestr('guide.md', '인증: ptsq_' + 'A' * 43)
    select(store, archive)

    with pytest.raises(worker.SquareError):
        store.dispatch('inspectPublishSource')

    assert not client.draft_calls and not client.commits


def test_private_zip_members_are_blocked_before_upload(ready):
    store, client, source = ready
    archive = source.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w') as zip_file:
        zip_file.writestr('.env', 'test')
    select(store, archive)
    with pytest.raises(worker.SquareError, match='인증정보'):
        store.dispatch('inspectPublishSource')
    with pytest.raises(worker.SquareError, match='인증정보'):
        prepare(store)
    assert not client.draft_calls


@pytest.mark.parametrize('suffix', ['.md', '.ps1', '.exe'])
def test_large_single_files_scan_secrets_across_chunk_boundaries(ready, suffix):
    store, client, source = ready
    artifact = source.with_suffix(suffix)
    # Put the token across the 3 MiB boundary, beyond the canonical small-file scan.
    artifact.write_bytes(b' ' * (3 * 1024 * 1024 - 8) + b'ptsq_' + b'A' * 43 + b'\n')
    select(store, artifact)
    for action, payload in [('inspectPublishSource', {}), ('preparePublish', {'target': 'new', 'metadata': metadata()})]:
        with pytest.raises(worker.SquareError, match='인증정보'):
            store.dispatch(action, payload)
    assert not client.draft_calls
    assert not any((store.directory / 'publish-staging').iterdir())


def test_visibility_and_target_must_be_explicit(ready):
    store, client, _ = ready
    for changes in ({'target': 'review'}, {'metadata': metadata(approval='public')}, {'toolId': 7}):
        with pytest.raises(worker.SquareError):
            prepare(store, **changes)
    assert not client.draft_calls


def test_direct_publish_requires_exact_prepared_digest_without_browser(ready):
    store, client, _ = ready
    original_draft=client.draft
    def draft(values, artifact=None):
        result=original_draft(values, artifact)
        client.drafts[result['id']]['reviewDigest']='a'*64
        return copy.deepcopy(client.drafts[result['id']])
    client.draft=draft
    original_json=client.json
    def direct(path, method='GET', data=None):
        if method=='POST' and path.endswith('/commit'):
            assert data=={'confirmed':True,'reviewDigest':'a'*64}
            client.drafts[path.split('/')[3]]['status']='approved'
        return original_json(path, method, data)
    client.json=direct
    pending=prepare(store)
    with pytest.raises(worker.SquareError):
        store.dispatch('publish',{'draftId':pending['id'],'confirmed':True,'reviewDigest':'b'*64})
    result=store.dispatch('publish',{'draftId':pending['id'],'confirmed':True,'reviewDigest':'a'*64})
    assert result['published'] and client.commits==1
    assert not any('/approve' in path for path,_,_ in client.calls)


def test_my_tools_reads_all_pages_and_preserves_owner_selection(ready):
    from urllib.parse import urlsplit, parse_qs
    store, client, _=ready
    original=client.json
    def pages(path,method='GET',data=None):
        if path.startswith('/api/publish-targets?'):
            offset=int(parse_qs(urlsplit(path).query).get('offset',['0'])[0])
            return {'items':[{'id':i,'name':f'내 도구 {i}'} for i in range(offset+1,min(offset+200,237)+1)],'nextOffset':200 if offset==0 else None}
        return original(path,method,data)
    client.json=pages
    result=store.dispatch('publishOptions')
    assert len(result['candidates'])==237
    assert len({row['id'] for row in result['candidates']})==237
