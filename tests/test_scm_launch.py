"""The SCM starts a frozen service by running its exe with no arguments. If
argparse handles that invocation instead of the service dispatcher, the
process exits before answering the SCM and Windows reports error 1053.
"""

from eres_print_agent import cli


def _freeze(monkeypatch, *, frozen=True, platform="win32", argv=("eres-print-agent.exe",)):
    monkeypatch.setattr(cli.sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(cli.sys, "platform", platform)
    monkeypatch.setattr(cli.sys, "argv", list(argv))


def test_frozen_no_argument_launch_is_treated_as_the_scm(monkeypatch):
    _freeze(monkeypatch)
    assert cli._looks_like_scm_launch(None) is True


def test_frozen_launch_with_a_subcommand_is_a_normal_cli_call(monkeypatch):
    _freeze(monkeypatch, argv=("eres-print-agent.exe", "status"))
    assert cli._looks_like_scm_launch(None) is False


def test_unfrozen_no_argument_launch_is_not_the_scm(monkeypatch):
    _freeze(monkeypatch, frozen=False)
    assert cli._looks_like_scm_launch(None) is False


def test_non_windows_is_never_the_scm(monkeypatch):
    _freeze(monkeypatch, platform="darwin")
    assert cli._looks_like_scm_launch(None) is False


def test_explicit_argv_from_tests_or_callers_is_never_the_scm(monkeypatch):
    _freeze(monkeypatch)
    assert cli._looks_like_scm_launch([]) is False
