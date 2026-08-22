from pathlib import Path

import pytest

from eres_print_agent.printing.mock import MockPrinterManager


def test_discover_returns_at_least_one_default_printer(tmp_path: Path):
    manager = MockPrinterManager(tmp_path)
    printers = manager.discover()
    assert len(printers) >= 1
    assert any(p.is_default for p in printers)


def test_print_copies_the_source_file_per_copy_count(tmp_path: Path):
    manager = MockPrinterManager(tmp_path / "out")
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF-1.4 mock")

    printer = manager.discover()[0]
    manager.print(printer.local_printer_id, str(source), copies=3)

    outputs = list((tmp_path / "out").glob("*.pdf"))
    assert len(outputs) == 3
    for output in outputs:
        assert output.read_bytes() == b"%PDF-1.4 mock"


def test_print_to_unknown_printer_raises(tmp_path: Path):
    manager = MockPrinterManager(tmp_path)
    source = tmp_path / "doc.pdf"
    source.write_bytes(b"%PDF-1.4")
    with pytest.raises(RuntimeError):
        manager.print("Nonexistent Printer", str(source), copies=1)


def test_get_status_reports_offline_for_unknown_printer(tmp_path: Path):
    manager = MockPrinterManager(tmp_path)
    status = manager.get_status("Nonexistent Printer")
    assert status.online is False
