"""WebSocket client: connect, authenticate, heartbeat, reconnect with
exponential backoff (spec section 14).

Two kinds of outbound message:
  - "durable" (print.job.* status events) — queued if the socket is down
    and flushed in order right after the next successful authenticate, so
    a network blip never silently drops a status the agent already
    computed. The true state of record is always the local SQLite queue;
    this buffer only covers "tell web/ what already happened."
  - everything else (heartbeat, printers.sync, agent.status) — best-effort,
    dropped if not connected, since the next periodic tick naturally
    re-sends current state anyway.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, List, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from ..constants import PROTOCOL_VERSION, RECONNECT_BACKOFF_SCHEDULE
from ..models import (
    AgentAuthenticate,
    AgentAuthenticated,
    AgentAuthenticateRejected,
    InboundHubMessage,
    OutboundAgentMessage,
)
from .protocol_codec import decode, encode

logger = logging.getLogger(__name__)

OnAuthenticated = Callable[[AgentAuthenticated], Awaitable[None]]
OnInboundMessage = Callable[[InboundHubMessage], Awaitable[None]]
OnDisconnected = Callable[[], Awaitable[None]]


class WsClient:
    def __init__(
        self,
        *,
        hub_url: str,
        agent_id: str,
        agent_secret: str,
        hostname: str,
        os_name: str,
        agent_version: str,
        on_authenticated: OnAuthenticated,
        on_inbound_message: OnInboundMessage,
        on_disconnected: OnDisconnected,
    ):
        self.hub_url = hub_url
        self.agent_id = agent_id
        self.agent_secret = agent_secret
        self.hostname = hostname
        self.os_name = os_name
        self.agent_version = agent_version
        self._on_authenticated = on_authenticated
        self._on_inbound_message = on_inbound_message
        self._on_disconnected = on_disconnected

        self._socket = None
        self._durable_queue: List[OutboundAgentMessage] = []
        self._stop_event = asyncio.Event()
        self.connected = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    async def send(self, message: OutboundAgentMessage, *, durable: bool = False) -> None:
        if self._socket is not None:
            try:
                await self._socket.send(encode(message))
                return
            except ConnectionClosed:
                pass  # fall through to queueing/dropping below

        if durable:
            self._durable_queue.append(message)
        else:
            logger.debug("Dropping non-durable message while disconnected: %s", message.type)

    async def _flush_durable_queue(self) -> None:
        pending, self._durable_queue = self._durable_queue, []
        for message in pending:
            await self.send(message, durable=True)

    async def _authenticate(self, socket) -> Optional[AgentAuthenticated]:
        await socket.send(
            encode(
                AgentAuthenticate(
                    agentId=self.agent_id,
                    agentSecret=self.agent_secret,
                    hostname=self.hostname,
                    os=self.os_name,
                    agentVersion=self.agent_version,
                    protocolVersion=PROTOCOL_VERSION,
                )
            )
        )
        raw = await asyncio.wait_for(socket.recv(), timeout=15)
        message = decode(raw)

        if isinstance(message, AgentAuthenticated):
            return message
        if isinstance(message, AgentAuthenticateRejected):
            logger.error("print-hub rejected authentication: %s", message.reason)
            return None

        logger.error("Unexpected first message from print-hub: %s", raw)
        return None

    async def run_forever(self) -> None:
        backoff_index = 0

        while not self._stop_event.is_set():
            try:
                async with websockets.connect(self.hub_url, open_timeout=15) as socket:
                    self._socket = socket
                    authenticated = await self._authenticate(socket)

                    if not authenticated:
                        self._socket = None
                        raise ConnectionClosed(None, None)

                    backoff_index = 0  # reset on any successful connection, per spec
                    self.connected.set()
                    await self._flush_durable_queue()
                    await self._on_authenticated(authenticated)

                    async for raw in socket:
                        message = decode(raw)
                        if message is not None:
                            await self._on_inbound_message(message)

            except (ConnectionClosed, OSError, asyncio.TimeoutError) as error:
                logger.warning("print-hub connection lost: %s", error)
            finally:
                self._socket = None
                self.connected.clear()
                await self._on_disconnected()

            if self._stop_event.is_set():
                break

            delay = RECONNECT_BACKOFF_SCHEDULE[min(backoff_index, len(RECONNECT_BACKOFF_SCHEDULE) - 1)]
            backoff_index += 1
            logger.info("Reconnecting to print-hub in %ss", delay)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass  # normal case: the backoff delay elapsed, loop again
