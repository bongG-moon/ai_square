Unicode true
RequestExecutionLevel user
ManifestDPIAware true
ManifestLongPathAware true
SetCompressor /SOLID lzma
!include "MUI2.nsh"
!include "LogicLib.nsh"
!define PRODUCT_ID "AX.OrganizationStore"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_ID}"
Name "P&T AI Square — AX Workspace 추가 기능"
OutFile "${OUTPUT_FILE}"
InstallDir "$LOCALAPPDATA\Programs\AX AI Store"
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=1042 "ProductName" "P&T AI Square — AX Workspace 추가 기능"
VIAddVersionKey /LANG=1042 "FileDescription" "현재 사용자에게 P&T AI Square 확장을 설치합니다"
VIAddVersionKey /LANG=1042 "FileVersion" "${APP_VERSION}.0"
VIAddVersionKey /LANG=1042 "ProductVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1042 "LegalCopyright" "AX Workspace contributors"
BrandingText "AX Workspace · 선택 설치형 추가 기능"
ShowInstDetails show
ShowUninstDetails show
Var HostExe
Var ConnectionPreset
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "P&T AI Square 추가 기능 설치"
!define MUI_WELCOMEPAGE_TEXT "확장 연결부가 포함된 AX Workspace가 먼저 설치되어 있어야 합니다.$\r$\n$\r$\n현재 사용자 계정에 P&T AI Square를 추가합니다. 기존 앱 파일, 업무, Claude 설정은 변경하지 않습니다.$\r$\n$\r$\n설치 후 AX Workspace를 완전히 종료한 뒤 다시 열어 주세요."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "P&T AI Square 설치 완료"
!define MUI_FINISHPAGE_TEXT "AX Workspace를 완전히 종료한 뒤 다시 열면 P&T AI Square 메뉴가 나타납니다.$\r$\n$\r$\n웹에서 받은 ZIP에 서버 주소가 포함되어 있으면 개인 KEY만 입력해 연결하세요. HTTP 서버는 사용 확인이 한 번 필요합니다.$\r$\n주소 파일 없이 설치했다면 플랫폼 주소도 입력해 주세요."
!insertmacro MUI_PAGE_FINISH
!define MUI_UNCONFIRMPAGE_TEXT_TOP "AX Workspace를 완전히 종료한 뒤 제거해 주세요.$\r$\n$\r$\n스토어 확장 프로그램만 제거합니다. 연결 설정, 다운로드와 설치한 스킬·플러그인은 유지합니다."
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH
!insertmacro MUI_LANGUAGE "Korean"
Function .onInit
  SetShellVarContext current
  SetRegView 64
  ReadRegStr $HostExe HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AX.Workspace.Desktop" "InstallLocation"
  ${If} $HostExe == ""
    StrCpy $HostExe "$LOCALAPPDATA\Programs\AX Workspace"
  ${EndIf}
  StrCpy $HostExe "$HostExe\AX-Workspace.exe"
FunctionEnd
Section "P&T AI Square" MainSection
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File /oname=StoreInstaller.exe "${SUPPORT_EXE}"
  File /oname=store-package.zip "${PACKAGE_ZIP}"
  StrCpy $ConnectionPreset ""
  ${If} ${FileExists} "$EXEDIR\connection.json"
    StrCpy $ConnectionPreset "$EXEDIR\connection.json"
    nsExec::ExecToStack /TIMEOUT=15000 '"$PLUGINSDIR\StoreInstaller.exe" check-connection "$ConnectionPreset"'
    Pop $0
    Pop $1
    ${If} $0 != 0
      MessageBox MB_ICONSTOP "$1" /SD IDOK
      SetErrorLevel 2
      Abort
    ${EndIf}
  ${EndIf}
  nsExec::ExecToStack /TIMEOUT=30000 '"$PLUGINSDIR\StoreInstaller.exe" check-host "$HostExe"'
  Pop $0
  Pop $1
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "$1" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
  nsExec::ExecToStack /TIMEOUT=15000 '"$PLUGINSDIR\StoreInstaller.exe" check-control "$INSTDIR"'
  Pop $0
  Pop $1
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "$1" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
  SetOutPath "$INSTDIR"
  ClearErrors
  File /oname=StoreInstaller.exe "${SUPPORT_EXE}"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  File /oname=NSIS-COPYING.txt "${LICENSE_DIR}\NSIS-COPYING.txt"
  File /oname=NSIS-Modern-UI-2.txt "${LICENSE_DIR}\NSIS-Modern-UI-2.txt"
  File /oname=THIRD_PARTY_NOTICES.md "${NOTICE_FILE}"
  FileOpen $0 "$INSTDIR\store.install-id" w
  FileWrite $0 "${PRODUCT_ID}"
  FileClose $0
  ${If} ${Errors}
    MessageBox MB_ICONSTOP "설치 도구를 저장하지 못했습니다. 폴더 접근 권한을 확인해 주세요." /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
  ${If} $ConnectionPreset == ""
    nsExec::ExecToStack /TIMEOUT=120000 '"$PLUGINSDIR\StoreInstaller.exe" install "$LOCALAPPDATA\CompanyAgent" "$PLUGINSDIR\store-package.zip" "$HostExe"'
  ${Else}
    nsExec::ExecToStack /TIMEOUT=120000 '"$PLUGINSDIR\StoreInstaller.exe" install "$LOCALAPPDATA\CompanyAgent" "$PLUGINSDIR\store-package.zip" "$HostExe" "$ConnectionPreset"'
  ${EndIf}
  Pop $0
  Pop $1
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "$1" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
  DetailPrint "$1"
  ClearErrors
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "P&T AI Square — AX Workspace 추가 기능"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "AX Workspace"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
  ${If} ${Errors}
    MessageBox MB_ICONSTOP "스토어 파일은 설치했지만 Windows의 설치 프로그램 목록에 등록하지 못했습니다.$\r$\n$INSTDIR\Uninstall.exe에서 제거할 수 있습니다. 계정의 등록 권한을 확인해 주세요." /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
SectionEnd
Function un.onInit
  SetShellVarContext current
  SetRegView 64
FunctionEnd
Section "Uninstall"
  nsExec::ExecToStack /TIMEOUT=15000 '"$INSTDIR\StoreInstaller.exe" check-control "$INSTDIR"'
  Pop $0
  Pop $1
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "$1" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
  nsExec::ExecToStack /TIMEOUT=120000 '"$INSTDIR\StoreInstaller.exe" uninstall "$LOCALAPPDATA\CompanyAgent"'
  Pop $0
  Pop $1
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "$1" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
  Delete "$INSTDIR\StoreInstaller.exe"
  Delete "$INSTDIR\store.install-id"
  Delete "$INSTDIR\NSIS-COPYING.txt"
  Delete "$INSTDIR\NSIS-Modern-UI-2.txt"
  Delete "$INSTDIR\THIRD_PARTY_NOTICES.md"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
SectionEnd
