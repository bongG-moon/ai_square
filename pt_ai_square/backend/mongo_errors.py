"""Public-safe MongoDB diagnostics; never return exception text or details."""
from pymongo.errors import (
    BulkWriteError, ConnectionFailure, DuplicateKeyError, ExecutionTimeout,
    NetworkTimeout, OperationFailure, WTimeoutError,
)


def mongo_diagnostic(error):
    # Only the numeric server code is public. `details` and exception messages
    # can include hosts, credentials, queries and document contents.
    value = getattr(error, 'code', None)
    mongo_code = value if type(value) is int and 0 <= value <= 2147483647 else None
    if isinstance(error, BulkWriteError):
        code = 'DB-BULK-WRITE'
        message = 'MongoDB 일괄 저장 중 오류가 발생했습니다. 일부 항목은 저장되었을 수 있습니다.'
    elif isinstance(error, DuplicateKeyError) or mongo_code == 11000:
        code = 'DB-DUPLICATE'
        message = 'MongoDB에서 중복된 값으로 저장이 거부되었습니다. 기존 등록 내용과 중복 기준을 확인해야 합니다.'
    elif mongo_code == 18:
        code = 'DB-AUTHENTICATION'
        message = 'MongoDB 계정 인증에 실패했습니다. 운영자가 DB 계정과 인증 대상 DB 설정을 확인해야 합니다.'
    elif mongo_code == 13:
        code = 'DB-PERMISSION'
        message = 'MongoDB 계정에 이 작업을 수행할 권한이 없습니다. 운영자가 DB 계정 권한을 확인해야 합니다.'
    elif mongo_code == 121:
        code = 'DB-DOCUMENT'
        message = '저장할 데이터가 MongoDB의 데이터 검증 규칙에 맞지 않습니다. 운영자가 데이터 형식과 검증 규칙을 확인해야 합니다.'
    elif isinstance(error, (NetworkTimeout, ExecutionTimeout, WTimeoutError)) or mongo_code == 50:
        code = 'DB-TIMEOUT'
        message = 'MongoDB 작업의 제한 시간을 초과했습니다. 작업 지연이나 응답 시간 초과 원인을 확인해야 합니다.'
    elif isinstance(error, ConnectionFailure):
        code = 'DB-CONNECTION'
        message = 'MongoDB와 통신하지 못했거나 연결이 끊겼습니다. 서버 접근 가능 여부와 연결 상태를 확인해야 합니다.'
    elif isinstance(error, OperationFailure):
        code = 'DB-OPERATION'
        message = 'MongoDB가 요청한 작업을 처리하지 못했습니다. 표시된 MongoDB 코드로 원인을 확인해야 합니다.'
    else:
        code = 'DB-ERROR'
        message = 'MongoDB 처리 중 오류가 발생했습니다. 진단 코드와 어떤 작업에서 발생했는지 운영자에게 알려주세요.'
    return {'code': code, 'mongo_code': mongo_code, 'message': message}
