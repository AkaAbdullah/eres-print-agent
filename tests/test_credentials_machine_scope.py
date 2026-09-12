"""`pair` runs as the logged-in administrator, the service runs as
LocalSystem, and Windows' Credential Locker is per-user — so a secret saved
through keyring during pairing is invisible to the service, which concludes
it is unpaired and stops. The Windows path must therefore be machine-scoped.
"""

import pytest

from eres_print_agent import credentials


class FakeWin32Crypt:
    """Stands in for pywin32's win32crypt. Machine-scope DPAPI is modelled as
    a blob any 'account' can unprotect, which is the property under test."""

    def __init__(self):
        self.last_flags = None

    def CryptProtectData(self, data, description, entropy, reserved, prompt, flags):
        self.last_flags = flags
        return b"enc:" + data

    def CryptUnprotectData(self, blob, entropy, reserved, prompt, flags):
        assert blob.startswith(b"enc:")
        return ("ERES Print Agent credential", blob[len(b"enc:") :])


@pytest.fixture
def windows(monkeypatch, tmp_path):
    fake = FakeWin32Crypt()
    monkeypatch.setattr(credentials, "_try_win32crypt", lambda: fake)
    monkeypatch.setattr(credentials, "_WINDOWS_SECRET_PATH", tmp_path / "credential.dpapi")
    monkeypatch.setattr(credentials, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(credentials, "_restrict_to_system_and_admins", lambda path: None)
    return fake


def test_secret_round_trips_without_touching_the_per_user_keyring(windows, monkeypatch):
    # Any keyring use here would be the original bug: written to the pairing
    # user's vault, unreadable by the service.
    monkeypatch.setattr(
        credentials, "_try_keyring", lambda: pytest.fail("must not fall back to keyring")
    )

    credentials.save_agent_secret("agent-1", "s3cret")

    assert credentials.load_agent_secret("agent-1") == "s3cret"


def test_secret_is_encrypted_with_machine_scope(windows):
    credentials.save_agent_secret("agent-1", "s3cret")

    assert windows.last_flags == credentials._CRYPTPROTECT_LOCAL_MACHINE


def test_a_secret_stored_for_a_different_agent_is_not_returned(windows):
    credentials.save_agent_secret("agent-1", "s3cret")

    assert credentials.load_agent_secret("agent-2") is None


def test_delete_removes_the_machine_scoped_blob(windows):
    credentials.save_agent_secret("agent-1", "s3cret")
    credentials.delete_agent_secret("agent-1")

    assert credentials.load_agent_secret("agent-1") is None
