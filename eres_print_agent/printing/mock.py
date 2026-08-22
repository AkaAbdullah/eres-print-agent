"""A PrinterManager that never touches a real OS print API.

Used on macOS/Linux dev machines (there is no Windows print spooler to
call) and in unit/integration tests. `print()` just copies the given PDF
into a local directory so a human (or a test) can inspect what "would have
printed" — this is what makes the print-hub + mock-web + agent round-trip
independently verifiable from this repo without a Windows box or a
physical printer.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List

from .base import DiscoveredPrinter, PrinterManager, PrinterStatus


class MockPrinterManager(PrinterManager):
    def __init__(self, output_dir: Path, printers: List[DiscoveredPrinter] | None = None):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._printers = printers or [
            DiscoveredPrinter(
                local_printer_id="Mock Office Printer",
                display_name="Mock Office Printer",
                driver_name="Mock Driver",
                port_name="MOCK001",
                is_default=True,
                color=False,
                duplex=True,
                paper_sizes=["A4", "Letter"],
                status_detail="Ready",
            )
        ]
        self.print_calls: List[Dict] = []

    def discover(self) -> List[DiscoveredPrinter]:
        return list(self._printers)

    def get_status(self, local_printer_id: str) -> PrinterStatus:
        known = any(p.local_printer_id == local_printer_id for p in self._printers)
        return PrinterStatus(online=known, detail="Ready" if known else "Unknown printer")

    def print(self, local_printer_id: str, file_path: str, copies: int) -> None:
        known = any(p.local_printer_id == local_printer_id for p in self._printers)
        if not known:
            raise RuntimeError(f"Unknown printer: {local_printer_id}")

        source = Path(file_path)
        for copy_number in range(1, copies + 1):
            destination = self.output_dir / f"{source.stem}.{local_printer_id.replace(' ', '_')}.copy{copy_number}{source.suffix}"
            shutil.copyfile(source, destination)
        self.print_calls.append({"local_printer_id": local_printer_id, "file_path": file_path, "copies": copies})

    def cancel(self, local_printer_id: str, job_reference: str) -> bool:
        return False
