"""Account switching must not turn a shared local artifact into a missing download."""
import copy
import hashlib
import io
from pathlib import Path
import sys

import pytest

from .conftest import ready, publish
from .test_personal_api_usage import issue
from .test_receiver import server
from .test_mcp_real_api import fields
from pt_ai_square.backend.storage import db

PACKAGE = Path(__file__).resolve().parents[1] / 'integrations' / 'pt-square-mcp'
sys.path.insert(0, str(PACKAGE))
from pt_square_mcp.client import Client
from pt_square_mcp.config import Settings, SquareError, save_config
from pt_square_mcp.runtime import Runtime


def setup_runtime(tmp_path, server):
    project = tmp_path / 'project'
    home = tmp_path / 'home'
    project.mkdir(); home.mkdir()
    downloads = project / 'downloads'
    downloads.mkdir()
    config = tmp_path / 'config.json'
    save_config(config, server, [project], allow_http=True, download_directory=downloads)
    return Runtime(Settings(config), home=home), project


def assert_user(app, user, count, enabled):
    with app.app_context():
        row = db().activity_state.find_one({'tool': 1, 'user': user, 'kind': 'download'})
        subscription = db().subscriptions.find_one({'tool': 1, 'user': user})
        assert row and bool(row.get('firstDownloadedAt')) == bool(count)
        assert subscription and subscription['enabled'] is enabled


def test_cached_file_records_current_employee_and_respects_opt_out(app, server, tmp_path, monkeypatch):
    owner, headers = ready(app)
    assert publish(owner, headers).status_code == 201
    member, mh = ready(app, 'member')
    other, oh = ready(app, 'other')
    key_a, _ = issue(member, mh)
    key_b, _ = issue(other, oh)
    runtime, _ = setup_runtime(tmp_path, server)

    monkeypatch.setenv('PTAI_API_TOKEN', key_a['token'])
    first = Path(runtime.download_item(1)['file'])
    original = first.read_bytes()
    assert_user(app, 'member', 1, True)
    assert member.put('/api/tools/1/subscription', headers=mh, json={'enabled': False}).status_code == 200
    # A newly issued KEY is still the same employee; repeated use is deduplicated.
    key_a2, _ = issue(member, mh)
    monkeypatch.setenv('PTAI_API_TOKEN', key_a2['token'])
    assert Path(runtime.download_item(1)['file']) == first
    assert_user(app, 'member', 1, False)

    monkeypatch.setenv('PTAI_API_TOKEN', key_b['token'])
    assert Path(runtime.download_item(1)['file']) == first
    assert first.read_bytes() == original
    assert_user(app, 'other', 1, True)
    assert owner.get('/api/tools/1').json['downloads'] == 2

    # An invalid KEY must not get a successful cache hit.
    monkeypatch.setenv('PTAI_API_TOKEN', 'ptsq_' + 'x' * 43)
    with pytest.raises(SquareError):
        runtime.download_item(1)
    assert first.read_bytes() == original


def test_shared_installation_after_key_switch_counts_new_employee(app, server, tmp_path, monkeypatch):
    owner, headers = ready(app)
    assert publish(owner, headers, **fields()).status_code == 201
    member, mh = ready(app, 'member')
    other, oh = ready(app, 'other')
    key_a, _ = issue(member, mh)
    key_b, _ = issue(other, oh)
    runtime, project = setup_runtime(tmp_path, server)

    def install_for(key):
        monkeypatch.setenv('PTAI_API_TOKEN', key)
        plan = runtime.installer.prepare(1, 'project', str(project))
        assert runtime.installer.install(plan['planId'], plan['approvalDigest'], True)['installed']

    install_for(key_a['token'])
    assert_user(app, 'member', 1, True)
    assert member.put('/api/tools/1/subscription', headers=mh, json={'enabled': False}).status_code == 200
    key_a2, _ = issue(member, mh)
    install_for(key_a2['token'])
    assert_user(app, 'member', 1, False)
    install_for(key_b['token'])
    assert_user(app, 'other', 1, True)
    assert owner.get('/api/tools/1').json['downloads'] == 2
    # Pre-change records omit the account binding. The next installation
    # remains compatible and the server deduplicates this same employee.
    records = runtime.installer.records()
    next(iter(records.values())).pop('accountBinding')
    from pt_square_mcp.config import atomic_json
    atomic_json(runtime.installer.record_path, records)
    install_for(key_b['token'])
    assert owner.get('/api/tools/1').json['downloads'] == 2


