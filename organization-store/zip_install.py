"""Inspect verified legacy Skill ZIPs without running their bundled commands.

The canonical installer still owns confirmation, placement, conflict checks and
rollback. This adapter supplies a narrowly derived Skill profile only when the
server did not publish an installation profile at all.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from pt_square_mcp.client import automatic_download_directory
from pt_square_mcp.config import SquareError, no_links
from pt_square_mcp.files import safe_entries, sha256
from pt_square_mcp.install import digest
from pt_square_mcp.profiles import relative, validate_profile


DETECTION_KEY = '_axStoreZipSkill'
MAX_SKILL_BYTES = 128 * 1024
MAX_PACKAGE_BYTES = 64 * 1024
INSPECTION_NOTICE = ('ZIP 안의 Skill 구조를 확인한 뒤 설치할 수 있어요. '
                     '파일을 확인할 때 다운로드가 집계되며, 설치 전 변경 위치를 보여드립니다.')
DETECTED_NOTICE = ('ZIP 최상위 SKILL.md와 스킬 이름을 확인했습니다. 선택한 공간의 '
                   '.claude/skills 폴더에 파일을 설치합니다. ZIP의 설치 스크립트나 명령은 실행하지 않습니다.')
UNSUPPORTED_NOTICE = ('이 ZIP에서는 설치할 Skill 구조나 실행 명령을 확인할 수 없어요. '
                      '등록자가 앱 설치 정보(지원 범위·설치 방식·실행 명령)를 등록해야 합니다. '
                      '현재는 파일 다운로드와 등록자의 설치 안내를 이용해 주세요.')


class ZipInstallUnsupported(SquareError):
    """The inspected ZIP has no unambiguous supported Skill structure."""


def check_declaration(value):
    if value is None:
        return
    if not isinstance(value, dict):
        raise ZipInstallUnsupported(UNSUPPORTED_NOTICE)
    expected = {'schemaVersion': 1, 'type': 'Skill', 'platform': 'Claude',
                'kind': 'skill', 'host': 'claude', 'entryPoint': 'SKILL.md'}
    if (any(key in value and (value[key] != accepted or key == 'schemaVersion' and type(value[key]) is not int)
            for key, accepted in expected.items()) or 'installProfile' in value):
        # A root Skill used as instructions for a larger MCP/harness bundle must
        # not cause the whole bundle to be reported as an installed Skill.
        raise ZipInstallUnsupported(UNSUPPORTED_NOTICE)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ZipInstallUnsupported(UNSUPPORTED_NOTICE)
        result[key] = value
    return result


def can_inspect(manifest):
    # An explicit profile, even an invalid/manual one, must never be overridden.
    try:
        check_declaration(manifest.get('package'))
    except ZipInstallUnsupported:
        return False
    return (manifest.get('installProfile') is None
            and Path(str(manifest.get('filename', ''))).suffix.lower() == '.zip'
            and bool(manifest.get('downloadUrl')))


def inspect_skill(artifact):
    try:
        with zipfile.ZipFile(no_links(artifact)) as archive:
            entries = safe_entries(archive)
            declarations = [entry for entry in entries if entry.filename.casefold() == 'ai-square.json']
            if declarations:
                declaration = declarations[0]
                if (len(declarations) != 1 or declaration.filename != 'ai-square.json' or declaration.is_dir()
                        or not 0 < declaration.file_size <= MAX_PACKAGE_BYTES):
                    raise ZipInstallUnsupported(UNSUPPORTED_NOTICE)
                with archive.open(declaration) as source:
                    encoded = source.read(MAX_PACKAGE_BYTES + 1)
                if len(encoded) > MAX_PACKAGE_BYTES:
                    raise ZipInstallUnsupported(UNSUPPORTED_NOTICE)
                value = json.loads(encoded.decode('utf-8-sig'), object_pairs_hook=unique_object)
                if not isinstance(value, dict):
                    raise ZipInstallUnsupported(UNSUPPORTED_NOTICE)
                check_declaration(value)
            skills = [entry for entry in entries if entry.filename == 'SKILL.md' and not entry.is_dir()]
            if len(skills) != 1 or not 0 < skills[0].file_size <= MAX_SKILL_BYTES:
                raise ZipInstallUnsupported(UNSUPPORTED_NOTICE)
            with archive.open(skills[0]) as source:
                raw = source.read(MAX_SKILL_BYTES + 1)
            if len(raw) > MAX_SKILL_BYTES:
                raise ZipInstallUnsupported(UNSUPPORTED_NOTICE)
            text = raw.decode('utf-8-sig')
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, UnicodeError, json.JSONDecodeError, RecursionError):
        raise ZipInstallUnsupported(UNSUPPORTED_NOTICE) from None
    # A conservative YAML subset avoids executing tags or guessing folded names.
    frontmatter = re.match(r'\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)', text, re.S)
    names = re.findall(r'^name[ \t]*:[ \t]*(.*?)[ \t]*\r?$', frontmatter.group(1), re.M) if frontmatter else []
    if len(names) != 1 or not text[frontmatter.end():].strip():
        raise ZipInstallUnsupported(UNSUPPORTED_NOTICE)
    name = names[0]
    if len(name) >= 2 and name[0] == name[-1] and name[0] in {'"', "'"}:
        name = name[1:-1]
    if not re.fullmatch(r'[a-z][a-z0-9-]{1,63}', name) or name in {'synced', 'anthropic-skills'}:
        raise ZipInstallUnsupported(UNSUPPORTED_NOTICE)
    relative(name)  # Includes Windows reserved-device-name checks.
    return validate_profile(dict(schemaVersion=1, kind='skill', host='claude', slug=name,
                                 scopes=['project', 'user'], entrypoint='SKILL.md'))


class ZipSkillClient:
    """Present a derived profile while keeping original server bytes authoritative."""
    def __init__(self, client, settings, source_digest, *, update=False):
        self.client, self.settings = client, settings
        self.source_digest, self.update = source_digest, update
        self.snapshot = None

    def _source(self, tool_id):
        manifest = self.client.manifest(tool_id)
        if not can_inspect(manifest) or digest(manifest) != self.source_digest:
            raise SquareError('배포 파일 또는 설치 정보가 변경되었습니다. ZIP 설치 내용을 다시 확인해 주세요.')
        return manifest

    @staticmethod
    def _verify(artifact, manifest):
        artifact = no_links(artifact)
        if (not artifact.is_file() or artifact.stat().st_size != manifest.get('bytes')
                or sha256(artifact) != manifest.get('sha256')):
            raise SquareError('확인한 ZIP 파일이 변경되었습니다. 파일의 크기·SHA-256을 다시 확인해 주세요.')
        return artifact

    def manifest(self, tool_id):
        source = self._source(tool_id)
        if self.snapshot is not None:
            effective, artifact = self.snapshot
            self._verify(artifact, source)
            return json.loads(json.dumps(effective))
        directory = automatic_download_directory(self.settings, source)
        artifact = self.client.download(source, directory, update=self.update)
        self._verify(artifact, source)
        profile = inspect_skill(artifact)
        effective = dict(source, installProfile=profile)
        effective[DETECTION_KEY] = dict(schemaVersion=1, sourceManifestDigest=self.source_digest,
                                       archiveSha256=source['sha256'], entrypoint='SKILL.md',
                                       skillName=profile['slug'])
        self.snapshot = effective, artifact
        return json.loads(json.dumps(effective))

    def download(self, manifest, directory, *, update=False):
        # Never send a synthesized profile to Client.download: the server profile
        # is still None and its race/permission/hash validation must stay intact.
        source = self._source(manifest['toolId'])
        if self.snapshot is None:
            self.manifest(manifest['toolId'])
        effective, artifact = self.snapshot
        if digest(manifest) != digest(effective) or no_links(directory) != artifact.parent:
            raise SquareError('ZIP 설치 준비 내용이 변경되었습니다. 다시 확인해 주세요.')
        return self._verify(artifact, source)
