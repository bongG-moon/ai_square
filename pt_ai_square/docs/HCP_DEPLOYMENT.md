# 회사 Flask 기본 포맷과 연결되는 방식

## 운영 서버가 불러오는 파일

회사 기본 예제대로 `web_main.py`에 `app = Flask(__name__)`를 만들고, `index.py`에서 그 앱을 `application`이라는 이름으로 불러옵니다. 플랫폼의 화면·SSO·MongoDB·API는 공용 초기화 함수 `init_app(app)`가 같은 앱에 연결합니다. 별도 Flask 앱을 하나 더 만들지 않습니다.

`index.py`의 실행 부분은 다음 회사 기본 형식을 유지합니다.

```python
from web_main import app as application

if __name__ == "__main__":
    application.run(debug=True, host='0.0.0.0')
```

포트 인자를 추가하거나 Waitress로 바꾸지 않습니다. 직접 실행하면 위의 `debug=True`와 Flask 기본 실행 동작을 그대로 사용합니다. 회사 WSGI 실행기가 모듈을 불러올 때는 `__main__` 조건이 거짓이므로 `run()`을 호출하지 않으며, 회사 실행기가 웹 요청을 처리합니다.

| 실행 환경 | 진입점 |
|---|---|
| 회사 기본 파일을 직접 실행 | `python index.py` |
| 회사 실행기가 index.py의 application을 불러옴 | `index:application` |
| 기존 회사 실행기가 web_main.py의 app을 불러옴 | `web_main:app` — 같은 앱으로 호환 |
| 패키지의 상위 폴더에서 WSGI 실행기가 불러옴 | `pt_ai_square.web_main:app` |
| 개발자가 기존 로컬 보조 실행을 선택함 | `python __main__.py run` — 회사 기본 진입점과 별도 |

`index.py`와 `web_main.py`가 있는 폴더 전체를 배포합니다. 상위 프로젝트나 고정 폴더 이름이 필요하지 않습니다. VS Code에서는 `index.py`의 **Python 파일 실행**을 누르며, Windows의 `run_server.cmd`도 같은 파일을 실행합니다. `web_main.py`는 앱 정의용이므로 단독 실행해도 웹 서버를 시작하지 않습니다.

`PTAI_HOST`·`PTAI_PORT`는 선택적인 `__main__.py run` 보조 명령에만 적용됩니다. 회사 기본 `index.py`나 회사 실행기 설정을 바꾸는 값이 아닙니다. 회사에서 정한 실행 방식·포트는 유지하고, 플랫폼 설정만 `runtime_config.py`에 입력하세요.

`web_main.py`에는 `NLS_LANG='.UTF8'`와 `url_path=''`도 회사 기본값으로 둡니다. 이미 앱에 등록된 `/`·`/login` 함수를 예제에서 다시 붙이면 경로가 중복되므로 추가하지 않습니다. 홈은 현재 플랫폼 템플릿을 사용하고 로그인 후 이름·사번·부서 등은 기존 프로필 API와 세션으로 연결합니다.

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
- `TEMPLATES_AUTO_RELOAD`는 켜져 있으며 `NLS_LANG='.UTF8'`는 회사 기본값을 유지합니다. 전역 HTTPS 검증 경고 비활성화는 추가하지 않습니다.

로컬에서는 대역 SSO로 ORIGIN 전달, 로그인 이동, 세션 필드, 만료·권한 처리, 직접 실행과 WSGI 로딩을 검증했습니다. 실제 회사 hcputil·SSO 서버·프록시를 통한 로그인 성공까지 확인했다는 의미는 아닙니다. 회사 환경에서 첫 접속 → SSO 이동 → 플랫폼 복귀 → 사번 표시를 확인해야 합니다.
