# P&T AI SQUARE v3.3

Flask + MongoDB 사내 도구 공유 플랫폼입니다. 인증만 SSO 사용(sso)과 미사용(mock)으로 구분하며 로컬에서도 실제 업로드·다운로드·버전 관리가 동작합니다.

## 폴더 하나로 실행

저장소의 `pt_ai_square` 폴더 전체를 복사합니다. 상위 프로젝트나 고정된 폴더 이름은 필요하지 않습니다. `web_main.py`가 있는 폴더에서 실행하세요.

1. `runtime_config.example.py`를 `runtime_config.py`로 복사합니다.
2. 실제 `MONGODB_URI`, `MONGODB_DATABASE`와 테스트 사번 `PTAI_MOCK_USER`를 입력합니다. 기본 인증 모드는 mock입니다.
3. 다음 명령으로 설치하고 실행합니다.

```powershell
python -m pip install -r requirements.txt
python web_main.py
```

브라우저에서 http://127.0.0.1:5080/ 을 엽니다. MongoDB 미설정 시 설정을 요청하며 대체 데이터로 전환하지 않습니다. mock에서 Waitress가 없으면 로컬 Flask 서버로 실행합니다. SSO 직접 실행은 Waitress가 필요합니다. 회사 WSGI 진입점은 해당 폴더 기준 `web_main:app`입니다. 기존 패키지 실행도 지원합니다.

`.env`는 읽지 않습니다. 프로세스 환경변수 > runtime_config.py > 기본값 순서입니다. 비밀번호·연결 URI가 들어 있는 개인 설정 파일은 Git에 포함하지 마세요.

## 가이드

- [실행·운영 담당자 안내](pt_ai_square/OPERATOR_GUIDE.md)
- [사용자·등록자 안내](pt_ai_square/USER_GUIDE.md)
- [회사 Flask / SSO 배포](pt_ai_square/HCP_DEPLOYMENT.md)
- [상세 기획서](pt_ai_square/PLAN_V3.md)

`docs`에는 별도 실행·운영 HTML이 있습니다. 웹에서 다운로드하는 가이드는 사용자·등록자 내용만 담습니다.

## 저장과 배포

MongoDB에는 도구·버전·권한·사용 이력·요청·첨부 정보·알림을 저장합니다. 배포 원본은 DATA_DIR/artifacts, 기능 요청 첨부 원본은 DATA_DIR/request_attachments에 저장합니다. DB와 파일 폴더를 함께 백업하세요.

파일은 원본 형식으로 배포하며 자동 EXE 변환은 하지 않습니다. 실행 시 버전 확인 API와 Skill 예제를 제공하며 사용자 PC의 파일은 자동 교체하지 않습니다. 회사 SSO 실제 로그인 및 개별 도구 설치 호환성은 사내 환경에서 확인해야 합니다.

## 검증

테스트는 저장소 상위에서 `python -m pytest pt_ai_square/tests -q`로 실행합니다. MongoDB 시험 주소는 `PTAI_TEST_MONGO_URI` 또는 기본 `mongodb://127.0.0.1:27018/`이며 임시 DB만 생성·삭제합니다. 파일 UI 단위 검증은 `node pt_ai_square/tests/test_upload_ui.cjs`입니다.

## 샘플 데이터 화면

실제 MongoDB를 연결하지 않고 화면만 보려면 runtime_config.py에서 `PTAI_DATA_MODE = 'dummy'`, `PTAI_AUTH_MODE = 'mock'`으로 설정하고 서버를 재시작합니다. 별도 `pt_ai_square/dummy/catalog.json`의 가짜 데이터로 목록·순위·상세 화면을 표시하며 쓰기·파일 다운로드는 차단합니다. 실제 DB 연결 정보는 남겨 두어도 사용하지 않습니다.

실제 저장·업로드·버전 관리는 기본값 `PTAI_DATA_MODE = 'mongodb'`를 사용합니다. DB 장애 시 가짜 데이터로 자동 전환하지 않습니다. 설정 파일 예시에는 각 값의 용도·단위·입력 예시를 한국어 주석으로 제공합니다.
