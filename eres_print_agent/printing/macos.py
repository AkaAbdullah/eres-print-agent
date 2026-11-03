"""macOS printer discovery, status and printing through CUPS, the print
system built into macOS. Uses only the command-line tools every Mac ships
with (`lpstat`, `lp`, `cancel`), so no extra install or driver work is needed:
any printer that shows up in System Settings > Printers & Scanners works.

Receipt printers: ERES renders POS receipts on an 80 mm page as long as the
receipt. A 58 mm printer (48 mm printable) would cut the right side off, so
for roll printers this scales the page down to the paper width
(`fit-to-page`) and picks the shortest paper length from the printer's
driver that still fits, so the printer doesn't feed a metre of blank paper.

ESC/POS receipt printers skip the driver altogether: the receipt is drawn
to a bitmap and sent raw (escpos.py), because drivers such as the generic
POS-58 one ignore custom paper lengths.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import escpos
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


def _device_uri(name: str) -> str:
    """`lpstat -v NAME` → the queue's device URI (usb://..., ipp://...)."""
    result = _run(["lpstat", "-v", name])
    match = re.search(r"^device for [^:]+:\s*(\S+)", result.stdout, re.MULTILINE)
    return match.group(1) if match else ""


def _attached_usb_uris() -> Optional[set]:
    """Device URIs of the USB printers plugged in and switched on right now.
    CUPS keeps saying "idle" for an unplugged USB printer, so this is the only
    way to tell. None when it can't be checked (never marks a printer down)."""
    try:
        result = _run(["lpinfo", "--include-schemes", "usb", "-v"])
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    uris = set()
    for line in result.stdout.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[1].strip().startswith("usb://"):
            uris.add(parts[1].strip())
    return uris


def _usb_attached(uri: str, attached: Optional[set]) -> bool:
    """False only for a USB printer that is known not to be plugged in."""
    if not uri.startswith("usb://") or attached is None:
        return True
    if uri in attached:
        return True
    # Same printer, query parameters in another order or missing.
    base = uri.split("?", 1)[0]
    return any(item.split("?", 1)[0] == base for item in attached)


UNPLUGGED_DETAIL = "Not connected (unplugged or switched off)"


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


def _custom_size_range(name: str) -> Optional[Tuple[float, float, float]]:
    """(max width, min height, max height) in points when the driver accepts
    any paper length (`*CustomPageSize True`), else None."""
    try:
        text = _ppd_path(name).read_text(encoding="latin-1", errors="replace")
    except OSError:
        return None
    if not re.search(r"^\*CustomPageSize\s+True", text, re.MULTILINE):
        return None
    width = re.search(r"^\*ParamCustomPageSize\s+Width:\s*\d+\s+points\s+([\d.]+)\s+([\d.]+)", text, re.MULTILINE)
    height = re.search(r"^\*ParamCustomPageSize\s+Height:\s*\d+\s+points\s+([\d.]+)\s+([\d.]+)", text, re.MULTILINE)
    if not width or not height:
        return None
    return float(width.group(2)), float(height.group(1)), float(height.group(2))


def custom_roll_media(
    sizes: List[Tuple[str, float, float]],
    custom: Optional[Tuple[float, float, float]],
    page: Optional[Tuple[float, float]],
) -> Optional[str]:
    """A paper size exactly as long as the receipt once scaled to the roll's
    width, e.g. "Custom.136x202". A fixed size (210 mm) would leave the rest
    of the page blank above the receipt, because macOS anchors a page that
    is shorter than the paper to the bottom."""
    if not custom or not page or page[0] <= 0:
        return None
    is_roll = any(width > 0 and height / width >= _ROLL_RATIO for _choice, width, height in sizes) or (
        custom[2] / custom[0] >= _ROLL_RATIO
    )
    if not is_roll:
        return None
    width = custom[0]
    height = page[1] * min(1.0, width / page[0])
    height = max(custom[1], min(custom[2], height))
    return f"Custom.{int(round(width))}x{int(-(-height // 1))}"


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


# Roll printers that speak a label language, not ESC/POS: never send them raw.
_NOT_ESCPOS = re.compile(r"zebra|dymo|rollo|godex|\btsc\b|brother|label|zpl|epl", re.IGNORECASE)
# Widest ESC/POS receipt paper (80 mm roll, 72 mm printable), in points.
_MAX_RECEIPT_WIDTH_PT = 230.0


def _ppd_text(name: str) -> str:
    try:
        return _ppd_path(name).read_text(encoding="latin-1", errors="replace")
    except OSError:
        return ""


