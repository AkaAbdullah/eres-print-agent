# ERES Print Agent

A terminal/service-based background printer bridge for ERES. Installed once on a Windows
machine with a printer attached; after that, everything is managed from ERES's own
**Settings > Printers** page. No desktop UI, no system tray, no Electron.

## Technology decision (spec section 3/44)

**Python + pywin32**, not Node.js. Reasoning:

- **Windows Service integration**: `pywin32`'s `win32serviceutil.ServiceFramework` is the
  long-established, well-documented way to run a Python process as a real Windows Service
  (start automatically, survive without an interactive session, integrate with `sc.exe`
  for auto-restart-on-crash). Node's equivalents (`node-windows`, generating a wrapper
  around NSSM) are thinner community layers around the same underlying Windows APIs, with
  less real-world service-management track record.
- **Printer discovery/status**: `win32print` gives direct, first-class access to the Print
  Spooler (`EnumPrinters`, `GetPrinter`, device capabilities) — the same low-level surface
  the Node alternative (`pdf-to-printer`) itself calls out to via a bundled PowerShell/
  native helper anyway. Doing it directly in Python avoids an extra process hop.
  - Neither ecosystem's library renders PDF pages into printer output on its own — see
    `printing/windows.py`'s docstring for why this agent shells out to a bundled
    SumatraPDF for the actual print, same as `pdf-to-printer` does under the hood.
- **Everything else** (WebSocket client, SQLite queue, message validation) is equally
  well-supported in both ecosystems (`websockets`, stdlib `sqlite3`, `pydantic`), so those
  weren't deciding factors.

Packaged with PyInstaller into a single `eres-print-agent.exe`, wrapped in an Inno Setup
installer (see `installer/`).

## Architecture

```
eres_print_agent/
  cli.py               entry point: install/uninstall/start/stop/restart/status/
                        printers/pair/test-print/logs/version/run
  config.py             non-secret config.json (agentId, hubUrl, allowedDocumentHost)
  credentials.py         agentSecret via OS keyring (win32cred on Windows, Keychain on macOS)
  status_store.py        status.json snapshot — how a separate CLI invocation sees live state
  models.py               pydantic models mirroring print-hub/PROTOCOL.md
  state_machine.py         PrintJobStatus + legal transitions
  db/queue_store.py         SQLite job queue — the durability guarantee (see below)
  printing/                 PrinterManager interface + windows.py / mock.py / factory.py
  net/                       ws_client.py (connect/auth/heartbeat/backoff), downloader.py, protocol_codec.py
  core/                       agent.py (orchestrator), job_worker.py, printer_sync.py, pairing.py
  service/windows_service.py  the actual Windows Service wrapper (Windows-only)
```

See the sibling `print-hub/` repo's `PROTOCOL.md` for the full WebSocket message spec, and
its `README.md` for why the server side is a separate service rather than living inside the
main `web/` Next.js app.

## The durability guarantee

