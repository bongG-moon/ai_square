# P&T AI SQUARE v3.1

Flask + MongoDB로 구현한 사내 AI 도구 공유 웹입니다. 모든 서비스 정보는 MongoDB에 저장하고, 업로드 파일만 서버 디스크에 저장합니다. SQLite 실행 모드는 없습니다.

- [초보자용 실행·사용 안내](pt_ai_square/GUIDE_V3.md)
- [최신 상세 기획서](pt_ai_square/PLAN_V3.md)
- [설정 파일 예시](pt_ai_square/runtime_config.example.py)

## 빠른 실행

**화면만 체험할 때는 MongoDB와 설정 파일 없이** 아래 명령으로 실행합니다. `pt_ai_square/demo/catalog.json`의 예시 10개를 표시하며 등록·좋아요·수정·다운로드는 저장되지 않습니다. 실제 등록을 하려면 `runtime_config.example.py`를 `runtime_config.py`로 복사해 `MONGODB_URI`, 로그인 방식, DB 이름, 기본 관리자 사번을 입력합니다. `.env`는 사용하지 않습니다. 이미 설정된 MongoDB가 연결되지 않는 경우에는 오류를 표시하며 더미 데이터로 대체하지 않습니다.

```powershell
python -m venv .venv-square
.venv-square\Scripts\python.exe -m pip install -r pt_ai_square\requirements.txt
.venv-square\Scripts\python.exe -m pt_ai_square run
```

브라우저: http://127.0.0.1:5080/

`mock`은 로컬 전용 개발 인증입니다. 운영은 `local` 또는 회사 `sso`를 설정합니다. 비밀번호 포함 URI·세션 키가 들어 있는 runtime_config.py는 Git이나 배포 ZIP에 포함하지 않습니다.

## 기존 자료 이전

기존 서버를 멈추고 같은 파일 저장 경로를 유지한 상태에서 실행합니다.

```powershell
.venv-square\Scripts\python.exe -m pt_ai_square migrate-legacy "pt_ai_square\.preview\square.sqlite3"
```

원본은 읽기 전용으로 보존합니다. 이전 명령만 SQLite를 읽으며, 실행 중 웹은 MongoDB만 사용합니다. 이전 중인 DB에 대한 웹 요청은 차단됩니다.

## 개발

```powershell
python -m pt_ai_square.build_workspace
.venv-square\Scripts\python.exe -m pytest pt_ai_square\tests -q
```

MongoDB 통합 테스트는 별도 임시 DB에서 실행합니다.

실제 사내 SSO, 운영 배포, PC 설치·자동 업데이트 연동은 별도 검증 범위입니다. 새 메뉴·권한·알림의 세부 동작은 GUIDE_V3.md를 확인하세요.

## 소스 구성

- `pt_ai_square/demo/`: DB 없는 화면 체험용 가상 자료
- `pt_ai_square/static/guides/`: 다운로드할 배포 Skill 원본·ZIP·HTML 안내
- `pt_ai_square/runtime_config.example.py`: 복사해서 작성할 설정 예시
- `pt_ai_square/frontend_workspace.js`: 등록 관리·관리자·요청·알림 UI (수정 후 `python -m pt_ai_square.build_workspace`)
- `pt_ai_square/static/`: 실행 가능한 완성 UI. Node 빌드 없이 실행합니다.
- `pt_ai_square/build_frontend.py`: 과거 시안 가져오기용 선택 도구. 일반 실행·수정에서는 사용하지 않습니다.

테스트하려면 `python -m pip install pytest` 후 `python -m pytest pt_ai_square/tests -q`를 실행합니다. 로컬 MongoDB 기본 시험 주소는 `mongodb://127.0.0.1:27018/`이며 테스트는 별도 임시 DB를 생성·삭제합니다. 다른 시험 주소는 프로세스 환경변수 `PTAI_TEST_MONGO_URI`로 지정합니다. DB 없이 데모만 시험하려면 `python -m pytest pt_ai_square/tests/test_demo.py -q`를 실행합니다.

## 현재 검증 범위

2026-10-18, Windows / Python 3.13 / 로컬 MongoDB에서 25개 테스트 통과. Skill·MCP의 MD+Python ZIP 게시 → 파일 해시·바이트 확인 → v2 등록 → v1 배포 복구를 검증했습니다. 도구 자체의 업무 동작, 실제 회사 SSO와 운영 배포는 각 회사 환경에서 별도로 확인해야 합니다. 웹 버전 관리와 PC 자동 설치·업데이트는 다릅니다.

## 실행 시 버전 확인

`GET /api/tools/{id}/version-check?release={설치된번호}`는 현재 배포와 설치 버전을 비교하는 인증된 읽기 전용 API입니다. 새 버전·서버 롤백을 구분하며 파일을 다운로드하거나 교체하지 않습니다. 배포 Skill에 Python 예제를 포함했습니다. 각 도구의 실행 지점과 운영 인증 클라이언트 연결이 필요합니다. [등록자용 연결 안내](pt_ai_square/static/guides/pt-file-distribution/assets/VERSION_CHECK_GUIDE.md)를 확인하세요.
