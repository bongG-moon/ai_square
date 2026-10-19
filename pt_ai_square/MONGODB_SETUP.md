# MongoDB 설정 — v3.3

기본 PTAI_DATA_MODE='mongodb'에서는 로컬과 회사 환경 모두 실제 MongoDB를 사용합니다. URI와 DB 이름이 필요하며 장애 시 다른 저장소로 대체하지 않습니다. 화면 확인만 필요하면 PTAI_AUTH_MODE='mock', PTAI_DATA_MODE='dummy'를 직접 설정할 수 있습니다. 이때 dummy/catalog.json의 가짜 자료만 읽고 MongoDB에는 연결하지 않습니다. 실제 업로드·다운로드 검증은 mongodb 모드를 사용하세요.

현재는 좋아요·다운로드뿐 아니라 기능 목록, 버전, 사용자, 권한, 요청, 피드백, 알림, 관리자, 운영 이력까지 모두 MongoDB에 저장합니다. SQLite 대체 모드는 없습니다.

`runtime_config.py`에 `MONGODB_URI`, `MONGODB_DATABASE`, `PTAI_ADMIN_IDS` 등 필요한 값을 직접 입력합니다. 실제 프로세스 환경변수가 있으면 우선 적용됩니다. `.env`는 읽지 않습니다.

[실행 순서와 사용자별 버튼 안내](OPERATOR_GUIDE.md)를 확인하세요. 이전 v2의 SQLite 대기열 설명은 현재 구현에 적용되지 않습니다.