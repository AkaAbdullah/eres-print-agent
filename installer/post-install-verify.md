# Post-Install Verification Checklist (Windows)

Run this on a real Windows machine after installing `ERESPrintAgentSetup.exe`.
Nothing on this page can be verified from macOS/Linux — see the main
[README.md](../README.md#what-cannot-be-verified-from-macos) for why.

## 1. Service installed and running

```powershell
sc.exe query ERESPrintAgent
```
Expect `STATE: 4 RUNNING`. If `STOPPED`, the agent is likely unpaired (see step 3) —
check `%ProgramData%\ERES\PrintAgent\logs\agent.log`.

## 2. Auto-restart on crash is configured

```powershell
sc.exe qfailure ERESPrintAgent
```
Expect three `RESTART` actions with 5000ms delays (configured by
`service/windows_service.py`'s `_configure_auto_restart()` during `install`).

## 3. Pairing

ERES Settings > Printers hands the operator the **full-path** form, which works
regardless of PATH state:

```powershell
"C:\Program Files\ERES Print Agent\eres-print-agent.exe" pair <code-from-ERES-Settings-Printers>
```
Expect `Connection: connected` and `Paired: Yes` within a few seconds.

The installer also appends `{app}` to the machine `Path` (see `[Registry]` in
`eres-print-agent.iss`), so the bare command should work too — but only in a
terminal opened *after* install, and Windows often needs a sign-out or reboot
before the change propagates to newly spawned shells. Verify both forms:

```powershell
eres-print-agent status
eres-print-agent restart
```
If the bare form reports "not recognized" in a brand-new terminal after a
reboot, the PATH entry did not apply — investigate before shipping, since the
full-path form above will still mask the problem for pairing.

## 4. Printer discovery

```powershell
eres-print-agent printers
```
Every printer visible in Windows' own **Settings > Bluetooth & devices > Printers &
scanners** should appear here too — USB, network, and shared printers alike. Confirm
in ERES **Settings > Printers** that the same list appears within ~30s (the periodic
sync interval).

## 5. Test print — from the CLI (bypasses ERES)

```powershell
eres-print-agent test-print --printer "<exact printer name from step 4>"
```
Confirm physical output. This isolates whether `printing/windows.py`'s SumatraPDF
invocation works at all, independent of the network path.

## 6. Test print — from ERES (full path)

In ERES **Settings > Printers**, click **Test Print** next to the printer. Confirm:
- Physical output appears.
- ERES shows "Test Print Completed" (not stuck on "Sending...").

## 7. Restart survives a reboot

Restart the Windows machine. After it comes back:
```powershell
sc.exe query ERESPrintAgent
eres-print-agent status
```
Expect `RUNNING` and `Connection: connected` with no manual intervention.

## 8. Internet interruption

Disconnect Wi-Fi/Ethernet for ~60 seconds, then reconnect. `eres-print-agent logs`
should show reconnect attempts on the backoff schedule (1s, 2s, 5s, 10s, 30s, 60s)
and a successful reconnect shortly after connectivity returns.

## 9. Printer disconnected

Physically unplug (or disable) a USB printer. Within ~30s, ERES Settings > Printers
should show it offline. Reconnect it — it should flip back to online within ~30s,
without restarting the service.

## 10. Uninstall

```powershell
"C:\Program Files\ERES Print Agent\unins000.exe" /SILENT
sc.exe query ERESPrintAgent
```
Expect the service query to fail with "service does not exist."

## Known Windows-specific limitations to confirm/document while testing

- **Service account**: installed via `win32serviceutil.InstallService` with no
  explicit account, which defaults to `LocalSystem`. Confirm whether this is
  actually necessary for USB/locally-shared printer access on your test hardware,
  or whether a lower-privilege account (e.g. `NT AUTHORITY\LocalService` or a
  dedicated service account) also works — document the finding in README.md's
  security section. LocalSystem is broad; only keep it if a narrower account
  provably fails to reach the printers.
- **Per-user vs. all-users printers**: a printer installed only for one Windows
  user account may not be visible to a service running as LocalSystem/a different
  account. Confirm behavior with both an all-users-installed printer and a
  single-user one.
- **SumatraPDF licensing/distribution**: confirm the bundled SumatraPDF.exe version
  and its license terms are acceptable for redistribution with the installer.
