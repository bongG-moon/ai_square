# P&T AI SQUARE v3.3

Flask + MongoDB로 구현한 사내 AI 도구 공유 웹입니다. 모든 서비스 정보는 MongoDB에 저장하고, 업로드 파일만 서버 디스크에 저장합니다. SQLite 실행 모드는 없습니다.

- [실행·운영 안내](OPERATOR_GUIDE.md)
- [사용자·등록자 안내](USER_GUIDE.md)
- [최신 상세 기획서](PLAN_V3.md)
- [설정 파일 예시](runtime_config.example.py)
- [회사 Flask 포맷 / HCP SSO 배포 안내](HCP_DEPLOYMENT.md)

## 빠른 실행

`runtime_config.example.py`를 `runtime_config.py`로 복사하고 실제 `MONGODB_URI`, `MONGODB_DATABASE`를 입력합니다. SSO 기본값은 미사용(mock)입니다. 로컬에서도 같은 MongoDB와 파일 저장소로 실제 업로드·다운로드·버전 관리를 수행합니다. DB 미설정 시 설정 오류를 표시합니다. .env는 사용하지 않습니다.

```powershell
python -m pip install -r requirements.txt
python web_main.py
```

브라우저: http://127.0.0.1:5080/

위 명령은 `web_main.py`와 `requirements.txt`가 들어 있는 폴더에서 실행합니다. 이 폴더만 복사하면 되고, 상위 프로젝트나 `pt_ai_square`라는 폴더 이름은 필요하지 않습니다. VS Code의 **Python 파일 실행**도 지원합니다. WSGI 진입점은 해당 폴더 기준 `web_main:app`입니다. 기존 패키지 실행도 계속 지원합니다.

로컬 `mock`에서는 Waitress가 없어도 Flask 내장 서버로 실행합니다(디버그·자동 재시작 꺼짐). SSO 운영은 Waitress를 설치하거나 회사 WSGI 실행기를 사용하세요. 설치는 실행에 사용하는 동일한 Python에서 진행해야 합니다.

기본 인증 모드는 SSO를 사용하지 않는 `mock`입니다. 별도 설정이 없으면 로컬 주소 `http://127.0.0.1:5080`에서 실행되며 기본 시험 사번은 `1000001`입니다. `runtime_config.py`의 `PTAI_MOCK_USER`로 시험 사번을 바꿀 수 있습니다. 환경변수나 설정 파일에 명시한 값이 있으면 해당 값이 기본값보다 우선합니다.

`mock`은 로컬 전용 개발 인증입니다. 회사 운영은 `sso`를 설정합니다. 별도 아이디·비밀번호 로그인은 없습니다. mock에서도 MongoDB가 연결되어 있으면 업로드·업데이트·권한·알림이 실제로 저장됩니다. 비밀번호 포함 URI·세션 키가 들어 있는 runtime_config.py는 Git이나 배포 ZIP에 포함하지 않습니다.

## 기존 자료 이전

기존 서버를 멈추고 같은 파일 저장 경로를 유지한 상태에서 실행합니다.

```powershell
python __main__.py migrate-legacy ".preview\square.sqlite3"
```

원본은 읽기 전용으로 보존합니다. 이전 명령만 SQLite를 읽으며, 실행 중 웹은 MongoDB만 사용합니다. 이전 중인 DB에 대한 웹 요청은 차단됩니다.

## 개발

```powershell
python -m pt_ai_square.build_workspace
.venv-square\Scripts\python.exe -m pytest pt_ai_square\tests -q
```

MongoDB 통합 테스트는 별도 임시 DB에서 실행합니다. `tests/legacy_reference`의 텍스트는 이전 SQL 구현 테스트를 보관한 참고 자료이며 현재 테스트는 MongoDB 전용으로 대체했습니다.

실제 사내 SSO, 운영 배포, PC 설치·자동 업데이트 연동은 별도 검증 범위입니다. 새 메뉴·권한·알림의 세부 동작은 GUIDE_V3.md를 확인하세요.

실행 시 **버전만 확인**하는 읽기 전용 API(`/api/tools/{id}/version-check?release=1`)와 배포 Skill의 Python 예제를 제공합니다. 새 버전·서버 롤백을 알리고 파일은 교체하지 않습니다. 개별 도구 실행 지점과 운영 인증 클라이언트 연결이 필요합니다. [연결 안내](static/guides/pt-file-distribution/assets/VERSION_CHECK_GUIDE.md)를 확인하세요.

## 샘플 데이터 화면

runtime_config.py에서 `PTAI_DATA_MODE = 'dummy'`, `PTAI_AUTH_MODE = 'mock'`으로 설정하고 재시작하면 별도 dummy 폴더의 가짜 데이터로 화면을 볼 수 있습니다. 조회 전용이며 실제 DB에 연결하거나 저장하지 않습니다. 실제 업로드·다운로드·버전 관리는 기본값 `PTAI_DATA_MODE = 'mongodb'`를 사용하세요. 연결 장애 시 자동으로 샘플 모드가 되지는 않습니다.

ZIP·EXE 등은 업로드한 원본으로 배포합니다. MCP·소스를 EXE로 자동 변환하는 빌드 기능은 현재 없습니다.

## 배포 Skill 연결

Skill이 만든 ZIP 최상위 `ai-square.json`을 웹에서 읽고 필수 파일을 검사합니다. **도구 등록 → ZIP에서 불러오기**로 자동 입력한 뒤 게시하면 원본 ZIP과 별도의 배포 정보 JSON(ID·버전·해시·버전 확인 주소)을 제공합니다. 기존 일반 파일과 URL도 등록할 수 있습니다. 코드 변환·EXE 생성·PC 설치는 수행하지 않습니다.
