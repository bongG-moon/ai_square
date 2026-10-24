"""Scope-bound, reviewed installation plans with owned-change rollback."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid

from .config import SquareError, atomic_json, read_json, no_links, scoped_path
from .files import extract, sha256
from .profiles import validate_profile


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',',':')).encode()).hexdigest()


def tree_digest(path):
    path = no_links(path)
    return digest([(p.relative_to(path).as_posix(), sha256(p)) for p in sorted(path.rglob('*')) if no_links(p).is_file()])


def replace_args(args, scope_dir, install_dir, entrypoint):
    return [s.replace('{scopeDir}',str(scope_dir)).replace('{installDir}',str(install_dir)).replace('{entrypoint}',str(entrypoint)) for s in args]


class Installer:
    def __init__(self, settings, client, home=None):
        self.settings, self.client = settings, client
        self.home = no_links(home or Path.home())
        self.record_path = settings.state / 'installations.json'

    def records(self):
        return read_json(self.record_path) if self.record_path.exists() else {}

    def _identity(self, tool_id, host, scope, directory):
        return digest([self.settings.url,tool_id,host,scope,str(directory)])

    def prepare(self, tool_id, scope, project_path=''):
        if scope not in {'project','user'}:
            raise SquareError('설치 범위를 project(현재 작업 폴더) 또는 user(내 계정)로 명시하세요. 기본 범위는 없습니다.')
        scope_dir = scoped_path(project_path, self.settings.roots, existing=True) if scope == 'project' and project_path else self.home if scope == 'user' else None
        if scope_dir is None or not scope_dir.is_dir():
            raise SquareError('프로젝트 설치에는 허용된 프로젝트 폴더를 지정하세요.')
        manifest = self.client.manifest(tool_id)
        profile = validate_profile(manifest.get('installProfile'))
        if not profile or profile['kind'] == 'manual' or profile['host'] != 'claude' and profile['kind'] in {'skill','mcp'}:
            return {'canInstall':False,'toolId':tool_id,'release':manifest['release'],
                    'reason':'이 항목에는 지원되는 자동 설치 선언이 없습니다. download_item으로 받은 뒤 설치 안내를 따르세요.', 'installed':False}
        if scope not in profile['scopes']:
            raise SquareError('이 도구는 선택한 설치 범위를 지원하지 않습니다.')
        suffix = Path(str(manifest.get('filename',''))).suffix.lower()
        kind = profile['kind']
        if kind=='skill' and profile['slug'] in {'synced','anthropic-skills'}:
            raise SquareError('Claude가 예약한 Skill 이름입니다. 등록자에게 다른 설치 이름을 요청하세요.')
        if not manifest.get('downloadUrl'):
            return {'canInstall':False,'reason':'URL·명령형 항목은 다운로드 파일이 없습니다. 상세 설치 안내를 확인하세요.','installed':False}
        if kind == 'skill' and (suffix not in {'.zip','.md'} or suffix == '.zip' and profile['entrypoint'] != 'SKILL.md'):
            return {'canInstall':False,'reason':'Skill 자동 설치는 단일 MD 또는 최상위 SKILL.md를 포함한 ZIP을 지원합니다.','installed':False}
        if kind == 'mcp':
            cmd = profile['command']
            expected = {'.py'} if cmd['executable'] == 'python' else {'.js','.mjs','.cjs'}
            if suffix != '.zip' or not cmd['args'] or cmd['args'][0] != '{entrypoint}' or Path(profile['entrypoint']).suffix.lower() not in expected:
                return {'canInstall':False,'reason':'MCP 자동 연결은 ZIP의 Python/Node 시작 파일을 직접 실행하는 선언만 지원합니다.','installed':False}
            executable = shutil.which(cmd['executable'])
            if not executable:
                return {'canInstall':False,'reason':cmd['executable'] + ' 실행 환경이 없습니다. 먼저 설치 안내를 확인하세요.','installed':False}
        if kind == 'installer' and suffix not in {'.exe','.msi','.ps1'}:
            return {'canInstall':False,'reason':'설치기 자동 실행은 원본 EXE·MSI·PS1에만 지원됩니다.','installed':False}
        destination = no_links(scope_dir / '.claude' / 'skills' / profile['slug']) if kind == 'skill' else no_links(scope_dir / '.pt-ai-square' / 'tools' / profile['slug'])
        config_file = no_links(scope_dir / ('.mcp.json' if scope == 'project' else '.claude.json')) if kind == 'mcp' else None
        install_id = self._identity(tool_id, profile['host'], scope, scope_dir)
        record = self.records().get(install_id)
        if destination.exists() and (not record or record.get('target') != str(destination)):
            raise SquareError('같은 설치 위치를 다른 파일이 사용 중입니다. 기존 파일을 덮어쓰지 않습니다.')
        if record and destination.exists() and tree_digest(destination) != record.get('treeHash'):
            raise SquareError('설치 후 로컬 파일이 수정되었습니다. 변경 내용을 보관한 뒤 별도로 업데이트하세요.')
        existing_config = read_json(config_file) if config_file and config_file.exists() else {}
        if config_file and not isinstance(existing_config.get('mcpServers',{}),dict):
            raise SquareError('기존 MCP 설정의 mcpServers 형식을 확인하세요.')
        config_hash = sha256(config_file) if config_file and config_file.exists() else None
        server_name = 'pt-square-' + profile['slug']
        old_entry = existing_config.get('mcpServers',{}).get(server_name)
        if config_file and old_entry is not None and (not record or old_entry != record.get('configEntry')):
            raise SquareError('같은 이름의 MCP 설정이 이미 있습니다. 다른 설정을 덮어쓰지 않습니다.')
        plan = dict(id=uuid.uuid4().hex,origin=self.settings.url,created=time.time(),toolId=tool_id,manifest=manifest,
                    profile=profile,scope=scope,scopeDir=str(scope_dir),target=str(destination),installId=install_id,
                    configFile=str(config_file) if config_file else None,configHash=config_hash,serverName=server_name,
                    existingTreeHash=tree_digest(destination) if destination.exists() else None,
                    existingRecordDigest=digest(record) if record else None)
        if kind == 'mcp':
            plan['command'] = [executable] + replace_args(profile['command']['args'],scope_dir,destination,destination/profile['entrypoint'])
        if kind == 'installer':
            plan['arguments'] = replace_args(profile['installerArgs'][scope],scope_dir,destination,destination/('installer'+suffix))
            if profile.get('verification') and no_links(scope_dir/profile['verification']['relativePath']).exists():
                raise SquareError('설치 확인 파일이 이미 존재합니다. 이 설치기로 새 설치 성공을 판정할 수 없습니다.')
        plan['approvalDigest'] = digest(plan)
        atomic_json(self.settings.state / 'plans' / (plan['id'] + '.json'),plan)
        return dict(canInstall=True,planId=plan['id'],approvalDigest=plan['approvalDigest'],toolId=tool_id,
                    release=manifest['release'],scope=scope,scopeDir=str(scope_dir),destination=str(destination),
                    configurationFile=str(config_file) if config_file else None,command=plan.get('command'),arguments=plan.get('arguments'),
                    requiresConfirmation=True,notice='이 경로·범위·실행 인자를 사용자에게 보여주고 확인한 뒤 install_item을 호출하세요. 의존성은 자동 설치하지 않습니다.',
                    installerScopeNotice='설치기가 선언한 범위를 따르는지는 설치기 구현에 달려 있습니다. 관리자 승격이나 범위를 강제로 바꾸지 않습니다.' if kind=='installer' else None)

    def install(self, plan_id, approval_digest, confirmed=False):
        if not confirmed:
            raise SquareError('준비안의 설치 범위와 변경 내용을 사용자에게 확인받아야 합니다.')
        if not isinstance(plan_id,str) or len(plan_id)!=32 or any(c not in '0123456789abcdef' for c in plan_id):
            raise SquareError('설치 준비안 ID를 확인하세요.')
        path = self.settings.state/'plans'/(plan_id+'.json')
        plan = read_json(path)
        stored_digest = plan.pop('approvalDigest',None)
        if digest(plan)!=stored_digest or approval_digest!=stored_digest or plan['origin']!=self.settings.url or time.time()-plan['created']>3600:
            raise SquareError('설치 준비안이 변경되었거나 만료되었습니다. 다시 준비하고 확인하세요.')
        if plan.get('completed'):
            raise SquareError('이미 사용한 설치 준비안입니다.')
        current = self.client.manifest(plan['toolId'])
        if digest(current) != digest(plan['manifest']):
            raise SquareError('버전 또는 설치 정보가 변경되었습니다. 다시 준비하고 확인하세요.')
        profile = validate_profile(plan['profile'])
        scope_dir = scoped_path(plan['scopeDir'],self.settings.roots,existing=True) if plan['scope']=='project' else self.home
        if str(scope_dir)!=plan['scopeDir']:
            raise SquareError('설치 범위가 변경되었습니다.')
        target = no_links(plan['target'])
        expected_target = no_links(scope_dir/'.claude'/'skills'/profile['slug']) if profile['kind']=='skill' else no_links(scope_dir/'.pt-ai-square'/'tools'/profile['slug'])
        if target!=expected_target:
            raise SquareError('설치 위치가 변경되었습니다.')
        records = self.records()
        previous = records.get(plan['installId'])
        if (digest(previous) if previous else None)!=plan['existingRecordDigest']:
            raise SquareError('설치 상태가 변경되었습니다. 다시 준비하세요.')
        if (tree_digest(target) if target.exists() else None)!=plan['existingTreeHash']:
            raise SquareError('설치 대상 파일이 변경되었습니다. 다시 준비하세요.')
        config_file = no_links(plan['configFile']) if plan['configFile'] else None
        if config_file and (sha256(config_file) if config_file.exists() else None)!=plan['configHash']:
            raise SquareError('MCP 설정이 변경되었습니다. 다른 작업을 보존하기 위해 중단했습니다.')
        artifact = self.client.download(current,self.settings.state/'downloads'/plan_id,update=bool(previous))
        staging = no_links(self.settings.state/'staging'/plan_id)
        staging.parent.mkdir(parents=True,exist_ok=True)
        if artifact.suffix=='.zip':
            extract(artifact,staging)
        else:
            staging.mkdir(exist_ok=False)
            shutil.copyfile(artifact,staging/('SKILL.md' if profile['kind']=='skill' else 'installer'+artifact.suffix))
        entry = staging/('SKILL.md' if profile['kind']=='skill' else profile['entrypoint'])
        if profile['kind'] in {'skill','mcp'} and not no_links(entry).is_file():
            shutil.rmtree(staging)
            raise SquareError('선언한 시작 파일이 없습니다. 설치하지 않았습니다.')
        if profile['kind']=='skill':
            text = entry.read_text(encoding='utf-8-sig')
            if not text.strip():
                shutil.rmtree(staging)
                raise SquareError('Skill 지침이 비어 있습니다.')
        # A download/extract may take time; preserve edits made while it was running.
        if (tree_digest(target) if target.exists() else None)!=plan['existingTreeHash']:
            shutil.rmtree(staging)
            raise SquareError('파일을 받는 동안 설치 대상이 변경되었습니다. 다시 준비하세요.')
        if config_file and (sha256(config_file) if config_file.exists() else None)!=plan['configHash']:
            shutil.rmtree(staging)
            raise SquareError('파일을 받는 동안 MCP 설정이 변경되었습니다. 다시 준비하세요.')
        backup_dir = no_links(self.settings.state/'backups'/plan_id)
        backup_dir.mkdir(parents=True,exist_ok=False)
        original_config = config_file.read_bytes() if config_file and config_file.exists() else None
        moved_old = False
        committed_new = False
        committed_record = False
        written_config_hash = None
        try:
            target.parent.mkdir(parents=True,exist_ok=True)
            no_links(target)
            if target.exists():
                shutil.move(str(target),str(backup_dir/'files'))
                moved_old = True
            shutil.move(str(staging),str(target))
            committed_new = True
            entry_data = None
            result = {'installed':False,'toolId':plan['toolId'],'release':current['release'],'scope':plan['scope'],'destination':str(target)}
            if profile['kind']=='mcp':
                conf = read_json(config_file) if config_file.exists() else {}
                if not isinstance(conf.get('mcpServers',{}),dict):
                    raise SquareError('기존 MCP 설정의 mcpServers 형식을 확인하세요.')
                entry_data = {'command':plan['command'][0],'args':plan['command'][1:]}
                conf.setdefault('mcpServers',{})[plan['serverName']] = entry_data
                if original_config is not None:
                    (backup_dir/'config.before.json').write_bytes(original_config)
                atomic_json(config_file,conf)
                written_config_hash = sha256(config_file)
                if read_json(config_file).get('mcpServers',{}).get(plan['serverName'])!=entry_data:
                    raise SquareError('MCP 설정 저장을 확인하지 못했습니다.')
                result.update(installed=True,status='configured',connectionVerified=False,
                              notice='파일·연결 설정 저장을 확인했습니다. Claude 재시작 후 MCP 연결 상태를 확인하세요. 런타임 동작 검증은 별도입니다.')
            elif profile['kind']=='skill':
                result.update(installed=True,status='installed',notice='SKILL.md와 보조 파일의 배치를 확인했습니다. AI 호스트가 지침을 다시 읽으면 사용할 수 있습니다.')
            else:
                result.update(status='ready-to-launch',installed=False)
            record = dict(origin=self.settings.url,toolId=plan['toolId'],release=current['release'],sha256=current['sha256'],
                          host=profile['host'],scope=plan['scope'],scopeDir=str(scope_dir),target=str(target),treeHash=tree_digest(target),
                          configFile=str(config_file) if config_file else None,configEntry=entry_data,configHash=written_config_hash,
                          serverName=plan['serverName'],status=result['status'],backup=str(backup_dir),previous=previous,
                          verification=profile.get('verification'),created=time.time())
            records[plan['installId']] = record
            atomic_json(self.record_path,records)
            committed_record = True
            if profile['kind']=='installer':
                try:
                    result.update(self._launch_installer(plan,target,artifact.suffix,scope_dir))
                except OSError:
                    record['status']='launch-failed'
                    try:atomic_json(self.record_path,records)
                    except OSError:pass
                    raise SquareError('설치기 실행을 시작하지 못했습니다. 파일과 준비 기록은 보존했습니다. Windows 실행 정책과 설치기를 확인한 뒤 다시 준비하세요.') from None
                record['status']='launched'
                try:
                    atomic_json(self.record_path,records)
                except OSError:
                    result['notice']='설치기는 시작되었지만 로컬 실행 상태 저장을 확인하지 못했습니다. 자동 재실행하지 말고 열린 설치기를 먼저 확인하세요.'
            # Consume only after durable installation record. Reusing requires a fresh plan.
            plan['completed']=True
            plan['approvalDigest']=digest(plan)
            try:
                atomic_json(path,plan)
            except OSError:
                result['planCleanupPending']=True
            result.update(installationId=plan['installId'],rollbackAvailable=profile['kind'] in {'skill','mcp'})
            return result
        except Exception:
            if committed_record:
                # The durable record is the local commit point. Never remove installed
                # files after an unrelated plan-cleanup or installer follow-up failure.
                raise
            # Roll back only files/settings written by this call and still matching our write.
            if config_file and written_config_hash and config_file.exists() and sha256(config_file)==written_config_hash:
                if original_config is None:
                    config_file.unlink()
                else:
                    config_file.write_bytes(original_config)
            if committed_new and target.exists():
                shutil.rmtree(no_links(target))
            if moved_old:
                shutil.move(str(backup_dir/'files'),str(target))
            raise

    def _launch_installer(self,plan,target,suffix,scope_dir):
        if os.name!='nt':
            raise SquareError('EXE·MSI·PS1 설치기 실행은 Windows에서 지원합니다.')
        file = target/('installer'+suffix)
        if suffix=='.exe':
            command=[str(file)]
        elif suffix=='.msi':
            command=[str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32'/'msiexec.exe'),'/i',str(file)]
        else:
            command=[str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'),'-NoProfile','-File',str(file)]
        command+=plan['arguments']
        allowed_env={'SYSTEMROOT','WINDIR','SYSTEMDRIVE','COMSPEC','PATH','PATHEXT','TEMP','TMP','USERPROFILE','HOMEDRIVE','HOMEPATH',
                     'APPDATA','LOCALAPPDATA','PROGRAMDATA','PROGRAMFILES','PROGRAMFILES(X86)','COMMONPROGRAMFILES','COMMONPROGRAMFILES(X86)',
                     'USERNAME','USERDOMAIN','COMPUTERNAME','PROCESSOR_ARCHITECTURE','NUMBER_OF_PROCESSORS'}
        env={k:v for k,v in os.environ.items() if k.upper() in allowed_env}
        process=subprocess.Popen(command,cwd=str(scope_dir),env=env,shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        return {'status':'launched','installed':False,'processId':process.pid,
                'notice':'설치기를 시작했습니다. 설치 완료를 보장하지 않습니다. 설치 창을 완료한 뒤 verify_install로 선언한 결과 파일을 확인하세요. 외부 설치기 변경은 자동 복구할 수 없습니다.'}

    def verify(self, installation_id):
        records=self.records();record=records.get(installation_id)
        if not record:
            raise SquareError('설치 기록을 찾을 수 없습니다.')
        verification=record.get('verification')
        if record['status']!='launched':
            return {'status':record['status'],'installed':record['status'] in {'installed','configured','verified-file'},'connectionVerified':False}
        if not verification:
            return {'installed':False,'status':'launched','notice':'이 설치기는 자동 확인 경로를 선언하지 않았습니다. 실제 앱 실행 결과를 사용자가 확인해야 합니다.'}
        found=no_links(Path(record['scopeDir'])/verification['relativePath']).is_file()
        if found:
            record['status']='verified-file';atomic_json(self.record_path,records)
        return {'installed':found,'status':'verified-file' if found else 'launched','notice':'선언한 결과 파일의 존재 여부를 확인했습니다. 실제 기능 동작·보안 검증과는 다릅니다.'}

    def rollback(self, installation_id, confirmed=False):
        if not confirmed:
            raise SquareError('설치 복구 범위를 확인한 뒤 실행하세요.')
        records=self.records();record=records.get(installation_id)
        if not record or record['status'] not in {'installed','configured'}:
            raise SquareError('이 설치는 파일·설정 자동 복구 대상이 아닙니다.')
        target=no_links(record['target']);backup=no_links(record['backup'])
        if tree_digest(target)!=record['treeHash']:
            raise SquareError('설치 후 수정된 파일이 있어 자동 복구하지 않았습니다.')
        config_file=no_links(record['configFile']) if record.get('configFile') else None
        conf=read_json(config_file) if config_file else None
        if config_file and conf.get('mcpServers',{}).get(record['serverName'])!=record['configEntry']:
            raise SquareError('해당 MCP 설정이 바뀌어 자동 복구하지 않았습니다.')
        previous=record.get('previous')
        backup_root=no_links(self.settings.state/'backups')
        if backup_root not in backup.parents:
            raise SquareError('설치 백업 경로를 확인하세요.')
        previous_files=no_links(backup/'files')
        if previous and (not previous_files.is_dir() or tree_digest(previous_files)!=previous.get('treeHash')):
            raise SquareError('이전 버전 백업이 없거나 변경되었습니다. 현재 설치는 그대로 보존했습니다.')
        original_config=config_file.read_bytes() if config_file else None
        displaced=no_links(target.with_name('.pt-square-rollback-'+uuid.uuid4().hex))
        old_returned=False
        written_hash=None
        # Keep the current installation intact under a temporary sibling name until
        # the previous files, config and state are all safely restored.
        target.rename(displaced)
        try:
            if previous:
                shutil.move(str(previous_files),str(target));old_returned=True
                records[installation_id]=previous
            else:
                records.pop(installation_id,None)
            if config_file:
                if previous and previous.get('configEntry'):
                    conf['mcpServers'][record['serverName']]=previous['configEntry']
                else:
                    conf['mcpServers'].pop(record['serverName'],None)
                atomic_json(config_file,conf);written_hash=sha256(config_file)
            atomic_json(self.record_path,records)
        except Exception:
            if config_file and written_hash and sha256(config_file)==written_hash:
                config_file.write_bytes(original_config)
            if old_returned:
                shutil.move(str(target),str(previous_files))
            displaced.rename(target)
            raise
        cleanup_pending=False
        try:shutil.rmtree(displaced)
        except OSError:cleanup_pending=True
        return {'restored':True,'toolId':record['toolId'],'release':previous.get('release') if previous else None,
                'cleanupPending':cleanup_pending,'notice':'이 MCP가 관리한 파일·해당 MCP 설정 항목만 복구했습니다. 외부 설치기 변경은 대상이 아닙니다.'}
