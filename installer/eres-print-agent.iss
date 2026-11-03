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
#define MyAppVersion "1.1.3"
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
; On an upgrade `install` fails because the service already exists, and
; PrepareToInstall has just stopped it — so start it explicitly, or the
; upgrade would leave a working install sitting there stopped.
Filename: "{app}\{#MyAppExeName}"; Parameters: "start"; StatusMsg: "Starting ERES Print Agent service..."; Flags: runhidden
; Pairing runs from CurStepChanged below (it needs the code typed on the
; "Connect to ERES" page and must report a failure to the user).

[UninstallRun]
Filename: "{app}\{#MyAppExeName}"; Parameters: "uninstall"; RunOnceId: "StopService"; Flags: runhidden

[Code]
var
  PairPage: TInputQueryWizardPage;

// "Connect to ERES" page: the pairing code from ERES Settings > Printers.
// Can also be passed as ERESPrintAgentSetup.exe /CODE=ABCD-EFGH. Left empty
// (e.g. an upgrade of an already paired computer), pairing is skipped.
procedure InitializeWizard;
begin
  PairPage := CreateInputQueryPage(wpSelectDir,
    'Connect to ERES',
    'Enter the pairing code shown in ERES',
    'In ERES, open Settings > Printers, click "Add this computer" and choose Windows. ' +
    'Type the 8-character code shown there. Leave it empty if this computer is already connected.');
  PairPage.Add('Pairing code:', False);
  PairPage.Values[0] := ExpandConstant('{param:CODE|}');
end;

function PairCode(): String;
begin
  Result := Uppercase(Trim(PairPage.Values[0]));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep = ssPostInstall) and (PairCode() <> '') then
  begin
    WizardForm.StatusLabel.Caption := 'Connecting to ERES...';
    // `pair` saves the credential and restarts the service itself.
    if (not Exec(ExpandConstant('{app}\{#MyAppExeName}'), 'pair ' + PairCode(), '', SW_HIDE,
      ewWaitUntilTerminated, ResultCode)) or (ResultCode <> 0) then
      MsgBox('ERES Print Agent was installed, but connecting to ERES failed. ' +
        'The code may have expired: in ERES Settings > Printers click "New pairing code", ' +
        'then run this installer again and enter the new code.', mbError, MB_OK);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  // The running service holds eres-print-agent.exe open, so upgrading over
  // it fails with "DeleteFile failed; code 5. Access is denied." Stop it
  // before any file is copied. `sc stop` returns once the request is
  // accepted rather than once the process has exited, so give the SCM a
  // few seconds to actually release the handle.
  if Exec(ExpandConstant('{sys}\sc.exe'), 'stop ERESPrintAgent', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode) then
    Sleep(5000);
end;

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
