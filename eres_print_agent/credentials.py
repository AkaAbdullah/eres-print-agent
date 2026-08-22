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
from pathlib import Path
from typing import Optional

from .config import CONFIG_DIR
from .constants import KEYRING_SERVICE_NAME

logger = logging.getLogger(__name__)

_FALLBACK_PATH = CONFIG_DIR / "credential.fallback"


def _try_keyring():
    try:
        import keyring
        from keyring.errors import KeyringError

        return keyring, KeyringError
    except ImportError:
        return None, None


def save_agent_secret(agent_id: str, secret: str) -> None:
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
