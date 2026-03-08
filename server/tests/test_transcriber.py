"""Tests for the Transcriber wrapper around faster-whisper."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.models import Segment, TranscriptionResult


# ---------------------------------------------------------------------------
# Helpers – fake faster-whisper segment objects
# ---------------------------------------------------------------------------

def _make_fw_segment(start: float, end: float, text: str):
    """Return an object that mimics a faster-whisper Segment namedtuple."""
    return SimpleNamespace(start=start, end=end, text=text)


FAKE_SEGMENTS = [
    _make_fw_segment(0.0, 2.5, "Hello everyone."),
    _make_fw_segment(2.5, 5.0, "Welcome to the meeting."),
    _make_fw_segment(5.0, 8.3, "Let's get started."),
]

FAKE_INFO = SimpleNamespace(duration=8.3)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTranscriberInit:
    """M1-T2: Transcriber instantiation."""

    @patch("src.transcriber.WhisperModel")
    def test_transcriber_init(self, mock_whisper_cls):
        from src.transcriber import Transcriber

        t = Transcriber("base")
        mock_whisper_cls.assert_called_once_with(
            "base", device="cpu", compute_type="int8"
        )
        assert t is not None


class TestTranscribe:
    """M1-T2: Transcriber.transcribe() behaviour."""

    @patch("src.transcriber.WhisperModel")
    def test_transcribe_returns_result(self, mock_whisper_cls):
        from src.transcriber import Transcriber

        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter(FAKE_SEGMENTS), FAKE_INFO)
        mock_whisper_cls.return_value = mock_model

        t = Transcriber("base")
        audio = np.random.randn(16000 * 9).astype(np.float32)
        result = t.transcribe(audio, sr=16000)

        assert isinstance(result, TranscriptionResult)
        assert len(result.segments) == 3
        assert result.audio_duration == pytest.approx(8.3)

    @patch("src.transcriber.WhisperModel")
    def test_segments_have_valid_timestamps(self, mock_whisper_cls):
        from src.transcriber import Transcriber

        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter(FAKE_SEGMENTS), FAKE_INFO)
        mock_whisper_cls.return_value = mock_model

        t = Transcriber("base")
        audio = np.random.randn(16000 * 9).astype(np.float32)
        result = t.transcribe(audio, sr=16000)

        for seg in result.segments:
            assert seg.start >= 0, f"start must be >= 0, got {seg.start}"
            assert seg.start < seg.end, (
                f"start ({seg.start}) must be < end ({seg.end})"
            )

    @patch("src.transcriber.WhisperModel")
    def test_empty_audio_returns_empty(self, mock_whisper_cls):
        from src.transcriber import Transcriber

        mock_model = MagicMock()
        empty_info = SimpleNamespace(duration=0.0)
        mock_model.transcribe.return_value = (iter([]), empty_info)
        mock_whisper_cls.return_value = mock_model

        t = Transcriber("base")
        audio = np.array([], dtype=np.float32)
        result = t.transcribe(audio, sr=16000)

        assert isinstance(result, TranscriptionResult)
        assert result.segments == []

    @patch("src.transcriber.WhisperModel")
    def test_segment_ids_sequential(self, mock_whisper_cls):
        from src.transcriber import Transcriber

        mock_model = MagicMock()
        mock_model.transcribe.return_value = (iter(FAKE_SEGMENTS), FAKE_INFO)
        mock_whisper_cls.return_value = mock_model

        t = Transcriber("base")
        audio = np.random.randn(16000 * 9).astype(np.float32)
        result = t.transcribe(audio, sr=16000)

        expected_ids = ["seg_001", "seg_002", "seg_003"]
        actual_ids = [s.id for s in result.segments]
        assert actual_ids == expected_ids