def test_explicit_update_tracks_each_employee_and_key_rotation(app, server, tmp_path, monkeypatch):
    owner, headers = ready(app)
    assert publish(owner, headers).status_code == 201
    member, mh = ready(app, 'member')
    other, oh = ready(app, 'other')
    key_a, _ = issue(member, mh)
    key_b, _ = issue(other, oh)
    runtime, _ = setup_runtime(tmp_path, server)

    def receive(key, *, update):
        monkeypatch.setenv('PTAI_API_TOKEN', key)
        return Path(runtime.download_item(1, update=update)['file'])

    def last_purpose(user):
        with app.app_context():
            return db().activity.find_one({'tool': 1, 'user': user, 'kind': 'download'}, sort=[('created', -1)])['purpose']

    original = receive(key_a['token'], update=False)
    assert last_purpose('member') == 'download'
    assert member.put('/api/tools/1/subscription', headers=mh, json={'enabled': False}).status_code == 200
    key_a2, _ = issue(member, mh)
    assert receive(key_a2['token'], update=True) == original
    assert last_purpose('member') == 'update'
    assert_user(app, 'member', 1, False)

    assert receive(key_b['token'], update=True) == original
    assert last_purpose('other') == 'download'
    assert_user(app, 'other', 1, True)
    assert receive(key_b['token'], update=True) == original
    assert last_purpose('other') == 'update'
    assert owner.get('/api/tools/1').json['downloads'] == 2

    # A missing receipt can only make the next update a regular download;
    # server-side first-download deduplication and opt-out still hold.
    for receipt in (runtime.settings.state / 'download-receipts').glob('*.json'):
        receipt.unlink()
    assert receive(key_a2['token'], update=True) == original
    assert last_purpose('member') == 'download'
    assert_user(app, 'member', 1, False)
    assert owner.get('/api/tools/1').json['downloads'] == 2


def test_cache_hit_requires_valid_server_response_and_preserves_local_file(tmp_path, monkeypatch):
    raw = b'cached artifact'
    config = tmp_path / 'config.json'
    save_config(config, 'http://127.0.0.1:12345', [tmp_path], allow_http=True)
    client = Client(Settings(config))
    manifest = {'toolId': 1, 'release': 1, 'filename': 'skill.md', 'downloadUrl': '/download/1/1',
                'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'installProfile': None}
    target = tmp_path / 'tool-1-v1.md'
    target.write_bytes(raw)
    monkeypatch.setattr(client, 'manifest', lambda _: copy.deepcopy(manifest))
    monkeypatch.setattr(client, 'open', lambda *_a, **_k: io.BytesIO(b'broken'))
    with pytest.raises(SquareError, match='SHA-256'):
        client.download(manifest, tmp_path)
    assert target.read_bytes() == raw


def test_receipt_write_failure_does_not_report_saved_download_as_failed(app, server, tmp_path, monkeypatch):
    owner, headers = ready(app)
    assert publish(owner, headers).status_code == 201
    member, mh = ready(app, 'member')
    key, _ = issue(member, mh)
    runtime, _ = setup_runtime(tmp_path, server)
    monkeypatch.setenv('PTAI_API_TOKEN', key['token'])
    from pt_square_mcp import runtime as runtime_module
    def fail_receipt(*_args, **_kwargs):
        raise OSError('test receipt write failure')
    monkeypatch.setattr(runtime_module, 'atomic_json', fail_receipt)
    result = runtime.download_item(1, update=True)
    assert result['downloaded'] and result['receiptPending']
    assert Path(result['file']).is_file()
    assert_user(app, 'member', 1, True)
    # Repeating after a receipt failure still cannot add a second ranking point.
    assert runtime.download_item(1, update=True)['downloaded']
    assert owner.get('/api/tools/1').json['downloads'] == 1
