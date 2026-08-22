from pathlib import Path

import pytest

from eres_print_agent.db.queue_store import QueueStore
from eres_print_agent.state_machine import PrintJobStatus


@pytest.fixture
def store(tmp_path: Path) -> QueueStore:
    qs = QueueStore(tmp_path / "queue.sqlite3")
    yield qs
    qs.close()


def _insert(store: QueueStore, job_id: str = "job-1") -> bool:
    return store.insert_received(
        job_id=job_id,
        printer_local_id="Test Printer",
        document_type="test-page",
        document_id="test",
        document_url="https://example.com/doc.pdf",
        copies=1,
    )


def test_insert_received_creates_a_new_row(store: QueueStore):
    assert _insert(store) is True
    record = store.get("job-1")
    assert record is not None
    assert record.status == PrintJobStatus.RECEIVED
    assert record.attempts == 0


def test_insert_received_is_idempotent_by_job_id(store: QueueStore):
    assert _insert(store) is True
    assert _insert(store) is False  # duplicate — second call is a no-op
    record = store.get("job-1")
    assert record.status == PrintJobStatus.RECEIVED  # unchanged


def test_update_status_transitions_and_stamps_timestamp(store: QueueStore):
    _insert(store)
    store.update_status("job-1", PrintJobStatus.PRINTING)
    record = store.get("job-1")
    assert record.status == PrintJobStatus.PRINTING
    assert record.attempts == 1


def test_update_status_records_error_details(store: QueueStore):
    _insert(store)
    store.update_status("job-1", PrintJobStatus.FAILED, error_code="DOWNLOAD_FAILED", error_message="boom")
    record = store.get("job-1")
    assert record.status == PrintJobStatus.FAILED
    assert record.error_code == "DOWNLOAD_FAILED"
    assert record.error_message == "boom"
    assert record.is_terminal


def test_list_non_terminal_excludes_completed_failed_cancelled(store: QueueStore):
    _insert(store, "job-1")
    _insert(store, "job-2")
    _insert(store, "job-3")
    store.update_status("job-2", PrintJobStatus.COMPLETED)
    store.update_status("job-3", PrintJobStatus.CANCELLED)

    non_terminal = {r.job_id for r in store.list_non_terminal()}
    assert non_terminal == {"job-1"}


def test_mark_stuck_printing_as_failed_only_touches_printing_rows(store: QueueStore):
    _insert(store, "job-1")
    _insert(store, "job-2")
    store.update_status("job-1", PrintJobStatus.PRINTING)

    affected = store.mark_stuck_printing_as_failed()

    assert affected == ["job-1"]
    job1 = store.get("job-1")
    assert job1.status == PrintJobStatus.FAILED
    assert job1.error_code == "AGENT_RESTARTED_DURING_PRINT"
    job2 = store.get("job-2")
    assert job2.status == PrintJobStatus.RECEIVED  # untouched


def test_queue_survives_reopening_the_same_file(tmp_path: Path):
    db_path = tmp_path / "queue.sqlite3"
    store1 = QueueStore(db_path)
    _insert(store1, "job-1")
    store1.close()

    store2 = QueueStore(db_path)
    record = store2.get("job-1")
    assert record is not None
    assert record.status == PrintJobStatus.RECEIVED
    store2.close()
