# P&T AI SQUARE 로컬 MCP

Claude Code 등 **로컬 stdio MCP를 지원하는 프로그램**에서 실행합니다. 별도 MCP 호스팅 서버나 포트를 열지 않습니다. 기존 AI SQUARE 웹 서버에는 연결되어야 합니다. MongoDB 주소·계정·웹 서버 폴더 접근 권한은 이 패키지에 포함되지 않습니다.

## 1. ZIP을 풀고 전용 실행 환경 만들기

Windows PowerShell에서 압축을 푼 폴더로 이동한 뒤 실행합니다. Python 3.11 이상이 필요합니다.

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

회사망에서 pip가 차단되어 있다면 회사가 제공하는 Python 패키지 저장소를 사용하세요. 관리자 권한이나 전역 Python 변경은 필요하지 않습니다. 공식 MCP Python SDK **1.30.0**을 전용 가상환경에 설치합니다.

## 2. 서버 주소·작업 폴더·내 KEY 연결

아래 주소와 작업 폴더를 본인 환경에 맞게 바꿉니다. `--workspace`는 여러 번 넣을 수 있습니다. 폴더는 미리 만들어 두세요. 전체 C: 드라이브는 허용하지 않습니다.

```powershell
& .\.venv\Scripts\python.exe .\run_mcp.py setup --url "http://회사서버주소" --workspace "C:\Users\내사번\Desktop\공유할도구"
```

HTTP이면 비암호화 안내가 나오고 **정확한 서버 주소를 한 번 더 입력**합니다. KEY와 파일 전송이 암호화되는 것은 아닙니다. 설정한 정확한 주소에만 KEY를 보내고, 리다이렉트에는 따라가지 않습니다. HTTPS를 제공받으면 setup으로 주소를 변경하세요. 일반 웹 포트나 실행 진입점을 변경할 필요는 없습니다.

KEY는 화면에 표시되지 않는 입력란에 붙여넣습니다. KEY가 없으면 Enter를 누르세요. 웹의 `/local-access`가 열리면 **업로드 포함 → 연결 KEY 발급** 후 setup을 다시 실행합니다. 다운로드만 필요하면 읽기 KEY도 가능합니다.

KEY는 현재 Windows 사용자만 복호화할 수 있는 DPAPI로 저장합니다. 설정 JSON에는 KEY 원문이 없습니다. 채팅, MCP 도구 인자, 실행 명령줄에 KEY를 넣지 마세요. KEY 재발급 시 이전 키는 즉시 사용할 수 없으므로 setup을 다시 실행합니다.

설정 위치는 기본적으로 `%USERPROFILE%\.pt-ai-square\mcp\config.json`입니다. 별도 설정을 쓰려면 명령의 맨 앞에 `--config "C:\별도폴더\config.json"`을 넣습니다. `.env`를 사용하지 않습니다.

비대화형 설정 또는 Windows 이외 환경에서는 실행 프로세스에 `PTAI_API_TOKEN`을 제공하고 `--token-from-env`를 사용합니다. HTTP는 사용자가 위험을 확인한 정확한 주소를 `--accept-http-origin "http://회사서버주소"`에 명시해야 합니다. 이 옵션은 보안을 개선하는 옵션이 아니라 사용자가 확인한 연결 대상을 고정하는 옵션입니다.

## 3. 사용하는 AI 프로그램에 MCP 연결

해당 프로그램의 MCP 설정에 아래 항목을 추가합니다. 실제 압축 해제한 **절대 경로**로 바꾸세요. 기존 MCP 항목을 지우지 말고 `mcpServers` 안에 한 항목만 추가합니다.

```json
{
  "mcpServers": {
    "pt-ai-square": {
      "command": "C:\\도구\\pt-square-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\도구\\pt-square-mcp\\run_mcp.py", "serve"]
    }
  }
}
```

여기에 KEY를 넣지 않습니다. AI 프로그램을 다시 시작한 뒤 “AI SQUARE 연결 상태 확인해줘”라고 요청하면 사번·부서·연결 권한을 확인할 수 있습니다. 웹 전용 ChatGPT처럼 로컬 stdio를 직접 지원하지 않는 환경에는 이 JSON을 그대로 붙여 넣어 연결할 수 없습니다.

## 실제 사용 예

- “메일 조회 도구 추천해줘. 같은 부서에서 많이 쓰는 것도 알려줘.”
- “최근 7일 순위 TOP 10 보여줘.” / “누적 순위로 보여줘.”
- “첫 번째 Skill을 현재 프로젝트에 설치해줘.” → 설치 위치·변경 내용 확인 → 파일 받기·해시 검사·배치.
- “설치한 도구에 새 버전이 있는지만 확인해줘.” → 교체하지 않고 확인 결과만 반환.
- “이 폴더를 Skill로 등록해줘.” → 원문 확인·소개와 동작 흐름 작성 → 기존 본인 도구 후보 확인 → 신규/업데이트·조직·업무·공개 범위 선택 → ZIP/MD 준비 → 웹 승인 → 게시.

등록 정보는 사용하는 AI가 실제 소스와 지침을 읽고 작성합니다. MCP나 웹 서버에 별도 LLM 키는 필요하지 않습니다. 여러 파일 폴더는 `ai-square.json` v1에 맞는 ZIP으로 준비하고, 단일 MD는 **그대로 MD**로 등록합니다. 단일 ZIP을 입력하면 원본을 유지합니다. `installProfile`은 등록 메타데이터의 별도 속성이며 ZIP v1 선언 안에 넣지 않습니다.

## 설치 지원 범위

