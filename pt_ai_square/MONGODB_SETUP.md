# MongoDB 설정 — v3.3

로컬과 회사 환경 모두 실제 MongoDB를 사용합니다. URI와 DB 이름을 입력해야 시작할 수 있으며, 예시 데이터나 SQLite로 대체하지 않습니다.

현재는 좋아요·다운로드뿐 아니라 기능 목록, 버전, 사용자, 권한, 요청, 피드백, 알림, 관리자, 운영 이력까지 모두 MongoDB에 저장합니다. SQLite 대체 모드는 없습니다.

`runtime_config.py`에 `MONGODB_URI`, `MONGODB_DATABASE`, `PTAI_ADMIN_IDS` 등 필요한 값을 직접 입력합니다. 실제 프로세스 환경변수가 있으면 우선 적용됩니다. `.env`는 읽지 않습니다.

[실행 순서와 사용자별 버튼 안내](OPERATOR_GUIDE.md)를 확인하세요. 이전 v2의 SQLite 대기열 설명은 현재 구현에 적용되지 않습니다.