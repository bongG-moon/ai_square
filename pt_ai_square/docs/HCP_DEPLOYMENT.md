# 회사 Flask 기본 포맷과 연결되는 방식

## 운영 서버가 불러오는 파일

회사 기본 예제의 핵심은 `web_main.py`에 Flask 객체인 `app`이 존재하고, 그 객체에 화면 경로와 SSO 경로가 등록되어 있는 것입니다. 이 프로젝트는 `create_app()` 안에서 `Flask(...)`를 만들고 그 결과를 `web_main.py`의 `app`으로 제공합니다. 회사 서버에서 모듈을 불러올 때 별도 웹 서버를 실행하지 않습니다.

| 실행 환경 | 진입점 |
|---|---|
| 회사 실행기가 web_main.py가 있는 폴더에서 모듈을 불러옴 | `web_main:app` |
| 패키지의 상위 폴더에서 WSGI 실행기가 불러옴 | `pt_ai_square.web_main:app` |
| 개발자가 VS Code에서 파일 실행 | `python web_main.py` — 이때만 웹 서버 시작 |

`web_main.py`가 있는 폴더 전체만 배포하면 됩니다. 상위 프로젝트나 고정 폴더 이름이 필요하지 않습니다. 로컬 mock 모드에서는 Waitress가 없을 경우 Flask 내장 서버를 사용하며 디버그·자동 재시작은 끕니다. SSO 직접 실행은 Waitress가 필요합니다. 회사 실행기가 `web_main:app`을 불러올 때에는 내장 서버나 Waitress를 별도로 시작하지 않습니다.

`app = Flask(__name__)`를 web_main.py 안에 새로 추가하면 기존 등록 화면·API가 연결되지 않은 별도 앱이 생깁니다. 예제의 `main()`과 `/login` 함수를 그대로 추가하면 같은 경로가 겹칩니다. 따라서 실행 진입점은 제공된 파일을 그대로 사용합니다.

## SSO 주석 해제 대신 설정 한 줄

`runtime_config.py`에서 다음 값을 선택합니다. 프로세스 환경변수가 있으면 그 값이 우선입니다. `.env`는 읽지 않습니다.

```python
# 회사 SSO로 운영할 때
PTAI_AUTH_MODE = 'sso'
PTAI_COOKIE_SECURE = True  # HTTPS 운영

# 내 PC에서 지정한 사번으로 시험할 때는 위 AUTH_MODE 값만 mock으로 변경
# PTAI_AUTH_MODE = 'mock'
# PTAI_MOCK_USER = '1000001'
# PTAI_COOKIE_SECURE = False  # localhost HTTP 시험
```

SSO 코드의 주석을 켜고 끄는 대신 이 설정이 해당 분기를 선택합니다. mock에서는 hcputil을 불러오지 않으며 지정 사번으로 로컬 요청을 처리합니다. 실제 저장을 사용하려면 MongoDB 주소도 설정해야 합니다. URI와 DB 이름이 비어 있으면 설정을 요청하며 시작하지 않습니다.

## 회사 예제의 로그인 흐름 반영

1. 인증 없는 사용자가 홈에 접속하면 `/login?ORIGIN=원래접속주소`로 이동합니다. API는 HTML 대신 401 JSON과 로그인 주소를 반환하고 브라우저가 그 주소로 이동합니다.
2. `/login`과 `/login/<path:sub_path>`를 제공합니다. `SSO(request)`에 실제 Flask 요청과 ORIGIN 인자가 전달됩니다.
3. 요청의 Cookie를 `check_day_cookie()`로 검사하고, 유효하면 `get_sso_info()`의 6개 값을 받습니다.
4. 예제와 같은 `emp_no`, `emp_name`, `emp_name_en`, `dept`, `email`, `dept_cd`, `logFlag`를 Flask 세션에 저장합니다. 사번·부서 코드는 MongoDB 사용자 및 권한과 연결됩니다.
5. 로그인 경로에서는 SDK가 반환한 `sso.redirect_url`로 이동합니다. 하위 로그인 경로가 있으면 리디렉션 URL 경로에 붙입니다. 예제의 `url_path = ''`에 해당하는 루트 배포를 기준으로 합니다.
6. 인증 후 등록·조회·업데이트는 기존 API를 그대로 사용합니다. 세션의 logFlag만 보고 승인하지 않으며 매 요청에서 현재 SSO 쿠키와 사용자 활성 상태를 확인합니다. 세션이 남아 있어도 만료된 SSO 쿠키로 접근할 수 없습니다.

ORIGIN은 같은 서비스의 주소만 허용합니다. 회사 프록시를 거친 실제 요청의 호스트·HTTPS 정보가 외부 접속 주소와 맞게 전달되어야 합니다. 운영 프록시의 구체적인 전달 규칙은 회사 배포 환경에서 확인해야 합니다. 플랫폼의 임의 하위 URL 경로 마운트는 별도 검증 범위입니다.

## 운영환경에서 필요한 것

- 회사에서 제공하는 hcputil 설치와 `hcputil.auth.sso.SSO` 사용 가능 여부를 확인합니다. 사내 설치 주소·인증정보는 공개 저장소에 넣지 않습니다.
- 실제 인증 Cookie가 Flask까지 전달되어야 합니다. SDK의 redirect_url은 HTTPS 주소여야 합니다.
- MongoDB URI·DB 이름, 기본 관리자 사번, 파일 저장 경로를 설정합니다.
- SECRET_KEY는 예제처럼 프로세스 시작 때마다 무작위로 바꾸지 않고 설정값 또는 MongoDB의 동일한 키를 사용합니다. 서버 재시작이나 여러 작업 프로세스 때문에 세션이 서로 달라지는 것을 막기 위한 것입니다.
- `TEMPLATES_AUTO_RELOAD`는 켜져 있습니다. NLS_LANG은 Oracle 연결용 설정이므로 MongoDB 기반인 현재 플랫폼에 추가하지 않았습니다. requests·urllib3 경고 비활성화도 이 플랫폼의 실행 필수 조건은 아닙니다.

로컬에서는 대역 SSO로 ORIGIN 전달, 로그인 이동, 세션 필드, 만료·권한 처리, 직접 실행과 WSGI 로딩을 검증했습니다. 실제 회사 hcputil·SSO 서버·프록시를 통한 로그인 성공까지 확인했다는 의미는 아닙니다. 회사 환경에서 첫 접속 → SSO 이동 → 플랫폼 복귀 → 사번 표시를 확인해야 합니다.
