"""SQLite-backed persistent print job queue.

This is the durability guarantee described in the plan's "Receive ->
Validate -> Persist -> ACK -> Print" flow: `insert_received` is the write
that must commit before the agent acks a job, so a crash between receiving
a job and acking it just means the ack never went out and print-hub
re-dispatches on the agent's next `authenticate`.

Synchronous by design (stdlib `sqlite3`) — callers on the asyncio event
loop should wrap calls in `asyncio.to_thread`. Keeping this module
synchronous makes it trivial to unit test without an event loop.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ..state_machine import PrintJobStatus, is_terminal

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass
class PrintJobRecord:
    job_id: str
    printer_local_id: str
    document_type: str
    document_id: str
    document_url: str
    copies: int
    status: PrintJobStatus
    error_code: Optional[str]
    error_message: Optional[str]
    local_file_path: Optional[str]
    attempts: int

    @property
    def is_terminal(self) -> bool:
        return is_terminal(self.status)


def _row_to_record(row: sqlite3.Row) -> PrintJobRecord:
    return PrintJobRecord(
        job_id=row["job_id"],
        printer_local_id=row["printer_local_id"],
        document_type=row["document_type"],
        document_id=row["document_id"],
        document_url=row["document_url"],
        copies=row["copies"],
        status=PrintJobStatus(row["status"]),
        error_code=row["error_code"],
        error_message=row["error_message"],
        local_file_path=row["local_file_path"],
        attempts=row["attempts"],
    )


_TIMESTAMP_FIELD_BY_STATUS = {
    PrintJobStatus.RECEIVED: "received_at",
    PrintJobStatus.PRINTING: "started_at",
    PrintJobStatus.COMPLETED: "completed_at",
    PrintJobStatus.FAILED: "failed_at",
    PrintJobStatus.CANCELLED: "cancelled_at",
}


class QueueStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def get(self, job_id: str) -> Optional[PrintJobRecord]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM print_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return _row_to_record(row) if row else None

    def insert_received(
        self,
        *,
        job_id: str,
        printer_local_id: str,
        document_type: str,
        document_id: str,
        document_url: str,
        copies: int,
    ) -> bool:
        """Inserts a new job as RECEIVED. Returns True if this call actually
        inserted a row (a genuinely new job) — False means a row with this
        job_id already existed and nothing was changed, i.e. the caller
        must NOT ack or re-process; it should inspect the existing record
        instead (see job_worker.py's dedupe handling).
        """
        now = _now_iso()
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO print_jobs (
                    job_id, printer_local_id, document_type, document_id, document_url,
                    copies, status, attempts, received_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    job_id,
                    printer_local_id,
                    document_type,
                    document_id,
                    document_url,
                    copies,
                    PrintJobStatus.RECEIVED.value,
                    now,
                    now,
                    now,
                ),
            )
            self._conn.commit()
            return cursor.rowcount == 1

    def update_status(
        self,
        job_id: str,
        status: PrintJobStatus,
        *,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        now = _now_iso()
        timestamp_field = _TIMESTAMP_FIELD_BY_STATUS.get(status)
        set_clauses = ["status = ?", "attempts = attempts + 1", "updated_at = ?"]
        params: list = [status.value, now]
        if error_code is not None:
            set_clauses.append("error_code = ?")
            params.append(error_code)
        if error_message is not None:
            set_clauses.append("error_message = ?")
            params.append(error_message)
        if timestamp_field:
            set_clauses.append(f"{timestamp_field} = ?")
            params.append(now)
        params.append(job_id)

        with self._lock:
            self._conn.execute(
                f"UPDATE print_jobs SET {', '.join(set_clauses)} WHERE job_id = ?",
                params,
            )
            self._conn.commit()

    def set_local_file_path(self, job_id: str, path: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE print_jobs SET local_file_path = ?, updated_at = ? WHERE job_id = ?",
                (path, _now_iso(), job_id),
            )
            self._conn.commit()

    def list_non_terminal(self) -> List[PrintJobRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM print_jobs WHERE status NOT IN (?, ?, ?)",
                (
                    PrintJobStatus.COMPLETED.value,
                    PrintJobStatus.FAILED.value,
                    PrintJobStatus.CANCELLED.value,
                ),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def mark_stuck_printing_as_failed(self) -> List[str]:
        """Startup crash recovery: a job left PRINTING means the agent died
        mid-print. Whether physical output happened is unknowable, so the
        safe default is FAILED/AGENT_RESTARTED_DURING_PRINT rather than a
        blind retry (which could double-print) or silently dropping it
        (which could lose it). Returns the affected job_ids so the caller
        can emit print.job.failed for each once reconnected.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT job_id FROM print_jobs WHERE status = ?",
                (PrintJobStatus.PRINTING.value,),
            ).fetchall()
            job_ids = [row["job_id"] for row in rows]
            if job_ids:
                now = _now_iso()
                self._conn.executemany(
                    """
                    UPDATE print_jobs
                    SET status = ?, error_code = ?, error_message = ?,
                        failed_at = ?, updated_at = ?, attempts = attempts + 1
                    WHERE job_id = ?
                    """,
                    [
                        (
                            PrintJobStatus.FAILED.value,
                            "AGENT_RESTARTED_DURING_PRINT",
                            "The agent restarted while this job was printing.",
                            now,
                            now,
                            job_id,
                        )
                        for job_id in job_ids
                    ],
                )
                self._conn.commit()
        return job_ids
