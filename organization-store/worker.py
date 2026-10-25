"""Optional AI store worker: one bounded stdio request, no background service.

Development imports the platform's canonical installer; the extension builder
vendors those exact sources into vendor/. Personal KEYs never enter host state.
"""
from __future__ import annotations

import json
import importlib.util
import re
import sys
import time
import uuid
import hashlib
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request

HERE = Path(__file__).resolve().parent


def import_root(path):
    # Windows Python's module discovery may still apply MAX_PATH even when
    # ordinary pathlib reads succeed. Versioned extension packages can exceed
    # it under long user/state folders; keep the full verified package path.
    value = str(path)
    if sys.platform == 'win32' and not value.startswith('\\\\?\\'):
        value = '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    return Path(value)


PACKAGE_ROOT = import_root(HERE / 'vendor')
if not (PACKAGE_ROOT / 'pt_square_mcp' / 'config.py').is_file():
    PACKAGE_ROOT = import_root(HERE.parent / 'pt_ai_square' / 'integrations' / 'pt-square-mcp')
sys.path.insert(0, str(PACKAGE_ROOT))

from pt_square_mcp.client import Client, positive
from pt_square_mcp.config import (DEFAULT_CONFIG, Settings, SquareError, TOKEN_RE,
                                 atomic_json, no_links, normalize_url, operation_lock,
                                 read_json, save_config)
from pt_square_mcp.install import Installer, tree_digest, check_directory_identity, digest
from pt_square_mcp.profiles import validate_profile
from pt_square_mcp.runtime import Runtime
from pt_square_mcp.files import validate_publish_archive, sha256, SECRET_PATTERN
from pt_square_mcp._vendor.package_contract import read_package, registration_fields

# -I excludes the script directory from module search. Load only this verified
# extension's adjacent helper, never a same-named module in the user's folder.
_zip_spec = importlib.util.spec_from_file_location('ax_store_zip_install', import_root(HERE / 'zip_install.py'))
zip_install = importlib.util.module_from_spec(_zip_spec)
_zip_spec.loader.exec_module(zip_install)

VERSION = '0.1.0'
ACTIONS = frozenset({'status', 'connect', 'disconnect', 'options', 'catalog', 'detail',
                     'like', 'download', 'prepareInstall', 'install', 'installations',
                     'checkUpdates', 'verify', 'rollback', 'publishOptions',
                     'inspectPublishSource', 'preparePublish', 'publishStatus', 'publish'})
PUBLISH_FIELDS = frozenset({'name', 'desc', 'owner', 'platform', 'type', 'guide', 'orgId',
                           'categoryId', 'approval', 'workTags', 'environment', 'changes',
                           'mode', 'url', 'commandProject', 'commandUser', 'packageId',
                           'workflow', 'installProfile'})
MAX_PUBLISH_BYTES = 64 * 1024 * 1024
PUBLISH_SUFFIXES = {'.zip', '.md', '.axextension', '.exe', '.msi', '.ps1'}
MAX_INPUT = 128 * 1024
MAX_OUTPUT = 2 * 1024 * 1024
MANUAL_NOTICE = '이 항목은 파일을 내려받은 뒤 웹의 설치 안내에 따라 직접 설치하세요. 다운로드만으로 설치되지는 않습니다.'
INSTALL_METADATA_NOTICE = '등록자가 앱 설치 정보(지원 범위·설치 방식)를 등록해야 앱에서 바로 설치할 수 있어요. 현재는 파일 다운로드와 등록자의 설치 안내를 이용해 주세요.'


class StoreClient(Client):
    """Narrow web accounting mutations; no arbitrary remote writes or commands."""
    def open(self, path, method='GET', body=None, content_type=None):
        view = method == 'POST' and isinstance(path, str) and re.fullmatch(r'/api/tools/[1-9][0-9]*/view', path)
        if method != 'PUT' and not view:
            return super().open(path, method, body, content_type)
        if not view and (not isinstance(path, str) or not re.fullmatch(r'/api/tools/[1-9][0-9]*/like', path)):
            raise SquareError('허용되지 않은 API 작업입니다.')
        try:
            data = json.loads(body)
        except (ValueError, TypeError, UnicodeError):
            raise SquareError('플랫폼 활동 요청을 확인하세요.') from None
        if not isinstance(data, dict) or (data != {} if view else set(data) != {'liked'} or type(data['liked']) is not bool):
            raise SquareError('플랫폼 활동 요청을 확인하세요.')
        headers = {'Authorization': 'Bearer ' + self.settings.token(),
                   'Accept': 'application/json', 'Content-Type': 'application/json',
                   'User-Agent': 'AX-Organization-Store/1'}
        try:
            # Optional accounting must not keep the already fetched detail
            # screen waiting for the normal mutation/network timeout.
            return self.opener.open(Request(self.url + path, body, headers, method=method), timeout=2 if view else 30)
        except HTTPError as error:
            messages = {401: 'KEY가 취소·재발급되었습니다. 웹에서 KEY를 확인한 뒤 다시 연결하세요.',
                        403: '이 도구의 조회 권한 또는 서버의 확장 연동 지원 여부를 확인하세요.',
                        404: '항목을 찾을 수 없습니다.', 429: '잠시 후 다시 시도하세요.'}
            raise SquareError(messages.get(error.code, '플랫폼 활동 상태를 저장하지 못했습니다. 목록을 다시 확인하세요.')) from None
        except (URLError, OSError, TimeoutError):
            raise SquareError('서버에 연결하지 못했습니다. 주소·사내망·인증서를 확인하세요.') from None


