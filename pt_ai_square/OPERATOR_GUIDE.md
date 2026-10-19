# P&T AI SQUARE 실행·운영 가이드

웹 서버를 실행하는 담당자용입니다. 웹에서 내려받는 사용자·등록자 가이드와 분리되어 있습니다.

## 1. 폴더 준비

pt_ai_square 폴더 전체를 복사합니다. web_main.py, __main__.py, __init__.py, _square_bootstrap.py 등 Python 파일과 templates·static 폴더가 함께 있어야 합니다. 상위 프로젝트나 고정 폴더 이름은 필요하지 않습니다. 업데이트할 때 기존 runtime_config.py와 업로드 저장 폴더를 보존하세요.

## 2. 패키지 설치

web_main.py가 있는 폴더에서 터미널을 엽니다.

```powershell
python -m pip install -r requirements.txt
```

VS Code에서 선택한 Python과 설치에 쓰는 Python이 같아야 합니다. 특정 Python을 사용한다면 아래처럼 같은 실행 파일로 설치합니다. 사내망에서는 회사에서 안내한 pip 저장소 설정을 사용하세요.

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe" -m pip install -r requirements.txt
```

## 3. 설정 입력

runtime_config.example.py를 같은 폴더의 runtime_config.py로 복사해 값을 입력합니다. .env는 읽지 않습니다. 프로세스 환경변수가 있으면 Python 파일보다 우선합니다.

```python
PTAI_DATA_MODE = 'mongodb'  # 실제 저장. 가짜 화면 확인은 'dummy'
PTAI_AUTH_MODE = 'mock'
PTAI_MOCK_USER = '1000001'
PTAI_MOCK_NAME = '테스트 사용자'
PTAI_MOCK_ADMIN = True
PTAI_COOKIE_SECURE = False
PTAI_HOST = '127.0.0.1'
PTAI_PORT = 5080
MONGODB_URI = '실제 MongoDB 연결 주소'
MONGODB_DATABASE = '사용할 DB 이름'
# 선택: 업로드 자료를 보존할 절대 경로
# PTAI_DATA_DIR = r'C:\pt_ai_square_data'
```

기본 DATA_MODE='mongodb'에서는 로컬에서도 실제 DB를 사용합니다. 정보를 비워두면 설정을 요청하는 오류가 나오며 예시 데이터로 자동 대체하지 않습니다. 시험용 DB를 운영 DB와 분리하면 운영 자료에 영향을 주지 않고 확인할 수 있습니다. 비밀번호 포함 URI와 세션 키는 Git에 올리지 마세요.

## 샘플 데이터로 화면 확인하기

실제 자료를 바꾸지 않고 목록·순위·상세·등록 관리 화면을 보려면 runtime_config.py의 두 값을 설정합니다.

```python
PTAI_DATA_MODE = 'dummy'
PTAI_AUTH_MODE = 'mock'
```

서버를 종료하고 다시 실행한 뒤 브라우저를 새로고침합니다. 상단에 **샘플 데이터 · 조회 전용**이 표시됩니다. MongoDB 주소가 이미 있어도 연결하지 않으므로 지울 필요가 없습니다. 샘플은 별도 dummy/catalog.json 폴더 파일에서 읽고, 설정 사번은 처음 3개 예시 도구의 등록자로 표시됩니다. 실제 MongoDB나 업로드 폴더는 바뀌지 않습니다.

이 모드는 조회 전용입니다. 업로드·좋아요·수정·승인·실제 다운로드를 누르면 저장하지 않고 안내합니다. 실제 업로드·다운로드·버전 관리 점검은 DATA_MODE를 'mongodb'로 되돌려 재시작하세요. 회사 SSO와 함께 사용하는 모드는 'mongodb'입니다.

| 설정 조합 | 동작 |
|---|---|
| mock + mongodb | 설정 사번으로 접속, 실제 DB·파일 저장 및 버전 관리 |
| sso + mongodb | 회사 SSO 사용자로 접속, 실제 DB·파일 저장 및 버전 관리 |
| mock + dummy | 설정 사번으로 가짜 데이터 화면 조회, DB 연결 및 저장 없음 |

프로세스 환경변수 PTAI_DATA_MODE가 있으면 파일보다 우선합니다. 파일을 고쳤는데 모드가 바뀌지 않으면 실행 환경의 같은 이름 변수를 확인하세요. MongoDB 장애가 발생해도 dummy로 자동 전환하지 않습니다.

## 4. 실행과 종료

```powershell
python web_main.py
```

VS Code에서 web_main.py의 Python 파일 실행을 눌러도 됩니다. 터미널을 켜 둔 채 http://127.0.0.1:5080/ 을 엽니다. Ctrl+C로 종료하고, 설정 변경 후 다시 실행합니다. python __main__.py run도 지원합니다.

mock은 SSO 미사용이며 설정 사번으로 동작합니다. 로컬에서 Waitress가 없으면 Flask 내장 서버로 실행합니다. 디버그와 자동 재시작은 꺼져 있습니다. Flask·pymongo 기본 패키지는 여전히 필요합니다.

## 5. 회사 SSO 및 배포

회사 환경에서 hcputil을 설치한 뒤 PTAI_AUTH_MODE를 'sso'로 바꾸고 HTTPS 환경에서는 PTAI_COOKIE_SECURE를 True로 설정합니다. 기본 관리자 사번은 PTAI_ADMIN_IDS에 쉼표로 구분하고 추가 관리자는 관리자 메뉴에서 지정합니다. 상세 회사 인증 흐름은 HCP_DEPLOYMENT.md를 참고하세요.

회사 WSGI 실행기는 이 폴더에서 web_main:app을 불러옵니다. 이때 별도 서버를 시작하지 않습니다. SSO 모드로 직접 실행할 때는 Waitress가 필요합니다. 실제 사내 인증은 회사 환경에서 검증해야 합니다. 인증 이후의 저장·권한·버전 API는 SSO 사용과 미사용이 동일합니다.

## 6. MongoDB와 파일 저장소

| 저장 위치 | 저장 내용 |
|---|---|
| MongoDB | 도구 설명·등록자·조직·업무, 버전·파일명·경로 식별자·크기·해시, 권한, 좋아요·다운로드 이력, 요청·답변·담당자·첨부 정보, 개인 알림 |
| DATA_DIR/artifacts | ZIP·EXE·MSI·PS1 배포 파일 원본 |
| DATA_DIR/request_attachments | 요청에 첨부한 이미지·PDF·문서·ZIP 원본 |

DATA_DIR 기본값은 앱 폴더의 instance입니다. DB와 DATA_DIR을 함께 백업하고 서버 재배포 시 저장 폴더를 보존하세요. 첨부는 인증된 API로 다운로드하며 저장 폴더를 정적 URL로 공개하지 않습니다. 저장 공간 사용량에는 두 파일 폴더가 모두 포함됩니다.

관리자 → 저장 공간의 이전 버전 정리는 배포 파일에 적용합니다. 요청 첨부는 요청과 함께 보관하며 배포 정리로 삭제하지 않습니다. DB 응답이 끊겨 저장 여부가 불명확하면 파일을 보존하므로 장애 복구 후 연결되지 않은 파일은 별도 운영 점검이 필요합니다.

## 7. 실행 후 점검 순서

1. SSO 미사용 표시와 설정한 사번을 확인합니다.
2. 작은 ZIP을 도구 등록으로 게시하고 다운로드해 원본을 확인합니다.
3. 등록 관리 → 버전에서 새 ZIP을 게시해 v2 발급을 확인합니다.
4. 이전 버전으로 복구하고 다운로드 대상이 바뀌는지 확인합니다.
5. 기능 요청에 이미지나 문서를 첨부하고 다운로드합니다.
6. 서버 재시작 후 도구·요청·파일이 유지되는지 확인합니다.

## 8. 배포 파일과 EXE

웹은 파일 형식을 변환하지 않습니다. EXE는 제작자가 만든 완성 파일을 업로드하며 ZIP은 ZIP으로 배포합니다. 일반 Python·Skill·MCP의 자동 EXE 변환은 구현되어 있지 않습니다. 설치·연결 안내는 파일 실행, Skill 폴더 배치, 재시작, MCP URL 연결 등 사용을 시작할 절차를 설명하는 항목입니다.

### 실제 등록 예시

1. 개발자가 MCP 소스가 담긴 검색도구.zip을 올립니다.
2. 서버가 파일 형식·크기·ZIP 경로 등을 검사하고 v1을 발급합니다.
3. 사용자는 검색도구.zip 원본을 내려받습니다. 검색도구.exe가 만들어지지 않습니다.
4. 개발자가 완성된 설치용 검색도구.exe를 올렸다면 그 EXE 원본을 배포합니다.
5. 다음 파일을 새 버전으로 올리면 v2가 되고 이전 v1로 배포 대상을 복구할 수 있습니다.

배포 번호는 플랫폼의 파일 버전이며 EXE 내부의 프로그램 버전을 다시 작성하지 않습니다. 과거 기획에서 다룬 자동 설치 EXE 생성은 현재 구현과 다릅니다. 현재 Flask 서버에는 NSIS 등의 설치 파일 생성 과정이나 Python 소스 컴파일 과정이 없습니다. EXE 제작은 LLM의 필수 작업이 아니라 별도의 빌드 도구와 유형별 설치 규칙이 필요한 기능입니다. 모든 MCP·Skill·플러그인 파일을 일괄적으로 EXE로 바꾸는 기능은 제공하지 않습니다.

## 9. 오류 확인

- requirements 오류: 실행과 설치에 같은 Python을 쓰는지 확인합니다.
- 상대 import 오류: web_main.py 한 파일만 바꾸지 말고 최신 관련 Python 파일 전체를 갱신합니다.
- MongoDB 오류: URI·DB 이름·네트워크·계정 권한을 확인합니다. 예시 자료나 SQLite로 대체하지 않습니다.
- 주소 사용 중: 먼저 실행한 터미널을 종료하거나 PTAI_PORT를 바꿉니다.
