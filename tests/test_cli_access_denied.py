import pytest

from eres_print_agent import cli


class FakeWin32Error(Exception):
    """Stands in for pywintypes.error, which only exists on Windows."""

    def __init__(self, winerror, funcname, strerror):
        super().__init__(winerror, funcname, strerror)
        self.winerror = winerror
        self.funcname = funcname
        self.strerror = strerror


def _raise_access_denied(_args):
    raise FakeWin32Error(5, "OpenSCManager", "Access is denied.")


def test_service_command_access_denied_explains_elevation(monkeypatch, capsys):
    monkeypatch.setattr(cli, "cmd_restart", _raise_access_denied)

    exit_code = cli.main(["restart"])

    assert exit_code == 1
    assert "Run as administrator" in capsys.readouterr().err


def test_other_errors_on_service_commands_still_propagate(monkeypatch):
    def boom(_args):
        raise FakeWin32Error(1060, "OpenService", "The specified service does not exist.")

    monkeypatch.setattr(cli, "cmd_restart", boom)

    with pytest.raises(FakeWin32Error):
        cli.main(["restart"])


def test_access_denied_outside_service_commands_still_propagates(monkeypatch):
    monkeypatch.setattr(cli, "cmd_status", _raise_access_denied)

    with pytest.raises(FakeWin32Error):
        cli.main(["status"])
