# AX Workspace용 P&T AI Square 확장

공통 AX Workspace는 범용 확장 연결부만 제공합니다. P&T AI SQUARE의 주소, KEY 연결, 카탈로그, 설치 엔진과 UI는 이 별도 패키지에 포함됩니다. 스토어를 설치하지 않은 사용자에게 메뉴가 생기거나 플랫폼에 접속하는 작업은 없습니다.

## 사용 순서

1. 설정에 **추가 기능 → 확장 ZIP 가져오기**가 있는 AX Workspace를 먼저 설치합니다. 이 개발본의 앱 버전은 0.23.32입니다. 기존에 배포된 동일 버전에는 가져오기 기능이 없을 수 있으므로 버전 숫자만으로 호환성을 판단하지 않습니다.
2. 웹의 **AX Workspace** 탭에서 관리자가 등록한 `PNT-AI-Square-0.1.0-Extension.zip`을 받습니다. **압축을 풀거나 EXE를 실행하지 않고** 앱의 확장 ZIP 가져오기에서 파일을 선택합니다. 이름·버전·설치 위치·서버 주소를 확인하고 설치하면 왼쪽 메뉴에 **P&T AI Square**가 나타납니다. 현재 Windows 계정의 확장 폴더에만 설치하며 일반 대화와 업무 모드 모두에서 열 수 있습니다.
3. 배포자가 서버 주소를 담은 `connection.json`을 포함했다면 앱에서는 웹 `/local-access`에서 발급받은 **기존의 유효한 개인 KEY만 입력**합니다. 주소 파일이 없는 범용 설치 파일은 서버 주소도 직접 입력합니다. HTTP 서버는 최초 연결 시 암호화되지 않은 전송임을 확인합니다. 새 KEY를 자동 발급하거나 교체하지 않습니다. 기존 플랫폼 MCP 연결이 있다면 **기존 플랫폼 MCP 연결 사용**을 직접 선택할 수도 있습니다.
4. 기능을 검색하고 상세 화면에서 사용 방법을 확인합니다. **파일 다운로드**와 **설치하기**는 다른 동작입니다.
5. 설치하려면 **전체 공간(내 계정) / 현재 업무 폴더 / 특정 폴더 선택**을 직접 선택한 뒤 실제 변경 경로를 확인합니다. 진행 중인 대화를 자동으로 끊거나 Claude를 재시작하지 않습니다.

일반 대화에서는 **현재 업무 폴더**만 비활성화되며, **전체 공간(내 계정)**이나 **특정 폴더 선택**은 사용할 수 있습니다. 전체 공간은 현재 Windows 계정의 여러 업무에서 사용한다는 뜻이며, PC의 모든 계정에 설치하는 동작이 아닙니다. 특정 폴더는 공통 앱의 폴더 선택 창에서 선택합니다. 선택한 폴더가 현재 업무나 폴더 신뢰 설정을 바꾸지는 않습니다. 확장 화면이 임의 경로를 지정할 수 없고, 서버가 발급한 15분 유효 토큰과 실제 경로를 설치 준비·확정 시 다시 대조합니다.

## 화면과 상세 정보

P&T AI Square는 스킬과 기능처럼 본문을 사용하는 전용 화면입니다. 개별 항목만 **소개 / 설치·연결 / 버전 / 의견** 상세 팝업으로 열립니다. 팝업을 닫으면 검색·필터·스크롤 위치가 유지됩니다. 웹의 유형별 색상으로 Skill, Tool, MCP, 하네스와 플러그인을 구분합니다.

카드와 상세에 **등록자**, **조회**, **좋아요**, **다운로드**를 표시합니다. 등록자는 게시한 사용자이며 입력한 담당자와 구분합니다. 예전 서버에서 등록자·조회수를 제공하지 않으면 정보 없음 또는 `—`로 표시합니다. 서버의 실제 통계만 표시하며 누락된 값을 임의로 0으로 만들지 않습니다.

