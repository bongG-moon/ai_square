# 웹에서 읽는 배포 정보 v1

`assets/ai-square.example.json`을 실제 프로젝트에 맞게 채우고 ZIP 최상위에 `ai-square.json`으로 넣는다. 상위 폴더로 한 번 더 감싸지 않는다. 웹과 `scripts/prepare_package.py`가 같은 `package_contract.py` 규칙을 사용한다.

| 항목 | 규칙 |
|---|---|
| schemaVersion | 숫자 1 |
| packageId | 3~80자, 영문 소문자 시작, 소문자·숫자·점·하이픈. 같은 도구의 다음 버전도 유지 |
| name / desc | 도구 이름 50자 / 한 줄 소개 200자 |
| platform | Claude / ChatGPT / 기타 |
| type | MCP/Tool / Skill / 플러그인/하네스 |
| entryPoint | 시작 파일의 ZIP 내부 상대 경로. Skill은 SKILL.md, Python MCP는 실제 시작 스크립트 등 |
| guideFile | UTF-8 설치 안내 파일 경로. 최대 40KB, 내용 1~10000자 |
| requiredFiles | 필요한 파일 경로 목록, 최대 100개. 시작 파일과 안내 파일도 항상 검사 |
| requirements | 사용자에게 알릴 의존성·권한·설치 조건, 최대 20개·각 200자. 설치 명령으로 실행하지 않음 |
| workTags | 선택, 최대 8개·각 30자 |
| environment / changes | 선택, 환경 200자 / 변경 설명 2000자 |

경로는 `/` 구분자를 사용한다. 절대 경로, `..`, 빈 파일, 누락 파일, 중복 경로·중복 JSON 키, 알 수 없는 항목은 거절된다. guideFile 내용은 설치 안내 입력란으로 가져온다. 이름·설명·안내는 웹에서 검토하고 수정할 수 있다. 프로그램·유형은 ZIP과 일치해야 한다. 조직·업무 분야·담당자·권한은 웹에서 선택하며 패키지로 권한을 지정하지 않는다.

toolId·release·버전 확인 URL은 입력하지 않는다. 게시 후 웹에서 발급한 별도 배포 정보 JSON에 들어간다. 원본 ZIP은 서버에서 수정하지 않는다. JSON의 상대 URL은 사용자가 접속한 플랫폼 주소 기준이며 인증이 필요하다. 실행 파일에 버전 확인 코드를 넣거나 SSO 인증을 연결하는 작업은 자동 완료되지 않는다.

배포 정보가 없는 기존 ZIP·EXE·MSI·PS1도 일반 등록을 유지한다. ai-square.json이 있는 ZIP은 틀린 선언을 무시하지 않고 오류를 안내한다. 한 번 배포 정보를 연결한 도구는 이후 버전에서도 같은 packageId의 선언을 유지한다. ZIP 내부 선언은 코드의 실제 동작·호환성·라이선스·보안 검증을 대신하지 않는다.
