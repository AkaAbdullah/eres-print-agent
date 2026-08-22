# Full Windows build sequence: venv -> deps -> PyInstaller -> Inno Setup.
# Run ON WINDOWS (or a Windows CI runner) from the print-agent/ directory:
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
#
# Prerequisites:
#   - Python 3.11+ on PATH
#   - Inno Setup 6 installed, ISCC.exe on PATH
#   - installer\SumatraPDF.exe present (download separately — see
#     printing/windows.py's docstring; not fetched by this script since it's
#     a third-party binary this repo doesn't redistribute automatically)

$ErrorActionPreference = "Stop"

Write-Host "==> Creating build venv"
python -m venv .venv-build
.\.venv-build\Scripts\pip install --upgrade pip
.\.venv-build\Scripts\pip install -r requirements.txt
.\.venv-build\Scripts\pip install "pywin32>=306" pyinstaller

Write-Host "==> Running tests before packaging anything"
.\.venv-build\Scripts\pip install -r requirements-dev.txt
.\.venv-build\Scripts\python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed — not building an installer from broken code." }

Write-Host "==> Running PyInstaller"
.\.venv-build\Scripts\pyinstaller installer\build_exe.spec --distpath dist --workpath build --noconfirm

if (-not (Test-Path "dist\eres-print-agent.exe")) {
    throw "PyInstaller did not produce dist\eres-print-agent.exe"
}

if (-not (Test-Path "installer\SumatraPDF.exe")) {
    throw "installer\SumatraPDF.exe is missing — download it and place it there before continuing (see printing/windows.py)."
}

Write-Host "==> Compiling the Inno Setup installer"
& ISCC.exe installer\eres-print-agent.iss

Write-Host "==> Done. Installer is in installer\Output\ERESPrintAgentSetup.exe"
Write-Host "==> Now follow installer\post-install-verify.md on a real Windows machine."