조회수는 이번 서버 개선부터 집계합니다. 웹과 확장의 상세 열람을 같은 API에 기록하며 동일 사용자의 같은 항목 열람은 30분 동안 한 번만 셉니다. 탭 전환, 설치 준비, 자동 갱신, 단순 상세 GET은 조회수를 증가시키지 않습니다. 이전 열람 이력은 추정하여 채우지 않고, 좋아요·다운로드 및 추천 순위 계산은 유지합니다.

## 설치 상태의 의미

| 기능/배포 형식 | 스토어에서 하는 일 | 완료 표시의 의미 |
| --- | --- | --- |
| 설치 선언이 있는 Claude Skill | 파일 확인 후 `.claude/skills/<slug>`에 설치 | 파일 설치 완료 |
| 설치 선언이 있는 Claude MCP | 파일 설치와 기존 MCP 설정에 해당 항목 병합 | 연결 설정 완료. 실제 서버 실행은 다음 Claude 연결에서 확인 |
| EXE/MSI/PS1, 선언 없는 ZIP, 하네스 | 파일 다운로드와 웹의 설치 안내 제공 | 다운로드 완료. 설치·실행 완료로 표시하지 않음 |
| URL/명령어형 항목 | 상세의 주소·사용 방법과 웹 이동 제공 | 연결/설치 안내 확인 |

플랫폼의 `installProfile`은 설치 동작을 선언하는 서버 정보입니다. 배포 파일의 유형만 보고 임의의 명령을 만들어 실행하지 않습니다. 이 버전은 EXE/MSI를 자동 실행하지 않습니다.

**설치된 기능**에서 파일·설정 상태를 확인하거나 이전 상태로 복구합니다. 처음 설치한 기능의 복구는 해당 설치를 제거하는 동작입니다. 사용자가 이후 변경한 파일·설정은 자동으로 덮어쓰지 않습니다. 업데이트는 사용자가 **업데이트** 화면을 열 때 조회하며, 새 버전을 자동 설치하지 않습니다.

## 웹과 연결하는 정보

### 완성된 프로그램을 AX Workspace 탭에 등록하기

이 폴더는 선택 확장의 개발 소스입니다. 웹에 특정 확장 소개나 고정 설치 파일을 내장하지 않습니다. 프로그램을 완성한 뒤 관리자가 **AX Workspace → 파일 등록**에서 이름·설명·분류·배포 버전과 완성된 파일을 등록합니다. 이후 KEY 페이지에서 AX Workspace 탭으로 이동한 사용자가 해당 카드를 찾아 받습니다.

서버 주소는 **배포자**가 `package_for_upload.py --server-url <서버 기본 주소>`로 지정합니다. 확장 코드·`extension.json`·`connection.json`·설치 안내를 한 ZIP으로 만들며 별도 설치 EXE는 포함하지 않습니다. 주소 파일은 `{"schemaVersion": 1, "baseUrl": "http://pntaisquare.company.example"}` 형식입니다. 서버 실행 주소 `0.0.0.0` 대신 사용자가 접속하는 주소를 사용하고 KEY·쿠키·MongoDB 접속 정보를 넣지 않습니다. 사내 주소가 포함된 ZIP은 사내 배포용으로 관리하고 공개 Git에 올리지 않습니다. ZIP 전체를 원본 그대로 등록하세요.

Git 릴리즈에서 받은 **`PNT-AI-Square-0.1.0-Distribution.zip`**은 서버 주소가 없는 관리자용 준비 자료입니다. 전체를 풀고 아래 명령으로 실제 서버 주소를 지정한 **`Extension.zip`**을 만든 다음, 이 최종 ZIP을 웹에 등록합니다. Python 3.10 이상 표준 라이브러리만 사용하며 소스 저장소·vendor·추가 패키지·네이티브 빌드 도구는 필요하지 않습니다.

```powershell
python configure_server.py --server-url 'https://square.company.example' --output 'PNT-AI-Square-0.1.0-Extension.zip'
```

