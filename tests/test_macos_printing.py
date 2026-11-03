"""Pure parts of the macOS backend (no CUPS calls)."""

from pathlib import Path

from eres_print_agent.printing import macos
from eres_print_agent.printing.macos import _pdf_page_size, _status_from_state, roll_media_for

POS58 = [("X48MMY210MM", 136.0, 595.0), ("X48MMY297MM", 136.0, 842.0), ("X48MMY3276MM", 136.0, 9282.0)]
A4 = [("A4", 595.0, 842.0), ("Letter", 612.0, 792.0)]


def test_short_receipt_uses_shortest_roll():
    # 80 mm x 119 mm slip → scaled to 48 mm wide it is ~71 mm long.
    assert roll_media_for(POS58, (227.04, 337.92)) == "X48MMY210MM"


def test_long_receipt_picks_a_length_that_fits():
    # 80 mm x 600 mm receipt → ~360 mm long at 48 mm wide.
    assert roll_media_for(POS58, (227.0, 1700.0)) == "X48MMY3276MM"
    # ~280 mm long at 48 mm wide fits the 297 mm size.
    assert roll_media_for(POS58, (227.0, 1300.0)) == "X48MMY297MM"


def test_office_printer_is_left_alone():
    assert roll_media_for(A4, (595.0, 842.0)) is None
    assert roll_media_for([], (227.0, 300.0)) is None


def test_unknown_page_size_uses_shortest_roll():
    assert roll_media_for(POS58, None) == "X48MMY210MM"


def test_pdf_media_box(tmp_path: Path):
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF-1.4\n3 0 obj<</Type/Page/MediaBox [0 0 227.03999 337.91998]>>endobj\n%%EOF")
    assert _pdf_page_size(str(pdf)) == (227.03999, 337.91998)


def test_status_lines():
    assert _status_from_state("printer POS58 is idle.  enabled since Sat").online
    assert not _status_from_state("printer POS58 disabled since Sat -").online
    assert not _status_from_state("").online


def test_ppd_paper_sizes(tmp_path: Path, monkeypatch):
    (tmp_path / "POS.ppd").write_text(
        '*PaperDimension X48MMY210MM:        "136 595"\n*PaperDimension X48MMY297MM/58 x 297: "136 842"\n',
        encoding="latin-1",
    )
    monkeypatch.setattr(macos, "PPD_DIR", tmp_path)
    assert macos._paper_sizes("POS") == [("X48MMY210MM", 136.0, 595.0), ("X48MMY297MM", 136.0, 842.0)]


def test_custom_length_matches_receipt():
    from eres_print_agent.printing.macos import custom_roll_media

    # 80 x 119 mm receipt on a 48 mm roll → 136 pt wide, ~203 pt long.
    assert custom_roll_media(POS58, (136.0, 48.0, 9282.0), (227.04, 337.92)) == "Custom.136x203"
    # Driver without custom sizes → caller falls back to the fixed sizes.
    assert custom_roll_media(POS58, None, (227.04, 337.92)) is None
    # Office printer → left alone.
    assert custom_roll_media(A4, (612.0, 72.0, 1008.0), (595.0, 842.0)) is None


def test_custom_size_range_from_ppd(tmp_path, monkeypatch):
    (tmp_path / "POS.ppd").write_text(
        '*CustomPageSize True: "pop"\n'
        "*ParamCustomPageSize Width:        1 points 48 136\n"
        "*ParamCustomPageSize Height:       2 points 48 9282\n",
        encoding="latin-1",
    )
    monkeypatch.setattr(macos, "PPD_DIR", tmp_path)
    assert macos._custom_size_range("POS") == (136.0, 48.0, 9282.0)


def test_usb_attached():
    uri = "usb://GEZHI/micro-printer?serial=000000000004"
    assert macos._usb_attached(uri, {uri})
    assert macos._usb_attached(uri, {"usb://GEZHI/micro-printer"})  # params differ
    assert not macos._usb_attached(uri, set())  # unplugged / switched off
    assert macos._usb_attached(uri, None)  # couldn't check: never mark down
    assert macos._usb_attached("ipp://192.168.1.5/ipp/print", set())  # network printer


def test_unplugged_usb_printer_is_offline(monkeypatch):
    monkeypatch.setattr(macos, "_printer_details", lambda name: {"state": "printer POS58 is idle.  enabled since Sat", "description": "POS-58", "connection": "direct"})
    monkeypatch.setattr(macos, "_device_uri", lambda name: "usb://GEZHI/micro-printer?serial=000000000004")
    monkeypatch.setattr(macos, "_attached_usb_uris", lambda: set())
    status = macos.MacPrinterManager().get_status("POS58")
    assert not status.online and status.detail == macos.UNPLUGGED_DETAIL
    monkeypatch.setattr(macos, "_attached_usb_uris", lambda: {"usb://GEZHI/micro-printer?serial=000000000004"})
    assert macos.MacPrinterManager().get_status("POS58").online