Every print job follows **Receive → Validate → Persist → ACK → Download → Print**
(`core/job_worker.py`). The SQLite `INSERT` happens *before* the agent acks receipt — a
crash between receiving and acking just means the ack never went out, and print-hub
re-dispatches the job (still `QUEUED` in ERES's own database) on the agent's next
`authenticate`. A crash mid-*print* is handled conservatively: on the next startup, any job
found `PRINTING` is marked `FAILED`/`AGENT_RESTARTED_DURING_PRINT` rather than blindly
retried (which could double-print) or silently dropped (which could lose it) — see
`db/queue_store.py`'s `mark_stuck_printing_as_failed()`.

## Local development (macOS/Linux)

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
./.venv/bin/pytest -q
```

To exercise the full pairing → connect → print round trip without a real Windows box,
physical printer, or production ERES:

```bash
# In print-hub/: start the mock web/ callback layer + the real print-hub
pnpm --dir ../print-hub dev:mock-web   # seeds pairing code MOCK-CODE
pnpm --dir ../print-hub dev            # WEB_CALLBACK_URL pointed at the mock

# Here: pair against the mock, then run in the foreground
./scripts/dev_run.sh pair MOCK-CODE
./scripts/dev_run.sh run
```

`ERES_PRINT_AGENT_FORCE_MOCK_PRINTER=1` (set by `dev_run.sh`) swaps in `printing/mock.py`,
which "prints" by copying the PDF to `./mock-print-output/` — this is what makes the whole
pipeline testable without a physical printer or Windows.

## Testing

```bash
pytest -q
```

Covers: state machine legality, SQLite queue durability/dedupe/crash-recovery, protocol
codec validation, document downloader (URL/host/content-type/size validation, via
`httpx.MockTransport` — no real network calls), the mock printer backend, and a live
reconnect-with-backoff test against a real local WebSocket server.

**Not covered by these tests** (see `installer/post-install-verify.md` for the manual
checklist): `printing/windows.py`'s actual `win32print`/SumatraPDF calls,
`service/windows_service.py`'s actual service install/start/crash-restart, and
`credentials.py`'s Windows keyring backend specifically (its macOS/Keychain path IS
exercised by running this on macOS, since `keyring` uses the same API surface on both).

## Security notes (spec section 29)

- WSS only in production (`ws://` is only ever used against `localhost` in dev).
- `agentSecret` never touches disk in plaintext when an OS keyring is available; see
  `credentials.py` for the fallback behavior when one genuinely isn't.
- Every `print.job.documentUrl` is validated against `allowedDocumentHost` (pinned at
  pairing time from the paired ERES app's own origin) before being fetched — closes off a
  compromised/malicious print-hub handing the agent a job pointing anywhere else on the
  internet. See `net/downloader.py`.
- No shell execution of agent-supplied or job-supplied strings. The one external process
  invocation (`printing/windows.py`'s SumatraPDF call) uses an explicit argument list via
  `subprocess.run`, never `shell=True`, and every argument originates from this codebase or
  a locally-downloaded file path — never a raw string from the network.
- Logs are redacted (`logging_setup.py`) for `agentSecret` and `Authorization` headers; no
  document contents are ever logged.

## Building the Windows installer

Handled by `.github/workflows/build-installer.yml` on a `windows-latest` GitHub Actions
runner — that's the only environment PyInstaller/pywin32/Inno Setup can actually produce a
working artifact on. Two ways to trigger it:

- **Manual**: Actions tab → "Build Windows Installer" → Run workflow. Artifact appears
  under the run's Artifacts section.
- **Tagged release**: `git tag v1.0.0 && git push origin v1.0.0` — also attaches
  `ERESPrintAgentSetup.exe` to a GitHub Release automatically.

The workflow downloads SumatraPDF (bundled for actual PDF printing — see
`printing/windows.py`'s docstring) and checks it against a SHA256 pinned in the workflow
file, computed by hand at the time it was added, since SumatraPDF doesn't publish an
official checksum. A mismatch fails the build rather than silently bundling whatever the
URL currently serves.

For a one-off local build instead, `scripts/build_windows.ps1` does the same steps — run it
on an actual Windows machine (see the script's own header for prerequisites).

## What cannot be verified from macOS

- `service/windows_service.py`: real Windows Service install/start/stop/crash-restart, and
  the `sc.exe failure` auto-restart configuration actually firing.
- `printing/windows.py`: real `win32print` discovery/status/printing against a physical or
  virtual Windows printer.
- `credentials.py`'s Windows keyring backend (Credential Locker) specifically.
- CI (`.github/workflows/build-installer.yml`) verifies the installer *compiles*, but not
  that it *works* — actually running it, installing the service, and everything in
  `installer/post-install-verify.md` still needs a human on a real Windows machine.

Everything else — the full WS protocol round trip, SQLite queue behavior, reconnect/backoff
timing, and the CLI's non-service commands — has been exercised end-to-end against
`print-hub` + its mock harness during development (pair → connect → sync → dispatch →
complete → offline-queue → reconnect-redelivery, including killing and restarting the agent
mid-session).

## Troubleshooting

- `eres-print-agent status --json` / `eres-print-agent logs` are the first stop — status.json
  and the rotating log file are both readable without stopping the service.
- "Not paired" — run `eres-print-agent pair <code>` with a fresh code from ERES Settings >
  Printers (codes expire after 15 minutes).
- "Paired, but no credential found in the OS keyring" — the keyring entry was removed
  outside this tool (or you're on a machine with no working keyring backend and the
  fallback file was deleted). Re-run `pair`.
- Windows-specific: see `installer/post-install-verify.md`.
