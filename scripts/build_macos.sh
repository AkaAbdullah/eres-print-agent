#!/usr/bin/env bash
# Builds dist/eres-print-agent-macos-<arch>.tar.gz — the file the ERES
# one-line Mac installer downloads (web/app/api/print-agent/install/mac).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

ARCH="$(uname -m)"
PY="${PYTHON:-./.venv/bin/python}"
"$PY" -m pip install -q -e . pyinstaller
"$PY" -m PyInstaller installer/build_macos.spec --distpath dist --workpath build --noconfirm
tar -C dist -czf "dist/eres-print-agent-macos-${ARCH}.tar.gz" eres-print-agent
echo "Built dist/eres-print-agent-macos-${ARCH}.tar.gz"