`Distribution.zip` 자체를 사용자 설치 파일로 올리지 않습니다. 도우미는 동봉 template의 전체 SHA256과 각 payload 파일·경로·빌드 해시를 검증하고, 실행 코드는 그대로 유지한 채 주소·등록 정보·안내만 새 ZIP에 넣습니다. 압축 해제·payload 실행·서버 접속·개인 프로필 변경을 하지 않고 기존 출력 파일을 덮어쓰지 않습니다. HTTP 전송 주의 안내를 최종 ZIP과 실행 결과에 표시합니다. 해시는 전자서명이 아니므로 Git 릴리즈의 출처와 공개 체크섬을 함께 확인하세요. 상세 절차는 [DISTRIBUTION_README.txt](DISTRIBUTION_README.txt)를 따릅니다.

웹은 등록한 파일을 원본 그대로 제공합니다. EXE를 ZIP에 추가하거나 `connection.json`을 만들지 않으며 `PTAI_PUBLIC_URL`도 AX 자료실 파일에 적용하지 않습니다. `PTAI_PUBLIC_URL`에 따른 주소 포함 기능은 별도의 로컬 MCP 다운로드에만 유지됩니다.

공통 앱은 ZIP 경로·크기·해시·대상 폴더를 검사한 뒤 사용자 확인을 받아 설치합니다. 주소 파일은 `extension-data/pt-ai-square.store/connection.json`에 저장합니다. 이미 인증된 연결이 있으면 기존 주소·KEY를 우선 사용하며 새 ZIP의 주소로 자동 전환하지 않습니다. 다른 서버로 바꾸려면 연결 화면의 **서버 주소 변경**에서 해당 서버의 KEY로 다시 연결합니다.

`python organization-store/build.py`로 만든 설치 EXE를 웹의 `static/guides`에 복사하지 않습니다. 관리자가 등록할 완성된 배포 파일로 준비합니다. 이전 `/local-access/workspace-extension.zip`과 `/static/guides/ax-workspace-extension-setup.exe` 링크는 로그인 후 AX Workspace 탭(`/?view=ax`)으로 이동합니다. 이미 사용자가 설치한 프로그램이나 내려받은 파일을 자동 교체하지 않습니다.

| 용도 | 기존 플랫폼 계약 |
| --- | --- |
| KEY/계정 확인 | `GET /api/integration/me` |
| 검색·조직·유형·정렬 | `GET /api/catalog`, `/api/catalog/options` |
| 상세/현재 배포/업데이트 | `/api/tools/{id}`, `/manifest`, `/version-check` |
| 좋아요 | `PUT /api/tools/{id}/like` + 명시적 `liked: true/false` |
| 상세 열람 집계 | `POST /api/tools/{id}/view` + 빈 JSON. 실패해도 상세 열람 유지 |
| 다운로드 | `/download/{id}/{release}` |

좋아요와 다운로드는 웹의 같은 기록을 사용합니다. 설치 기록이 있는 항목의 새 버전 수신은 서버가 제공하는 `purpose=update` 경로로 처리합니다. 검증된 기존 다운로드 파일을 다시 사용하는 경우에는 가짜 다운로드 요청을 보내지 않습니다. 앱의 로컬 설치 기록과 서버의 다운로드 수는 서로 다른 정보입니다.

이번 플랫폼 보완에는 **개인 KEY의 좋아요·상세 열람 API 허용**, **목록·상세의 부서 권한 판정 일치**, **실제 등록자 이름과 조회수 제공**이 포함됩니다. 사내 플랫폼에도 이 서버 수정이 반영되어야 같은 결과를 얻습니다. `orgId`는 분류용 조직이며 SSO의 `dept_cd`와 같은 값으로 간주하지 않습니다.

## 데이터·수명·분리

