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

**현재처럼 브라우저에서 접속하는 실제 서비스 주소가 `http://`이면 `PTAI_AUTH_MODE = 'sso'`를 유지하고 `PTAI_COOKIE_SECURE = False`로 설정합니다.** 위 예시의 `True`는 실제 브라우저 접속이 HTTPS일 때의 값입니다. HTTPS 프록시 뒤에서 앱 내부 통신만 HTTP인 경우에는 `True`를 유지합니다. 쿠키 설정은 SDK가 반환한 이동 주소가 아니라 브라우저의 실제 서비스 접속 방식으로 결정합니다.

이 옵션은 브라우저가 앱 세션 쿠키를 전송할 조건을 정합니다. HTTP 접속에서 `True`이면 세션 쿠키가 전송되지 않아 로그인 상태가 유지되지 않습니다. `False`로 설정해도 SSO 인증·세션 만료·권한 검사는 그대로 적용됩니다.

## 회사 예제의 로그인 흐름 반영

1. 인증 없는 사용자가 홈에 접속하면 `/login?ORIGIN=원래접속주소`로 이동합니다. API는 HTML 대신 401 JSON과 로그인 주소를 반환하고 브라우저가 그 주소로 이동합니다.
2. `/login`과 `/login/<path:sub_path>`를 제공합니다. 유효한 SSO 인증 세션이 없을 때 이 로그인 경로에서만 hcputil을 불러오고 `SSO(request)`를 만듭니다. 실제 Flask 요청과 ORIGIN 인자가 전달됩니다.
3. 로그인 요청의 Cookie를 `check_day_cookie()`로 검사하고, 유효하면 `get_sso_info()`의 6개 값을 받습니다. 실패하면 mock 사용자로 대체하지 않습니다.
4. 예제와 같은 `emp_no`, `emp_name`, `emp_name_en`, `dept`, `email`, `dept_cd`, `logFlag`와 SSO 인증 신원·시각 표식을 서명된 Flask 세션에 저장합니다. 사번·부서 코드는 MongoDB 사용자 및 권한과 연결됩니다. logFlag나 프로필 문자열만 있는 이전 세션은 한 번 다시 로그인해야 합니다.
5. SDK가 필요한 로그인 흐름에서는 `sso.redirect_url`로 이동합니다. 회사 SDK가 반환한 HTTP·HTTPS 절대 주소와 `/`로 시작하는 서비스 내 경로를 지원하며, 절대 주소의 호스트·scheme·포트를 임의로 바꾸지 않습니다. 하위 로그인 경로가 있으면 리디렉션 URL 경로에 붙입니다. 위험한 scheme이나 잘못된 URL 형식은 거절합니다. 이미 유효한 앱 세션으로 `/login`에 접속하면 SDK를 다시 호출하지 않고 같은 서비스의 원래 주소로 돌아갑니다. 예제의 `url_path = ''`에 해당하는 루트 배포를 기준으로 합니다.
6. 인증 세션은 로그인 시점부터 최대 8시간 유효하며 새로고침·조회·삭제 등 활동으로 만료 시각을 연장하지 않습니다. 유효한 세션의 일반 페이지·API·DELETE 요청에서는 SDK를 다시 호출하지 않습니다. 보호된 요청마다 MongoDB의 현재 사용자 활성 상태와 역할·도구 권한을 확인하며 기존 CSRF 검사와 API 인증키 인증은 유지합니다.
7. 세션이 없거나 만료되면 페이지는 로그인으로 이동하고 API는 401 JSON과 로그인 주소를 반환합니다. 플랫폼 로그아웃은 앱 세션을 지웁니다. 회사 SSO에서만 로그아웃하거나 회사 쿠키가 만료되어도 이미 발급한 앱 세션은 즉시 취소되지 않으며, 플랫폼 로그아웃·8시간 만료·MongoDB 계정 비활성화로 접근을 차단합니다.

요청자가 보낸 ORIGIN은 같은 서비스의 주소만 허용하며, SDK가 제공한 SSO 이동 주소와 별도로 검사합니다. 회사 프록시를 거친 실제 요청의 호스트·scheme 정보가 외부 접속 주소와 맞게 전달되어야 합니다. 운영 프록시의 구체적인 전달 규칙과 신뢰할 프록시 개수는 회사 배포 환경에서 확인해야 합니다. 확인 없이 ProxyFix를 추가하거나 전달 헤더를 자동 신뢰하지 않습니다. 플랫폼의 임의 하위 URL 경로 마운트는 별도 검증 범위입니다.

