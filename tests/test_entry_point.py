import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_main_module_runs_as_a_top_level_script():
    """PyInstaller runs __main__.py as the top-level script, with no parent
    package — the condition a relative import in that file dies under. The rest
    of the suite imports the package normally and never exercises this, so a
    relative import here shipped three broken releases before being caught.
    """
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "eres_print_agent" / "__main__.py"), "--help"],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "eres-print-agent" in result.stdout