- 확장 소스: `%LOCALAPPDATA%\CompanyAgent\extensions\pt-ai-square.store`.
- 스토어 연결/다운로드/기록: 공통 앱 상태 폴더 옆 `extension-data\pt-ai-square.store`.
- 설치 패키지와 사용자 데이터는 분리됩니다. 확장 제거가 기존 대화, Claude 설정, 다운로드한 파일이나 설치된 Skill/MCP까지 지우지 않습니다.
- KEY는 현재 Windows 계정의 DPAPI로 암호화하며 URL·명령행·로그·대화에 넣지 않습니다. UI 입력 값은 연결 시도 후 비웁니다.
- 기존 MCP 연결을 재사용하면 원본 설정과 설치 기록을 공유하되, 연결 해제로 원본 KEY를 취소하지 않습니다.
- 전용 화면 안의 격리된 iframe은 앱 토큰·대화 내용을 받지 않습니다. 네트워크 호출은 명시된 작업을 처리하는 Python worker에서만 실행합니다.
- worker는 작업 요청 때 실행하고 끝나면 종료합니다. 상주 스토어 서버, 주기적 폴링, 앱 시작 시 카탈로그/업데이트 전체 조회가 없습니다.
- 화면을 닫아도 이미 시작한 설치를 자동 취소하거나 재실행하지 않습니다. 앱 종료/시간 초과로 프로세스가 중단된 경우 설치 기록을 다시 확인합니다.
- 설치 변경 전에 복구 기록을 저장합니다. 중단 후 파일·설정이 승인한 결과와 정확히 일치하면 기록을 확정하고, 일부만 변경되었으면 이전 상태로 되돌립니다. 예상과 다른 사용자 변경은 **중단된 설치 확인 필요**로 표시하며 보관 경로를 안내합니다. 파일 다운로드나 실행 명령을 자동 반복하지 않습니다.
- 공통 호스트는 **운영체제 수준의 코드 샌드박스가 아닙니다**. 설치된 Python 확장은 사용자 권한으로 실행하므로 조직이 검토한 설치 파일만 배포해야 합니다. 파일 해시는 손상 탐지이며 게시자 전자서명과 같지 않습니다.

## 소스 구성

- `ui/`: 연결, 카탈로그, 상세, 설치 범위·준비안 확인, 설치/업데이트 관리 화면.
- `worker.py`: 공통 호스트 stdio 계약과 기존 플랫폼 설치 엔진 연결.
- `extension.template.json`: 범용 호스트용 ID/진입점/작업 목록.
- `package_for_upload.py`: 수동 등록용 ZIP 생성. 서버 주소를 인자로 받고 설치 도우미를 만들거나 실행하지 않습니다.
- `configure_server.py`: 공개 배포본에 함께 넣는 독립 서버 설정 도우미. stdlib만 사용하며 재빌드 없이 검증된 template에 서버 주소를 지정합니다. 직접 빌드와 공개 배포본이 같은 등록 선언·설치 안내를 사용합니다.
- `build.py`: 공통 확장 소스 패키징 함수. `installer/`는 이전 EXE 방식의 참고 소스이며 새 ZIP 경로에서는 사용하지 않습니다.
- `tests/`: 개인 프로필 대신 격리 경로와 합성 자료를 사용하는 시험.
- `../pt_ai_square/integrations/pt-square-mcp/pt_square_mcp`: 설치 엔진 정본. 빌드 시 정확한 소스를 vendor로 포함합니다. 복사본을 직접 편집하지 않습니다.

확장 개발 규격은 공통 앱 소스의 `docs/WORKSPACE_EXTENSIONS.md`를 참고합니다. UI의 네트워크 주소·KEY·실행 동작은 공통 앱에 하드코딩하지 않습니다.

### 독립 Git 저장소에서 개발·검증하기

이 저장소에는 `organization-store/`와 그 옆 `pt_ai_square/`가 함께 있습니다. worker는 개발 중에는 이 이웃 폴더의 MCP 정본을 읽고, 배포 패키지에서는 동봉된 `vendor/pt_square_mcp/`를 읽습니다. 별도 AX Workspace 소스나 개인 설정을 웹 저장소에 복사할 필요는 없습니다. 웹 운영 서버는 관리자가 등록한 완성 파일을 전달하므로 빌드 도구가 필요하지 않습니다.

등록용 확장 ZIP은 Python만으로 생성합니다. .NET·NSIS·설치 도우미 실행이 필요하지 않습니다. 아래 예시 주소를 실제 접속 주소로 바꾸고 새 출력 폴더를 지정합니다.

