# P&T AI Square — AX Workspace 선택 확장 연동

2026-10-25 · 확장 버전 0.1.0

공통 AX Workspace와 별도로 설치하는 P&T AI Square 확장과 웹 연동을 제공합니다. 확장에서는 등록된 기능, 등록자, 조회·좋아요·다운로드 정보와 상세 내용을 볼 수 있습니다. 파일 다운로드와 실제 설치는 구분하며, 지원되는 Skill/MCP의 설치 범위는 내 계정·현재 업무·선택한 폴더에서 고릅니다.

## 사내에 가져갈 파일

- **ai-square-2026.10.25-source.zip**: 플랫폼과 확장 소스입니다. `pt_ai_square/` 전체를 기존 웹 서버 배포 절차로 반영합니다. 웹에서 제공할 확장 설치 파일 `static/guides/ax-workspace-extension-setup.exe`도 포함되어 있습니다. 기존 `runtime_config.py`, MongoDB와 업로드 저장소는 유지하세요.
- **PNT-AI-Square-Extension-0.1.0-Setup.exe**: 서버에 배치하는 범용 확장 설치 파일입니다. 위 플랫폼 소스 ZIP에 같은 파일이 이미 포함되어 있으므로 따로 받을 필요는 없습니다. 서버 주소 파일 없이 단독 설치하면 주소를 직접 입력해야 합니다.
- **SHA256SUMS.txt**: 위 두 파일의 SHA-256입니다.

공통 앱의 사내 GitLab 배포에는 별도로 [workspace-local-0.23.32-source.zip](https://github.com/bongG-moon/workspace_local/releases/download/v0.23.32/workspace-local-0.23.32-source.zip)을 사용합니다. PC 설치에는 [AX Workspace 0.23.32 설치 파일](https://github.com/bongG-moon/workspace_local/releases/download/v0.23.32/AX-Workspace-0.23.32-Setup.exe)을 사용합니다. 버전 숫자가 같아도 이전 배포본에는 확장 연결부가 없을 수 있으므로 앱을 완전히 종료한 뒤 갱신된 설치 파일을 사용하세요.

## 운영 서버 설정

- 공개 소스와 확장 설치 파일에는 사내 서버 주소와 개인 KEY, DB 접속 정보를 넣지 않습니다. 실제 값은 Git에 포함하지 않는 `runtime_config.py` 또는 서버 환경변수로 관리합니다.
- 리버스 프록시 뒤에서 내부 주소가 보이면 `PTAI_PUBLIC_URL`에 사용자가 접속하는 웹 기본 주소를 지정합니다. 서버 실행 주소 `0.0.0.0`을 넣지 않습니다. 기존 DB 접속 설정과 실행 방식을 바꾸는 옵션이 아닙니다.
- 직원 사진은 선택 설정인 `PTAI_EMPLOYEE_PHOTO_BASE_URL`에 사진 폴더의 HTTP(S) 주소를 지정하면 제공합니다. 서버가 그 주소에 사번과 `.jpg`를 붙여 조회합니다. 미설정 또는 사진 조회 실패 시 이름 첫 글자를 표시하며 나머지 기능은 유지됩니다. 실제 주소는 운영 담당자가 설정합니다.

웹의 **P&T AI Square 확장 받기**는 설치 EXE 원본과 해당 서버 주소를 담은 `connection.json`, 설치 안내를 ZIP으로 제공합니다. 사용자는 ZIP 전체를 풀어 설치한 뒤 개인 KEY를 입력합니다. HTTP 연결은 최초 전송 확인이 필요합니다. 배포 시 이미 연결된 서버를 다른 주소로 자동 교체하지 않습니다.

## 검증 범위

공통 앱의 확장 연결, 미설치 상태, 기존 업무·초안 보존, 웹 다운로드, 설치 도우미, 패키지 worker 인증, 기존 연결 보존, HTTP 확인과 긴 Windows 경로를 로컬 격리 환경에서 검증했습니다. 사내 서버·개인 KEY·VDI 정책은 실제 운영 환경에서 확인해야 합니다.

이 릴리즈 게시가 사내 GitLab이나 웹 서버를 자동으로 갱신하지는 않습니다. 확장을 설치하지 않은 사용자에게 조직용 화면이나 백그라운드 작업이 추가되지 않습니다.
