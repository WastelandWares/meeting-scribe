"""Tests for WebSocket server (M1-T6)."""

from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio
import websockets

from src.models import ServerState, WSMessage
from src.ws_server import WSServer


@pytest_asyncio.fixture
async def server():
    """Create a WSServer on a dynamic port and yield it, then stop."""
    srv = WSServer(host="localhost", port=0)
    await srv.start()
    yield srv
    await srv.stop()


@pytest.mark.asyncio
async def test_server_starts(server: WSServer):
    """WSServer starts and accepts a WebSocket connection."""
    uri = f"ws://localhost:{server.port}"
    async with websockets.connect(uri) as ws:
        assert ws.open


@pytest.mark.asyncio
async def test_client_receives_status(server: WSServer):
    """On connect, the client immediately receives a status message."""
    uri = f"ws://localhost:{server.port}"
    async with websockets.connect(uri) as ws:
        raw = await asyncio.wait_for(ws.recv(), timeout=2)
        msg = json.loads(raw)
        assert msg["type"] == "status"
        assert msg["data"]["state"] in [s.value for s in ServerState]


@pytest.mark.asyncio
async def test_broadcast_segments(server: WSServer):
    """broadcast() sends a WSMessage to all connected clients."""
    uri = f"ws://localhost:{server.port}"
    async with websockets.connect(uri) as ws:
        # Drain the initial status message
        await asyncio.wait_for(ws.recv(), timeout=2)

        # Broadcast a segments message
        msg = WSMessage(type="segments", data={"segments": [{"id": "1", "text": "hello"}]})
        await server.broadcast(msg)

        raw = await asyncio.wait_for(ws.recv(), timeout=2)
        parsed = json.loads(raw)
        assert parsed["type"] == "segments"
        assert parsed["data"]["segments"][0]["text"] == "hello"


@pytest.mark.asyncio
async def test_client_commands(server: WSServer):
    """Client sends a command; the on_command callback fires."""
    received: list[dict] = []

    async def handler(cmd: dict) -> None:
        received.append(cmd)

    server.on_command = handler

    uri = f"ws://localhost:{server.port}"
    async with websockets.connect(uri) as ws:
        # Drain the initial status message
        await asyncio.wait_for(ws.recv(), timeout=2)

        await ws.send(json.dumps({"type": "start"}))
        # Give the server a moment to process
        await asyncio.sleep(0.1)

    assert len(received) == 1
    assert received[0]["type"] == "start"


@pytest.mark.asyncio
async def test_multiple_clients(server: WSServer):
    """Both connected clients receive a broadcast message."""
    uri = f"ws://localhost:{server.port}"
    async with websockets.connect(uri) as ws1, websockets.connect(uri) as ws2:
        # Drain initial status messages
        await asyncio.wait_for(ws1.recv(), timeout=2)
        await asyncio.wait_for(ws2.recv(), timeout=2)

        msg = WSMessage(type="ping", data={"ts": 1})
        await server.broadcast(msg)

        raw1 = await asyncio.wait_for(ws1.recv(), timeout=2)
        raw2 = await asyncio.wait_for(ws2.recv(), timeout=2)

        assert json.loads(raw1)["type"] == "ping"
        assert json.loads(raw2)["type"] == "ping"


@pytest.mark.asyncio
async def test_malformed_json(server: WSServer):
    """Server does not crash when a client sends malformed JSON."""
    uri = f"ws://localhost:{server.port}"
    async with websockets.connect(uri) as ws:
        # Drain the initial status message
        await asyncio.wait_for(ws.recv(), timeout=2)

        # Send garbage
        await ws.send("this is not json{{{")
        # Give the server time to process (and NOT crash)
        await asyncio.sleep(0.2)

    # Server should still be functional — new client can connect
    async with websockets.connect(uri) as ws2:
        raw = await asyncio.wait_for(ws2.recv(), timeout=2)
        assert json.loads(raw)["type"] == "status"
