; Standard per-user NSIS handoff. No custom executable helper or file association.
Unicode true
RequestExecutionLevel user
ManifestDPIAware true
ManifestLongPathAware true
SetCompressor /SOLID lzma
CRCCheck force
!include "MUI2.nsh"
!include "LogicLib.nsh"

Name "P&T AI Square 확장 설치"
OutFile "${OUTPUT_FILE}"
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=1042 "ProductName" "P&T AI Square 확장 설치"
VIAddVersionKey /LANG=1042 "FileDescription" "AX Workspace에서 확장 설치 확인창을 엽니다"
VIAddVersionKey /LANG=1042 "FileVersion" "${APP_VERSION}.0"
VIAddVersionKey /LANG=1042 "ProductVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1042 "LegalCopyright" "AX Workspace contributors"
BrandingText "P&T AI Square · AX Workspace 선택 확장"
ShowInstDetails show
AutoCloseWindow false
Var HostExe
Var HostResult

!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "AX Workspace에서 설치를 마쳐 주세요"
!define MUI_FINISHPAGE_TEXT "AX Workspace에 확장 설치 확인창을 열었습니다.$\r$\n$\r$\n앱에서 서버 주소와 설치 위치를 확인하고 [설치]를 누른 뒤, P&T AI Square 메뉴에서 개인 KEY를 입력하세요.$\r$\n$\r$\n이미 열려 있는 다른 팝업이 있다면 먼저 닫아 주세요."
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "Korean"

Function .onInit
  SetShellVarContext current
!ifdef IMPORT_TEST_HOST
  ; Compile-time fixture hook, never set by configure_server.py or distribution.
  StrCpy $HostExe "${IMPORT_TEST_HOST}"
!else
  SetRegView 64
  ReadRegStr $HostExe HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AX.Workspace.Desktop" "InstallLocation"
  ${If} $HostExe == ""
    SetRegView 32
    ReadRegStr $HostExe HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AX.Workspace.Desktop" "InstallLocation"
  ${EndIf}
  ${If} $HostExe == ""
    StrCpy $HostExe "$LOCALAPPDATA\Programs\AX Workspace"
  ${EndIf}
  ClearErrors
  FileOpen $0 "$HostExe\AX-Workspace.install-id" r
  IfErrors invalid_host
  FileRead $0 $1
  FileClose $0
  StrCmp $1 "AX.Workspace.Desktop" owned_host
  StrCmp $1 "AX.Workspace.Desktop$\r$\n" owned_host
  StrCmp $1 "AX.Workspace.Desktop$\n" owned_host
  Goto invalid_host
  owned_host:
  StrCpy $HostExe "$HostExe\AX-Workspace.exe"
!endif
  ${IfNot} ${FileExists} "$HostExe"
    invalid_host:
    MessageBox MB_OK|MB_ICONSTOP "AX Workspace를 찾지 못했습니다.$\r$\n최신 AX Workspace 설치 파일을 현재 Windows 계정에 먼저 설치한 뒤 다시 실행해 주세요." /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
FunctionEnd

Section "AX Workspace에서 설치 확인"
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  ClearErrors
  File /oname=package.axextension "${PACKAGE_ZIP}"
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "확장 파일을 준비하지 못했습니다. 임시 폴더 접근 권한과 보안 프로그램 기록을 확인해 주세요." /SD IDOK
    SetErrorLevel 5
    Abort
  ${EndIf}
  DetailPrint "AX Workspace의 확장 설치 확인창을 여는 중입니다."
  ClearErrors
  ; The host waits until receive() owns a verified copy. Only then may NSIS
  ; remove this temporary source; the app owns review/install/cancel lifetime.
  ExecWait '"$HostExe" --import-extension "$PLUGINSDIR\package.axextension"' $HostResult
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "AX Workspace를 실행하지 못했습니다. 최신 앱이 설치되어 있는지 확인해 주세요." /SD IDOK
    SetErrorLevel 3
    Abort
  ${EndIf}
  ${If} $HostResult != 0
    MessageBox MB_OK|MB_ICONSTOP "확장 설치 확인창을 열지 못했습니다. AX Workspace에 표시된 안내를 확인해 주세요.$\r$\n오래된 앱이라면 최신 설치 파일로 갱신한 뒤 다시 실행해 주세요.$\r$\n진단 코드: $HostResult" /SD IDOK
    SetErrorLevel 4
    Abort
  ${EndIf}
  DetailPrint "확장 파일 전달 완료. 앱에서 [설치]를 선택해 주세요."
  SetErrorLevel 0
SectionEnd
