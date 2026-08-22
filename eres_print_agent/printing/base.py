"""Printer abstraction — the interface every platform backend implements.

Kept deliberately narrow (spec section 16) so business logic (job_worker,
printer_sync) never touches a platform API directly, and a future
MacOSPrinterManager/LinuxPrinterManager only has to implement this same
four-method contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class DiscoveredPrinter:
    local_printer_id: str
    display_name: str
    driver_name: Optional[str] = None
    port_name: Optional[str] = None
    is_default: bool = False
    color: Optional[bool] = None
    duplex: Optional[bool] = None
    paper_sizes: Optional[List[str]] = None
    status_detail: Optional[str] = None


@dataclass
class PrinterStatus:
    online: bool
    detail: str


class PrinterManager(ABC):
    @abstractmethod
    def discover(self) -> List[DiscoveredPrinter]:
        """Enumerates printers currently available to this machine."""

    @abstractmethod
    def get_status(self, local_printer_id: str) -> PrinterStatus:
        """Point-in-time status of one printer (used before attempting a print)."""

    @abstractmethod
    def print(self, local_printer_id: str, file_path: str, copies: int) -> None:
        """Spools `file_path` (a local PDF) to the given printer.

        Raises on failure. Success here means the OS print system accepted
        the job — see printing/windows.py's docstring for why that's the
        strongest guarantee available.
        """

    @abstractmethod
    def cancel(self, local_printer_id: str, job_reference: str) -> bool:
        """Best-effort cancel of an in-flight OS print job. Returns whether
        anything was actually found and cancelled."""
