# PyInstaller spec — builds a single eres-print-agent.exe.
#
# Run ON WINDOWS (or a Windows CI runner) from the print-agent/ directory:
#   pyinstaller installer/build_exe.spec --distpath dist --workpath build
#
# Cannot be run/verified on macOS — pywin32's win32serviceutil/win32print
# modules this depends on don't exist there. See scripts/build_windows.ps1
# for the full build sequence (this spec is one step of it).

# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ["../eres_print_agent/__main__.py"],
    pathex=["../"],
    binaries=[],
    datas=[
        ("../eres_print_agent/db/schema.sql", "eres_print_agent/db"),
    ],
    hiddenimports=[
        "win32timezone",  # pywin32 service framework pulls this in lazily
        "servicemanager",
        "win32serviceutil",
        "win32service",
        "win32event",
        "win32print",
        "win32con",
        "win32cred",
        "keyring.backends.Windows",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="eres-print-agent",
    console=True,  # a CLI tool — must keep a console for `status`/`printers`/etc. output
    onefile=True,
    icon=None,
)
