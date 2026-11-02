"""macOS printer discovery, status and printing through CUPS, the print
system built into macOS. Uses only the command-line tools every Mac ships
with (`lpstat`, `lp`, `cancel`), so no extra install or driver work is needed:
any printer that shows up in System Settings > Printers & Scanners works.

Receipt printers: ERES renders POS receipts on an 80 mm page as long as the
receipt. A 58 mm printer (48 mm printable) would cut the right side off, so
for roll printers this scales the page down to the paper width
(`fit-to-page`) and picks the shortest paper length from the printer's
driver that still fits, so the printer doesn't feed a metre of blank paper.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base import DiscoveredPrinter, PrinterManager, PrinterStatus

COMMAND_TIMEOUT_SECONDS = 20
PRINT_TIMEOUT_SECONDS = 120
PPD_DIR = Path("/private/etc/cups/ppd")

# A paper size this many times longer than it is wide is a roll.
_ROLL_RATIO = 3.0


def _run(args: List[str], timeout: int = COMMAND_TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    # Explicit argument list, never a shell: printer names come from CUPS
    # but are still passed as plain arguments.
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def _printer_names() -> List[str]:
    result = _run(["lpstat", "-e"])
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _default_printer() -> Optional[str]:
    result = _run(["lpstat", "-d"])
    match = re.search(r"system default destination:\s*(\S+)", result.stdout)
    return match.group(1) if match else None


def _printer_details(name: str) -> Dict[str, str]:
    """`lpstat -l -p` → state line plus Description / Interface fields."""
    result = _run(["lpstat", "-l", "-p", name])
    details: Dict[str, str] = {"state": "", "description": "", "interface": "", "alerts": ""}
    for index, line in enumerate(result.stdout.splitlines()):
        if index == 0:
            details["state"] = line.strip()
            continue
        key, _, value = line.strip().partition(":")
        key = key.strip().lower()
        if key in {"description", "interface", "alerts", "connection"}:
            details[key] = value.strip()
    return details


def _status_from_state(state_line: str) -> PrinterStatus:
    text = state_line.lower()
    if "disabled" in text:
        return PrinterStatus(online=False, detail="Paused in macOS (resume it in Printers & Scanners)")
    if "not accepting" in text:
        return PrinterStatus(online=False, detail="Not accepting jobs")
    if "now printing" in text:
        return PrinterStatus(online=True, detail="Printing")
    if "idle" in text:
        return PrinterStatus(online=True, detail="Ready")
    return PrinterStatus(online=bool(state_line), detail=state_line or "Unknown")


def _ppd_path(name: str) -> Path:
    return PPD_DIR / f"{name}.ppd"


def _paper_sizes(name: str) -> List[Tuple[str, float, float]]:
    """(PageSize choice, width pt, height pt) from the printer's PPD, if any."""
    try:
        text = _ppd_path(name).read_text(encoding="latin-1", errors="replace")
    except OSError:
        return []
    sizes = []
    for match in re.finditer(r'^\*PaperDimension\s+([^/:\s]+)[^:]*:\s*"([\d.]+)\s+([\d.]+)"', text, re.MULTILINE):
        sizes.append((match.group(1), float(match.group(2)), float(match.group(3))))
    return sizes


def _pdf_page_size(file_path: str) -> Optional[Tuple[float, float]]:
    """First page's MediaBox in points. ERES's PDFs (Chromium) keep it in plain text."""
    try:
        head = Path(file_path).read_bytes()[: 2 * 1024 * 1024]
    except OSError:
        return None
    match = re.search(rb"/MediaBox\s*\[\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*\]", head)
    if not match:
        return None
    x0, y0, x1, y1 = (float(value) for value in match.groups())
    return abs(x1 - x0), abs(y1 - y0)


def roll_media_for(sizes: List[Tuple[str, float, float]], page: Optional[Tuple[float, float]]) -> Optional[str]:
    """The shortest roll paper size the page fits on once scaled to the
    paper's width. None when the printer is not a roll printer."""
    rolls = [size for size in sizes if size[1] > 0 and size[2] / size[1] >= _ROLL_RATIO]
    if not rolls:
        return None
    rolls.sort(key=lambda size: size[2])
    if not page or page[0] <= 0:
        return rolls[0][0]
    for choice, width, height in rolls:
        scaled_height = page[1] * min(1.0, width / page[0])
        if scaled_height <= height:
            return choice
    return rolls[-1][0]


class MacPrinterManager(PrinterManager):
    def discover(self) -> List[DiscoveredPrinter]:
        default_name = _default_printer()
        printers: List[DiscoveredPrinter] = []
        for name in _printer_names():
            details = _printer_details(name)
            status = _status_from_state(details["state"])
            sizes = _paper_sizes(name)
            printers.append(
                DiscoveredPrinter(
                    local_printer_id=name,
                    # The friendly name shown in System Settings, not the CUPS queue name.
                    display_name=details["description"] or name.replace("_", " "),
                    driver_name=None,
                    port_name=details.get("connection") or None,
                    is_default=(name == default_name),
                    paper_sizes=[choice for choice, _w, _h in sizes] or None,
                    status_detail=status.detail,
                )
            )
        return printers

    def get_status(self, local_printer_id: str) -> PrinterStatus:
        details = _printer_details(local_printer_id)
        if not details["state"]:
            return PrinterStatus(online=False, detail="Printer not found on this Mac")
        return _status_from_state(details["state"])

    def print(self, local_printer_id: str, file_path: str, copies: int) -> None:
        args = ["lp", "-d", local_printer_id, "-n", str(max(1, int(copies)))]
        media = roll_media_for(_paper_sizes(local_printer_id), _pdf_page_size(file_path))
        if media:
            # Roll printer: shrink an 80 mm receipt onto narrower paper.
            args += ["-o", f"media={media}", "-o", "fit-to-page"]
        args.append(file_path)
        result = _run(args, timeout=PRINT_TIMEOUT_SECONDS)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"macOS print failed: {message or f'lp exited {result.returncode}'}")

    def cancel(self, local_printer_id: str, job_reference: str) -> bool:
        # The agent does not keep the CUPS job id; cancel is best-effort per
        # spec and is honoured before printing starts (core/job_worker.py).
        return False
