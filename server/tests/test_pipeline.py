"""Tests for the transcription pipeline (M1-T8)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from src.models import Segment, ServerState, TranscriptionResult, WSMessage
from src.pipeline import Pipeline


@pytest.fixture
def mock_audio_capture():
    """Create a mock AudioCapture."""
    ac = AsyncMock()
    ac.start = AsyncMock()
    ac.stop = AsyncMock()
    ac.pause = AsyncMock()
    ac.resume = AsyncMock()
    return ac


@pytest.fixture
def mock_transcriber():
    """Create a mock Transcriber."""
    t = MagicMock()
    # Default: return two segments per transcription call
    t.transcribe = MagicMock(
        return_value=TranscriptionResult(
            segments=[
                Segment(id="seg_001", start=0.0, end=1.5, text="hello"),
                Segment(id="seg_002", start=1.5, end=3.0, text="world"),
            ],
            audio_duration=3.0,
        )
    )
    return t


@pytest.fixture
def mock_ws_server():
    """Create a mock WSServer."""
    ws = AsyncMock()
    ws.start = AsyncMock()
    ws.stop = AsyncMock()
    ws.broadcast = AsyncMock()
    ws.on_command = None
    return ws


@pytest.fixture
def pipeline(mock_audio_capture, mock_transcriber, mock_ws_server):
    """Create a Pipeline with mocked dependencies."""
    with (
        patch("src.pipeline.AudioCapture", return_value=mock_audio_capture),
        patch("src.pipeline.Transcriber", return_value=mock_transcriber),
        patch("src.pipeline.WSServer", return_value=mock_ws_server),
    ):
        p = Pipeline(model_size="base", chunk_duration=30, host="localhost", port=9876)
    # Store mocks for test access
    p._audio_capture = mock_audio_capture
    p._transcriber = mock_transcriber
    p._ws_server = mock_ws_server
    return p


@pytest.mark.asyncio
async def test_pipeline_init(pipeline):
    """Pipeline wires AudioCapture, Transcriber, WSServer."""
    assert pipeline._audio_capture is not None
    assert pipeline._transcriber is not None
    assert pipeline._ws_server is not None
    assert pipeline._state == ServerState.STOPPED


@pytest.mark.asyncio
async def test_chunk_triggers_transcription(pipeline, mock_transcriber):
    """When an audio chunk arrives, transcriber.transcribe is called."""
    chunk = np.zeros(16000 * 30, dtype=np.float32)
    await pipeline._process_chunk(chunk)
    mock_transcriber.transcribe.assert_called_once_with(chunk)


@pytest.mark.asyncio
async def test_transcription_broadcasts(pipeline, mock_ws_server):
    """Transcription result is broadcast to WS clients."""
    chunk = np.zeros(16000 * 30, dtype=np.float32)
    await pipeline._process_chunk(chunk)

    # Should have broadcast a segments message
    mock_ws_server.broadcast.assert_called()
    call_args = mock_ws_server.broadcast.call_args[0][0]
    assert isinstance(call_args, WSMessage)
    assert call_args.type == "segments"
    assert len(call_args.data["segments"]) == 2


@pytest.mark.asyncio
async def test_start_command(pipeline, mock_audio_capture, mock_ws_server):
    """'start' command starts audio capture."""
    await pipeline.handle_command({"type": "start"})
    mock_audio_capture.start.assert_called_once()
    assert pipeline._state == ServerState.RECORDING

    # Should broadcast status change
    mock_ws_server.broadcast.assert_called()
    status_msg = mock_ws_server.broadcast.call_args[0][0]
    assert status_msg.type == "status"
    assert status_msg.data["state"] == "recording"


@pytest.mark.asyncio
async def test_stop_command(pipeline, mock_audio_capture, mock_ws_server):
    """'stop' command stops capture."""
    # Start first, then stop
    pipeline._state = ServerState.RECORDING
    await pipeline.handle_command({"type": "stop"})
    mock_audio_capture.stop.assert_called_once()
    assert pipeline._state == ServerState.STOPPED

    # Should broadcast status change
    mock_ws_server.broadcast.assert_called()
    status_msg = mock_ws_server.broadcast.call_args[0][0]
    assert status_msg.type == "status"
    assert status_msg.data["state"] == "stopped"


@pytest.mark.asyncio
async def test_pause_command(pipeline, mock_audio_capture, mock_ws_server):
    """'pause' command pauses capture."""
    pipeline._state = ServerState.RECORDING
    await pipeline.handle_command({"type": "pause"})
    mock_audio_capture.pause.assert_called_once()
    assert pipeline._state == ServerState.PAUSED

    # Should broadcast status change
    mock_ws_server.broadcast.assert_called()
    status_msg = mock_ws_server.broadcast.call_args[0][0]
    assert status_msg.type == "status"
    assert status_msg.data["state"] == "paused"


@pytest.mark.asyncio
async def test_segment_ids_sequential(pipeline, mock_transcriber, mock_ws_server):
    """Segments get sequential IDs across chunks."""
    chunk = np.zeros(16000 * 30, dtype=np.float32)

    # First chunk: transcriber returns 2 segments
    mock_transcriber.transcribe.return_value = TranscriptionResult(
        segments=[
            Segment(id="seg_001", start=0.0, end=1.5, text="hello"),
            Segment(id="seg_002", start=1.5, end=3.0, text="world"),
        ],
        audio_duration=3.0,
    )
    await pipeline._process_chunk(chunk)

    first_call = mock_ws_server.broadcast.call_args[0][0]
    first_segments = first_call.data["segments"]
    assert first_segments[0]["id"] == "seg_001"
    assert first_segments[1]["id"] == "seg_002"

    # Second chunk: transcriber again returns seg_001, seg_002 (its own numbering)
    # but pipeline should renumber to seg_003, seg_004
    mock_transcriber.transcribe.return_value = TranscriptionResult(
        segments=[
            Segment(id="seg_001", start=0.0, end=2.0, text="foo"),
            Segment(id="seg_002", start=2.0, end=4.0, text="bar"),
        ],
        audio_duration=4.0,
    )
    await pipeline._process_chunk(chunk)

    second_call = mock_ws_server.broadcast.call_args[0][0]
    second_segments = second_call.data["segments"]
    assert second_segments[0]["id"] == "seg_003"
    assert second_segments[1]["id"] == "seg_004"
