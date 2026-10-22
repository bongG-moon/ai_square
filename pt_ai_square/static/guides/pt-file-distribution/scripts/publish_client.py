"""Prepare/review/publish a package through the employee-bound API. No LLM needed."""
import argparse
import getpass
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid
from urllib.parse import urlencode, urlsplit
from square_client import Client, ClientError, AuthenticationRequired, DEFAULT_CONFIG, open_auth_page


def read_json(path):
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ClientError('JSON 최상위는 객체여야 합니다.')
    return value


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        json.dump(value, f, ensure_ascii=False, indent=2)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def multipart(client, endpoint, artifact, metadata=None):
    boundary = 'square' + uuid.uuid4().hex
    csrf_headers = {}
    if not client.token:
        csrf_headers['X-CSRF-Token'] = client.get('/api/bootstrap')['csrf']
    with tempfile.TemporaryFile() as body:
        if metadata is not None:
            body.write((f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n'
                        + json.dumps(metadata, ensure_ascii=False) + '\r\n').encode())
        if artifact:
            artifact = Path(artifact)
            filename = artifact.name.replace('"', '_').replace('\r', '_').replace('\n', '_')
            body.write((f'--{boundary}\r\nContent-Disposition: form-data; name="artifact"; filename="{filename}"\r\n'
                        'Content-Type: application/octet-stream\r\n\r\n').encode())
            with artifact.open('rb') as f:
                while chunk := f.read(1024 * 1024):
                    body.write(chunk)
            body.write(b'\r\n')
        body.write(f'--{boundary}--\r\n'.encode())
        length = body.tell()
        body.seek(0)
        with client.open(endpoint, body, {**csrf_headers, 'Content-Type': 'multipart/form-data; boundary='+boundary,
                                         'Content-Length': str(length)}) as response:
            return json.loads(response.read(4 * 1024 * 1024))


def prepare(client, artifact, metadata, plan_path, tool_id=None, new=False):
    """Inspect server-side; fill package fields. Never silently choose visibility."""
    plan_path = Path(plan_path).resolve()
    state_path = plan_path.parent / '.ai-square-publish-state.json'
    options = client.get('/api/catalog/options')
    package = None
    warning = ''
    fields = {}
    if artifact:
        artifact = Path(artifact).resolve()
        inspected = multipart(client, '/api/packages/inspect', artifact)
        fields = inspected.get('metadata', {})
        package = inspected.get('package')
        warning = inspected.get('warning', '')
    if new and tool_id:
        raise ClientError('--new와 --tool은 함께 사용할 수 없습니다.')
    binding = read_json(state_path) if state_path.exists() else {}
    source_key = 'package:' + package['packageId'] if package else 'file:' + str(artifact) if artifact else 'named:' + str(metadata.get('name', ''))
    same_identity = (binding.get('baseUrl') == client.url and binding.get('employeeId') == options['employee']['id']
                     and binding.get('sourceKey') == source_key)
    if not new and not tool_id and same_identity:
        tool_id = binding.get('toolId')
    if not new and not tool_id and package:
        candidates = client.get('/api/publish-targets?' + urlencode({'packageId': package['packageId']}))['items']
        if len(candidates) > 1:
            raise ClientError('같은 packageId의 관리 가능한 도구가 여러 개입니다. 사용자에게 확인 후 --tool ID로 선택하세요.')
        if candidates:
            tool_id = candidates[0]['id']
    previous = {}
    revision = None
    if tool_id:
        previous = client.details(tool_id)
        if not previous.get('canManage'):
            raise ClientError('이 도구의 새 버전을 게시할 권한이 없습니다.')
        revision = previous['revision']
    keys = ['name','desc','platform','type','guide','environment','changes','workTags','orgId','categoryId']
    values = {k: previous[k] for k in keys if k in previous}
    values.update(fields)
    values.update(metadata)
    values.setdefault('owner', options['employee']['name'])
    values['mode'] = 'file' if artifact else values.get('mode')
    values.pop('approval', None)  # Explicit publish --visibility is always required.
    missing = [k for k in ['name','desc','platform','type','guide','orgId','categoryId','mode'] if not values.get(k)]
    plan = dict(schemaVersion=1, baseUrl=client.url, employeeId=options['employee']['id'],
                toolId=tool_id, expectedRevision=revision, artifact=str(artifact) if artifact else None,
                artifactSha256=sha(artifact) if artifact else None, metadata=values,
                clientRequestId=str(uuid.uuid4()), statePath=str(state_path),
                packageId=package.get('packageId') if package else None, sourceKey=source_key)
    save(plan_path, plan)
    return dict(plan=str(plan_path), action='new_version' if tool_id else 'new_tool', toolId=tool_id,
                metadata=values, missing=missing, requiredChoice='공개(public) 또는 조회 승인 필요(approval)',
                currentApproval=previous.get('approval') if previous else None, options=options, packageWarning=warning)


