"""Tests for audio capture module."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.audio_capture import AudioCapture


@pytest.fixture
def mock_stream():
    """Create a mock sounddevice.InputStream."""
    with patch("src.audio_capture.sd") as mock_sd:
        mock_instance = MagicMock()
        mock_sd.InputStream.return_value = mock_instance
        yield mock_sd, mock_instance


class TestAudioCaptureInit:
    def test_audio_capture_init(self):
        """AudioCapture stores chunk_duration, sample_rate, and device."""
        cap = AudioCapture(chunk_duration=30, sample_rate=16000)
        assert cap.chunk_duration == 30
        assert cap.sample_rate == 16000
        assert cap.device is None

    def test_audio_capture_init_custom_device(self):
        cap = AudioCapture(chunk_duration=10, sample_rate=44100, device=3)
        assert cap.chunk_duration == 10
        assert cap.sample_rate == 44100
        assert cap.device == 3


class TestStartStop:
    @pytest.mark.asyncio
    async def test_start_begins_recording(self, mock_stream):
        mock_sd, mock_instance = mock_stream
        cap = AudioCapture(chunk_duration=30, sample_rate=16000)

        await cap.start()

        mock_sd.InputStream.assert_called_once()
        call_kwargs = mock_sd.InputStream.call_args[1]
        assert call_kwargs["samplerate"] == 16000
        assert call_kwargs["channels"] == 1
        mock_instance.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_cleans_up(self, mock_stream):
        mock_sd, mock_instance = mock_stream
        cap = AudioCapture(chunk_duration=30, sample_rate=16000)

        await cap.start()
        await cap.stop()

        mock_instance.stop.assert_called_once()
        mock_instance.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self, mock_stream):
        """Calling stop() before start() should not raise."""
        _mock_sd, _mock_instance = mock_stream
        cap = AudioCapture()
        await cap.stop()  # should not raise


class TestChunkCallback:
    @pytest.mark.asyncio
    async def test_chunk_callback_fires(self, mock_stream):
        """After chunk_duration worth of audio, a chunk is available."""
        mock_sd, mock_instance = mock_stream
        chunk_duration = 1  # 1 second for fast test
        sample_rate = 16000
        cap = AudioCapture(chunk_duration=chunk_duration, sample_rate=sample_rate)

        await cap.start()

        # Extract the callback that was passed to InputStream
        call_kwargs = mock_sd.InputStream.call_args[1]
        callback = call_kwargs["callback"]

        # Simulate feeding exactly chunk_duration worth of audio
        total_samples = chunk_duration * sample_rate
        audio_data = np.zeros((total_samples, 1), dtype=np.float32)
        callback(audio_data, total_samples, None, None)

        # The chunk should now be available on the queue
        chunk = await asyncio.wait_for(cap._queue.get(), timeout=1.0)
        assert chunk.shape == (total_samples,)

    @pytest.mark.asyncio
    async def test_chunk_callback_accumulates(self, mock_stream):
        """Multiple small callbacks accumulate into one chunk."""
        mock_sd, mock_instance = mock_stream
        chunk_duration = 1
        sample_rate = 16000
        cap = AudioCapture(chunk_duration=chunk_duration, sample_rate=sample_rate)

        await cap.start()

        callback = mock_sd.InputStream.call_args[1]["callback"]

        # Feed audio in two halves
        half = sample_rate // 2
        audio_half = np.ones((half, 1), dtype=np.float32)
        callback(audio_half, half, None, None)

        # Queue should be empty (not enough samples yet)
        assert cap._queue.empty()

        # Feed second half
        callback(audio_half, half, None, None)

        chunk = await asyncio.wait_for(cap._queue.get(), timeout=1.0)
        assert chunk.shape == (sample_rate,)
        np.testing.assert_array_equal(chunk, np.ones(sample_rate, dtype=np.float32))


class TestPauseResume:
    @pytest.mark.asyncio
    async def test_pause_stops_chunk_emission(self, mock_stream):
        """While paused, audio callbacks do not produce chunks."""
        mock_sd, mock_instance = mock_stream
        cap = AudioCapture(chunk_duration=1, sample_rate=16000)

        await cap.start()
        callback = mock_sd.InputStream.call_args[1]["callback"]

        await cap.pause()

        # Feed a full chunk while paused
        audio = np.zeros((16000, 1), dtype=np.float32)
        callback(audio, 16000, None, None)

        # Queue should remain empty
        assert cap._queue.empty()

    @pytest.mark.asyncio
    async def test_resume_restarts_emission(self, mock_stream):
        """After resume(), chunks are emitted again."""
        mock_sd, mock_instance = mock_stream
        cap = AudioCapture(chunk_duration=1, sample_rate=16000)

        await cap.start()
        callback = mock_sd.InputStream.call_args[1]["callback"]

        await cap.pause()
        await cap.resume()

        audio = np.zeros((16000, 1), dtype=np.float32)
        callback(audio, 16000, None, None)

        chunk = await asyncio.wait_for(cap._queue.get(), timeout=1.0)
        assert chunk.shape == (16000,)

    @pytest.mark.asyncio
    async def test_pause_clears_partial_buffer(self, mock_stream):
        """Pausing discards any partially accumulated audio."""
        mock_sd, mock_instance = mock_stream
        cap = AudioCapture(chunk_duration=1, sample_rate=16000)

        await cap.start()
        callback = mock_sd.InputStream.call_args[1]["callback"]

        # Feed half a chunk
        audio_half = np.ones((8000, 1), dtype=np.float32)
        callback(audio_half, 8000, None, None)

        await cap.pause()
        await cap.resume()

        # Feed another half — should NOT complete a chunk (buffer was cleared)
        callback(audio_half, 8000, None, None)
        assert cap._queue.empty()

        # Feed a full chunk to confirm it works from fresh
        audio_full = np.zeros((16000, 1), dtype=np.float32)
        callback(audio_full, 16000, None, None)

        chunk = await asyncio.wait_for(cap._queue.get(), timeout=1.0)
        assert chunk.shape == (16000,)


class TestChunksGenerator:
    @pytest.mark.asyncio
    async def test_chunks_yields_from_queue(self, mock_stream):
        """The async chunks() generator yields items from the queue."""
        mock_sd, mock_instance = mock_stream
        cap = AudioCapture(chunk_duration=1, sample_rate=16000)

        await cap.start()
        callback = mock_sd.InputStream.call_args[1]["callback"]

        # Feed two chunks
        audio = np.zeros((16000, 1), dtype=np.float32)
        callback(audio, 16000, None, None)
        callback(audio, 16000, None, None)

        received = []
        gen = cap.chunks()
        received.append(await asyncio.wait_for(gen.__anext__(), timeout=1.0))
        received.append(await asyncio.wait_for(gen.__anext__(), timeout=1.0))

        assert len(received) == 2
        assert all(c.shape == (16000,) for c in received)
