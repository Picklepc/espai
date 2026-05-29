; ESPAI Windows Installer
; Requires Inno Setup 6.x  (https://jrsoftware.org/isinfo.php)
;
; Two-directory install model:
;
;   Install dir  {localappdata}\Programs\ESPAI   — exe + bundled read-only assets
;                Overwritten on every update.
;
;   User data    %USERPROFILE%\Documents\ESPAI    — projects, DB, firmware catalog,
;                content packs, .env              — created on first launch.
;                NEVER written by this installer; survives updates and uninstalls.
;
; Build manually:
;   iscc /DMyAppVersion=0.1.0 installer\espai.iss
;
; Build via CI:
;   The release workflow passes /DMyAppVersion automatically from the git tag.

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

#define MyAppName      "ESPAI"
#define MyAppExe       "espai.exe"
#define MyAppPublisher "ESPAI Project"
#define MyAppURL       "https://github.com/espai/espai"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
; Install to per-user Programs folder — no elevation required.
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=..\installer-output
OutputBaseFilename=ESPAI-Setup-{#MyAppVersion}
; LZMA solid compression for smallest single-file output.
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExe}
WizardStyle=modern
LicenseFile=..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
  GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "startup"; Description: "Start &ESPAI Hub automatically with Windows"; \
  GroupDescription: "Startup options:"

[Files]
; Bundle the entire PyInstaller one-dir output.
Source: "..\dist\espai\*"; DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";           Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}";   Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; \
  Tasks: desktopicon

[Registry]
; Write startup registry key when "startup" task is selected during install.
Root: HKCU; \
  Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; \
  ValueName: "{#MyAppName}"; \
  ValueData: """{app}\{#MyAppExe}"""; \
  Flags: uninsdeletevalue; \
  Tasks: startup

[Run]
; Offer to launch the app at the end of installation.
Filename: "{app}\{#MyAppExe}"; \
  Description: "Launch {#MyAppName} Hub"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
; Kill the running process before uninstall proceeds.
Filename: "taskkill"; Parameters: "/F /IM {#MyAppExe}"; \
  Flags: runhidden; RunOnceId: "KillESPAI"

[Code]
// Clean up autostart registry key on uninstall even if the user toggled it
// via the tray menu after installation (which doesn't carry an uninsdeletevalue flag).
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(
      HKEY_CURRENT_USER,
      'Software\Microsoft\Windows\CurrentVersion\Run',
      '{#MyAppName}'
    );
end;
