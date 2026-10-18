# P&T AI SQUARE v3.1

Flask + MongoDB로 구현한 사내 AI 도구 공유 웹입니다. 모든 서비스 정보는 MongoDB에 저장하고, 업로드 파일만 서버 디스크에 저장합니다. SQLite 실행 모드는 없습니다.

- [초보자용 실행·사용 안내](GUIDE_V3.md)
- [최신 상세 기획서](PLAN_V3.md)
- [설정 파일 예시](runtime_config.example.py)

## 빠른 실행

**화면만 체험할 때는 MongoDB와 설정 파일 없이** 아래 명령으로 실행합니다. `demo/catalog.json`의 예시 10개를 표시하며 등록·좋아요·수정·다운로드는 저장되지 않습니다. 실제 등록을 하려면 `runtime_config.example.py`를 `runtime_config.py`로 복사해 `MONGODB_URI`, 로그인 방식, DB 이름, 기본 관리자 사번을 입력합니다. `.env`는 사용하지 않습니다. 이미 설정된 MongoDB가 연결되지 않는 경우에는 오류를 표시하며 더미 데이터로 대체하지 않습니다.

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

MongoDB 통합 테스트는 별도 임시 DB에서 실행합니다. `tests/legacy_reference`의 텍스트는 이전 SQL 구현 테스트를 보관한 참고 자료이며 현재 테스트는 MongoDB 전용으로 대체했습니다.

실제 사내 SSO, 운영 배포, PC 설치·자동 업데이트 연동은 별도 검증 범위입니다. 새 메뉴·권한·알림의 세부 동작은 GUIDE_V3.md를 확인하세요.
