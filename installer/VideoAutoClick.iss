; ============================================================
;  VideoAutoClick - Inno Setup 설치 파일 스크립트
;  사용법: Windows에서 Inno Setup 6 설치 후 이 파일을 더블클릭(또는 ISCC.exe로 컴파일)
;  전제: build_exe.bat(또는 GitHub Actions)로 dist\VideoAutoClick.exe 가 이미 만들어져 있어야 함
;  다운로드: https://jrsoftware.org/isdl.php
; ============================================================

#define MyAppName      "VideoAutoClick"
#define MyAppVersion   "2.0"
#define MyAppExeName   "VideoAutoClick.exe"

[Setup]
; AppId는 프로그램마다 고유해야 함 (표준 16진수 GUID 형식으로 수정됨)
AppId={{8F3C2A51-9D7B-4E6A-B1C4-000000000002}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=VideoAutoClick
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; 프로그램 파일 폴더에 설치하므로 관리자 권한 필요
PrivilegesRequired=admin
OutputDir=..\installer_output
OutputBaseFilename={#MyAppName}-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; 64비트 Windows 전용
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 최소 OS: Windows 10 1809 이상 (OpenCV/tkinter 호환)
MinVersion=10.0.17763
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕 화면에 바로 가기 만들기"; GroupDescription: "추가 바로 가기:"; Flags: unchecked

[Files]
; 실행 파일
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; 사용 설명서 (설치 마지막에 읽기 창 표시)
Source: "..\사용설명서.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\사용 설명서"; Filename: "{app}\사용설명서.txt"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "지금 {#MyAppName} 실행하기"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 설정/로그는 사용자 데이터이므로 제거하지 않고 보존 (원하면 이 섹션 삭제)
