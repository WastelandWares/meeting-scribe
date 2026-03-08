"""WebSocket server for real-time transcription streaming (M1-T7)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

import websockets.asyncio.server as ws_server
from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosed

from src.models import ServerState, WSMessage

logger = logging.getLogger(__name__)


class WSServer:
    """WebSocket server that broadcasts transcription data to connected clients."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9876,
        on_command: Optional[Callable[[dict], Awaitable[None]]] = None,
    ) -> None:
        self.host = host
        self._requested_port = port
        self.port: int = port
        self.on_command = on_command
        self._clients: set[ServerConnection] = set()
        self._server: Optional[ws_server.Server] = None
        self._state = ServerState.STOPPED

    async def start(self) -> None:
        """Start the WebSocket server."""
        server = await ws_server.serve(
            self._handler,
            self.host,
            self._requested_port,
        )
        self._server = server
        # Resolve actual port (important when port=0 for dynamic allocation)
        for sock in self._server.sockets:
            addr = sock.getsockname()
            self.port = addr[1]
            break
        logger.info("WebSocket server started on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Stop the WebSocket server and close all connections."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._clients.clear()
        logger.info("WebSocket server stopped")

    async def broadcast(self, message: WSMessage) -> None:
        """Send a message to all connected clients."""
        if not self._clients:
            return
        payload = message.to_json()
        # Send to all clients concurrently, removing any that have disconnected
        disconnected: set[ServerConnection] = set()
        await asyncio.gather(
            *(self._send_safe(client, payload, disconnected) for client in self._clients)
        )
        self._clients -= disconnected

    async def _send_safe(
        self,
        client: ServerConnection,
        payload: str,
        disconnected: set[ServerConnection],
    ) -> None:
        """Send a payload to a client, tracking failures."""
        try:
            await client.send(payload)
        except ConnectionClosed:
            disconnected.add(client)

    async def _handler(self, websocket: ServerConnection) -> None:
        """Handle a single WebSocket client connection."""
        self._clients.add(websocket)
        logger.info("Client connected (%d total)", len(self._clients))

        try:
            # Send current status on connect
            status_msg = WSMessage(
                type="status",
                data={"state": self._state.value},
            )
            await websocket.send(status_msg.to_json())

            # Listen for commands from the client
            async for raw in websocket:
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Received malformed JSON from client: %s", raw[:200])
                    continue

                if "type" not in data:
                    logger.warning("Received message without type field: %s", raw[:200])
                    continue

                if self.on_command is not None:
                    try:
                        await self.on_command(data)
                    except Exception:
                        logger.exception("Error in on_command callback")
        except ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            logger.info("Client disconnected (%d remaining)", len(self._clients))
