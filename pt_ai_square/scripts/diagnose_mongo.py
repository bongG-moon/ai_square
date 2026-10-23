"""Read-only MongoDB connection diagnostics; never initialize the application."""
import json
import re
import sys
from pathlib import Path

if __package__ in {None, ''}:
    # Support a copied/renamed pt_ai_square folder without a parent package.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from _square_bootstrap import load_package
    __package__ = load_package().__name__ + '.scripts'

from ..config import settings
from ..backend.mongo_store import mongo_client
from ..backend.mongo_errors import mongo_diagnostic
from pymongo.errors import PyMongoError


def diagnose(config):
    """Only ping/hello/buildInfo. No DB names, credentials or raw errors escape."""
    result = {'retryWrites': config.get('MONGODB_RETRY_WRITES', False),
              'ping': 'unknown', 'maxWireVersion': None, 'sessionsSupported': None,
              'replicaSet': None, 'router': None, 'version': None, 'errors': []}
    client = mongo_client(config)
    try:
        result['retryWrites'] = client.options.retry_writes
        for command in ('ping', 'hello', 'buildInfo'):
            try:
                response = client.admin.command(command)
            except PyMongoError as error:
                diagnostic = mongo_diagnostic(error)
                result['errors'].append({'command': command, 'code': diagnostic['code'],
                                         'mongoCode': diagnostic['mongo_code']})
                if command == 'ping': result['ping'] = 'failed'
                continue
            if command == 'ping':
                result['ping'] = 'ok' if response.get('ok') == 1 else 'failed'
            elif command == 'hello':
                wire = response.get('maxWireVersion')
                result.update(maxWireVersion=wire if type(wire) is int else None,
                              sessionsSupported=response.get('logicalSessionTimeoutMinutes') is not None,
                              replicaSet=bool(response.get('setName')),
                              router=response.get('msg') == 'isdbgrid')
            elif command == 'buildInfo':
                version = response.get('version')
                if isinstance(version, str) and re.fullmatch(r'[0-9][0-9A-Za-z.+-]{0,63}', version):
                    result['version'] = version
    finally:
        client.close()
    return result


def main():
    try:
        result = diagnose(settings())
    except Exception:
        # Configuration/URI parsing errors can include secrets too.
        print(json.dumps({'error': '설정 파일·MongoDB 접속 옵션을 확인하세요. 상세 접속 정보는 출력하지 않습니다.'}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ping'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
