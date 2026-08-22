"""Encode outbound / decode inbound WS frames against models.py."""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..models import InboundHubMessage, OutboundAgentMessage, parse_inbound_message

logger = logging.getLogger(__name__)


def encode(message: OutboundAgentMessage) -> str:
    return message.model_dump_json()


def decode(raw: str) -> Optional[InboundHubMessage]:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Dropping non-JSON frame from print-hub")
        return None

    message = parse_inbound_message(payload)
    if message is None:
        logger.warning("Dropping unrecognized/malformed frame from print-hub: %s", payload.get("type") if isinstance(payload, dict) else payload)
    return message
