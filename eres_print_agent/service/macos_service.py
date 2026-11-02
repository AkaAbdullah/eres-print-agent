"""macOS background service: a per-user launchd LaunchAgent.

launchd starts the agent when the user logs in, restarts it if it ever
exits, and keeps running it with the Mac's screen locked. A LaunchAgent (not
a system LaunchDaemon) is used on purpose: it needs no administrator
password, and printing as the logged-in user sees exactly the printers that
user added in System Settings > Printers & Scanners.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import List

from ..config import LOG_DIR, ensure_directories

LABEL = "cloud.eres.printagent"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"

# Passed through to the service when set at install time (local development
# against an http:// ERES; never set for a normal install).
_PASSTHROUGH_ENV = ("ERES_PRINT_AGENT_ALLOW_INSECURE_HTTP",)


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _target() -> str:
    return f"{_domain()}/{LABEL}"


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def _program_arguments() -> List[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "run"]
    return [sys.executable, "-m", "eres_print_agent", "run"]


def service_exists() -> bool:
    return PLIST_PATH.exists()


def _is_loaded() -> bool:
    return _launchctl("print", _target()).returncode == 0


def install_service() -> None:
    ensure_directories()
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": LABEL,
        "ProgramArguments": _program_arguments(),
        "RunAtLoad": True,
        "KeepAlive": True,
        # If it exits straight away (e.g. not paired yet), don't spin.
        "ThrottleInterval": 15,
        "ProcessType": "Background",
        "StandardOutPath": str(LOG_DIR / "launchd.out.log"),
        "StandardErrorPath": str(LOG_DIR / "launchd.err.log"),
    }
    env = {key: os.environ[key] for key in _PASSTHROUGH_ENV if os.environ.get(key)}
    if env:
        plist["EnvironmentVariables"] = env
    with open(PLIST_PATH, "wb") as handle:
        plistlib.dump(plist, handle)

    if _is_loaded():
        _launchctl("bootout", _target())
    result = _launchctl("bootstrap", _domain(), str(PLIST_PATH))
    if result.returncode != 0 and not _is_loaded():
        raise RuntimeError(f"launchctl bootstrap failed: {(result.stderr or result.stdout).strip()}")


def uninstall_service() -> None:
    if _is_loaded():
        _launchctl("bootout", _target())
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()


def start_service() -> None:
    if not service_exists():
        install_service()
        return
    if not _is_loaded():
        _launchctl("bootstrap", _domain(), str(PLIST_PATH))
    _launchctl("kickstart", _target())


def stop_service() -> None:
    # bootout, not `kill`: KeepAlive would start it again straight away.
    if _is_loaded():
        _launchctl("bootout", _target())


def restart_service() -> None:
    if not _is_loaded():
        start_service()
        return
    result = _launchctl("kickstart", "-k", _target())
    if result.returncode != 0:
        raise RuntimeError(f"launchctl kickstart failed: {(result.stderr or result.stdout).strip()}")


def query_service_status() -> str:
    if not service_exists():
        return "not installed"
    result = _launchctl("print", _target())
    if result.returncode != 0:
        return "stopped"
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("state ="):
            return line.split("=", 1)[1].strip()
    return "loaded"