## 운영환경에서 필요한 것

- 회사에서 제공하는 hcputil 설치와 `hcputil.auth.sso.SSO` 사용 가능 여부를 확인합니다. 사내 설치 주소·인증정보는 공개 저장소에 넣지 않습니다.
- 실제 인증 Cookie가 Flask까지 전달되어야 합니다. SDK의 redirect_url은 유효한 HTTP·HTTPS 절대 주소 또는 `/`로 시작하는 서비스 내 경로를 지원합니다.
- MongoDB URI·DB 이름, 기본 관리자 사번, 파일 저장 경로를 설정합니다.
- SECRET_KEY는 예제처럼 프로세스 시작 때마다 무작위로 바꾸지 않고 설정값 또는 MongoDB의 동일한 키를 사용합니다. 서버 재시작이나 여러 작업 프로세스 때문에 세션이 서로 달라지는 것을 막기 위한 것입니다.
- `TEMPLATES_AUTO_RELOAD`는 켜져 있으며 `NLS_LANG='.UTF8'`는 회사 기본값을 유지합니다. 전역 HTTPS 검증 경고 비활성화는 추가하지 않습니다.

로컬에서는 대역 SSO로 ORIGIN 전달, 로그인 이동, 세션 필드, 만료·권한 처리, 직접 실행과 WSGI 로딩을 검증했습니다. 실제 회사 hcputil·SSO 서버·프록시를 통한 로그인 성공까지 확인했다는 의미는 아닙니다. 회사 환경에서 첫 접속 → SSO 이동 → 플랫폼 복귀 → 사번 표시를 확인해야 합니다.

## 새로고침·관리자 삭제 오류 수정 반영

이 수정에는 새 환경설정이 필요하지 않습니다. 기존 `runtime_config.py`, MongoDB 주소·DB, 업로드 파일이 있는 `PTAI_DATA_DIR`을 보존한 채 코드를 갱신하고, 현재 회사 실행기 또는 `index.py` 프로세스를 기존 방식으로 재시작합니다. 시작 명령과 포트를 바꾸지 않습니다. 배포 전 세션은 SSO 인증 표식이 없으므로 한 번 다시 로그인한 뒤 홈 새로고침, 일반 API 조회, 관리자 권한이 필요한 검수용 항목 삭제를 확인합니다.

로그인의 SDK 실패는 `HCP SSO failure stage=... error=...` 로그에서 실패 단계와 예외 유형만 확인합니다. 쿠키·인증키·사번·예외 메시지 원문은 기록하지 않습니다. MongoDB 오류는 별도의 DB 오류 503으로 처리하므로 HCP SSO 오류와 구분하여 DB 연결·계정 권한을 점검합니다.

## SDK 로그인 이동 주소 오류 수정 반영

기존 코드가 SDK의 HTTP 주소나 서비스 내 경로까지 거절한 것은 로그인 이동 주소 검증 문제입니다. `PTAI_AUTH_MODE = 'sso'`가 잘못된 설정이라는 뜻이 아니며, 회사 예제처럼 SDK가 제공한 유효한 이동 주소로 연결하도록 검사를 보완했습니다. 요청자가 보낸 외부 ORIGIN은 계속 거절합니다. 이동 주소를 거절할 때는 `HCP SSO failure stage=redirect_url reason=<code>`에 진단용 사유 코드만 남기며 전체 URL·쿼리·쿠키는 기록하지 않습니다. 예를 들어 `unsupported_scheme`은 허용하지 않는 scheme, `malformed_url`은 잘못된 URL 형식입니다.

1. 수정 코드를 반영하고 기존 `runtime_config.py`, MongoDB, `PTAI_DATA_DIR`을 보존합니다.
2. 현재 확인된 브라우저 접속 주소가 HTTP이므로 `PTAI_AUTH_MODE = 'sso'`는 유지하고 `PTAI_COOKIE_SECURE = False`를 적용합니다. 실제 브라우저 접속을 HTTPS로 전환하면 `True`를 사용합니다.
3. 현재 회사 실행기 또는 `index.py` 프로세스를 기존 명령·포트로 재시작하고, 회사 주소에서 한 번 로그인한 뒤 홈 새로고침과 일반 API 조회를 확인합니다.

SDK의 이동 주소가 HTTP라는 이유만으로 쿠키 설정을 바꾸지는 않습니다. 실제 회사 SDK·프록시·SSO 서버를 통한 로그인 성공은 이 재확인으로 판단하며, 로컬 대역 검증만으로 운영 로그인 완료를 단정하지 않습니다.
