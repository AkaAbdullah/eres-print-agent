"""Printer discovery -> agent.printers.sync, on connect and periodically."""

from __future__ import annotations

import asyncio
import logging

from ..constants import PRINTER_SYNC_INTERVAL_SECONDS
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
            )
            for printer in discovered
        ]
    )


async def sync_now(ws_client: WsClient, printer_manager: PrinterManager) -> None:
    try:
        message = build_sync_message(printer_manager)
    except Exception:
        logger.exception("Printer discovery failed")
        return
    await ws_client.send(message)


async def run_periodic_sync(
    ws_client: WsClient,
    printer_manager: PrinterManager,
    stop_event: asyncio.Event,
    interval_seconds: int = PRINTER_SYNC_INTERVAL_SECONDS,
) -> None:
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            break
        if ws_client.connected.is_set():
            await sync_now(ws_client, printer_manager)