def publish(client, plan_path, visibility):
    if visibility not in {'public','approval'}:
        raise ClientError('공개 또는 조회 승인 필요 여부를 먼저 확인하세요.')
    plan = read_json(plan_path)
    identity = client.get('/api/catalog/options')['employee']
    if plan['baseUrl'] != client.url or plan['employeeId'] != identity['id']:
        raise ClientError('준비안의 서버 또는 사번이 다릅니다. 다시 준비하세요.')
    if plan.get('artifact') and sha(plan['artifact']) != plan['artifactSha256']:
        raise ClientError('준비 이후 파일이 변경되었습니다. prepare를 다시 실행하세요.')
    metadata = dict(plan['metadata'], approval=visibility=='approval',
                    clientRequestId=plan['clientRequestId'])
    target = plan.get('toolId')
    if target:
        metadata['expectedRevision'] = plan['expectedRevision']
    # Server revalidates taxonomy, permissions and revision. Same plan retries
    # reuse clientRequestId; a changed plan must be prepared afresh.
    result = multipart(client, f'/api/tools/{target}/versions' if target else '/api/tools',
                       plan.get('artifact'), metadata)
    save(plan['statePath'], dict(baseUrl=client.url, employeeId=identity['id'],
                               toolId=result['id'], release=result['version'], packageId=plan.get('packageId'),
                               sourceKey=plan['sourceKey']))
    return dict(result, approval=metadata['approval'], notice='게시 완료. 설치·자동 실행은 하지 않았습니다.')


def main(argv=None):
    p = argparse.ArgumentParser(description='배포 파일 자동 입력·게시 (공개 여부 명시 필수)')
    p.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    p.add_argument('--authenticate', action='store_true')
    s = p.add_subparsers(dest='command', required=True)
    s.add_parser('auth')
    a = s.add_parser('prepare')
    a.add_argument('--artifact', type=Path)
    a.add_argument('--metadata', type=Path, help='MD/URL/명령어 또는 추가 설명 JSON')
    a.add_argument('--plan', type=Path, required=True)
    a.add_argument('--org-id')
    a.add_argument('--category-id')
    a.add_argument('--tool', type=int)
    a.add_argument('--new', action='store_true')
    b = s.add_parser('publish')
    b.add_argument('--plan', type=Path, required=True)
    b.add_argument('--visibility', required=True, choices=['public','approval'])
    args = p.parse_args(argv)
    url = None
    try:
        url = read_json(args.config)['baseUrl']
        client = Client(url, os.environ.get('PTAI_API_TOKEN', os.environ.get('PTAI_READ_TOKEN','')).strip(), timeout=120)
        if args.command == 'auth':
            print(json.dumps(open_auth_page(url), ensure_ascii=False))
            return 0
        if args.authenticate or (not client.token and urlsplit(client.url).hostname not in {'localhost','127.0.0.1','::1'}):
            info = open_auth_page(client.url) if not client.token else {'authUrl':client.url+'/local-access'}
            if not sys.stdin.isatty():
                raise ClientError('인증키 발급 화면: '+info['authUrl']+' · 업로드 포함 키를 사용자 터미널 또는 PTAI_API_TOKEN으로 입력하세요.')
            client = Client(url, getpass.getpass('업로드 포함 인증키: ').strip(), timeout=120)
        if args.command == 'prepare':
            fields = read_json(args.metadata) if args.metadata else {}
            if args.org_id: fields['orgId'] = args.org_id
            if args.category_id: fields['categoryId'] = args.category_id
            result = prepare(client, args.artifact, fields, args.plan, args.tool, args.new)
        else:
            result = publish(client, args.plan, args.visibility)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except AuthenticationRequired as error:
        print(json.dumps(dict(error=str(error), **open_auth_page(url)), ensure_ascii=False), file=sys.stderr)
    except (ClientError, OSError, ValueError, KeyError, HTTPException) as error:
        message = str(error) if isinstance(error, ClientError) else '설정·파일·응답을 확인하세요. 실패 시 같은 준비안으로 재시도할 수 있습니다.'
        print(json.dumps(dict(error=message), ensure_ascii=False), file=sys.stderr)
    return 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
