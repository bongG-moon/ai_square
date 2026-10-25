"""Registration runs canonical preparation without touching real profiles/servers."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
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
    denied = store.dispatch('publish', {'draftId': pending['id'], 'confirmed': True})
    assert denied['published'] is False and not client.commits
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
