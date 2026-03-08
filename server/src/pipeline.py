"""Transcription pipeline orchestrating audio capture, transcription, and WS broadcast."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import numpy as np

from src.audio_capture import AudioCapture
from src.diarizer import Diarizer, assign_speakers
from src.models import (
    Segment,
    ServerState,
    TranscriptionResult,
    WSMessage,
    WS_MSG_DIARIZATION_UPDATE,
    WS_MSG_LABEL_SPEAKER,
)
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
        diarization_interval: int = 3,
        hf_token: Optional[str] = None,
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

        # Diarization support
        self._diarization_interval = diarization_interval
        self._chunk_count = 0
        self._audio_offset = 0.0  # absolute time offset for current chunk
        self._all_segments: list[Segment] = []
        self._speaker_labels: dict[str, str] = {}
        self._last_diarization = None

        token = hf_token or os.environ.get("HF_TOKEN")
        self._diarizer: Optional[Diarizer] = Diarizer(hf_token=token) if token else None

    async def run(self) -> None:
        """Start the WS server, then loop: capture audio chunks -> transcribe -> broadcast."""
        await self._ws_server.start()
        self._running = True
        logger.info("Pipeline running — waiting for 'start' command")

        try:
            while self._running:
                # Wait for chunks; generator ends when audio_capture.stop() is called
                async for chunk in self._audio_capture.chunks():
                    if not self._running:
                        break
                    await self._process_chunk(chunk)
                # Audio stopped (user hit stop) but server stays alive
                # waiting for the next "start" command
                if self._running:
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("Pipeline loop cancelled")
        finally:
            await self._cleanup()

    async def _process_chunk(self, chunk: np.ndarray) -> None:
        """Transcribe a chunk and broadcast the resulting segments."""
        self._state = ServerState.PROCESSING
        result: TranscriptionResult = self._transcriber.transcribe(chunk)

        # Renumber segments with sequential IDs and absolute timestamps
        renumbered: list[Segment] = []
        for seg in result.segments:
            self._segment_counter += 1
            renumbered.append(
                Segment(
                    id=f"seg_{self._segment_counter:03d}",
                    start=self._audio_offset + seg.start,
                    end=self._audio_offset + seg.end,
                    text=seg.text,
                    speaker_id=seg.speaker_id,
                    speaker_name=seg.speaker_name,
                )
            )

        # Advance the offset by the chunk duration
        self._audio_offset += len(chunk) / self._audio_capture.sample_rate

        # Accumulate all segments for diarization re-assignment
        self._all_segments.extend(renumbered)

        msg = WSMessage(
            type="segments",
            data={"segments": [s.to_dict() for s in renumbered]},
        )
        await self._ws_server.broadcast(msg)

        # Diarization: accumulate audio and trigger periodically
        if self._diarizer is not None:
            self._diarizer.accumulate(chunk)
            self._chunk_count += 1

            if self._chunk_count % self._diarization_interval == 0:
                await self._run_diarization()

        # Return to recording state if we were recording
        if self._running:
            self._state = ServerState.RECORDING

    async def _run_diarization(self) -> None:
        """Run diarization and broadcast updated segments with speaker info."""
        if self._diarizer is None:
            return

        self._last_diarization = await self._diarizer.run_diarization()
        assign_speakers(self._all_segments, self._last_diarization, self._speaker_labels)

        msg = WSMessage(
            type=WS_MSG_DIARIZATION_UPDATE,
            data={"segments": [s.to_dict() for s in self._all_segments]},
        )
        await self._ws_server.broadcast(msg)

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

        elif cmd_type == WS_MSG_LABEL_SPEAKER:
            speaker_id = cmd.get("speaker_id", "")
            name = cmd.get("name", "")
            if speaker_id:
                self._speaker_labels[speaker_id] = name
                # Re-assign speakers on accumulated segments
                if self._last_diarization is not None:
                    assign_speakers(
                        self._all_segments,
                        self._last_diarization,
                        self._speaker_labels,
                    )
                else:
                    # No diarization yet — just apply name to matching segments
                    for seg in self._all_segments:
                        if seg.speaker_id == speaker_id:
                            seg.speaker_name = name
                # Always broadcast the update
                msg = WSMessage(
                    type=WS_MSG_DIARIZATION_UPDATE,
                    data={"segments": [s.to_dict() for s in self._all_segments]},
                )
                await self._ws_server.broadcast(msg)

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
        await self._ws_server.stop()
