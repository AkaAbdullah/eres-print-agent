# PyInstaller spec — builds the macOS eres-print-agent binary.
#
# Run ON A MAC from the print-agent/ directory (see scripts/build_macos.sh):
#   pyinstaller installer/build_macos.spec --distpath dist --workpath build
# Produces a binary for the Mac's own CPU (arm64 or x86_64).

# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

a = Analysis(
    ["../eres_print_agent/__main__.py"],
    pathex=["../"],
    binaries=[],
    datas=[
        ("../eres_print_agent/db/schema.sql", "eres_print_agent/db"),
        *collect_data_files("certifi"),
    ],
    hiddenimports=[
        *collect_submodules("eres_print_agent"),
    ],
    hookspath=[],
    runtime_hooks=[],
    # Windows-only modules the package imports lazily.
    excludes=["win32print", "win32con", "win32crypt", "win32serviceutil", "servicemanager"],
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="eres-print-agent",
    console=True,
    onefile=True,
    icon=None,
)
