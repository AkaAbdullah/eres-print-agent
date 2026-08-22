"""Pydantic models mirroring print-hub/PROTOCOL.md 1:1.

print-hub is TypeScript and this agent is Python, so there is no shared
code across that boundary — PROTOCOL.md is the source of truth and these
models (plus print-hub's src/ws/protocol.ts) are both hand-kept in sync
with it. Keep field names and required-ness identical to the zod schemas.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---------------------------------------------------------------------------
# Outbound: agent -> hub
# ---------------------------------------------------------------------------


class AgentAuthenticate(BaseModel):
    type: Literal["agent.authenticate"] = "agent.authenticate"
    ts: str = Field(default_factory=now_iso)
    agentId: str
    agentSecret: str
    hostname: Optional[str] = None
    os: Optional[str] = None
    agentVersion: Optional[str] = None
    protocolVersion: Optional[int] = None


class AgentHeartbeat(BaseModel):
    type: Literal["agent.heartbeat"] = "agent.heartbeat"
    ts: str = Field(default_factory=now_iso)
    queueDepth: Optional[int] = None


class PrinterCapabilities(BaseModel):
    color: Optional[bool] = None
    duplex: Optional[bool] = None
    paperSizes: Optional[List[str]] = None


class SyncedPrinter(BaseModel):
    localPrinterId: str
    displayName: Optional[str] = None
    driverName: Optional[str] = None
    portName: Optional[str] = None
    isDefault: Optional[bool] = None
    capabilities: Optional[PrinterCapabilities] = None
    statusDetail: Optional[str] = None


class AgentPrintersSync(BaseModel):
    type: Literal["agent.printers.sync"] = "agent.printers.sync"
    ts: str = Field(default_factory=now_iso)
    printers: List[SyncedPrinter]


class AgentStatus(BaseModel):
    type: Literal["agent.status"] = "agent.status"
    ts: str = Field(default_factory=now_iso)
    queueDepth: Optional[int] = None
    diskFreeBytes: Optional[int] = None


class PrintJobReceived(BaseModel):
    type: Literal["print.job.received"] = "print.job.received"
    ts: str = Field(default_factory=now_iso)
    jobId: str


class PrintJobStarted(BaseModel):
    type: Literal["print.job.started"] = "print.job.started"
    ts: str = Field(default_factory=now_iso)
    jobId: str


class PrintJobCompleted(BaseModel):
    type: Literal["print.job.completed"] = "print.job.completed"
    ts: str = Field(default_factory=now_iso)
    jobId: str


class PrintJobFailed(BaseModel):
    type: Literal["print.job.failed"] = "print.job.failed"
    ts: str = Field(default_factory=now_iso)
    jobId: str
    errorCode: Optional[str] = None
    message: Optional[str] = None


class PrintJobCancelled(BaseModel):
    type: Literal["print.job.cancelled"] = "print.job.cancelled"
    ts: str = Field(default_factory=now_iso)
    jobId: str


OutboundAgentMessage = Union[
    AgentAuthenticate,
    AgentHeartbeat,
    AgentPrintersSync,
    AgentStatus,
    PrintJobReceived,
    PrintJobStarted,
    PrintJobCompleted,
    PrintJobFailed,
    PrintJobCancelled,
]


# ---------------------------------------------------------------------------
# Inbound: hub -> agent
# ---------------------------------------------------------------------------


class KnownPrinter(BaseModel):
    printerId: str
    localPrinterId: str


class AgentAuthenticated(BaseModel):
    type: Literal["agent.authenticated"] = "agent.authenticated"
    ts: str
    agentId: str
    tenantId: str
    siteId: Optional[str] = None
    serverTime: str
    heartbeatIntervalMs: int
    knownPrinters: List[KnownPrinter] = Field(default_factory=list)


class AgentAuthenticateRejected(BaseModel):
    type: Literal["agent.authenticate.rejected"] = "agent.authenticate.rejected"
    ts: str
    reason: Literal["invalid_credentials", "revoked", "malformed"]


class PrintJobDispatch(BaseModel):
    type: Literal["print.job"] = "print.job"
    ts: str
    jobId: str
    printerId: str
    documentType: str
    documentId: str
    documentUrl: str
    copies: int = 1


class PrintJobCancel(BaseModel):
    type: Literal["print.job.cancel"] = "print.job.cancel"
    ts: str
    jobId: str


InboundHubMessage = Union[
    AgentAuthenticated,
    AgentAuthenticateRejected,
    PrintJobDispatch,
    PrintJobCancel,
]

_INBOUND_MODEL_BY_TYPE = {
    "agent.authenticated": AgentAuthenticated,
    "agent.authenticate.rejected": AgentAuthenticateRejected,
    "print.job": PrintJobDispatch,
    "print.job.cancel": PrintJobCancel,
}


def parse_inbound_message(raw: dict) -> Optional[InboundHubMessage]:
    """Returns None (rather than raising) for anything unrecognized or
    malformed — the caller logs and drops it, matching print-hub's own
    "malformed inbound message, dropping" behavior rather than crashing
    the connection over one bad frame.
    """
    message_type = raw.get("type") if isinstance(raw, dict) else None
    model = _INBOUND_MODEL_BY_TYPE.get(message_type)
    if not model:
        return None
    try:
        return model.model_validate(raw)
    except Exception:
        return None
