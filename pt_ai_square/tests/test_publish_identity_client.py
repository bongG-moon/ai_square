"""Target-selection and local identity hints without a network or real account."""
from contextlib import contextmanager
import io
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from .test_auto_publish import publisher


class Client:
    url = 'https://square.example.test'
    token = 'test-key'

    def __init__(self):
        self.employee = '1001'
        self.tools = {}
        self.candidates = []
        self.candidates_by_query = None
        self.queries = []
        self.writes = []
        self.result = dict(id=7, version=2, packageId='original-tool', sourcePackageId='fresh-zip')

    def get(self, path):
        self.queries.append(path)
        if path == '/api/catalog/options':
            return dict(employee=dict(id=self.employee, name='작성자'), organizations=[], categories=[])
        if path.startswith('/api/publish-targets?'):
            if self.candidates_by_query is not None:
                query = parse_qs(urlsplit(path).query)
                key, values = next(iter(query.items()))
                return dict(items=self.candidates_by_query.get((key, values[0]), []))
            return dict(items=self.candidates)
        raise AssertionError(path)

    def details(self, tool_id):
        return self.tools[tool_id]

    @contextmanager
    def open(self, path, data, headers):
        self.writes.append(path)
        yield io.BytesIO(json.dumps(self.result).encode())


def tool(**changes):
    return dict(id=7, name='기존 도구', revision=4, canManage=True, ownerId='1001',
                packageId='original-tool', approval=False, **changes)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    client = Client()
    artifact = tmp_path/'release.zip'
    artifact.write_bytes(b'original ZIP bytes, never rewritten by this client')
    plan = tmp_path/'plan.json'
    inspected = dict(package=dict(packageId='fresh-zip'), metadata=dict(name='동일 표시 이름'), warning='')
    def multipart(client, path, artifact, metadata=None):
        if path == '/api/packages/inspect':
            return inspected
        assert path == '/api/publish-drafts'
        return dict(id='draft-1', status='approved', metadata=metadata)
    monkeypatch.setattr(publisher, 'multipart', multipart)
    return client, artifact, plan, inspected


def bind(plan, artifact, **changes):
    row = dict(baseUrl=Client.url, employeeId='1001', toolId=7, sourcePath=str(artifact.resolve()),
               packageId='original-tool', sourcePackageId='original-tool')
    row.update(changes)
    publisher.remember_binding(plan.parent/'.ai-square-publish-state.json', row)


def test_same_source_path_preserves_candidate_when_source_id_changes(setup):
    client, artifact, plan, _ = setup
    client.tools[7] = tool()
    bind(plan, artifact)
    before = artifact.read_bytes()
    preview = publisher.prepare(client, artifact, {}, plan)
    assert preview['action'] == 'choose_target'
    assert preview['candidates'][0] == dict(id=7, name='기존 도구', revision=4,
                                            packageId='original-tool', reason='same_source_path')
    assert preview['toolId'] is None and preview['requiresTargetSelection']
    with pytest.raises(publisher.ClientError, match='--tool'):
        publisher.publish(client, plan, 'public')
    assert client.writes == [] and artifact.read_bytes() == before


def test_explicit_target_keeps_canonical_and_original_separate(setup):
    client, artifact, plan, _ = setup
    client.tools[7] = tool()
    preview = publisher.prepare(client, artifact, dict(packageId='spoofed', sourcePackageId='spoofed', toolId=999), plan, tool_id=7)
    assert preview['action'] == 'new_version' and preview['toolId'] == 7
    assert preview['packageId'] == 'original-tool' and preview['sourcePackageId'] == 'fresh-zip'
    assert preview['packageIdentityChanged'] and not preview['requiresTargetSelection']
    assert not {'packageId', 'sourcePackageId', 'toolId'} & preview['metadata'].keys()
    assert publisher.read_json(plan)['expectedRevision'] == 4
    result = publisher.publish(client, plan, 'public')
    state = publisher.read_json(plan.parent/'.ai-square-publish-state.json')
    assert result['packageId'] == state['packageId'] == 'original-tool'
    assert result['sourcePackageId'] == state['sourcePackageId'] == 'fresh-zip'
    assert state['sourcePath'] == str(artifact.resolve()) and state['toolId'] == 7
    assert state['bindings'][0]['sourcePackageId'] == 'fresh-zip'


@pytest.mark.parametrize('change', [dict(baseUrl='https://other.example.test'), dict(employeeId='other')])
def test_other_account_or_server_binding_is_not_a_candidate(setup, change):
    client, artifact, plan, _ = setup
    bind(plan, artifact, **change)
    assert publisher.prepare(client, artifact, {}, plan)['candidates'] == []


def test_different_file_in_shared_plan_directory_does_not_reuse_binding(setup):
    client, artifact, plan, _ = setup
    bind(plan, artifact.with_name('unrelated.zip'))
    preview = publisher.prepare(client, artifact, {}, plan)
    assert preview['action'] == 'new_tool' and preview['candidates'] == []


