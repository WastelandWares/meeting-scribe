"""Tests for the Diarizer class and assign_speakers function."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.diarizer import Diarizer, assign_speakers
from src.models import DiarizationResult, Segment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_pipeline():
    """Return a mock pyannote Pipeline factory and its instance."""
    mock_pipeline_instance = MagicMock()

    # Build a fake Annotation whose itertracks yields (turn, track, speaker)
    fake_turn_1 = MagicMock()
    fake_turn_1.start = 0.0
    fake_turn_1.end = 2.5
    fake_turn_2 = MagicMock()
    fake_turn_2.start = 2.5
    fake_turn_2.end = 5.0

    fake_annotation = MagicMock()
    fake_annotation.itertracks.return_value = [
        (fake_turn_1, "A", "SPEAKER_00"),
        (fake_turn_2, "B", "SPEAKER_01"),
    ]

    # Pipeline call returns a DiarizeOutput-like object with .speaker_diarization
    fake_result = MagicMock()
    fake_result.speaker_diarization = fake_annotation
    mock_pipeline_instance.return_value = fake_result

    # .to() should return self so MPS/CUDA path doesn't break the mock
    mock_pipeline_instance.to.return_value = mock_pipeline_instance

    mock_from_pretrained = MagicMock(return_value=mock_pipeline_instance)
    return mock_from_pretrained


# ---------------------------------------------------------------------------
# Tests — Diarizer
# ---------------------------------------------------------------------------


class TestDiarizerInit:
    def test_diarizer_init(self):
        """Diarizer(hf_token) creates an instance with token stored."""
        d = Diarizer(hf_token="hf_test_token")
        assert d._hf_token == "hf_test_token"
        assert d._pipeline is None  # lazy — not loaded yet
        assert d._revision == 0


class TestAccumulate:
    def test_accumulate_grows_buffer(self):
        """accumulate(chunk) appends to internal buffer."""
        d = Diarizer(hf_token="hf_test")
        assert len(d._chunks) == 0

        chunk1 = np.zeros(1600, dtype=np.int16)
        chunk2 = np.ones(1600, dtype=np.int16)

        d.accumulate(chunk1)
        assert len(d._chunks) == 1

        d.accumulate(chunk2)
        assert len(d._chunks) == 2


class TestRunDiarization:
    @patch("src.diarizer.DiarizationPipeline")
    def test_run_diarization_returns_result(self, mock_pipeline_cls):
        """run_diarization returns a DiarizationResult with timeline entries."""
        mock_pipeline_cls.from_pretrained = _make_mock_pipeline()

        d = Diarizer(hf_token="hf_test")
        d.accumulate(np.zeros(16000, dtype=np.int16))

        result = asyncio.get_event_loop().run_until_complete(d.run_diarization())

        assert isinstance(result, DiarizationResult)
        assert result.revision == 1
        assert len(result.speaker_timeline) == 2
        assert result.speaker_timeline[0] == ("SPEAKER_00", 0.0, 2.5)
        assert result.speaker_timeline[1] == ("SPEAKER_01", 2.5, 5.0)

    @patch("src.diarizer.DiarizationPipeline")
    def test_revision_increments(self, mock_pipeline_cls):
        """Each run_diarization() call increments revision."""
        mock_pipeline_cls.from_pretrained = _make_mock_pipeline()

        d = Diarizer(hf_token="hf_test")
        d.accumulate(np.zeros(16000, dtype=np.int16))

        loop = asyncio.get_event_loop()
        r1 = loop.run_until_complete(d.run_diarization())
        r2 = loop.run_until_complete(d.run_diarization())

        assert r1.revision == 1
        assert r2.revision == 2

    def test_empty_buffer_returns_empty(self):
        """run_diarization on empty buffer returns empty timeline."""
        d = Diarizer(hf_token="hf_test")

        result = asyncio.get_event_loop().run_until_complete(d.run_diarization())

        assert isinstance(result, DiarizationResult)
        assert result.speaker_timeline == []
        assert result.revision == 1


# ---------------------------------------------------------------------------
# Tests — assign_speakers
# ---------------------------------------------------------------------------


class TestAssignSpeakers:
    def test_assign_by_max_overlap(self):
        """Speaker with maximum time overlap is assigned to each segment."""
        segments = [
            Segment(id="s1", start=0.0, end=2.0, text="Hello"),
            Segment(id="s2", start=2.0, end=5.0, text="World"),
        ]
        diarization = DiarizationResult(
            revision=1,
            speaker_timeline=[
                ("SPEAKER_00", 0.0, 2.5),
                ("SPEAKER_01", 2.5, 5.0),
            ],
        )

        result = assign_speakers(segments, diarization)

        assert result[0].speaker_id == "SPEAKER_00"
        assert result[1].speaker_id == "SPEAKER_01"

    def test_assign_with_labels(self):
        """When labels dict provided, speaker_name is set."""
        segments = [
            Segment(id="s1", start=0.0, end=2.0, text="Hello"),
        ]
        diarization = DiarizationResult(
            revision=1,
            speaker_timeline=[("SPEAKER_00", 0.0, 3.0)],
        )
        labels = {"SPEAKER_00": "Alice"}

        result = assign_speakers(segments, diarization, labels=labels)

        assert result[0].speaker_id == "SPEAKER_00"
        assert result[0].speaker_name == "Alice"

    def test_assign_empty_diarization(self):
        """Empty diarization leaves speaker_id as None."""
        segments = [
            Segment(id="s1", start=0.0, end=2.0, text="Hello"),
        ]
        diarization = DiarizationResult(revision=1, speaker_timeline=[])

        result = assign_speakers(segments, diarization)

        assert result[0].speaker_id is None
