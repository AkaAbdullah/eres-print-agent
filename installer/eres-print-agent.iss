; Inno Setup script — builds the customer-facing Windows installer.
;
; Compile ON WINDOWS with Inno Setup 6 (https://jrsoftware.org/isinfo.php),
; after installer/build_exe.spec has produced dist/eres-print-agent.exe:
;   ISCC.exe installer\eres-print-agent.iss
;
; Cannot be compiled/tested from macOS. See installer/post-install-verify.md
; for the manual checklist to run on a real Windows machine after this
; produces ERESPrintAgentSetup.exe.

#define MyAppName "ERES Print Agent"
#define MyAppVersion "1.0.8"
#define MyAppPublisher "ERES"
#define MyAppExeName "eres-print-agent.exe"

[Setup]
AppId={{B7E2C6A0-1F3E-4B8A-9C7A-ERESPRINTAGENT}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ERES Print Agent
DisableProgramGroupPage=yes
; Requires elevation: installing a Windows Service needs admin rights.
PrivilegesRequired=admin
OutputBaseFilename=ERESPrintAgentSetup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "..\dist\eres-print-agent.exe"; DestDir: "{app}"; Flags: ignoreversion
; SumatraPDF.exe (bundled separately, not built by this repo — see
; printing/windows.py's docstring) must be placed here before compiling:
Source: "SumatraPDF.exe"; DestDir: "{app}"; Flags: ignoreversion
; %ProgramData%\ERES\PrintAgent is created by the agent itself on first run,
; not by the installer.

[Registry]
; Appends {app} to the machine PATH so `eres-print-agent` resolves from any
; terminal, matching the bare command shown in Settings > Printers
; (printers-manager.tsx) instead of requiring the full install path.
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
    Check: NeedsAddPath('{app}')

[Run]
; Installs + auto-starts the Windows Service (see service/windows_service.py's
; install_service(), which also configures `sc failure` auto-restart).
; Pairing (`eres-print-agent pair <code>`) is left to the operator afterward —
; there is nothing else for this installer to configure (spec section 33/42).
Filename: "{app}\{#MyAppExeName}"; Parameters: "install"; StatusMsg: "Installing ERES Print Agent service..."; Flags: runhidden

[UninstallRun]
Filename: "{app}\{#MyAppExeName}"; Parameters: "uninstall"; RunOnceId: "StopService"; Flags: runhidden

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKLM, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  // Only add if the install dir isn't already a substring of the PATH
  // (avoids duplicates on repair/reinstall).
  Result := Pos(';' + Uppercase(Param) + ';', ';' + Uppercase(OrigPath) + ';') = 0;
end;

procedure RemovePath(Path: string);
var
  Paths: string;
  P: Integer;
begin
  if not RegQueryStringValue(HKLM, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', Paths) then
    exit;

  P := Pos(';' + Uppercase(Path) + ';', ';' + Uppercase(Paths) + ';');
  if P = 0 then
  begin
    // Path may be at the very start or very end without a matching semicolon
    // on one side; the leading/trailing ';' padding above already handles
    // that, so P = 0 here means it's genuinely absent.
    exit;
  end;

  Delete(Paths, P - 1, Length(Path) + 1);
  RegWriteStringValue(HKLM, 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', Paths);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemovePath(ExpandConstant('{app}'));
end;
