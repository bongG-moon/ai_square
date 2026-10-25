"""Durable file/config transaction intent for hard process interruption.

Recovery never executes downloaded code or retries an installation. It only
confirms an exact on-disk result or restores exact, previously observed bytes.
An unexpected edit is retained and reported for human review.
Callers hold the shared operation_lock throughout install and recovery.
"""
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import time

from .config import SquareError, atomic_json, no_links, read_json
from .files import sha256


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                   separators=(',', ':')).encode()).hexdigest()


def json_bytes(value):
    # config.atomic_json uses text-mode writes, including Windows CRLF.
    return json.dumps(value, ensure_ascii=False, indent=2).replace('\n', os.linesep).encode('utf-8')


def _tree(path):
    from .install import tree_digest
    path = no_links(path)
    if not path.exists():
        return None
    if not path.is_dir():
        raise SquareError('설치 위치가 폴더가 아닙니다.')
    return tree_digest(path)


def _file(path):
    if path is None:
        return None
    path = no_links(path)
    return sha256(path) if path.is_file() else None if not path.exists() else 'not-a-file'


def _bytes(path, content):
    path = no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = no_links(path.with_name(path.name + '.recovery-new'))
    with temporary.open('wb') as stream:
        stream.write(content); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


def begin(installer, *, transaction_id, operation, install_id, scope, scope_dir, slug,
          target, old_source, new_source, before_record, after_record,
          config_file, config_before, config_after):
    if not re.fullmatch('[a-f0-9]{32}', transaction_id):
        raise SquareError('설치 복구 식별자를 확인하세요.')
    from .install import directory_identity, check_directory_identity
    identity = directory_identity(scope_dir)
    source_record = after_record if operation == 'install' else before_record
    if source_record and source_record.get('scopeIdentity') is not None:
        check_directory_identity(scope_dir, source_record['scopeIdentity'])
    state = no_links(installer.settings.state)
    recovery_dir = no_links(state / 'transactions-data' / transaction_id)
    recovery_dir.mkdir(parents=True, exist_ok=False)
    if config_before is not None:
        _bytes(recovery_dir / 'config.before', config_before)
    config_after_hash = (hashlib.sha256(json_bytes(config_after)).hexdigest()
                         if config_after is not None else None)
    journal = dict(schemaVersion=1, id=transaction_id, operation=operation,
                   origin=installer.settings.url, installId=install_id, scope=scope,
                   scopeDir=str(scope_dir), scopeIdentity=identity, slug=slug, target=str(target),
                   oldSource=str(old_source), newSource=str(new_source),
                   beforeRecord=before_record, afterRecord=after_record,
                   beforeTree=_tree(target), afterTree=_tree(new_source),
                   configFile=str(config_file) if config_file else None,
                   beforeConfig=hashlib.sha256(config_before).hexdigest() if config_before is not None else None,
                   afterConfig=config_after_hash, created=time.time())
    journal['digest'] = _digest(journal)
    path = no_links(state / 'transactions' / (transaction_id + '.json'))
    atomic_json(path, journal)
    return path


def finish(path):
    try:
        no_links(path).unlink(missing_ok=True)
    except OSError:
        # Exact committed state is recognized on the next read; no replay.
        pass


def _validate(installer, path, journal):
    raw = dict(journal); signature = raw.pop('digest', None)
    if signature != _digest(raw) or journal.get('schemaVersion') != 1:
        raise SquareError('중단된 설치 기록의 무결성을 확인하지 못했습니다.')
    tid = journal['id']
    if (not isinstance(tid, str) or not re.fullmatch('[a-f0-9]{32}', tid)
            or path.name != tid + '.json' or journal['operation'] not in {'install', 'rollback'}):
        raise SquareError('중단된 설치 기록의 경로를 확인하지 못했습니다.')
    scope = no_links(journal['scopeDir'])
    if journal.get('scopeIdentity') is not None:
        from .install import check_directory_identity
        check_directory_identity(scope, journal['scopeIdentity'])
    if journal['scope'] not in {'project', 'user'} or scope == Path(scope.anchor):
        raise SquareError('중단된 설치 범위를 확인하지 못했습니다.')
    if journal['scope'] == 'user' and scope != installer.home:
        raise SquareError('다른 사용자 범위의 설치 복구는 수행하지 않습니다.')
    slug = journal['slug']
    if not isinstance(slug, str) or not re.fullmatch('[a-z][a-z0-9-]{1,63}', slug):
        raise SquareError('중단된 설치 이름을 확인하지 못했습니다.')
    target = no_links(journal['target'])
    if target not in {scope / '.claude' / 'skills' / slug, scope / '.pt-ai-square' / 'tools' / slug}:
        raise SquareError('중단된 설치 대상이 변경되었습니다.')
    record = journal.get('afterRecord') or journal.get('beforeRecord')
    if (not isinstance(record, dict) or record.get('origin') != installer.settings.url
            or journal['installId'] != installer._identity(record['toolId'], record['host'], journal['scope'], scope)):
        raise SquareError('중단된 설치의 소유 기록을 확인하지 못했습니다.')
    for name, checksum in [('beforeRecord', 'beforeTree'), ('afterRecord', 'afterTree')]:
        entry = journal.get(name)
        if entry is not None and (entry.get('target') != str(target)
                                  or name == 'afterRecord' and entry.get('treeHash') != journal[checksum]):
            raise SquareError('중단된 설치 파일 기록이 일치하지 않습니다.')
    config = no_links(journal['configFile']) if journal.get('configFile') else None
    if config is not None and config != scope / ('.mcp.json' if journal['scope'] == 'project' else '.claude.json'):
        raise SquareError('중단된 설치의 설정 위치가 변경되었습니다.')
    state = no_links(installer.settings.state)
    old_source, new_source = no_links(journal['oldSource']), no_links(journal['newSource'])
    if journal['operation'] == 'install':
        if old_source != state/'backups'/tid/'files' or new_source != state/'staging'/tid:
            raise SquareError('설치 보관본 위치가 변경되었습니다.')
    elif (old_source != target.with_name('.pt-square-rollback-' + tid)
          or new_source != no_links(Path(journal['beforeRecord']['backup'])/'files')
          or state/'backups' not in new_source.parents):
        raise SquareError('복구 보관본 위치가 변경되었습니다.')
    return target, config, old_source, new_source, state/'transactions-data'/tid


