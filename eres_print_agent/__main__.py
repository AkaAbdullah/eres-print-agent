import sys

# Absolute, not `from .cli import main`: PyInstaller runs this file as the
# top-level __main__ with no parent package, where a relative import raises
# "attempted relative import with no known parent package" and the frozen exe
# dies before reaching the CLI. Absolute works both frozen and under
# `python -m eres_print_agent`.
from eres_print_agent.cli import main

if __name__ == "__main__":
    sys.exit(main())
