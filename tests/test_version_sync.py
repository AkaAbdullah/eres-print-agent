"""The agent reports __version__ to ERES, which shows it in Settings >
Printers. It is declared in three files that are bumped by hand, and they
silently drifted once already — the installer shipped 1.0.5 while every
agent reported 1.0.0.
"""

import re
from pathlib import Path

import eres_print_agent

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pyproject_version() -> str:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, "no version found in pyproject.toml"
    return match.group(1)


def _installer_version() -> str:
    text = (REPO_ROOT / "installer" / "eres-print-agent.iss").read_text(encoding="utf-8")
    match = re.search(r'^#define MyAppVersion "([^"]+)"', text, re.MULTILINE)
    assert match, "no MyAppVersion found in eres-print-agent.iss"
    return match.group(1)


def test_package_pyproject_and_installer_versions_match():
    assert eres_print_agent.__version__ == _pyproject_version() == _installer_version()