def test_explicit_new_ignores_prior_path_and_does_not_fetch_candidates(setup):
    client, artifact, plan, _ = setup
    bind(plan, artifact)
    preview = publisher.prepare(client, artifact, {}, plan, new=True)
    assert preview['action'] == 'new_tool' and preview['packageId'] == 'fresh-zip'
    assert not preview['requiresTargetSelection'] and not preview['candidates']
    assert client.queries == ['/api/catalog/options']


def test_name_only_match_is_candidate_and_cannot_publish_until_selected(setup):
    client, artifact, plan, inspected = setup
    inspected['package'] = None
    client.candidates = [dict(id=9, name='같은 이름', revision=1, packageId=None)]
    preview = publisher.prepare(client, artifact, dict(name='같은 이름'), plan)
    query = parse_qs(urlsplit(client.queries[-1]).query)
    assert query == {'q': ['같은 이름']}
    assert preview['action'] == 'choose_target' and preview['candidates'][0]['reason'] == 'name'
    with pytest.raises(publisher.ClientError, match='--new'):
        publisher.publish(client, plan, 'public')
    assert client.writes == []


def test_unique_package_match_also_requires_explicit_target(setup):
    client, artifact, plan, _ = setup
    client.candidates = [dict(id=9, name='일치한 도구', revision=1, packageId='fresh-zip')]
    preview = publisher.prepare(client, artifact, {}, plan)
    assert preview['toolId'] is None and preview['candidates'][0]['reason'] == 'package_id'
    assert preview['requiresTargetSelection']


def test_changed_source_id_without_binding_falls_back_to_name_candidates(setup):
    client, artifact, plan, _ = setup
    client.candidates_by_query = {('q', '동일 표시 이름'): [dict(id=7, name='동일 표시 이름', revision=4, packageId='original-tool')]}
    preview = publisher.prepare(client, artifact, {}, plan)
    assert preview['action'] == 'choose_target' and preview['toolId'] is None
    assert preview['candidates'][0]['packageId'] == 'original-tool'
    assert preview['candidates'][0]['reason'] == 'name'
    queries = [parse_qs(urlsplit(path).query) for path in client.queries if path.startswith('/api/publish-targets?')]
    assert queries == [{'packageId': ['fresh-zip']}, {'q': ['동일 표시 이름']}]
    with pytest.raises(publisher.ClientError, match='--tool'):
        publisher.publish(client, plan, 'public')


def test_unrelated_id_and_name_with_no_candidates_can_prepare_new_tool(setup):
    client, artifact, plan, _ = setup
    preview = publisher.prepare(client, artifact, dict(name='다른 프로젝트'), plan)
    assert preview['action'] == 'new_tool' and not preview['requiresTargetSelection']
    assert not preview['candidates']
    queries = [parse_qs(urlsplit(path).query) for path in client.queries if path.startswith('/api/publish-targets?')]
    assert queries == [{'packageId': ['fresh-zip']}, {'q': ['다른 프로젝트']}]


def test_multiple_source_paths_keep_independent_bindings(setup):
    client, artifact, plan, _ = setup
    second = artifact.with_name('other.zip')
    second.write_bytes(b'other')
    bind(plan, artifact)
    bind(plan, second, toolId=8)
    client.tools = {7: tool(), 8: {**tool(), 'id': 8}}
    assert publisher.prepare(client, artifact, {}, plan)['candidates'][0]['id'] == 7
    assert publisher.prepare(client, second, {}, plan)['candidates'][0]['id'] == 8


def test_legacy_package_binding_without_source_path_is_not_authority(setup):
    client, artifact, plan, _ = setup
    publisher.save(plan.parent/'.ai-square-publish-state.json',
                   dict(baseUrl=client.url, employeeId='1001', toolId=7, sourceKey='package:fresh-zip'))
    assert publisher.prepare(client, artifact, {}, plan)['candidates'] == []


def test_legacy_file_path_binding_is_a_candidate_only(setup):
    client, artifact, plan, inspected = setup
    inspected['package'] = None
    client.tools[7] = tool()
    publisher.save(plan.parent/'.ai-square-publish-state.json',
                   dict(baseUrl=client.url, employeeId='1001', toolId=7, sourceKey='file:'+str(artifact.resolve())))
    preview = publisher.prepare(client, artifact, {}, plan)
    assert preview['requiresTargetSelection'] and preview['candidates'][0]['id'] == 7


def test_explicit_admin_target_still_requires_actual_ownership(setup):
    client, artifact, plan, _ = setup
    client.tools[7] = {**tool(), 'ownerId': 'different-owner'}
    with pytest.raises(publisher.ClientError, match='본인'):
        publisher.prepare(client, artifact, {}, plan, tool_id=7)


def test_first_declaration_can_establish_identity_for_manual_tool(setup):
    client, artifact, plan, _ = setup
    client.tools[7] = {**tool(), 'packageId': None}
    preview = publisher.prepare(client, artifact, {}, plan, tool_id=7)
    assert preview['packageId'] == preview['sourcePackageId'] == 'fresh-zip'
    assert not preview['packageIdentityChanged']
