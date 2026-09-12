"""Secure storage for the agent's permanent credential (agentSecret).

Uses the `keyring` library rather than hand-rolled win32cred bindings: on
Windows its default backend IS win32cred (Windows Credential Locker), which
satisfies spec section 11's "never store it in plain text if secure OS
credential storage is available" with one code path instead of a
per-platform branch — and lets this exact code be exercised in dev on
macOS (Keychain) too, not just on a real Windows box.

Falls back to a 0600-permissioned file under the config directory only if
no OS keyring backend is available at all (e.g. a headless Linux box with
no secret service running) — logged loudly, since that's a real
degradation, not the intended path.
"""

from __future__ import annotations

import logging
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .config import CONFIG_DIR
from .constants import KEYRING_SERVICE_NAME

logger = logging.getLogger(__name__)

_FALLBACK_PATH = CONFIG_DIR / "credential.fallback"

# Windows-only, and the only store that actually works here. `pair` runs as
# the logged-in administrator while the service runs as LocalSystem, and the
# Credential Locker that keyring uses on Windows is per-user — so a secret
# saved by pairing is invisible to the service, which then treats itself as
# unpaired and stops immediately. DPAPI with CRYPTPROTECT_LOCAL_MACHINE is
# scoped to the machine rather than the user, so both can read it.
_WINDOWS_SECRET_PATH = CONFIG_DIR / "credential.dpapi"
_CRYPTPROTECT_LOCAL_MACHINE = 0x4

# LocalSystem and the Administrators group, by SID so this does not depend on
# the display language of the Windows install.
_LOCAL_SYSTEM_SID = "*S-1-5-18"
_ADMINISTRATORS_SID = "*S-1-5-32-544"


def _try_win32crypt():
    if sys.platform != "win32":
        return None
    try:
        import win32crypt

        return win32crypt
    except ImportError:
        return None


def _restrict_to_system_and_admins(path: Path) -> None:
    """The blob is machine-scoped, so anything that can read the file can
    decrypt it — keep it off limits to ordinary local accounts."""
    try:
        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{_LOCAL_SYSTEM_SID}:F",
                f"{_ADMINISTRATORS_SID}:F",
            ],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        logger.warning("Could not restrict permissions on %s: %s", path, error)


def _save_windows_secret(agent_id: str, secret: str) -> bool:
    win32crypt = _try_win32crypt()
    if not win32crypt:
        return False
    try:
        blob = win32crypt.CryptProtectData(
            f"{agent_id}\n{secret}".encode("utf-8"),
            "ERES Print Agent credential",
            None,
            None,
            None,
            _CRYPTPROTECT_LOCAL_MACHINE,
        )
    except Exception as error:
        logger.warning("DPAPI encryption failed (%s).", error)
        return False

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _WINDOWS_SECRET_PATH.write_bytes(blob)
    _restrict_to_system_and_admins(_WINDOWS_SECRET_PATH)
    return True


def _load_windows_secret(agent_id: str) -> Optional[str]:
    win32crypt = _try_win32crypt()
    if not win32crypt or not _WINDOWS_SECRET_PATH.exists():
        return None
    try:
        _description, data = win32crypt.CryptUnprotectData(
            _WINDOWS_SECRET_PATH.read_bytes(), None, None, None, 0
        )
    except Exception as error:
        logger.warning("DPAPI decryption failed (%s).", error)
        return None

    stored_id, _, secret = data.decode("utf-8").partition("\n")
    if stored_id != agent_id or not secret:
        return None
    return secret.strip()


def _try_keyring():
    try:
        import keyring
        from keyring.errors import KeyringError

        return keyring, KeyringError
    except ImportError:
        return None, None


def save_agent_secret(agent_id: str, secret: str) -> None:
    if _save_windows_secret(agent_id, secret):
        return

    keyring, KeyringError = _try_keyring()
    if keyring:
        try:
            keyring.set_password(KEYRING_SERVICE_NAME, agent_id, secret)
            return
        except KeyringError as error:
            logger.warning("OS keyring unavailable (%s), falling back to a local file.", error)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _FALLBACK_PATH.write_text(f"{agent_id}\n{secret}\n", encoding="utf-8")
    try:
        os.chmod(_FALLBACK_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # best-effort on platforms without POSIX permission bits (Windows ACLs differ)
    logger.warning("Credential stored in %s (no OS keyring backend found).", _FALLBACK_PATH)


def load_agent_secret(agent_id: str) -> Optional[str]:
    secret = _load_windows_secret(agent_id)
    if secret:
        return secret

    keyring, KeyringError = _try_keyring()
    if keyring:
        try:
            secret = keyring.get_password(KEYRING_SERVICE_NAME, agent_id)
            if secret:
                return secret
        except KeyringError as error:
            logger.warning("OS keyring read failed (%s), checking fallback file.", error)

    if _FALLBACK_PATH.exists():
        lines = _FALLBACK_PATH.read_text(encoding="utf-8").splitlines()
        if len(lines) >= 2 and lines[0] == agent_id:
            return lines[1]
    return None


def delete_agent_secret(agent_id: str) -> None:
    if _WINDOWS_SECRET_PATH.exists():
        try:
            _WINDOWS_SECRET_PATH.unlink()
        except OSError:
            pass

    keyring, KeyringError = _try_keyring()
    if keyring:
        try:
            keyring.delete_password(KEYRING_SERVICE_NAME, agent_id)
        except Exception:
            pass  # nothing to delete, or backend already gone — not fatal to uninstall
    if _FALLBACK_PATH.exists():
        try:
            _FALLBACK_PATH.unlink()
        except OSError:
            pass
