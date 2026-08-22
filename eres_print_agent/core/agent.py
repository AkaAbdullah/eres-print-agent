"""The orchestrator: wires ws_client + queue_store + printer_manager +
job_worker together. This IS what `eres-print-agent run` (and the Windows
service wrapper) drives.

Startup sequence (spec section 32, "Crash Recovery"):
  load configuration -> load SQLite -> recover unfinished jobs ->
  connect to ERES -> synchronize printers -> continue queued jobs
"""

from __future__ import annotations

import asyncio
import logging
import platform
import socket

from .. import __version__
from ..config import AgentConfig, CONFIG_DIR, DB_PATH
from ..constants import HEARTBEAT_INTERVAL_SECONDS
from ..db.queue_store import QueueStore
from ..models import (
    AgentAuthenticated,
    AgentHeartbeat,
    InboundHubMessage,
    PrintJobCancel,
    PrintJobDispatch,
    PrintJobFailed,
)
from ..net.ws_client import WsClient
from ..printing.factory import build_printer_manager
from ..state_machine import PrintJobStatus
from ..status_store import write_status
from . import printer_sync
from .job_worker import JobWorker

logger = logging.getLogger(__name__)

DOWNLOADS_DIR = CONFIG_DIR / "downloads"


class Agent:
    def __init__(self, config: AgentConfig, agent_secret: str):
        if not config.is_paired:
            raise RuntimeError("Agent is not paired — run `eres-print-agent pair <code>` first.")

        self.config = config
        self.agent_secret = agent_secret
        self.stop_event = asyncio.Event()
        self._heartbeat_interval_seconds = HEARTBEAT_INTERVAL_SECONDS
        self._tenant_id: str | None = None
        self._site_id: str | None = None

        self.queue_store = QueueStore(DB_PATH)
        self.printer_manager = build_printer_manager()

        self.ws_client = WsClient(
            hub_url=config.hubUrl,
            agent_id=config.agentId,
            agent_secret=agent_secret,
            hostname=socket.gethostname(),
            os_name=f"{platform.system()} {platform.release()}",
            agent_version=__version__,
            on_authenticated=self._on_authenticated,
            on_inbound_message=self._on_inbound_message,
            on_disconnected=self._on_disconnected,
        )

        self.job_worker = JobWorker(
            queue_store=self.queue_store,
            printer_manager=self.printer_manager,
            ws_client=self.ws_client,
            config=config,
            agent_secret=agent_secret,
            download_dir=DOWNLOADS_DIR,
        )

    async def _on_authenticated(self, message: AgentAuthenticated) -> None:
        self._heartbeat_interval_seconds = max(message.heartbeatIntervalMs / 1000, 5)
        self._tenant_id = message.tenantId
        self._site_id = message.siteId
        logger.info("Authenticated with ERES (tenant=%s, site=%s)", message.tenantId, message.siteId)
        self._write_status_snapshot(connection="connected")
        await printer_sync.sync_now(self.ws_client, self.printer_manager)

    async def _on_inbound_message(self, message: InboundHubMessage) -> None:
        if isinstance(message, PrintJobDispatch):
            await self.job_worker.handle_dispatch(message)
        elif isinstance(message, PrintJobCancel):
            await self.job_worker.handle_cancel(message)

    async def _on_disconnected(self) -> None:
        logger.warning("Disconnected from print-hub; reconnecting per backoff schedule")
        self._write_status_snapshot(connection="disconnected")

    def _write_status_snapshot(self, *, connection: str) -> None:
        try:
            printers = [
                {"localPrinterId": p.local_printer_id, "displayName": p.display_name}
                for p in self.printer_manager.discover()
            ]
        except Exception:
            printers = []

        write_status(
            {
                "agentId": self.config.agentId,
                "agentVersion": __version__,
                "tenantId": self._tenant_id,
                "siteId": self._site_id,
                "connection": connection,
                "hubUrl": self.config.hubUrl,
                "queueDepth": self.job_worker.active_count,
                "printers": printers,
            }
        )

    async def _recover_on_startup(self) -> None:
        stuck_job_ids = await asyncio.to_thread(self.queue_store.mark_stuck_printing_as_failed)
        for job_id in stuck_job_ids:
            logger.warning("Job %s was PRINTING when the agent last stopped — marked FAILED", job_id)
            await self.ws_client.send(
                PrintJobFailed(
                    jobId=job_id,
                    errorCode="AGENT_RESTARTED_DURING_PRINT",
                    message="The agent restarted while this job was printing.",
                ),
                durable=True,
            )

        resumable = await asyncio.to_thread(self.queue_store.list_non_terminal)
        for record in resumable:
            if record.status in (PrintJobStatus.RECEIVED, PrintJobStatus.WAITING_FOR_PRINTER):
                logger.info("Resuming job %s from local queue", record.job_id)
                await self.job_worker.resume_job(record)

    async def _heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self._heartbeat_interval_seconds)
            except asyncio.TimeoutError:
                pass
            if self.stop_event.is_set():
                break
            if self.ws_client.connected.is_set():
                await self.ws_client.send(AgentHeartbeat(queueDepth=self.job_worker.active_count))
                self._write_status_snapshot(connection="connected")

    async def run(self) -> None:
        logger.info("ERES Print Agent %s starting (agentId=%s)", __version__, self.config.agentId)
        self._write_status_snapshot(connection="disconnected")
        await self._recover_on_startup()

        tasks = [
            asyncio.create_task(self.ws_client.run_forever()),
            asyncio.create_task(self._heartbeat_loop()),
            asyncio.create_task(
                printer_sync.run_periodic_sync(self.ws_client, self.printer_manager, self.stop_event)
            ),
        ]
        try:
            await asyncio.gather(*tasks)
        finally:
            self.queue_store.close()

    def stop(self) -> None:
        logger.info("Stopping ERES Print Agent")
        self.stop_event.set()
        self.ws_client.stop()
