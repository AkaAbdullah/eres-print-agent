"""Printer discovery -> agent.printers.sync, on connect and periodically."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ..constants import PRINTER_STATUS_CHECK_SECONDS, PRINTER_SYNC_INTERVAL_SECONDS
from ..models import AgentPrintersSync, PrinterCapabilities, SyncedPrinter
from ..printing.base import PrinterManager
from ..net.ws_client import WsClient

logger = logging.getLogger(__name__)


def build_sync_message(printer_manager: PrinterManager) -> AgentPrintersSync:
    discovered = printer_manager.discover()
    return AgentPrintersSync(
        printers=[
            SyncedPrinter(
                localPrinterId=printer.local_printer_id,
                displayName=printer.display_name,
                driverName=printer.driver_name,
                portName=printer.port_name,
                isDefault=printer.is_default,
                capabilities=PrinterCapabilities(
                    color=printer.color, duplex=printer.duplex, paperSizes=printer.paper_sizes
                ),
                statusDetail=printer.status_detail,
                online=printer.online,
            )
            for printer in discovered
        ]
    )


def _fingerprint(message: AgentPrintersSync) -> str:
    """The message without its timestamp, to tell whether anything changed."""
    return message.model_dump_json(exclude={"ts"})


async def sync_now(ws_client: WsClient, printer_manager: PrinterManager) -> Optional[str]:
    """Sends the printer list; returns its fingerprint, or None on failure."""
    try:
        message = await asyncio.to_thread(build_sync_message, printer_manager)
    except Exception:
        logger.exception("Printer discovery failed")
        return None
    await ws_client.send(message)
    return _fingerprint(message)


async def run_periodic_sync(
    ws_client: WsClient,
    printer_manager: PrinterManager,
    stop_event: asyncio.Event,
    interval_seconds: int = PRINTER_SYNC_INTERVAL_SECONDS,
    check_seconds: int = PRINTER_STATUS_CHECK_SECONDS,
) -> None:
    """Checks the printers every `check_seconds` and sends a sync as soon as
    one is plugged in, unplugged or changes state, so ERES shows it within
    about that long. An unchanged list is still re-sent every
    `interval_seconds` as a keep-alive."""
    last_sent: Optional[str] = None
    last_sent_at = 0.0
    loop = asyncio.get_running_loop()
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=check_seconds)
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            break
        if not ws_client.connected.is_set():
            last_sent = None  # resend on reconnect
            continue
        try:
            message = await asyncio.to_thread(build_sync_message, printer_manager)
        except Exception:
            logger.exception("Printer discovery failed")
            continue
        fingerprint = _fingerprint(message)
        if fingerprint != last_sent or loop.time() - last_sent_at >= interval_seconds:
            await ws_client.send(message)
            last_sent, last_sent_at = fingerprint, loop.time()