def escpos_width_dots(
    ppd_text: str,
    sizes: List[Tuple[str, float, float]],
    custom: Optional[Tuple[float, float, float]],
) -> Optional[int]:
    """Printable width in printer dots when this looks like an ESC/POS
    receipt printer (a roll no wider than 80 mm, not a label printer), else
    None."""
    if not ppd_text:
        return None
    header = " ".join(re.findall(r'^\*(?:Manufacturer|ModelName|NickName|cupsFilter2?):\s*"([^"]*)"', ppd_text, re.MULTILINE))
    if _NOT_ESCPOS.search(header):
        return None
    # 2.5, not _ROLL_RATIO: an 80 mm driver's 210 mm length is only 2.9x its width.
    rolls = [width for _choice, width, height in sizes if width > 0 and height / width >= 2.5]
    if custom and custom[0] > 0 and custom[2] / custom[0] >= _ROLL_RATIO:
        rolls.append(custom[0])
    if not rolls:
        return None
    width_pt = max(rolls)
    if width_pt > _MAX_RECEIPT_WIDTH_PT:
        return None
    match = re.search(r"^\*DefaultResolution:\s*(\d+)", ppd_text, re.MULTILINE)
    dpi = int(match.group(1)) if match else 203
    # 48 mm at 203 dpi is 383.4 dots; printers take whole bytes (384).
    return max(8, int(round(width_pt / 72.0 * dpi / 8.0)) * 8)


def build_escpos_receipt(file_path: str, width_dots: int, dpi: int = 203) -> bytes:
    """The PDF as one ESC/POS job: each page trimmed to its ink, with
    DEFAULT_PAD_MM of blank paper above and below, then feed and cut."""
    from .macos_raster import render_pdf_gray

    rows: List[bytes] = []
    for gray, width, height in render_pdf_gray(file_path, width_dots):
        rows += escpos.trim_blank_rows(escpos.gray_to_rows(gray, width, height))
    if not rows:
        raise RuntimeError("The receipt is blank")
    return escpos.build_escpos_job(rows, pad_rows=escpos.mm_to_dots(escpos.DEFAULT_PAD_MM, dpi))


class MacPrinterManager(PrinterManager):
    def discover(self) -> List[DiscoveredPrinter]:
        default_name = _default_printer()
        printers: List[DiscoveredPrinter] = []
        attached = _attached_usb_uris()
        for name in _printer_names():
            details = _printer_details(name)
            status = _status_from_state(details["state"])
            if status.online and not _usb_attached(_device_uri(name), attached):
                status = PrinterStatus(online=False, detail=UNPLUGGED_DETAIL)
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
                    online=status.online,
                )
            )
        return printers

    def get_status(self, local_printer_id: str) -> PrinterStatus:
        details = _printer_details(local_printer_id)
        if not details["state"]:
            return PrinterStatus(online=False, detail="Printer not found on this Mac")
        status = _status_from_state(details["state"])
        if status.online and not _usb_attached(_device_uri(local_printer_id), _attached_usb_uris()):
            return PrinterStatus(online=False, detail=UNPLUGGED_DETAIL)
        return status

    def print(self, local_printer_id: str, file_path: str, copies: int) -> None:
        args = ["lp", "-d", local_printer_id, "-n", str(max(1, int(copies)))]
        sizes = _paper_sizes(local_printer_id)
        custom = _custom_size_range(local_printer_id)
        ppd = _ppd_text(local_printer_id)
        width_dots = escpos_width_dots(ppd, sizes, custom)
        if width_dots:
            # Receipt printer: send the receipt as an ESC/POS bitmap so it is
            # exactly as long as the receipt. macOS drivers often ignore
            # custom paper lengths and leave blank paper above or below.
            try:
                match = re.search(r"^\*DefaultResolution:\s*(\d+)", ppd, re.MULTILINE)
                data = build_escpos_receipt(file_path, width_dots, int(match.group(1)) if match else 203)
                raw_path = f"{file_path}.escpos"
                Path(raw_path).write_bytes(data)
                try:
                    result = _run(args + ["-o", "raw", raw_path], timeout=PRINT_TIMEOUT_SECONDS)
                finally:
                    Path(raw_path).unlink(missing_ok=True)
                if result.returncode == 0:
                    return
            except Exception:  # noqa: BLE001 - fall back to the driver below
                pass
        page = _pdf_page_size(file_path)
        media = custom_roll_media(sizes, custom, page) or roll_media_for(sizes, page)
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
