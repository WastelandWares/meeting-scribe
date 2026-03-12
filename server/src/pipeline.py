"""Transcription pipeline orchestrating audio capture, transcription, and WS broadcast.

Dual-stream architecture:
  Stream 1: audio -> STT -> broadcast (real-time, unchanged)
  Stream 2: segments -> accumulator -> Assistant -> broadcast (batched analysis)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import numpy as np

from src.assistant import Assistant, AssistantConfig
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
        assistant_config: Optional[AssistantConfig] = None,
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

        # Stream 2: Assistant (batched analysis)
        self._assistant_config = assistant_config or AssistantConfig()
        self._assistant: Optional[Assistant] = None

    def get_server_info(self) -> dict:
        """Build capabilities dict broadcast to clients on connect."""
        info: dict = {
            "diarization": self._diarizer is not None,
            "assistant": self._assistant is not None and self._assistant._ready,
            "assistant_window": self._assistant_config.window_seconds if self._assistant_config.enabled else 0,
            "warnings": [],
        }
        if self._diarizer is None:
            info["warnings"].append({
                "id": "no_diarization",
                "level": "warning",
                "title": "Speaker labels unavailable",
                "message": "Set HF_TOKEN to enable speaker diarization. Get a free token at huggingface.co/settings/tokens",
            })
        if self._assistant_config.enabled and (self._assistant is None or not self._assistant._ready):
            info["warnings"].append({
                "id": "no_assistant",
                "level": "warning",
                "title": "AI assistant unavailable",
                "message": "Ollama is not running or has no supported model. Install phi4-mini: ollama pull phi4-mini",
            })
        elif not self._assistant_config.enabled:
            info["warnings"].append({
                "id": "assistant_disabled",
                "level": "info",
                "title": "AI assistant disabled",
                "message": "Start the server without --no-assistant to enable summaries and action items.",
            })
        if self._assistant is not None and self._assistant._ready:
            info["assistant_model"] = self._assistant._ollama.model
        if self._assistant is not None:
            info["skills"] = self._assistant.get_skills_info()
        return info

    async def run(self) -> None:
        """Start the WS server, then loop: capture audio chunks -> transcribe -> broadcast."""
        # Pre-load diarization model so first run isn't slow
        if self._diarizer is not None:
            logger.info("Pre-loading diarization model...")
            self._diarizer._ensure_pipeline()
            logger.info("Diarization model ready")

        # Set the server_info callback so clients get capabilities on connect
        self._ws_server.on_client_connect = self._on_client_connect

        await self._ws_server.start()

        # Initialize assistant (Stream 2)
        if self._assistant_config.enabled:
            self._assistant = Assistant(
                config=self._assistant_config,
                broadcast=self._ws_server.broadcast,
            )
            assistant_ready = await self._assistant.start()
            if assistant_ready:
                logger.info("Assistant initialized — dual-stream active")
            else:
                logger.info("Assistant unavailable — single-stream mode")

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

        # Stream 2: feed segments to assistant for batched analysis
        if self._assistant is not None:
            self._assistant.feed_segments(renumbered)

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
            # Run final diarization so the transcript gets speaker labels
            if self._diarizer is not None and self._diarizer._chunks:
                await self._run_diarization()
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

    async def _on_client_connect(self, websocket) -> None:
        """Send server capabilities to a newly connected client."""
        info_msg = WSMessage(
            type="server_info",
            data=self.get_server_info(),
        )
        await websocket.send(info_msg.to_json())

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        await self._audio_capture.stop()
        if self._assistant is not None:
            await self._assistant.stop()
        await self._ws_server.stop()
        logger.info("Pipeline stopped")

    async def _cleanup(self) -> None:
        """Clean up resources on exit."""
        if self._assistant is not None:
            await self._assistant.stop()
        await self._ws_server.stop()
