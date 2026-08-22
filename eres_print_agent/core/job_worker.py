"""RECEIVED -> (WAITING_FOR_PRINTER) -> PRINTING -> COMPLETED/FAILED.

Implements the plan's "Receive -> Validate -> Persist -> ACK -> Download ->
Print" pipeline. `handle_dispatch` is called for every inbound `print.job`
message; `resume_job` is called at startup for anything crash-recovery
found left in a resumable, non-terminal state.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, Optional

from ..config import AgentConfig
from ..db.queue_store import PrintJobRecord, QueueStore
from ..models import (
    PrintJobCancel,
    PrintJobCancelled,
    PrintJobCompleted,
    PrintJobDispatch,
    PrintJobFailed,
    PrintJobReceived,
    PrintJobStarted,
)
from ..net.downloader import DownloadError, download_document
from ..net.ws_client import WsClient
from ..printing.base import PrinterManager
from ..state_machine import PrintJobStatus

logger = logging.getLogger(__name__)

WAIT_FOR_PRINTER_POLL_SECONDS = 5
WAIT_FOR_PRINTER_MAX_SECONDS = 60


class JobWorker:
    def __init__(
        self,
        *,
        queue_store: QueueStore,
        printer_manager: PrinterManager,
        ws_client: WsClient,
        config: AgentConfig,
        agent_secret: str,
        download_dir: Path,
    ):
        self._queue_store = queue_store
        self._printer_manager = printer_manager
        self._ws_client = ws_client
        self._config = config
        self._agent_secret = agent_secret
        self._download_dir = download_dir
        self._tasks: Dict[str, asyncio.Task] = {}
        self._cancel_requested: set[str] = set()

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    async def handle_dispatch(self, dispatch: PrintJobDispatch) -> None:
        existing = await asyncio.to_thread(self._queue_store.get, dispatch.jobId)

        if existing:
            if existing.is_terminal:
                await self._resend_terminal_event(existing)
            else:
                logger.info("Duplicate dispatch for in-flight job %s, ignoring", dispatch.jobId)
            return

        inserted = await asyncio.to_thread(
            self._queue_store.insert_received,
            job_id=dispatch.jobId,
            printer_local_id=dispatch.printerId,
            document_type=dispatch.documentType,
            document_id=dispatch.documentId,
            document_url=dispatch.documentUrl,
            copies=dispatch.copies,
        )
        if not inserted:
            # Lost a race with a concurrent dispatch of the same jobId —
            # treat identically to the "already exists" branch above.
            existing = await asyncio.to_thread(self._queue_store.get, dispatch.jobId)
            if existing and existing.is_terminal:
                await self._resend_terminal_event(existing)
            return

        await self._ws_client.send(PrintJobReceived(jobId=dispatch.jobId), durable=True)
        self._tasks[dispatch.jobId] = asyncio.create_task(self._process(dispatch.jobId))

    async def handle_cancel(self, cancel: PrintJobCancel) -> None:
        self._cancel_requested.add(cancel.jobId)
        record = await asyncio.to_thread(self._queue_store.get, cancel.jobId)
        if not record or record.status not in (PrintJobStatus.RECEIVED, PrintJobStatus.WAITING_FOR_PRINTER):
            return  # already printing/terminal — spec: cancel is only honored before PRINTING

        task = self._tasks.get(cancel.jobId)
        if task:
            task.cancel()

        await asyncio.to_thread(self._queue_store.update_status, cancel.jobId, PrintJobStatus.CANCELLED)
        await self._ws_client.send(PrintJobCancelled(jobId=cancel.jobId), durable=True)

    async def resume_job(self, record: PrintJobRecord) -> None:
        """Startup crash recovery: a RECEIVED/WAITING_FOR_PRINTER row found
        in SQLite on boot gets fed back into the same processing pipeline,
        as if it had just arrived.
        """
        self._tasks[record.job_id] = asyncio.create_task(self._process(record.job_id))

    async def _resend_terminal_event(self, record: PrintJobRecord) -> None:
        if record.status == PrintJobStatus.COMPLETED:
            await self._ws_client.send(PrintJobCompleted(jobId=record.job_id), durable=True)
        elif record.status == PrintJobStatus.FAILED:
            await self._ws_client.send(
                PrintJobFailed(jobId=record.job_id, errorCode=record.error_code, message=record.error_message),
                durable=True,
            )
        elif record.status == PrintJobStatus.CANCELLED:
            await self._ws_client.send(PrintJobCancelled(jobId=record.job_id), durable=True)

    async def _fail(self, job_id: str, error_code: str, message: str) -> None:
        logger.warning("Job %s failed: %s — %s", job_id, error_code, message)
        await asyncio.to_thread(
            self._queue_store.update_status,
            job_id,
            PrintJobStatus.FAILED,
            error_code=error_code,
            error_message=message,
        )
        await self._ws_client.send(PrintJobFailed(jobId=job_id, errorCode=error_code, message=message), durable=True)

    async def _process(self, job_id: str) -> None:
        record = await asyncio.to_thread(self._queue_store.get, job_id)
        if record is None:
            logger.error("Job %s vanished from the queue mid-processing", job_id)
            return

        logger.info("Processing job %s (%s -> %s)", job_id, record.document_type, record.printer_local_id)
        try:
            local_path = record.local_file_path
            if not local_path or not Path(local_path).exists():
                try:
                    result = await download_document(
                        url=record.document_url,
                        agent_secret=self._agent_secret,
                        dest_dir=self._download_dir,
                        job_id=job_id,
                        allowed_host=self._config.allowedDocumentHost,
                        # Dev-only: the local mock-web harness (print-hub/dev/mock-web.ts)
                        # has no TLS. Production pairing always yields an https:// documentUrl.
                        allow_insecure_http=os.environ.get("ERES_PRINT_AGENT_ALLOW_INSECURE_HTTP") == "1",
                    )
                except DownloadError as error:
                    await self._fail(job_id, error.error_code, str(error))
                    return
                local_path = str(result.file_path)
                await asyncio.to_thread(self._queue_store.set_local_file_path, job_id, local_path)

            if job_id in self._cancel_requested:
                return  # handle_cancel already transitioned + notified

            if not await self._wait_for_printer(job_id, record.printer_local_id):
                await self._fail(job_id, "PRINTER_OFFLINE", f"Printer {record.printer_local_id} did not come online")
                return

            if job_id in self._cancel_requested:
                return

            await asyncio.to_thread(
                self._queue_store.update_status, job_id, PrintJobStatus.PRINTING
            )
            await self._ws_client.send(PrintJobStarted(jobId=job_id), durable=True)

            try:
                await asyncio.to_thread(
                    self._printer_manager.print, record.printer_local_id, local_path, record.copies
                )
            except Exception as error:
                await self._fail(job_id, "PRINTER_ERROR", str(error))
                return

            await asyncio.to_thread(self._queue_store.update_status, job_id, PrintJobStatus.COMPLETED)
            await self._ws_client.send(PrintJobCompleted(jobId=job_id), durable=True)
            logger.info("Job %s completed", job_id)

        except asyncio.CancelledError:
            raise
        finally:
            self._tasks.pop(job_id, None)
            self._cancel_requested.discard(job_id)

    async def _wait_for_printer(self, job_id: str, printer_local_id: str) -> bool:
        status = await asyncio.to_thread(self._printer_manager.get_status, printer_local_id)
        if status.online:
            return True

        await asyncio.to_thread(self._queue_store.update_status, job_id, PrintJobStatus.WAITING_FOR_PRINTER)
        waited = 0
        while waited < WAIT_FOR_PRINTER_MAX_SECONDS:
            if job_id in self._cancel_requested:
                return False
            await asyncio.sleep(WAIT_FOR_PRINTER_POLL_SECONDS)
            waited += WAIT_FOR_PRINTER_POLL_SECONDS
            status = await asyncio.to_thread(self._printer_manager.get_status, printer_local_id)
            if status.online:
                return True
        return False
