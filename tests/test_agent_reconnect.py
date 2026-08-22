import asyncio
import json

import pytest
import websockets

from eres_print_agent.net import ws_client as ws_client_module
from eres_print_agent.net.ws_client import WsClient


@pytest.mark.asyncio
async def test_reconnects_with_backoff_after_a_dropped_connection(monkeypatch):
    # Shrink the backoff schedule so the test doesn't take the real 1s/2s/...
    monkeypatch.setattr(ws_client_module, "RECONNECT_BACKOFF_SCHEDULE", [0.05, 0.05])

    attempt_count = 0
    authenticated_event = asyncio.Event()

    async def handler(socket):
        nonlocal attempt_count
        attempt_count += 1

        if attempt_count == 1:
            # Simulate a dropped connection before authentication completes.
            await socket.close()
            return

        raw = await socket.recv()
        auth = json.loads(raw)
        assert auth["type"] == "agent.authenticate"
        assert auth["agentId"] == "agent-1"

        await socket.send(
            json.dumps(
                {
                    "type": "agent.authenticated",
                    "ts": "2026-01-01T00:00:00.000Z",
                    "agentId": "agent-1",
                    "tenantId": "tenant-1",
                    "siteId": None,
                    "serverTime": "2026-01-01T00:00:00.000Z",
                    "heartbeatIntervalMs": 30000,
                    "knownPrinters": [],
                }
            )
        )
        # Keep the socket open until the test explicitly stops the client.
        await socket.wait_closed()

    server = await websockets.serve(handler, "localhost", 0)
    port = server.sockets[0].getsockname()[1]

    authenticated_messages = []

    async def on_authenticated(message):
        authenticated_messages.append(message)
        authenticated_event.set()

    async def on_inbound_message(_message):
        pass

    disconnected_count = 0

    async def on_disconnected():
        nonlocal disconnected_count
        disconnected_count += 1

    client = WsClient(
        hub_url=f"ws://localhost:{port}",
        agent_id="agent-1",
        agent_secret="secret",
        hostname="test-host",
        os_name="test-os",
        agent_version="0.0.0-test",
        on_authenticated=on_authenticated,
        on_inbound_message=on_inbound_message,
        on_disconnected=on_disconnected,
    )

    run_task = asyncio.create_task(client.run_forever())
    was_connected = False

    try:
        await asyncio.wait_for(authenticated_event.wait(), timeout=5)
        was_connected = client.connected.is_set()
    finally:
        client.stop()
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task
        server.close()
        await server.wait_closed()

    assert attempt_count >= 2  # first attempt dropped, second succeeded
    assert len(authenticated_messages) == 1
    assert authenticated_messages[0].tenantId == "tenant-1"
    assert disconnected_count >= 1  # the first dropped attempt fired on_disconnected
    assert was_connected
