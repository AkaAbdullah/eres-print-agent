"""Platform dispatch for PrinterManager — the one place that decides which
backend runs. core/agent.py and everything downstream of it only ever see
the PrinterManager interface (base.py), never a platform check.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .base import PrinterManager
from .mock import MockPrinterManager


def build_printer_manager(mock_output_dir: Path | None = None) -> PrinterManager:
    # Escape hatch for integration tests / local dev harness runs on
    # Windows too, without needing a real printer attached.
    if os.environ.get("ERES_PRINT_AGENT_FORCE_MOCK_PRINTER") == "1":
        return MockPrinterManager(mock_output_dir or Path.cwd() / "mock-print-output")

    if sys.platform == "win32":
        from .windows import WindowsPrinterManager

        return WindowsPrinterManager()

    # macOS/Linux: no supported backend yet (spec section 45 — V1 is
    # Windows-first). Falling back to the mock keeps the rest of the agent
    # runnable for development rather than crashing at startup.
    return MockPrinterManager(mock_output_dir or Path.cwd() / "mock-print-output")
