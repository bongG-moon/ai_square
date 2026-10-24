# P&T AI SQUARE 폴더 구조

최상위에는 실행·설정·의존성 파일만 두고, 서버 기능·화면 소스·스크립트·문서를 역할별 폴더로 나눴습니다. 회사 기본 진입점은 `python index.py` 또는 회사 실행기의 `index:application`입니다. 기존 `web_main:app`도 같은 Flask 앱을 가리킵니다.

```text
pt_ai_square/
├─ index.py                    회사 기본 실행 진입점 / application 제공
├─ web_main.py                 Flask app 생성 및 기능 연결 (서버 시작 없음)
├─ run_server.cmd              Windows index.py 실행 바로가기
├─ runtime_config.example.py   설정 예시
├─ runtime_config.py           직접 만드는 개인·운영 설정 (Git 제외)
├─ config.py                   설정을 읽는 코드
├─ __init__.py                 기존 Flask 앱에 기능 연결 / 테스트용 앱 생성
├─ __main__.py                 선택적인 로컬 실행·관리 명령
├─ _square_bootstrap.py        폴더 단독 실행 지원
├─ requirements.txt            서비스 의존성
├─ requirements-lock.txt       고정 버전 의존성
├─ README.md                   시작 안내
├─ .gitignore                  개인 설정·데이터 제외 규칙
├─ backend/                    서버 API·인증·DB·파일 관리
├─ frontend/                   화면 기능별 JavaScript 원본
├─ templates/                  Flask HTML 템플릿
├─ static/                     실제 서비스 JS·CSS·폰트·이미지·Skill ZIP
├─ scripts/                    빌드·문서 생성·로컬 실행 보조 도구
├─ docs/                       상세 기획서·사용자·운영·SSO 가이드
├─ receiver/                   로컬 검색·다운로드 Skill 원본
├─ dummy/                      화면 확인용 샘플 데이터
└─ tests/                      기능·권한·독립 실행 검증
```

## 수정하려는 기능별로 찾아가기

| 수정할 내용 | 위치 |
|---|---|
| MongoDB 주소·SSO 사용 여부·기본 관리자 사번 | runtime_config.py |
| 설정 읽기와 기본값 | config.py |
| 회사 SSO / mock 인증 | backend/auth.py |
| 도구 등록·수정·권한·버전 API | backend/mongo_api.py |
| MongoDB 초기화·프로세스별 연결·사용자·권한 | backend/mongo_store.py |
| MongoDB 오류 분류·사용자 진단 안내 | backend/mongo_errors.py / templates/database_error.html |
| 이력·구독·알림 outbox 전달 / 이전 postCommit 형식 호환 | backend/mongo_store.py / backend/post_commit.py |
| 읽기 전용 MongoDB 연결 진단 | scripts/diagnose_mongo.py |
| 좋아요·다운로드 집계 | backend/mongo_activity.py |
| 파일 검사·저장 / 배포 정보 검사 | backend/artifacts.py / backend/package_contract.py |
| 개인 API 인증키·로컬 다운로드 | backend/local_access.py |
| 내 프로필 사진·함께한 동료 집계 | backend/people.py |
| 상단 프로필·KEY 바로가기·함께한 동료·동작 FLOW | frontend/frontend_people.js / static/people.css |
| 파일 용량 관리 | backend/storage_capacity.py |
| 등록 관리·관리자 화면 | frontend/frontend_workspace.js |
| 파일 선택·업로드 화면 | frontend/frontend_upload.js |
| 저장 공간 화면 | frontend/frontend_storage.js |
| 기본 HTML·현재 서비스 스타일 | templates/ / static/ |
| 배포 Skill | static/guides/pt-file-distribution/ |
| 다운로드 Skill·공용 HTTP 클라이언트 원본 | receiver/pt-square-receiver/ |

backend/api.py·storage.py·activity.py는 MongoDB 구현을 연결하는 짧은 진입 파일입니다. 현재 서비스 저장은 MongoDB로 통일되어 있으며 별도 SQLite 실행 모드가 아닙니다.

`mongo_store.py`는 프로세스 ID를 확인해 각 작업 프로세스가 자기 MongoClient와 연결 풀을 사용하게 합니다. 같은 프로세스의 여러 스레드는 클라이언트를 공유합니다. `config.py`의 선택 설정 `PTAI_MONGODB_RETRY_WRITES`는 생략하면 `False`이며 URI의 `retryWrites`보다 우선합니다. 기존 `runtime_config.py`에 필수로 추가할 값은 없습니다. `True`는 DB 제품·드라이버·실행 환경을 검증한 뒤 선택하고, 쓰기 결과 확인과 읽기 재시도 설정은 유지합니다.

변경 요청은 주 기록과 후속 이력·구독·알림 이벤트를 같은 문서에 저장합니다. `mongo_store.py`가 `tools`, `access`, `feedback`, `ideas`, `administrators`, `settings`, `taxonomy`, `users`의 outbox를 전달하고, `post_commit.py`는 이전 버전이 남긴 postCommit 작업도 이어서 처리합니다. 좋아요·다운로드는 `mongo_activity.py`의 상태와 활동 대기열을 함께 저장합니다. 주 저장이 끝난 뒤 후속 처리만 실패하면 이미 저장된 결과와 대기 상태를 구분합니다. 일반 변경 요청 전체를 자동 재실행하지 않습니다.

