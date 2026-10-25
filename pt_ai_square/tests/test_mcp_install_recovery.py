"""Recovery after an actual process exit, not a catchable Python exception."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from .mcp_crash_fixture import setup

SCRIPT = Path(__file__).with_name('mcp_crash_fixture.py')


CASES = [(kind, mode, phase) for kind in ('skill', 'mcp') for mode in ('first', 'update', 'rollback_first', 'rollback_update')
         for phase in ('journal', 'old_moved', 'new_moved', 'config_after', 'record_before', 'record_after')
         if not (phase == 'old_moved' and mode == 'first')
         and not (phase == 'new_moved' and mode == 'rollback_first')
         and not (phase == 'config_after' and kind == 'skill')]


def crashed(tmp_path, kind, mode, phase):
    run = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(SCRIPT), str(tmp_path), kind, mode, phase],
                         capture_output=True, timeout=20)
    assert run.returncode == 93, run.stderr.decode('utf-8', errors='replace')
    installer, project = setup(tmp_path, kind)
    network_before = (tmp_path/'network-calls').read_bytes()
    installer.client.manifest = lambda *_: pytest.fail('recovery must not contact server')
    installer.client.download = lambda *_args, **_kwargs: pytest.fail('recovery must not download or execute')
    return installer, project, network_before


@pytest.mark.parametrize('kind,mode,phase', CASES)
def test_hard_exit_recovery_preserves_files_configuration_and_records(tmp_path, kind, mode, phase):
    installer, project, network_before = crashed(tmp_path, kind, mode, phase)
    result = installer.recover()
    assert not result['blocked'], result
    assert len(result['recovered']) == 1, result
    records = installer.records()
    target = project/('.claude/skills/crash-fixture' if kind == 'skill' else '.pt-ai-square/tools/crash-fixture')
    if records:
        record = next(iter(records.values()))
        file = target/('SKILL.md' if kind == 'skill' else 'server.py')
        assert file.read_text() == f'# version {record["release"]}\n'
        from pt_square_mcp.install import tree_digest
        assert tree_digest(target) == record['treeHash']
        if kind == 'mcp':
            config = json.loads((project/'.mcp.json').read_text())
            assert config['mcpServers'][record['serverName']] == record['configEntry']
    else:
        assert not target.exists()
    if kind == 'mcp':
        config = json.loads((project/'.mcp.json').read_text())
        assert config['mcpServers']['unrelated'] == {'command': 'keep'} and config['preference'] is True
        if not records:
            assert 'pt-square-crash-fixture' not in config['mcpServers']
    assert installer.recover() == {'recovered': [], 'blocked': []}
    assert (tmp_path/'network-calls').read_bytes() == network_before


@pytest.mark.parametrize('change', ['files', 'config', 'backup'])
def test_user_edit_after_process_exit_is_never_overwritten(tmp_path, change):
    installer, project, network_before = crashed(tmp_path, 'mcp', 'update', 'old_moved' if change == 'backup' else 'new_moved')
    target = project/'.pt-ai-square/tools/crash-fixture'
    if change == 'files':
        altered = target/'personal.txt'; altered.write_text('do not change')
    elif change == 'config':
        altered = project/'.mcp.json'; altered.write_text('{"mcpServers":{"personal":{"command":"keep-new"}}}')
    else:
        journal = json.loads(next((installer.settings.state/'transactions').glob('*.json')).read_text())
        altered = Path(journal['oldSource'])/'personal.txt'; altered.write_text('do not change')
    expected = altered.read_bytes()
    result = installer.recover()
    assert result['blocked'] and not result['recovered']
    assert altered.read_bytes() == expected
    assert (tmp_path/'network-calls').read_bytes() == network_before


def test_malformed_journal_is_reported_without_touching_files(tmp_path):
    installer, project, _ = crashed(tmp_path, 'skill', 'first', 'record_before')
    path = next((installer.settings.state/'transactions').glob('*.json'))
    raw = json.loads(path.read_text()); raw['target'] = str(tmp_path/'do-not-touch')
    path.write_text(json.dumps(raw))
    result = installer.recover()
    assert result['blocked'] and not (tmp_path/'do-not-touch').exists()


def test_concurrent_mcp_edit_after_rollback_write_is_not_claimed_completed(tmp_path, monkeypatch):
    from pt_square_mcp import install as engine
    from pt_square_mcp.config import SquareError
    installer, project = setup(tmp_path, 'mcp')
    plan = installer.prepare(1, 'project', str(project))
    installed = installer.install(plan['planId'], plan['approvalDigest'], True)
    configuration = project/'.mcp.json'
    original = engine.atomic_json
    def changed_after_write(path, value):
        original(path, value)
        if Path(path) == configuration:
            changed = json.loads(configuration.read_text())
            changed['mcpServers']['pt-square-crash-fixture'] = {'command': 'user-change'}
            configuration.write_text(json.dumps(changed))
    monkeypatch.setattr(engine, 'atomic_json', changed_after_write)
    with pytest.raises(SquareError, match='설정이 변경'):
        installer.rollback(installed['installationId'], True)
    assert installer.records()
    assert json.loads(configuration.read_text())['mcpServers']['pt-square-crash-fixture']['command'] == 'user-change'
    recovery = installer.recover()
    assert recovery['blocked'] and not recovery['recovered']
