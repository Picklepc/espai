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

; ── Code signing ─────────────────────────────────────────────────────────────
; Windows Smart App Control (SAC) and SmartScreen both require a code-signing
; certificate to trust unsigned executables. Without one, SAC may block the
; installer, the app, and the uninstaller.
;
; To enable signing, set SIGNTOOL_PATH and SIGNTOOL_PARAMS in your environment
; and uncomment the SignTool= line below:
;
;   SignTool=signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f "cert.pfx" /p "%CERT_PASS%" $f
;
; Workaround when SAC blocks the uninstaller:
;   Settings → Privacy & Security → Windows Security →
;   App & browser control → Smart App Control → Off
;   Then uninstall, then re-enable SAC if desired.

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
; Stable GUID — never change this; Windows uses it to associate installer/uninstaller.
AppId={{8F3C2A1B-4D7E-4F9A-B2C3-D1E5F6A7B8C9}
; Version info embedded in the generated uninstaller exe.
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Hub — Local-first ESP32 fleet management
VersionInfoProductName={#MyAppName}
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
var
  DeleteUserData: Boolean;
  DataPromptShown: Boolean;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  // usUninstall fires just before files are removed — reliable hook regardless
  // of whether uninstall was triggered from Settings, Control Panel, or directly.
  if (CurUninstallStep = usUninstall) and (not DataPromptShown) then
  begin
    DataPromptShown := True;
    DataDir := ExpandConstant('{userdocs}\{#MyAppName}');
    if DirExists(DataDir) then
    begin
      DeleteUserData := MsgBox(
        'Remove ESPAI user data?' + #13#10#13#10 +
        DataDir + #13#10#13#10 +
        'This contains your projects, database, firmware catalog,' + #13#10 +
        'content packs, and settings.' + #13#10#13#10 +
        'Yes = delete everything     No = keep (can re-use after reinstall)',
        mbConfirmation,
        MB_YESNO or MB_DEFBUTTON2
      ) = IDYES;
    end;
  end;

  if CurUninstallStep = usPostUninstall then
  begin
    // Always remove the autostart registry entry.
    RegDeleteValue(
      HKEY_CURRENT_USER,
      'Software\Microsoft\Windows\CurrentVersion\Run',
      '{#MyAppName}'
    );
    // Delete user data only if user explicitly chose Yes.
    if DeleteUserData then
    begin
      DataDir := ExpandConstant('{userdocs}\{#MyAppName}');
      if DirExists(DataDir) then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
