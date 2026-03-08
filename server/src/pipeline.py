"""Transcription pipeline orchestrating audio capture, transcription, and WS broadcast."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import numpy as np

from src.audio_capture import AudioCapture
from src.models import Segment, ServerState, TranscriptionResult, WSMessage
from src.transcriber import Transcriber
from src.ws_server import WSServer

logger = logging.getLogger(__name__)


class Pipeline:
    """Orchestrates AudioCapture -> Transcriber -> WSServer."""

    def __init__(
        self,
        model_size: str = "base",
        chunk_duration: int = 30,
        host: str = "localhost",
        port: int = 9876,
        device: Optional[int] = None,
    ) -> None:
        self._audio_capture = AudioCapture(
            chunk_duration=chunk_duration,
            device=device,
        )
        self._transcriber = Transcriber(model_size=model_size)
        self._ws_server = WSServer(
            host=host,
            port=port,
            on_command=self.handle_command,
        )
        self._state = ServerState.STOPPED
        self._segment_counter = 0
        self._running = False

    async def run(self) -> None:
        """Start the WS server, then loop: capture audio chunks -> transcribe -> broadcast."""
        await self._ws_server.start()
        self._running = True
        logger.info("Pipeline running — waiting for 'start' command")

        try:
            async for chunk in self._audio_capture.chunks():
                if not self._running:
                    break
                await self._process_chunk(chunk)
        except asyncio.CancelledError:
            logger.info("Pipeline loop cancelled")
        finally:
            await self._cleanup()

    async def _process_chunk(self, chunk: np.ndarray) -> None:
        """Transcribe a chunk and broadcast the resulting segments."""
        self._state = ServerState.PROCESSING
        result: TranscriptionResult = self._transcriber.transcribe(chunk)

        # Renumber segments with sequential IDs across chunks
        renumbered: list[Segment] = []
        for seg in result.segments:
            self._segment_counter += 1
            renumbered.append(
                Segment(
                    id=f"seg_{self._segment_counter:03d}",
                    start=seg.start,
                    end=seg.end,
                    text=seg.text,
                    speaker_id=seg.speaker_id,
                    speaker_name=seg.speaker_name,
                )
            )

        msg = WSMessage(
            type="segments",
            data={"segments": [s.to_dict() for s in renumbered]},
        )
        await self._ws_server.broadcast(msg)

        # Return to recording state if we were recording
        if self._running:
            self._state = ServerState.RECORDING

    async def handle_command(self, cmd: dict) -> None:
        """Handle start/pause/stop commands from WS clients."""
        cmd_type = cmd.get("type", "")

        if cmd_type == "start":
            await self._audio_capture.start()
            self._state = ServerState.RECORDING
            await self._broadcast_status()

        elif cmd_type == "stop":
            await self._audio_capture.stop()
            self._state = ServerState.STOPPED
            await self._broadcast_status()

        elif cmd_type == "pause":
            await self._audio_capture.pause()
            self._state = ServerState.PAUSED
            await self._broadcast_status()

        elif cmd_type == "resume":
            await self._audio_capture.resume()
            self._state = ServerState.RECORDING
            await self._broadcast_status()

        else:
            logger.warning("Unknown command type: %s", cmd_type)

    async def _broadcast_status(self) -> None:
        """Broadcast the current server state to all clients."""
        msg = WSMessage(type="status", data={"state": self._state.value})
        await self._ws_server.broadcast(msg)

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        await self._audio_capture.stop()
        await self._ws_server.stop()
        logger.info("Pipeline stopped")

    async def _cleanup(self) -> None:
        """Clean up resources on exit."""
        await self._audio_capture.stop()
        await self._ws_server.stop()