class Store:
    def __init__(self, directory, context=None, *, home=None, existing_config=None,
                 client_factory=StoreClient, package_directory=None):
        if not isinstance(directory, (str, Path)) or not Path(directory).is_absolute():
            raise SquareError('확장 저장 위치를 확인하세요.')
        self.directory = no_links(directory)
        if self.directory == Path(self.directory.anchor):
            raise SquareError('드라이브 전체를 확장 저장 위치로 사용할 수 없습니다.')
        self.directory.mkdir(parents=True, exist_ok=True)
        self.context = context if isinstance(context, dict) else {}
        self.home = no_links(home or Path.home())
        self.existing_config = no_links(existing_config or DEFAULT_CONFIG)
        self.client_factory = client_factory
        self.package_directory = Path(package_directory) if package_directory is not None else HERE
        self.selection_path = self.directory / 'connection-selection.json'
        self.config_path = self.directory / 'connection' / 'config.json'

    def preset_url(self):
        # The installer imports only the public origin. Never read credentials,
        # HTTP consent, or user settings from a downloaded connection manifest.
        primary = self.directory / 'connection.json'
        path = no_links(primary if primary.exists() else self.package_directory / 'connection.json')
        if not path.exists():
            return ''
        try:
            if not path.is_file() or path.stat().st_size > 4096:
                raise ValueError('Invalid preset')
            value = read_json(path)
            if (set(value) != {'schemaVersion', 'baseUrl'}
                    or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1):
                raise ValueError('Invalid preset')
            return normalize_url(value['baseUrl'])
        except (SquareError, OSError, ValueError):
            raise SquareError('설치 파일의 서버 주소를 읽지 못했습니다. 플랫폼에서 확장을 다시 받거나 서버 주소를 직접 입력하세요.') from None

    def selection(self):
        return read_json(self.selection_path) if self.selection_path.exists() else {'mode': 'disconnected'}

    def settings(self):
        mode = self.selection().get('mode')
        if mode not in {'local', 'existing'}:
            raise SquareError('먼저 웹에서 발급한 개인 KEY로 스토어를 연결하세요.')
        return Settings(self.existing_config if mode == 'existing' else self.config_path)

    def status(self):
        mode = self.selection().get('mode', 'disconnected')
        result = dict(configured=False, connectionMode=mode, baseUrl='', storeVersion=VERSION,
                      existingConnectionAvailable=self.existing_config.is_file(),
                      workspace=self.context.get('workspace'))
        try:
            result['presetBaseUrl'] = self.preset_url()
        except (SquareError, OSError):
            result['presetBaseUrl'] = ''
            result['presetMessage'] = '설치 파일의 서버 주소를 읽지 못했습니다. 플랫폼에서 확장을 다시 받거나 서버 주소를 직접 입력하세요.'
        if mode in {'local', 'existing'}:
            try:
                settings = self.settings()
                result.update(configured=True, baseUrl=settings.url,
                              encryptedTransport=settings.url.startswith('https:'),
                              downloadDirectory=str(settings.downloads))
            except (SquareError, OSError):
                result['message'] = '저장된 연결 설정을 읽지 못했습니다. 다시 연결해 주세요.'
        return result

    def connect(self, payload):
        with operation_lock(self.directory / 'connection-lock'):
            previous_credential = None
            if payload.get('reuseExisting') is True:
                settings = Settings(self.existing_config)
                identity = self.client_factory(settings).json('/api/integration/me')
                mode = 'existing'
            else:
                candidate = payload.get('url')
                if candidate is None:
                    # Reinstalling from another server must never silently move
                    # a saved connection or send its credential to that origin.
                    candidate = self.settings().url if self.selection().get('mode') in {'local', 'existing'} else self.preset_url()
                url = normalize_url(candidate)
                token = payload.get('key')
                if not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
                    raise SquareError('웹에서 발급한 연결 KEY를 입력하세요.')
                accepted = payload.get('allowHttp') is True
                if url.startswith('http:') and not accepted:
                    raise SquareError('사내 HTTP 주소는 KEY 전송이 암호화되지 않습니다. 해당 주소의 HTTP 연결을 확인하세요.')
                # Validate before replacing a working connection or storing a KEY.
                probe = SimpleNamespace(url=url, token=lambda: token)
                identity = self.client_factory(probe).json('/api/integration/me')
                downloads = no_links(self.directory / 'downloads')
                downloads.mkdir(parents=True, exist_ok=True)
                if self.config_path.is_file():
                    try:
                        old_ref = read_json(self.config_path).get('credentialRef', '')
                    except (SquareError, OSError, ValueError):
                        old_ref = ''  # A new valid connection may repair broken local metadata.
                    if re.fullmatch(r'windows-dpapi:credential\.[a-f0-9]{32}\.dpapi\.json', old_ref):
                        previous_credential = no_links(self.config_path.parent / old_ref.split(':', 1)[1])
                save_config(self.config_path, url, [self.directory], token, accepted,
                            download_directory=downloads,
                            credential_name='credential.' + uuid.uuid4().hex + '.dpapi.json')
                mode = 'local'
            atomic_json(self.selection_path, {'mode': mode})
            if previous_credential is not None:
                try:
                    previous_credential.unlink(missing_ok=True)
                except OSError:
                    pass
        return dict(self.status(), user=identity.get('user', {}), capabilities=identity.get('capabilities', {}))

    def project(self):
        raw = self.context.get('workspace')
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            raise SquareError('현재 업무의 폴더를 먼저 선택해 주세요. 일반 대화에서는 내 계정 범위를 사용하세요.')
        path = no_links(raw)
        if not path.is_dir() or path == Path(path.anchor):
            raise SquareError('현재 업무 폴더를 확인하세요. 드라이브 전체는 설치 범위로 사용할 수 없습니다.')
        return path

    def selected_directory(self):
        # Caller payload paths/tokens never authorize a filesystem location.
        # The common host alone adds this context after its native picker.
        raw, token = self.context.get('selectedDirectory'), self.context.get('directoryToken')
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            raise SquareError('설치할 폴더를 선택 창에서 다시 선택해 주세요.')
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            raise SquareError('설치할 폴더를 선택 창에서 다시 선택해 주세요.')
        path = no_links(raw)
        if not path.is_dir() or path == Path(path.anchor):
            raise SquareError('드라이브 전체 대신 설치할 폴더를 선택해 주세요.')
        check_directory_identity(path, self.context.get('selectedDirectoryIdentity'))
        return path

    @staticmethod
    def install_support(manifest):
        suffix = Path(str(manifest.get('filename', ''))).suffix.lower()
        if suffix == '.axextension':
            return False, 'AX Workspace 확장 파일입니다. 파일을 다운로드한 뒤 더블클릭해 설치하세요.'
        if suffix in {'.exe', '.msi', '.ps1'}:
            return False, '별도 설치 프로그램입니다. 파일을 내려받아 실행하고 등록자의 안내에 따라 설치하세요. 이 화면에서는 자동 실행하지 않습니다.'
        try:
            profile = validate_profile(manifest.get('installProfile'))
        except SquareError:
            return False, INSTALL_METADATA_NOTICE
        if profile is None:
            return False, INSTALL_METADATA_NOTICE
        can = bool(profile.get('kind') in {'skill', 'mcp'}
                   and profile.get('host') == 'claude' and manifest.get('downloadUrl'))
        return can, ('설치 범위를 선택하면 변경할 파일과 경로를 먼저 확인할 수 있습니다.' if can else MANUAL_NOTICE)

    def records(self, runtime):
        return {key: record for key, record in runtime.installer.records().items()
                if record.get('origin') == runtime.settings.url}

    def receipt_path(self, plan_id):
        if not isinstance(plan_id, str) or not re.fullmatch('[0-9a-f]{32}', plan_id):
            raise SquareError('설치 준비안을 다시 확인하세요.')
        return no_links(self.directory / 'store-plans' / (plan_id + '.json'))

    def prepare(self, runtime, payload):
        tool_id = positive(payload.get('toolId'))
        manifest = runtime.client.manifest(tool_id)
        supported, notice = self.install_support(manifest)
        inspect_zip = zip_install.can_inspect(manifest)
        if not supported and not inspect_zip:
            return dict(canInstall=False, installed=False, toolId=tool_id, reason=notice)
        scope = payload.get('scope')
        if scope not in {'project', 'directory', 'user'}:
            raise SquareError('전체 공간(내 계정), 현재 업무 폴더 또는 다른 폴더 중 설치 범위를 선택하세요.')
        workspace = self.selected_directory() if scope == 'directory' else self.project() if scope == 'project' else None
        if workspace is not None:
            runtime.settings.roots = [*runtime.settings.roots, workspace]
        if inspect_zip:
            update = any(record.get('toolId') == tool_id for record in self.records(runtime).values())
            runtime.installer.client = zip_install.ZipSkillClient(runtime.client, runtime.settings, digest(manifest), update=update)
        try:
            plan = runtime.installer.prepare(tool_id, 'project' if scope == 'directory' else scope, str(workspace or ''))
        except zip_install.ZipInstallUnsupported as error:
            return dict(canInstall=False, installed=False, toolId=tool_id, reason=str(error))
        if scope == 'directory':
            self.selected_directory()
        if plan.get('canInstall'):
            prepared = read_json(runtime.settings.state / 'plans' / (plan['planId'] + '.json'))
            if not self.install_support(prepared['manifest'])[0]:
                return dict(canInstall=False, installed=False, toolId=tool_id, reason=MANUAL_NOTICE)
            atomic_json(self.receipt_path(plan['planId']), {
                'origin': runtime.settings.url, 'config': str(runtime.settings.path),
                'scope': scope, 'scopeDir': plan['scopeDir'], 'created': time.time(),
                'directoryToken': self.context.get('directoryToken') if scope == 'directory' else None,
                'zipDetection': prepared['manifest'].get(zip_install.DETECTION_KEY) if inspect_zip else None,
                'approvalDigest': plan['approvalDigest']})
            if inspect_zip:
                plan['detectionNotice'] = zip_install.DETECTED_NOTICE
        return plan

    def install(self, runtime, payload):
        if payload.get('confirmed') is not True:
            raise SquareError('설치 범위와 변경 내용을 확인한 뒤 설치하세요.')
        path = self.receipt_path(payload.get('planId'))
        receipt = read_json(path)
        if (receipt.get('origin') != runtime.settings.url
                or receipt.get('config') != str(runtime.settings.path)
                or receipt.get('approvalDigest') != payload.get('approvalDigest')
                or time.time() - receipt.get('created', 0) > 3600):
            raise SquareError('연결 또는 설치 준비안이 변경되었습니다. 설치를 다시 준비하세요.')
        if receipt['scope'] in {'project', 'directory'}:
            if receipt['scope'] == 'directory' and receipt.get('directoryToken') != self.context.get('directoryToken'):
                raise SquareError('설치할 폴더 선택이 변경되었습니다. 설치 내용을 다시 확인해 주세요.')
            workspace = self.selected_directory() if receipt['scope'] == 'directory' else self.project()
            if str(workspace) != receipt['scopeDir']:
                raise SquareError('설치를 준비한 업무 폴더와 현재 업무 폴더가 다릅니다. 다시 준비하세요.')
            runtime.settings.roots = [*runtime.settings.roots, workspace]
        plan = read_json(runtime.settings.state / 'plans' / (payload['planId'] + '.json'))
        detection = receipt.get('zipDetection')
        if detection is not None:
            if (not isinstance(detection, dict) or detection != plan['manifest'].get(zip_install.DETECTION_KEY)
                    or not isinstance(detection.get('sourceManifestDigest'), str)
                    or not re.fullmatch('[0-9a-f]{64}', detection['sourceManifestDigest'])):
                raise SquareError('ZIP 설치 준비 내용이 변경되었습니다. 다시 확인해 주세요.')
            runtime.installer.client = zip_install.ZipSkillClient(runtime.client, runtime.settings,
                                                                detection['sourceManifestDigest'],
                                                                update=bool(plan.get('existingRecordDigest')))
        supported, _ = self.install_support(plan['manifest'])
        if not supported or plan.get('profile', {}).get('kind') not in {'skill', 'mcp'}:
            raise SquareError(MANUAL_NOTICE)
        result = runtime.installer.install(payload['planId'], payload.get('approvalDigest'), True)
        # The canonical engine consumes the plan after durable commit; a failed
        # cosmetic receipt cleanup must never turn a completed install into error.
        try:
            path.unlink()
        except OSError:
            pass
        return result

    @staticmethod
    def publish_identity(runtime, required=True):
        identity = runtime.client.json('/api/integration/me')
        capable = identity.get('capabilities', {}).get('publishDraft') is True
        user, key = identity.get('user') or {}, identity.get('key') or {}
        if required and (not capable or not isinstance(user.get('id'), str)
                         or not isinstance(key.get('id'), str) or not key['id']):
            raise SquareError('웹의 KEY 화면에서 업로드 포함 권한을 확인하고 해당 KEY로 연결하세요.')
        return identity, {'origin': runtime.settings.url, 'config': str(runtime.settings.path),
                          'userId': user.get('id'), 'keyId': key.get('id')}

    def publish_options(self, runtime, payload):
        identity, _ = self.publish_identity(runtime, required=False)
        query = payload.get('q', '')
        if not isinstance(query, str) or len(query) > 200:
            raise SquareError('기존 도구 검색어는 200자 이내로 입력하세요.')
        can_publish = identity.get('capabilities', {}).get('publishDraft') is True
        result = dict(canPublish=can_publish, user=identity.get('user', {}),
                      options=runtime.client.json('/api/catalog/options'),
                      candidates=runtime.client.json('/api/publish-targets?' + urlencode({'q': query})).get('items', []) if can_publish else [],
                      keyGuideUrl=runtime.settings.url + '/local-access')
        if payload.get('toolId') is not None:
            self.publish_identity(runtime)
            item = runtime.get_item(positive(payload['toolId']))
            if item.get('ownerId') != identity.get('user', {}).get('id'):
                raise SquareError('본인이 등록한 도구만 새 버전으로 등록할 수 있습니다.')
            metadata = {key: item[key] for key in PUBLISH_FIELDS if key in item}
            current = next((row for row in item.get('versions', []) if row.get('n') == item.get('active')), {})
            metadata['installProfile'] = current.get('installProfile')
            metadata['mode'] = {'zip': 'file', 'server': 'url', 'command': 'command'}.get(item.get('mode'), 'file')
            commands = current.get('commands') or {}
            metadata.update(commandProject=commands.get('project', ''), commandUser=commands.get('user', ''))
            result['existing'] = dict(toolId=item['id'], revision=item.get('revision'), metadata=metadata)
        return result

    def selected_file(self):
        # Only the common host may grant a native file picker selection. A path
        # or token in the iframe's payload is never a filesystem capability.
        raw = self.context.get('selectedFile')
        identity = self.context.get('selectedFileIdentity')
        if (not isinstance(raw, str) or not Path(raw).is_absolute()
                or not isinstance(identity, list) or len(identity) != 4
                or any(type(part) is not int for part in identity)):
            raise SquareError('등록할 배포 파일을 선택 창에서 다시 선택하세요.')
        path = no_links(raw)
        info = path.stat()
        if (not path.is_file() or path.suffix.lower() not in PUBLISH_SUFFIXES
                or not 0 < info.st_size <= MAX_PUBLISH_BYTES
                or [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns] != identity):
            raise SquareError('선택한 파일이 변경되었거나 지원 범위를 벗어났습니다. 64 MiB 이하의 배포 파일을 다시 선택하세요.')
        return path

    @staticmethod
    def scan_publish_file(path, destination=None):
        """Bounded streaming scan also covers large single MD/PS1/binary files."""
        hasher, total, previous = hashlib.sha256(), 0, b''
        with path.open('rb') as original:
            while chunk := original.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_PUBLISH_BYTES:
                    raise SquareError('등록 파일은 64 MiB 이하여야 합니다.')
                content = previous + chunk
                if SECRET_PATTERN.search(content):
                    raise SquareError('파일에 인증정보로 보이는 내용이 있습니다. 배포에서 제거하세요.')
                previous = content[-4096:]
                hasher.update(chunk)
                if destination is not None:
                    destination.write(chunk)
        return hasher.hexdigest()

    def inspect_publish_source(self, runtime, payload):
        self.publish_identity(runtime)
        path = self.selected_file()
        # Canonical inspection rejects credential/private configuration names.
        runtime.settings.roots = [path]
        source = runtime.inspect_source(str(path))
        metadata, warning = {}, ''
        if path.suffix.lower() in {'.zip', '.axextension'}:
            try:
                with zipfile.ZipFile(path) as archive:
                    validate_publish_archive(archive)
                    try:
                        declaration = read_package(archive)
                    except ValueError as error:
                        declaration, warning = None, str(error)
                    if declaration:
                        metadata = dict(registration_fields(declaration), packageId=declaration['packageId'])
            except zipfile.BadZipFile:
                raise SquareError('ZIP 파일 형식을 읽지 못했습니다. 올바른 배포 ZIP을 선택하세요.') from None
        elif path.suffix.lower() == '.md':
            # A single MD is not rewritten into a ZIP; do not infer compatibility.
            metadata['type'] = 'Skill'
        file_hash = self.scan_publish_file(path)
        self.selected_file()
        query = {'packageId': metadata['packageId']} if metadata.get('packageId') else {'q': metadata.get('name', '')}
        candidates = runtime.client.json('/api/publish-targets?' + urlencode(query)).get('items', [])
        return dict(source=dict(name=path.name, bytes=path.stat().st_size, sha256=file_hash),
                    metadata=metadata, packageWarning=warning, options=source['options'], candidates=candidates)

    def publish_receipt(self, draft_id):
        Runtime._draft_id(draft_id)
        return no_links(self.directory / 'store-publish' / 'drafts' / (draft_id + '.json'))

    @staticmethod
    def publish_result(runtime, result):
        result = dict(result)
        draft_id = Runtime._draft_id(result.get('id'))
        # The external link is reconstructed from a validated draft ID + the
        # configured origin, never trusted from arbitrary server response data.
        result['reviewUrl'] = runtime.settings.url + '/publish-review/' + draft_id
        result.pop('preparedFile', None)
        result.pop('localPreparationId', None)
        return result

    def prepare_publish(self, runtime, payload):
        _, identity = self.publish_identity(runtime)
        metadata = payload.get('metadata')
        if not isinstance(metadata, dict) or set(metadata) - PUBLISH_FIELDS:
            raise SquareError('지원하는 등록 정보만 입력하세요.')
        values = dict(metadata)
        target = payload.get('target')
        if target not in {'new', 'update'}:
            raise SquareError('새 도구 등록 또는 기존 도구 새 버전을 직접 선택하세요.')
        tool_id = payload.get('toolId')
        if target == 'update':
            positive(tool_id)
        elif tool_id is not None:
            raise SquareError('새 도구에는 기존 도구 ID를 지정하지 않습니다.')
        if type(values.get('approval')) is not bool:
            raise SquareError('전체 사용자가 상세 조회 가능 또는 조회 승인 필요를 선택하세요.')
        mode = values.get('mode')
        if mode not in {'file', 'url', 'command'}:
            raise SquareError('파일·URL·명령어 중 등록 방식을 선택하세요.')
        path = self.selected_file() if mode == 'file' else None
        source_hash = sha256(path) if path else None
        if path:
            self.selected_file()
        binding = digest(dict(identity=identity, target=target, toolId=tool_id,
                              metadata=values, sourceSha256=source_hash))
        request_id = payload.get('requestId')
        if request_id is None:
            request_id = str(uuid.uuid5(uuid.NAMESPACE_URL, binding))
        try:
            request_id = str(uuid.UUID(request_id))
        except (ValueError, TypeError, AttributeError):
            raise SquareError('등록 준비 요청 번호를 확인하세요.') from None
        request_path = no_links(self.directory / 'store-publish' / 'requests' / (request_id + '.json'))
        with operation_lock(self.directory / 'store-publish'):
            request_record = read_json(request_path) if request_path.exists() else None
            if request_record:
                if request_record.get('binding') != binding or time.time() - request_record.get('created', 0) > 86400:
                    raise SquareError('등록 내용이나 연결이 변경되었거나 확인 기간이 지났습니다. 새 등록 준비를 시작하세요.')
                if request_record.get('draftId'):
                    return self.publish_result(runtime, runtime.get_publish_status(request_record['draftId']))
            else:
                request_record = dict(binding=binding, created=time.time())
                atomic_json(request_path, request_record)
            values['clientRequestId'] = request_id
            # Snapshot only the selected file into a private temporary folder.
            # Canonical packaging revalidates it; no installed files/config are
            # changed and no original artifact or executable is ever run.
            staging_root = no_links(self.directory / 'publish-staging')
            staging_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='request-', dir=staging_root) as staging:
                staging = no_links(staging)
                snapshot = None
                if path:
                    snapshot = staging / path.name
                    self.selected_file()
                    with snapshot.open('xb') as destination:
                        copied_hash = self.scan_publish_file(path, destination)
                    self.selected_file()
                    if copied_hash != source_hash:
                        raise SquareError('등록 자료가 바뀌었습니다. 파일을 다시 선택하세요.')
                runtime.settings.roots = [staging]
                runtime.settings.state = staging / 'state'
                result = runtime.prepare_publish(values, str(snapshot or ''), target=target, tool_id=tool_id)
            if result.get('ready') is False:
                return result
            result = self.publish_result(runtime, result)
            result['notice'] = ('웹 검토 화면에서 파일·등록 내용·공개 범위를 확인하고 승인하세요. '
                                '앱으로 돌아와 등록 완료를 누르면 동일한 초안으로 게시합니다.')
            draft_id = result['id']
            atomic_json(self.publish_receipt(draft_id), dict(identity, created=time.time(), requestId=request_id))
            atomic_json(request_path, dict(request_record, draftId=draft_id))
            return result

    def publish_status_or_commit(self, runtime, payload, *, commit=False):
        _, identity = self.publish_identity(runtime)
        draft_id = payload.get('draftId')
        receipt = read_json(self.publish_receipt(draft_id))
        if any(receipt.get(key) != value for key, value in identity.items()):
            raise SquareError('이 앱에서 현재 연결로 준비한 등록 초안만 사용할 수 있습니다. 다시 준비하세요.')
        status = self.publish_result(runtime, runtime.get_publish_status(draft_id))
        if not commit:
            return status
        if status.get('status') not in {'approved', 'committing', 'committed'}:
            return dict(status, published=False, notice='웹 검토 화면에서 승인한 뒤 등록 완료를 눌러 주세요.')
        # The server independently checks owner, KEY, digest, revision and human
        # browser approval. Client booleans cannot grant or substitute approval.
        result = runtime.publish_item(draft_id)
        return dict(result, published=True, status='committed')

    def dispatch(self, action, payload=None):
        if action not in ACTIONS or not isinstance(payload, (dict, type(None))):
            raise SquareError('지원하지 않는 스토어 요청입니다.')
        payload = payload or {}
        if action == 'status':
            return self.status()
        if action == 'connect':
            return self.connect(payload)
        if action == 'disconnect':
            with operation_lock(self.directory / 'connection-lock'):
                atomic_json(self.selection_path, {'mode': 'disconnected'})
            return dict(self.status(), notice='스토어 연결만 해제했습니다. 기존 MCP 연결·KEY·설치 파일은 유지됩니다.')
        settings = self.settings()
        client = self.client_factory(settings)
        runtime = Runtime(settings, client=client, home=self.home)
        if action == 'publishOptions':
            return self.publish_options(runtime, payload)
        if action == 'inspectPublishSource':
            return self.inspect_publish_source(runtime, payload)
        if action == 'preparePublish':
            return self.prepare_publish(runtime, payload)
        if action in {'publishStatus', 'publish'}:
            return self.publish_status_or_commit(runtime, payload, commit=action == 'publish')
        if action == 'options':
            return client.json('/api/catalog/options')
        if action == 'catalog':
            fields = ('q', 'type', 'sort', 'orgId', 'platform')
            if any(key in payload and not isinstance(payload[key], str) for key in fields):
                raise SquareError('검색 조건을 확인하세요.')
            return runtime.search_items(payload.get('q', ''), payload.get('type', ''),
                                        payload.get('sort', 'recommended'), payload.get('orgId', ''),
                                        payload.get('platform', ''), payload.get('offset', 0), payload.get('limit', 20))
        if action == 'detail':
            tool_id = positive(payload.get('toolId'))
            item, manifest = runtime.get_item(tool_id), client.manifest(tool_id)
            # Only an explicit popup opening counts. GET/refresh/prepare stay
            # read-only; the shared server deduplicates web + extension views.
            if payload.get('recordView') is True:
                try:
                    viewed = client.json(f'/api/tools/{tool_id}/view', 'POST', {})
                    if type(viewed.get('views')) is int:
                        item['views'] = viewed['views']
                except SquareError:
                    pass  # Older servers or accounting errors cannot hide details.
            supported, notice = self.install_support(manifest)
            inspect_zip = zip_install.can_inspect(manifest)
            return dict(item=item, manifest=manifest, canInstall=supported, installNotice=notice,
                        canInspectInstall=inspect_zip,
                        inspectionNotice=zip_install.INSPECTION_NOTICE if inspect_zip else None,
                        webUrl=settings.url + '/')
        if action == 'like':
            if type(payload.get('liked')) is not bool:
                raise SquareError('좋아요 상태를 확인하세요.')
            return client.json(f'/api/tools/{positive(payload.get("toolId"))}/like', 'PUT', {'liked': payload['liked']})
        # Share exactly the canonical MCP lock and installation records. UI reads
        # never hold this lock while searching; local mutations cannot overlap.
        with operation_lock(settings.state):
            if action == 'prepareInstall':
                return self.prepare(runtime, payload)
            if action == 'install':
                return self.install(runtime, payload)
            recovery = runtime.installer.recover()
            records = self.records(runtime)
            if action == 'download':
                tool_id = positive(payload.get('toolId'))
                update = any(r.get('toolId') == tool_id and r.get('status') in {'installed', 'configured', 'verified-file'}
                             for r in records.values())
                return dict(runtime.download_item(tool_id, update=update), purpose='update' if update else 'download',
                            installNotice=MANUAL_NOTICE)
            if action == 'installations':
                fields = ('toolId', 'release', 'scope', 'scopeDir', 'target', 'status', 'created')
                return {'recovery': recovery, 'items': [dict({k: r.get(k) for k in fields}, installationId=key,
                                      rollbackAvailable=r.get('status') in {'installed', 'configured'})
                                  for key, r in records.items()]}
            if action == 'checkUpdates':
                return dict(runtime.check_updates(positive(payload['toolId']) if 'toolId' in payload else None), recovery=recovery)
            installation_id = payload.get('installationId')
            if not isinstance(installation_id, str) or installation_id not in records:
                raise SquareError('현재 연결의 설치 기록을 찾을 수 없습니다.')
            record = records[installation_id]
            if action == 'verify':
                if any(row.get('toolId') == record['toolId'] for row in recovery['blocked']):
                    return dict(status='recovery-required', installed=False, filesIntact=False, recovery=recovery,
                                notice='중단된 설치의 파일과 보관본을 먼저 확인해 주세요. 사용자 변경은 보존했습니다.')
                if record.get('status') in {'installed', 'configured'}:
                    intact = Path(record['target']).is_dir() and tree_digest(no_links(record['target'])) == record.get('treeHash')
                    config_intact = True
                    if record.get('configFile'):
                        configuration = no_links(record['configFile'])
                        config_intact = (configuration.is_file() and read_json(configuration).get('mcpServers', {}).get(record['serverName']) == record.get('configEntry'))
                    notice = ('설치 파일과 연결 설정이 보관된 기록과 일치합니다. MCP 실행 연결은 다음 Claude 연결에서 확인하세요.'
                              if intact and config_intact else
                              '설치 파일이 없거나 변경되었습니다. 자동으로 덮어쓰지 않았습니다. 변경 내용을 먼저 확인해 주세요.'
                              if not intact else
                              '해당 MCP 연결 설정이 없거나 변경되었습니다. 다른 설정은 그대로 유지했습니다. 설치 안내와 현재 설정을 확인해 주세요.')
                    return dict(status=record['status'], installed=intact and config_intact, filesIntact=intact,
                                configurationIntact=config_intact,
                                connectionVerified=False, notice=notice)
                return runtime.installer.verify(installation_id)
            if action == 'rollback':
                if payload.get('confirmed') is not True:
                    raise SquareError('복구할 설치 범위와 경로를 확인한 뒤 실행하세요.')
                return runtime.installer.rollback(installation_id, True)
        raise SquareError('지원하지 않는 스토어 요청입니다.')