| 유형 | 지원 범위와 결과 |
|---|---|
| Claude Skill MD | 선택한 프로젝트 또는 내 계정의 `.claude/skills/<slug>/SKILL.md`에 복사하고 내용 확인 |
| Claude Skill ZIP | ZIP 최상위 SKILL.md와 보조 파일을 같은 위치에 함께 배치 |
| Python/Node MCP ZIP | 시작 파일·런타임 확인, 프로젝트 `.mcp.json` 또는 내 계정 `.claude.json`에 지정 MCP 항목 추가. 다른 항목 보존. 연결 설정 완료와 실제 MCP 핸드셰이크 성공은 구분 |
| EXE·MSI·PS1 | 사용자가 확인한 범위별 선언 인자로 설치기를 실행. 관리자 승격·실행 정책 우회 없음. `launched`는 설치 완료가 아님. `verify_install`은 선언한 결과 파일 존재만 확인 |
| URL·터미널 명령·지원하지 않는 호스트 | 상세의 연결·설치 안내 제공. 일반 임의 명령 실행 도구는 제공하지 않음 |

자동 설치는 등록자가 올바른 `installProfile`을 명시한 항목만 지원합니다. 의존성 pip/npm 설치는 자동 실행하지 않습니다. 기존 도구에 선언이 없으면 수동 설치 안내로 연결됩니다.

프로젝트/내 계정 범위는 **기본값이 없습니다**. 준비안에 보이는 경로와 인자를 확인한 뒤 설치합니다. 새 버전·설정·로컬 파일이 바뀌면 준비안을 다시 생성해야 합니다. 이 MCP가 설치한 파일과 해당 MCP 설정은 백업·복구할 수 있지만, 사용자가 바꾼 파일을 덮어쓰거나 EXE가 바꾼 시스템 상태를 되돌리지는 않습니다.

## 등록용 설치 선언 예

단일 MD 또는 최상위 SKILL.md가 있는 ZIP의 등록 metadata에 넣습니다.

```json
{
  "installProfile": {
    "schemaVersion": 1,
    "kind": "skill",
    "host": "claude",
    "slug": "memo-summary",
    "scopes": ["project", "user"],
    "entrypoint": "SKILL.md"
  }
}
```

MCP는 `kind: "mcp"`, 실제 `entrypoint: "server.py"`와 `command: {"executable":"python", "args":["{entrypoint}"]}`를 사용합니다. 실행 인자는 `{entrypoint}`, `{installDir}`, `{scopeDir}`만 치환하며 셸로 해석하지 않습니다. EXE·MSI·PS1은 `kind: "installer"`와 `installerArgs: {"project":["실제 지원 인자"], "user":["실제 지원 인자"]}`를 명시합니다. 실제 설치기에서 지원하지 않는 옵션을 만들지 마세요. 범위를 지원하지 않으면 `scopes`에서 빼고 이유를 guide에 적습니다.

## 권한과 데이터

- 검색·다운로드·본인 도구 신규/버전 게시만 제공합니다. 다른 사람 도구 수정, 관리자 설정, DB 명령, 임의 서버 파일 경로 API는 제공하지 않습니다.
- 서버가 매 요청마다 KEY의 사번·권한·소유권을 검사합니다. MCP를 수정해도 서버 검사를 우회할 수 없습니다. 사용자가 이미 별도의 DB 접속 권한을 가진 경우까지 이 MCP가 제한하는 것은 아닙니다.
- 게시 초안은 서버에 파일과 함께 저장되지만 웹에서 본인이 승인하기 전에는 일반 목록에 게시되지 않습니다. 승인은 MCP 도구가 아니라 SSO 또는 mock 웹 세션에서 처리합니다. 게시하지 않으려면 승인하지 않고 두면 됩니다. 승인 후 내용을 바꿀 수 없고 새 초안을 만들어야 합니다.
- 다운로드는 웹과 같은 API를 사용하여 도구당 사번별 첫 다운로드만 집계합니다. 업데이트 수신은 집계하지 않습니다. 파일 수신과 실제 설치 완료는 별개입니다.
- 로컬 작업 폴더 허용 목록, ZIP 경로/링크/크기 검사와 단순 인증정보 패턴 검사를 수행합니다. 악성코드 검사나 임의 코드의 안전성 보증은 아닙니다.
- 자동 실행 프로그램이 사용자의 권한으로 작동한다는 점은 일반 설치기와 같습니다. 로컬 확인 단계는 사용 편의를 위한 절차이며, 수정한 로컬 프로그램을 신뢰 경계로 삼지 않습니다.

## 문제 해결

1. **401:** 웹에서 KEY 취소/재발급 여부를 확인하고 setup을 다시 실행합니다.
2. **403:** 조회 권한 또는 업로드 포함 KEY인지 확인합니다. 관리자 KEY도 남의 도구를 업데이트할 수 없습니다.
3. **409:** 웹 승인 전인지, 배포 버전이 변경되었는지 초안 상태를 확인합니다. 재게시 시 같은 draft ID를 사용하면 중복 게시하지 않습니다.
4. **허용 폴더 밖:** setup의 `--workspace`에 실제 작업 폴더를 추가합니다. MCP가 임의로 접근 범위를 늘리지 않습니다.
5. **연결 설정 완료:** MCP 파일·설정 저장이 완료된 상태입니다. 필요한 의존성과 Claude의 실제 연결 상태는 별도로 확인합니다.

참고: [공식 MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.30.0), [Claude Code MCP 범위](https://code.claude.com/docs/en/mcp#mcp-installation-scopes), [Claude Code Skill 위치](https://code.claude.com/docs/en/skills#choose-where-skills-load). 이 패키지는 stdio만 실행합니다.
