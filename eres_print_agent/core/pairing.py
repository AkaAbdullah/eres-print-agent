"""Implements `eres-print-agent pair <code>` (spec sections 11/42).

Redeems a short-lived pairing code for a permanent credential, then writes
non-secret config (agentId, hubUrl, allowedDocumentHost) to config.json and
the secret (agentSecret) to the OS keyring. After this, the service can be
started with no further user configuration (spec section 33).
"""

from __future__ import annotations

import platform
import socket
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import httpx

from .. import __version__
from ..config import AgentConfig, save_config
from ..credentials import save_agent_secret


@dataclass
class PairingResult:
    success: bool
    agent_id: Optional[str] = None
    error: Optional[str] = None


def _local_hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown-host"


async def pair(*, web_url: str, code: str, timeout_seconds: int = 20) -> PairingResult:
    web_url = web_url.rstrip("/")
    payload = {
        "code": code.strip(),
        "hostname": _local_hostname(),
        "os": f"{platform.system()} {platform.release()}",
        "agentVersion": __version__,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(f"{web_url}/api/print-agent/pair", json=payload)
    except httpx.HTTPError as error:
        return PairingResult(success=False, error=f"Could not reach {web_url}: {error}")

    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code != 200 or not body.get("success"):
        return PairingResult(success=False, error=body.get("error") or f"Pairing failed (HTTP {response.status_code})")

    data = body["data"]
    agent_id = data["agentId"]
    agent_secret = data["agentSecret"]
    hub_url = data["hubUrl"]
    web_origin = data.get("webUrl", web_url)

    save_agent_secret(agent_id, agent_secret)
    save_config(
        AgentConfig(
            agentId=agent_id,
            hubUrl=hub_url,
            allowedDocumentHost=urlparse(web_origin).hostname,
        )
    )

    return PairingResult(success=True, agent_id=agent_id)