def handle(request):
    if not isinstance(request, dict) or type(request.get('protocol')) is not int or request['protocol'] != 1:
        raise SquareError('지원하지 않는 확장 연결 규격입니다.')
    return Store(request.get('dataDirectory'), request.get('context')).dispatch(request.get('action'), request.get('payload'))


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise SquareError('스토어 요청이 너무 큽니다.')
        result = {'ok': True, 'result': handle(json.loads(raw))}
    except SquareError as error:
        result = {'ok': False, 'error': str(error), 'code': 'store_request_failed'}
    except (ValueError, TypeError, KeyError, OSError):
        result = {'ok': False, 'error': '스토어 요청 또는 저장 파일을 확인하지 못했습니다. 다시 연결하거나 요청을 확인해 주세요.', 'code': 'store_invalid_state'}
    except Exception:
        result = {'ok': False, 'error': '스토어 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.', 'code': 'store_failed'}
    output = json.dumps(result, ensure_ascii=False)
    output = re.sub(r'ptsq_[A-Za-z0-9_-]{43}', '[KEY 숨김]', output)
    if len(output.encode('utf-8')) > MAX_OUTPUT:
        output = json.dumps({'ok': False, 'error': '응답이 너무 큽니다. 검색 범위를 줄이거나 웹에서 확인하세요.'}, ensure_ascii=False)
    sys.stdout.buffer.write(output.encode('utf-8'))
    sys.stdout.buffer.flush()


if __name__ == '__main__':
    main()
