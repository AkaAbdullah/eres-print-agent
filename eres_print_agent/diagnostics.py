"""Backends for `status`/`printers`/`logs` — read config.json, status.json,
and the log file directly rather than talking to the running service
process, since there's no IPC channel into it (see status_store.py).
"""

from __future__ import annotations

import sys
from typing import Any, Dict

from .config import LOG_DIR, load_config
from .status_store import read_status


def _service_status() -> str:
    if sys.platform != "win32":
        return "n/a (not Windows)"
    try:
        from .service.windows_service import query_service_status

        return query_service_status()
    except Exception as error:
        return f"unknown ({error})"


def collect_status() -> Dict[str, Any]:
    config = load_config()
    snapshot = read_status() or {}

    return {
        "service": _service_status(),
        "paired": config.is_paired,
        "agentId": config.agentId,
        "hubUrl": config.hubUrl,
        "connection": snapshot.get("connection", "unknown"),
        "tenantId": snapshot.get("tenantId"),
        "siteId": snapshot.get("siteId"),
        "agentVersion": snapshot.get("agentVersion"),
        "queueDepth": snapshot.get("queueDepth"),
        "printerCount": len(snapshot.get("printers", [])),
        "lastUpdatedAt": snapshot.get("updatedAt"),
    }


def collect_printers() -> list:
    snapshot = read_status() or {}
    return snapshot.get("printers", [])


def format_status_text(status: Dict[str, Any]) -> str:
    lines = [
        "ERES Print Agent",
        "",
        f"Service:       {status['service']}",
        f"Paired:        {'Yes' if status['paired'] else 'No'}",
        f"Agent ID:      {status['agentId'] or '-'}",
        f"Connection:    {status['connection']}",
        f"Hub URL:       {status['hubUrl'] or '-'}",
        f"Organization:  {status['tenantId'] or '-'}",
        f"Version:       {status['agentVersion'] or '-'}",
        f"Printers:      {status['printerCount']}",
        f"Queued Jobs:   {status['queueDepth'] if status['queueDepth'] is not None else '-'}",
        f"Last Update:   {status['lastUpdatedAt'] or '-'}",
    ]
    return "\n".join(lines)


def format_printers_text(printers: list) -> str:
    if not printers:
        return "No printers discovered yet. Is the agent running and connected?"
    lines = []
    for printer in printers:
        lines.append(printer.get("displayName") or printer.get("localPrinterId", "Unknown"))
    return "\n".join(lines)


def tail_log_lines(max_lines: int = 200) -> str:
    log_path = LOG_DIR / "agent.log"
    if not log_path.exists():
        return "No logs yet."
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])
