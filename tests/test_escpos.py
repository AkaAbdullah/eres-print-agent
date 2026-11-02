from eres_print_agent.printing import escpos
from eres_print_agent.printing.macos import escpos_width_dots

POS58_PPD = '*Manufacturer: "POS"\n*ModelName: "POS-58"\n*cupsFilter: "application/vnd.cups-raster 0 pos"\n'
POS58_SIZES = [("X48MMY210MM", 136.0, 595.0), ("X48MMY297MM", 136.0, 842.0)]


def test_gray_to_rows_and_trim():
    # 8x3: blank row, one black pixel at x=0, blank row
    gray = bytes([255] * 8) + bytes([0] + [255] * 7) + bytes([255] * 8)
    rows = escpos.gray_to_rows(gray, 8, 3)
    assert rows == [b"\x00", b"\x80", b"\x00"]
    assert escpos.trim_blank_rows(rows) == [b"\x80"]
    assert escpos.trim_blank_rows([b"\x00"]) == []


def test_build_job_pads_and_cuts():
    job = escpos.build_escpos_job([b"\xff\xff"], pad_rows=2)
    assert job.startswith(b"\x1b@\x1dv0\x00\x02\x00\x05\x00")  # 2 bytes wide, 5 rows
    assert job.endswith(b"\x1bd\x04\x1dV\x01")
    assert escpos.mm_to_dots(4, 203) == 32


def test_large_image_is_split_into_blocks():
    job = escpos.build_escpos_job([b"\x01"] * 600)
    assert job.count(b"\x1dv0\x00") == 25


def test_width_dots_for_receipt_printers_only():
    assert escpos_width_dots(POS58_PPD, POS58_SIZES, (136.0, 48.0, 9282.0)) == 384
    assert escpos_width_dots(POS58_PPD + "*DefaultResolution: 180dpi\n", POS58_SIZES, None) == 336
    # 80 mm roll
    assert escpos_width_dots(POS58_PPD, [("X72MMY210MM", 204.0, 595.0)], None) == 576
    # A4 office printer, label printer, no PPD
    assert escpos_width_dots(POS58_PPD, [("A4", 595.0, 842.0)], None) is None
    assert escpos_width_dots('*Manufacturer: "Zebra"\n', [("4x6", 288.0, 432.0), ("roll", 144.0, 900.0)], None) is None
    assert escpos_width_dots("", POS58_SIZES, None) is None
