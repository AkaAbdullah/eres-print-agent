"""Windows printer discovery, status, and printing via the native Print
Spooler (win32print) plus a bundled PDF renderer for the actual print.

win32print itself has no PDF rendering engine — it can enumerate printers,
read their status, and submit RAW/spooler jobs, but turning a PDF's pages
into printer output requires something that can rasterize PDF, which is
what every practical Windows PDF-printing tool (including the `pdf-to-printer`
npm package the spec names as the Node alternative) ends up shelling out
to. This module shells out to a bundled SumatraPDF.exe (free, portable,
has a `-print-to "<printer>" -silent` CLI mode built exactly for this) —
the installer is responsible for placing it next to the agent executable
(see installer/eres-print-agent.iss). The path is configurable via
ERES_PRINT_AGENT_SUMATRA_PATH for the same reason MockPrinterManager
exists: so this exact code can at least import-check and unit-test its
non-Windows-API parts without a bundled binary present.

NOT independently verifiable from macOS — see print-agent/README.md's
verification checklist. Everything in this file needs a human to confirm
against a real Windows box: win32print's exact status bitmask behavior
varies by driver, and the SumatraPDF command line has changed across
versions.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import List

from .base import DiscoveredPrinter, PrinterManager, PrinterStatus

try:
    import win32con
    import win32print
except ImportError:  # pragma: no cover - exercised only on Windows
    win32con = None  # type: ignore[assignment]
    win32print = None  # type: ignore[assignment]

PRINT_TIMEOUT_SECONDS = 120


def _require_win32print() -> None:
    if win32print is None:
        raise RuntimeError(
            "pywin32 is not available — WindowsPrinterManager can only run on Windows "
            "with the 'windows' extra installed (pip install .[windows])."
        )


def _sumatra_path() -> str:
    configured = os.environ.get("ERES_PRINT_AGENT_SUMATRA_PATH")
    if configured:
        return configured
    # Default: installed alongside the agent executable by the Windows installer.
    return str(Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "ERES Print Agent" / "SumatraPDF.exe")


# win32print status bitmask values that mean "cannot currently accept a job."
# See Microsoft's PRINTER_INFO_2 documentation for the full bit list — these
# are the ones that matter for a customer-facing "online"/"offline" signal.
_OFFLINE_STATUS_BITS = {
    "PRINTER_STATUS_OFFLINE": 0x00000080,
    "PRINTER_STATUS_ERROR": 0x00000002,
    "PRINTER_STATUS_NOT_AVAILABLE": 0x00001000,
    "PRINTER_STATUS_NO_TONER": 0x00040000,
    "PRINTER_STATUS_PAPER_OUT": 0x00000010,
    "PRINTER_STATUS_PAPER_JAM": 0x00000008,
    "PRINTER_STATUS_DOOR_OPEN": 0x00400000,
}


def _status_detail(status_bits: int) -> str:
    if status_bits == 0:
        return "Ready"
    active = [name for name, bit in _OFFLINE_STATUS_BITS.items() if status_bits & bit]
    return ", ".join(active) if active else f"Status code {status_bits}"


class WindowsPrinterManager(PrinterManager):
    def __init__(self, sumatra_path: str | None = None):
        _require_win32print()
        self.sumatra_path = sumatra_path or _sumatra_path()

    def discover(self) -> List[DiscoveredPrinter]:
        _require_win32print()
        default_name = None
        try:
            default_name = win32print.GetDefaultPrinter()
        except Exception:
            pass  # no default printer configured — not fatal

        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        raw_printers = win32print.EnumPrinters(flags, None, 2)

        discovered: List[DiscoveredPrinter] = []
        for entry in raw_printers:
            name = entry["pPrinterName"]
            color = None
            duplex = None
            try:
                handle = win32print.OpenPrinter(name)
                try:
                    info = win32print.GetPrinter(handle, 2)
                    devmode = info.get("pDevMode")
                    if devmode is not None:
                        color = bool(getattr(devmode, "Color", 0) == 2)  # DMCOLOR_COLOR == 2
                        duplex = bool(getattr(devmode, "Duplex", 0) not in (0, 1))  # DMDUP_SIMPLEX == 1
                finally:
                    win32print.ClosePrinter(handle)
            except Exception:
                pass  # discovery must not fail entirely because one printer's driver misbehaves

            discovered.append(
                DiscoveredPrinter(
                    local_printer_id=name,
                    display_name=name,
                    driver_name=entry.get("pDriverName"),
                    port_name=entry.get("pPortName"),
                    is_default=(name == default_name),
                    color=color,
                    duplex=duplex,
                    status_detail=_status_detail(entry.get("Status", 0)),
                )
            )
        return discovered

    def get_status(self, local_printer_id: str) -> PrinterStatus:
        _require_win32print()
        try:
            handle = win32print.OpenPrinter(local_printer_id)
        except Exception as error:
            return PrinterStatus(online=False, detail=f"Printer unavailable: {error}")

        try:
            info = win32print.GetPrinter(handle, 2)
            status_bits = info.get("Status", 0)
            offline = any(status_bits & bit for bit in _OFFLINE_STATUS_BITS.values())
            return PrinterStatus(online=not offline, detail=_status_detail(status_bits))
        finally:
            win32print.ClosePrinter(handle)

    def print(self, local_printer_id: str, file_path: str, copies: int) -> None:
        if not Path(self.sumatra_path).exists():
            raise RuntimeError(
                f"PDF print helper not found at {self.sumatra_path}. "
                "The Windows installer must bundle it alongside the agent."
            )

        args = [self.sumatra_path, "-print-to", local_printer_id, "-silent"]
        if copies > 1:
            args += ["-print-settings", f"copies={copies}"]
        args.append(file_path)

        result = subprocess.run(
            args,
            timeout=PRINT_TIMEOUT_SECONDS,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Print helper exited {result.returncode}: {stderr or 'no error output'}")

    def cancel(self, local_printer_id: str, job_reference: str) -> bool:
        # Printing is delegated to an external process (SumatraPDF), which
        # does not hand back a spooler job id we could target with
        # win32print.SetJob(JOB_CONTROL_CANCEL). A reliable cancel would
        # need to enumerate the printer's spooler queue (EnumJobs) and
        # match on submission time/document name immediately after
        # dispatch — not implemented in V1. print.job.cancel is
        # best-effort per spec; the agent honors it only when the job
        # hasn't reached print() yet (see core/job_worker.py).
        return False
