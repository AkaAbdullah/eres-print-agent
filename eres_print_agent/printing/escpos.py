"""ESC/POS raster output for receipt printers.

Some macOS receipt drivers (e.g. the generic "POS-58" driver) ignore custom
paper lengths, so a short receipt lands on a fixed 210 mm page with blank
paper above or below it. Sending the receipt as an ESC/POS bitmap skips the
driver: the printer prints exactly the rows it gets, then feeds and cuts.
"""

from __future__ import annotations

from typing import List

# Blank space kept above and below the receipt, in mm.
DEFAULT_PAD_MM = 4.0
# Lines fed after the receipt so the last line clears the cutter.
FEED_LINES = 4
# Small strips (about 1 KB each on 58 mm): cheap printers have tiny buffers
# and turn a big image block into garbage text when it overflows.
_ROWS_PER_BLOCK = 24


def mm_to_dots(mm: float, dpi: int) -> int:
    return max(0, int(round(mm / 25.4 * dpi)))


def gray_to_rows(gray: bytes, width: int, height: int, threshold: int = 128) -> List[bytes]:
    """8-bit gray pixels (top row first, 0 = black) → 1-bit rows, 1 = ink.
    Floyd-Steinberg dithering, so light colours (a blue logo) print as
    shading instead of vanishing; black text stays solid."""
    bytes_per_row = (width + 7) // 8
    rows: List[bytes] = []
    current = [float(value) for value in gray[0:width]]
    for y in range(height):
        following = [float(value) for value in gray[(y + 1) * width : (y + 2) * width]] if y + 1 < height else None
        row = bytearray(bytes_per_row)
        for x in range(width):
            old = current[x]
            new = 0.0 if old < threshold else 255.0
            if new == 0.0:
                row[x >> 3] |= 0x80 >> (x & 7)
            error = old - new
            if error:
                if x + 1 < width:
                    current[x + 1] += error * 7 / 16
                if following is not None:
                    if x > 0:
                        following[x - 1] += error * 3 / 16
                    following[x] += error * 5 / 16
                    if x + 1 < width:
                        following[x + 1] += error * 1 / 16
        rows.append(bytes(row))
        if following is not None:
            current = following
    return rows


def trim_blank_rows(rows: List[bytes]) -> List[bytes]:
    ink = [index for index, row in enumerate(rows) if any(row)]
    if not ink:
        return []
    return rows[ink[0] : ink[-1] + 1]


def build_escpos_job(rows: List[bytes], pad_rows: int = 0, feed_lines: int = FEED_LINES, cut: bool = True) -> bytes:
    """Bitmap rows (all the same width) → ESC/POS bytes: init, GS v 0 image
    blocks, feed, partial cut. `pad_rows` blank rows go above and below."""
    if not rows:
        return b""
    bytes_per_row = len(rows[0])
    blank = bytes(bytes_per_row)
    rows = [blank] * pad_rows + rows + [blank] * pad_rows
    out = bytearray(b"\x1b@")
    for start in range(0, len(rows), _ROWS_PER_BLOCK):
        block = rows[start : start + _ROWS_PER_BLOCK]
        out += b"\x1dv0\x00"
        out += bytes([bytes_per_row & 0xFF, bytes_per_row >> 8, len(block) & 0xFF, len(block) >> 8])
        out += b"".join(block)
    if feed_lines:
        out += b"\x1bd" + bytes([min(255, feed_lines)])
    if cut:
        out += b"\x1dV\x01"
    return bytes(out)