`/api/bootstrap` 목록 조회는 후속 작업을 재처리하지 않습니다. 저장 요청은 해당 문서·도구·사용자 범위의 후속 작업을 처리하고, 남은 작업은 알림 조회에서 다시 시도합니다. 일반 outbox는 컬렉션당 최대 50개 문서·문서당 최대 50개 이벤트, 활동 대기열은 한 번에 최대 50개 상태 문서를 처리합니다. 이는 응답 시간의 상한을 보장하지 않습니다. 상주 백그라운드 worker는 없으므로 접속자가 없거나 DB 실패가 계속되면 작업이 남을 수 있습니다.

화면은 저장 결과와 후속 조회 실패를 구분합니다. `frontend_api.js`는 목록 조회 순서와 동일 도구 좋아요 중복 요청을 제어하고, `frontend_publish.js`는 게시 요청 ID·동시 게시 차단을 관리합니다. `frontend_storage.js`는 저장 응답의 정책·revision을 직접 반영합니다. 실제 서비스가 읽는 `static/app.js`에도 같은 내용을 반영해야 합니다.

225는 `mongo_errors.py`에서 기존 이름 `DB-SESSION-ORDER`로 분류합니다. 운영 보고서의 `DB-TRANSACTION-ORDER`와 같은 MongoDB 225를 뜻합니다. `scripts/diagnose_mongo.py`는 웹과 같은 `mongo_client(config)` 연결 옵션을 사용하며 ping·hello·buildInfo만 요청합니다. 자세한 절차와 검증 범위는 `docs/SSO_OPERATIONS_GUIDE.md` 13-2·13-3절, `docs/OPERATOR_GUIDE.md`의 저장 성공과 후속 작업 재처리 항목을 참고하세요.

## 빌드·검증 명령

아래 빌드 명령은 web_main.py가 있는 폴더에서 실행합니다.

```powershell
# 등록 관리 등 기능별 화면 코드를 현재 서비스 JS에 반영
python scripts/build_workspace.py

# 배포 Skill의 공용 코드 반영 및 배포 ZIP 갱신
python scripts/build_guides.py

# 다운로드 Skill ZIP 갱신
python scripts/build_receiver.py

# 운영·사용자 문서 HTML 생성
python scripts/build_docs.py
```

scripts/build_frontend.py는 초기 화면 생성용 이력입니다. 현재 UI를 보존하는 일반 수정 작업에서 실행하면 안 됩니다. 화면을 수정할 때는 현재 static/app.js와 관련 frontend 모듈의 연결을 확인하고 필요한 빌드만 실행합니다.

문서 HTML은 앱 폴더의 상위 위치 아래 outputs/pt-ai-square-web-20261018에 생성됩니다. 공개 사용자 가이드만 static/guides에 복사하고 운영 가이드는 일반 사용자 다운로드에 넣지 않습니다. 저장소 루트 docs/에는 읽기 쉬운 HTML 배포본을 둡니다.

테스트는 저장소 루트, 즉 pt_ai_square의 상위 폴더에서 실행합니다. 테스트용 MongoDB 주소는 PTAI_TEST_MONGO_URI로 지정하며 기본값은 mongodb://127.0.0.1:27018/입니다. 테스트는 별도의 임시 DB를 만들고 정리합니다.

```powershell
python -m pytest pt_ai_square/tests -q
node pt_ai_square/tests/test_upload_ui.cjs
```

## 기존 버전에서 새 폴더 구조로 바꿀 때

1. 실행 중인 서버를 멈추고 기존 runtime_config.py와 PTAI_DATA_DIR의 실제 파일 저장소를 백업합니다.
2. 새 Git ZIP은 기존 코드 위에 겹쳐 풀지 말고 새 폴더에 풉니다. 겹쳐 풀면 이전 최상위 파일이 그대로 남습니다.
3. 기존 runtime_config.py를 새 앱 폴더로 복사합니다. 설정의 PTAI_DATA_DIR이 기존 영구 저장소를 가리키는지 확인합니다.
4. 기본 instance 폴더에 저장하던 경우에는 해당 폴더도 보존하여 옮기거나 절대 경로로 연결합니다. 경로 변경만으로 파일이 이동되지는 않습니다.
5. 기존 MongoDB 주소·DB 이름을 유지하고 회사의 기존 절차로 모든 작업 프로세스를 재시작하거나 교체합니다. 직접 실행 방식은 python index.py입니다. 회사 실행기는 index:application을 불러오며 기존 web_main:app 설정도 호환됩니다. 회사 실행 방식과 포트를 임의로 바꾸지 않습니다.
6. 로그인, 기존 도구 조회, 파일 다운로드를 확인합니다. 쓰기 안정화 반영 시 검수용 게시·좋아요·저장 공간 한도 저장을 각각 한 번 실행하고 새로고침 후 결과가 유지되는지도 확인합니다. 한도에는 승인된 운영 값을 사용합니다.

실행 후 생기는 __pycache__, instance, .preview, .local-mongo 등은 실행 데이터·캐시이며 Git 소스에는 포함하지 않습니다. 운영 자료를 정리 목적으로 삭제하지 마세요. 실제 runtime_config.py도 Git에서 제외하며 코드 업데이트 때 보존합니다.