```powershell
python organization-store/package_for_upload.py --server-url 'https://square.company.example' --output-directory outputs/square-upload
```

출력 중 `PNT-AI-Square-0.1.0-Extension.zip`을 등록하고 `SHA256SUMS.txt`·등록 안내·빌드 보고서는 관리자가 보관합니다. 일반 도구 등록에서도 `ai-square.json`을 읽을 수 있습니다. ZIP 생성은 웹 업로드·게시·개인 프로필 설치를 하지 않습니다.

공개 Git 릴리즈용은 주소를 넣지 않고 별도로 생성합니다. 아래 출력의 `Distribution.zip`과 체크섬을 전달하면 관리자가 사내에서 위 `configure_server.py` 명령을 실행할 수 있습니다. 기존에 만든 서버 포함 ZIP을 공개 ZIP 안에 다시 넣지 않습니다.

```powershell
python organization-store/package_for_upload.py --distribution --output-directory outputs/square-public
```

다음 시험은 플랫폼 개발·테스트 의존성을 설치한 Python에서 실행합니다. 구형 네이티브 설치기 시험은 새 ZIP 배포 검증과 분리합니다.

```powershell
python -m pytest organization-store/tests/test_upload_package.py organization-store/tests/test_distribution_package.py organization-store/tests/test_worker.py organization-store/tests/test_onboarding.py -q
```

실제 AX 호스트와의 패키지 검증·브라우저 시험을 추가하려면 확장 연결부가 구현된 **별도 공통 앱 소스**를 지정합니다. 이 경로가 없으면 해당 호스트 통합 시험만 사유와 함께 건너뜁니다. NSIS EXE를 새로 생성하는 시험에는 NSIS도 필요합니다. 다른 worker·설치 보호 시험 전체를 건너뛰지는 않습니다. 이전 서버가 확장 ZIP을 조립하던 다운로드 시험은 현재 AX 자료실의 원본 전달 정책과 구분합니다.

```powershell
$env:AX_WORKSPACE_SOURCE = 'C:\src\AX-Workspace'
$env:NSIS_MAKENSIS = 'C:\build-tools\nsis-3.12\makensis.exe'
python -m pytest organization-store/tests -q
python organization-store/tests/serve_browser_fixture.py --output outputs/square-page-qa
```

브라우저 fixture를 실행한 상태에서 별도 터미널의 `node organization-store/tests/browser-ui.cjs`와 `browser-lifecycle.cjs`로 실제 공통 화면을 확인합니다. Playwright 모듈은 `PLAYWRIGHT_MODULE`로 지정할 수 있으며 Chromium 시험은 설치된 Microsoft Edge를 사용합니다. `browser-onboarding.cjs`는 합성 호스트 메시지로 폼만 검사하므로 AX 소스가 필요하지 않습니다.

빌드된 패키지의 실제 호스트 검증은 `python organization-store/tests/verify_preview.py --host-source 'C:\src\AX-Workspace'`로 실행합니다. `--preview`로 별도 빌드 결과 폴더를, `--host-exe`로 검사할 공통 앱 EXE를 지정할 수 있습니다. 개인 프로필·실행 중인 앱을 재설치하는 명령은 아닙니다.

## 검증 범위

- 미설치 시 추가 UI·worker·네트워크·주기 작업이 없는지, 기존 종료·초안 처리 회귀.
- 실제 Chromium + 공통 앱 + 격리 iframe의 연결/검색/좋아요/다운로드/설치 확인/복구/다크·좁은 화면. UI 시험의 서버 자료는 합성 데이터입니다.
- 실제 Python worker/HTTP/해시 다운로드/설치 엔진, Flask/Mongo의 KEY·권한·웹 집계 계약.
- 중단된 파일 설치의 복구, 수정한 사용자 파일 보호, 별도 설치기의 갱신/제거.

개발 PC의 격리 시험이며 사내 운영 서버·VDI 보안 정책·실제 조직 KEY를 사용한 실운영 검증을 대신하지 않습니다. 실제 Claude/MCP 실행 여부를 설치 파일 검사만으로 성공 처리하지 않습니다.