def recover(installer, *, prefer_restore=False):
    result = {'recovered': [], 'blocked': []}
    directory = no_links(installer.settings.state/'transactions')
    if not directory.exists():
        return result
    paths = sorted(itertools.islice(directory.glob('*.json'), 65))
    if len(paths) > 64:
        return {'recovered': [], 'blocked': [{'message': '중단된 설치 기록이 많습니다. 보관 기록을 먼저 확인해 주세요.'}]}
    for path in paths:
        journal = {}
        try:
            journal = read_json(path)
            if not isinstance(journal.get('origin'), str) or not journal.get('origin'):
                raise SquareError('중단된 설치의 연결 출처를 확인하지 못했습니다.')
            if journal['origin'] != installer.settings.url:
                continue
            target, config, old_source, new_source, recovery_dir = _validate(installer, path, journal)
            records = installer.records()
            current_record = records.get(journal['installId'])
            before, after = journal['beforeRecord'], journal['afterRecord']
            if current_record != before and current_record != after:
                raise SquareError('다른 설치 기록이 반영되었습니다. 자동으로 변경하지 않았습니다.')
            tree, config_hash = _tree(target), _file(config)
            if (tree == journal['afterTree'] and config_hash == journal['afterConfig']
                    and not (prefer_restore and current_record == before and current_record != after)):
                # The approved mutation already finished. Confirm only the record.
                if current_record != after:
                    if after is None:
                        records.pop(journal['installId'], None)
                    else:
                        records[journal['installId']] = after
                    atomic_json(installer.record_path, records)
                outcome = 'completed'
            else:
                if current_record != before:
                    raise SquareError('완료 기록과 파일 상태가 다릅니다. 변경 내용을 먼저 확인해 주세요.')
                if tree not in {None, journal['beforeTree'], journal['afterTree']}:
                    raise SquareError('설치 파일이 추가로 변경되었습니다. 사용자 변경을 보존하기 위해 자동 복구하지 않았습니다.')
                if config_hash not in {journal['beforeConfig'], journal['afterConfig']}:
                    raise SquareError('연결 설정이 추가로 변경되었습니다. 사용자 설정은 그대로 보존했습니다.')
                if journal['beforeTree'] is not None and tree != journal['beforeTree'] and _tree(old_source) != journal['beforeTree']:
                    raise SquareError('이전 파일 보관본을 확인하지 못했습니다. 현재 파일은 그대로 보존했습니다.')
                original = None
                if config_hash != journal['beforeConfig'] and journal['beforeConfig'] is not None:
                    saved = no_links(recovery_dir/'config.before')
                    if _file(saved) != journal['beforeConfig']:
                        raise SquareError('이전 설정 보관본을 확인하지 못했습니다. 현재 설정은 그대로 보존했습니다.')
                    original = saved.read_bytes()
                # Recheck each target immediately before changing it. Never replay
                # package extraction or a command, and retain displaced bytes.
                if tree != journal['beforeTree']:
                    if tree is not None:
                        if _tree(target) != tree:
                            raise SquareError('복구 중 설치 파일이 변경되었습니다.')
                        destination = new_source if not new_source.exists() else no_links(recovery_dir/'displaced')
                        if destination.exists():
                            raise SquareError('복구 보관 위치를 먼저 확인해 주세요.')
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        target.rename(destination)
                    if journal['beforeTree'] is not None:
                        if _tree(old_source) != journal['beforeTree']:
                            raise SquareError('복구 중 이전 파일이 변경되었습니다.')
                        target.parent.mkdir(parents=True, exist_ok=True)
                        old_source.rename(target)
                if config_hash != journal['beforeConfig']:
                    if _file(config) != config_hash:
                        raise SquareError('복구 중 연결 설정이 변경되었습니다.')
                    if original is None:
                        no_links(config).unlink()
                    else:
                        _bytes(config, original)
                if _tree(target) != journal['beforeTree'] or _file(config) != journal['beforeConfig']:
                    raise SquareError('설치 복구 결과를 확인하지 못했습니다.')
                outcome = 'restored'
            finish(path)
            record = after if outcome == 'completed' else before
            result['recovered'].append(dict(transactionId=journal['id'], toolId=(after or before)['toolId'],
                                            release=record.get('release') if record else None, outcome=outcome))
        except (SquareError, OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            report_record = journal.get('afterRecord') or journal.get('beforeRecord') or {}
            if not isinstance(report_record, dict):
                report_record = {}
            result['blocked'].append(dict(transactionId=journal.get('id', path.stem),
                toolId=report_record.get('toolId'),
                target=journal.get('target', ''), backup=journal.get('oldSource', ''),
                message=str(error) if isinstance(error, SquareError) else '중단된 설치를 확인하지 못했습니다. 파일과 보관본을 먼저 확인해 주세요.'))
    return result
