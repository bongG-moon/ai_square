# P&T AI SQUARE v3.3

Flask + MongoDB로 구현한 사내 AI 도구 공유 웹입니다. 모든 서비스 정보는 MongoDB에 저장하고, 업로드 파일만 서버 디스크에 저장합니다. SQLite 실행 모드는 없습니다.

- [실행·운영 안내](docs/OPERATOR_GUIDE.md)
- [SSO 운영 설정 상세 가이드 — 입력 값·배포·관리자·API 검수](docs/SSO_OPERATIONS_GUIDE.md)
- [사용자·등록자 안내](docs/USER_GUIDE.md)
- [최신 상세 기획서](docs/PLAN_V3.md)
- [설정 파일 예시](runtime_config.example.py)
- [개발자를 위한 폴더 구조](docs/PROJECT_STRUCTURE.md)
- [회사 Flask 포맷 / HCP SSO 배포 안내](docs/HCP_DEPLOYMENT.md)
- [로컬 검색·다운로드 및 인증키 안내](docs/LOCAL_RECEIVER.md)

## 빠른 실행

최근 반영: SSO 사번·이름·부서명·부서코드를 기존 사용자와 연결하고, 상단에 이름 TL·프로필 사진과 연결 KEY 바로가기를 표시합니다. 기여도 순위는 구성원이 등록한 도구 5점 + 받은 좋아요 2점 + 고유 다운로드 1점으로 전체 기간을 집계합니다. 새 연결 KEY는 유효기간 선택 없이 발급하고 사번당 하나만 활성화합니다. MongoDB에 사번과 KEY 해시를 연결해 저장하며 재발급·사용 취소·계정 비활성화 후에는 인증되지 않습니다. 기존 기간형 KEY는 원래 만료일을 유지합니다. 배포 Skill이 작성한 `workflow.steps`는 도구 상세에서 순서도로 표시합니다. 기존 설정·업로드 파일·MongoDB 데이터를 지우거나 초기화할 필요는 없습니다.

`runtime_config.example.py`를 `runtime_config.py`로 복사하고 실제 `MONGODB_URI`, `MONGODB_DATABASE`를 입력합니다. SSO 기본값은 미사용(mock)입니다. 로컬에서도 같은 MongoDB와 파일 저장소로 실제 업로드·다운로드·버전 관리를 수행합니다. DB 미설정 시 설정 오류를 표시합니다. .env는 사용하지 않습니다.

```powershell
python -m pip install -r requirements.txt
python index.py
```

같은 PC의 브라우저에서 실행 터미널에 표시된 로컬 주소를 엽니다. 회사에 배포한 뒤에는 회사에서 발급한 HTTPS 웹 주소로 접속합니다.

위 명령은 `index.py`, `web_main.py`, `requirements.txt`가 들어 있는 폴더에서 실행합니다. 이 폴더만 복사하면 되고, 상위 프로젝트나 `pt_ai_square`라는 폴더 이름은 필요하지 않습니다. VS Code에서는 **index.py의 Python 파일 실행**을 누릅니다. `web_main.py`는 앱을 만드는 파일이며 단독 실행으로 서버를 시작하지 않습니다.

`index.py`는 회사 기본 코드대로 `from web_main import app as application`으로 앱을 불러오고, 직접 실행할 때 `application.run(debug=True, host='0.0.0.0')`를 호출합니다. 별도 포트 지정이나 Waitress 자동 선택은 하지 않습니다. 회사 실행기가 `index:application`을 불러오면 이 실행문은 호출되지 않습니다. 기존 실행기가 `web_main:app`을 사용 중이면 같은 앱을 그대로 불러올 수 있습니다. 회사의 실행 방식·포트 설정을 임의로 바꾸지 않습니다.

기본 인증 모드는 SSO를 사용하지 않는 `mock`이며 기본 시험 사번은 `1000001`입니다. `runtime_config.py`의 `PTAI_MOCK_USER`로 시험 사번을 바꿀 수 있습니다. 환경변수나 설정 파일에 명시한 값이 있으면 해당 값이 기본값보다 우선합니다. 기존 로컬 보조 명령 `python __main__.py run`도 남아 있으며, `PTAI_HOST`·`PTAI_PORT`는 이 보조 명령에서만 사용합니다. 회사 기본 `index.py`의 실행 설정에는 영향을 주지 않습니다.

`mock`은 로컬 전용 개발 인증입니다. 회사 운영은 `sso`를 설정합니다. 별도 아이디·비밀번호 로그인은 없습니다. mock에서도 MongoDB가 연결되어 있으면 업로드·업데이트·권한·알림이 실제로 저장됩니다. 비밀번호 포함 URI·세션 키가 들어 있는 runtime_config.py는 Git이나 배포 ZIP에 포함하지 않습니다.

## 기존 자료 이전

기존 서버를 멈추고 같은 파일 저장 경로를 유지한 상태에서 실행합니다.

```powershell
python __main__.py migrate-legacy ".preview\square.sqlite3"
```

원본은 읽기 전용으로 보존합니다. 이전 명령만 SQLite를 읽으며, 실행 중 웹은 MongoDB만 사용합니다. 이전 중인 DB에 대한 웹 요청은 차단됩니다.

## 개발

```powershell
python scripts/build_workspace.py
python scripts/build_guides.py
python -m pytest tests -q
```

위 명령은 이 폴더 안에서 실행합니다. 테스트는 상위 디렉토리에서 `python -m pytest pt_ai_square/tests -q`로도 실행할 수 있습니다.

### 소스 구조

| 위치 | 역할 |
|---|---|
| `index.py`, `web_main.py`, `run_server.cmd` | 회사 기본 실행 진입점 / Flask 앱 / Windows index.py 실행 바로가기 |
| `runtime_config.py`, `runtime_config.example.py`, `config.py` | 개인 운영 설정 / 설정 예시 / 설정 로더 |
| `backend/` | Flask API, SSO, MongoDB, 권한, 파일 검사·저장, 배포 정보 |
| `frontend/` | 화면 기능별 JS 원본. `frontend_workspace.js`, `frontend_upload.js`, `frontend_package.js`, `frontend_commands.js`는 build_workspace로 반영 |
| `static/app.js` | 실제 로딩되는 앱. 기본 화면·Core·일부 초기 fragment는 이 파일도 함께 수정. 현재 완전한 번들 빌드 구조는 아님 |
| `static/`, `templates/` | CSS·아이콘·폰트·HTML과 다운로드용 가이드/Skill |
| `scripts/` | 화면 확장 조립, 가이드 생성, 로컬 개발 도구 |
| `docs/` | 기획서·사용자 가이드·실행/운영 안내 |
| `tests/` | 임시 MongoDB를 사용하는 통합 테스트 및 UI 로직 검사 |
| `dummy/` | 샘플 화면용 자료. 실제 DB 장애 시 자동 대체하지 않음 |

`scripts/build_frontend.py`는 초기 디자인 가져오기용입니다. 현재 화면을 덮어쓰므로 일반 개발에서 실행하지 않습니다. 기존 테스트 임시 폴더는 프로젝트 밖의 `outputs/square-local-archive-20261020`으로 옮겼으며, 실제 저장소와 로컬 MongoDB 경로는 유지했습니다.

### 배포 형식과 설치 범위

- ZIP의 배포 정보를 읽지 못해도 직접 입력한 정보로 게시할 수 있습니다. 경로 탈출·손상 ZIP 등 기본 파일 검사 실패는 계속 차단됩니다.
- 단일 `.md`는 압축하지 않고 그대로 업로드·다운로드합니다. 여러 보조 파일이 필요한 경우 ZIP을 사용합니다.
- **명령어 안내**는 파일 없이 범위별 명령어를 MongoDB의 각 버전에 저장합니다. 사용자가 범위를 선택하고 복사하여 터미널에서 실행합니다. 서버에서 실행하거나 EXE로 만들지 않습니다.
- 배포 Skill은 실제 구조를 보고 유형을 정하고 ZIP 선언에 기록합니다. 웹은 이 선언을 읽습니다. 단일 MD·URL·명령어는 등록자가 유형을 선택합니다.
- Skill의 설치 템플릿은 범위 기본값 없이 프로젝트/사용자 전역을 선택하도록 합니다. 임의의 기존 EXE 내부 동작을 웹이 변경하지는 않습니다.

MongoDB 통합 테스트는 별도 임시 DB에서 실행합니다. `tests/legacy_reference`의 텍스트는 이전 SQL 구현 테스트를 보관한 참고 자료이며 현재 테스트는 MongoDB 전용으로 대체했습니다.

실제 사내 SSO, 운영 배포, PC 설치·자동 업데이트 연동은 별도 검증 범위입니다. 새 메뉴·권한·알림의 세부 동작은 GUIDE_V3.md를 확인하세요.

실행 시 **버전만 확인**하는 읽기 전용 API(`/api/tools/{id}/version-check?release=1`)와 배포 Skill의 Python 예제를 제공합니다. 새 버전·서버 롤백을 알리고 파일은 교체하지 않습니다. 개별 도구 실행 지점과 운영 인증 클라이언트 연결이 필요합니다. [연결 안내](static/guides/pt-file-distribution/assets/VERSION_CHECK_GUIDE.md)를 확인하세요.

## 샘플 데이터 화면

runtime_config.py에서 `PTAI_DATA_MODE = 'dummy'`, `PTAI_AUTH_MODE = 'mock'`으로 설정하고 재시작하면 별도 dummy 폴더의 가짜 데이터로 화면을 볼 수 있습니다. 조회 전용이며 실제 DB에 연결하거나 저장하지 않습니다. 실제 업로드·다운로드·버전 관리는 기본값 `PTAI_DATA_MODE = 'mongodb'`를 사용하세요. 연결 장애 시 자동으로 샘플 모드가 되지는 않습니다.

ZIP·EXE 등은 업로드한 원본으로 배포합니다. MCP·소스를 EXE로 자동 변환하는 빌드 기능은 현재 없습니다.

## 배포 Skill 연결

Skill이 만든 ZIP 최상위 `ai-square.json`을 웹에서 읽고 필수 파일을 검사합니다. **도구 등록 → ZIP에서 불러오기**로 자동 입력한 뒤 게시하면 원본 ZIP과 별도의 배포 정보 JSON(ID·버전·해시·버전 확인 주소)을 제공합니다. 기존 일반 파일과 URL도 등록할 수 있습니다. 코드 변환·EXE 생성·PC 설치는 수행하지 않습니다.
## 관리자 파일 저장 한도

**관리자 → 저장 공간**에서 직접 한도 지정 또는 디스크 여유 공간에 따른 자동 계산을 선택합니다. 확보할 여유 공간과 한도는 MongoDB에 저장하고 재시작 없이 적용합니다. 원격 MongoDB 용량이 아닌 DATA_DIR 디스크 기준이며 파일을 자동 삭제하지 않습니다. 자세한 적용 범위와 운영 제약은 [실행·운영 안내](docs/OPERATOR_GUIDE.md)의 저장 한도 항목을 확인하세요.
