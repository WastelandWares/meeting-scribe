"""Tests for assign_speakers() in diarizer module (M2-T4)."""

import pytest

from src.models import DiarizationResult, Segment
from src.diarizer import assign_speakers


# ── helpers ──────────────────────────────────────────────────────────────────

def _seg(id: str, start: float, end: float, text: str = "") -> Segment:
    """Create a Segment with sensible defaults."""
    return Segment(id=id, start=start, end=end, text=text)


def _diar(timeline: list[tuple[str, float, float]]) -> DiarizationResult:
    """Create a DiarizationResult from a speaker timeline."""
    return DiarizationResult(revision=1, speaker_timeline=timeline)


# ── tests ────────────────────────────────────────────────────────────────────


class TestAssignSpeakers:
    def test_correct_speaker_by_overlap(self):
        """Segment overlapping most with SPEAKER_00 gets that ID."""
        segments = [_seg("s1", 0.0, 5.0, "hello")]
        diarization = _diar([
            ("SPEAKER_00", 0.0, 4.0),
            ("SPEAKER_01", 4.0, 6.0),
        ])
        result = assign_speakers(segments, diarization)
        assert result[0].speaker_id == "SPEAKER_00"

    def test_speaker_name_from_labels(self):
        """When labels map is provided, speaker_name is populated."""
        segments = [_seg("s1", 0.0, 3.0, "hi")]
        diarization = _diar([("SPEAKER_00", 0.0, 5.0)])
        labels = {"SPEAKER_00": "Thomas"}
        result = assign_speakers(segments, diarization, labels=labels)
        assert result[0].speaker_id == "SPEAKER_00"
        assert result[0].speaker_name == "Thomas"

    def test_unlabeled_keeps_speaker_id(self):
        """Without labels, speaker_name stays None."""
        segments = [_seg("s1", 1.0, 4.0)]
        diarization = _diar([("SPEAKER_00", 0.0, 5.0)])
        result = assign_speakers(segments, diarization)
        assert result[0].speaker_id == "SPEAKER_00"
        assert result[0].speaker_name is None

    def test_empty_diarization(self):
        """Empty timeline leaves speaker_id as None."""
        segments = [_seg("s1", 0.0, 3.0, "test")]
        diarization = _diar([])
        result = assign_speakers(segments, diarization)
        assert result[0].speaker_id is None
        assert result[0].speaker_name is None

    def test_multiple_segments_different_speakers(self):
        """Two segments overlapping different speakers get different IDs."""
        segments = [
            _seg("s1", 0.0, 3.0, "first speaker"),
            _seg("s2", 5.0, 8.0, "second speaker"),
        ]
        diarization = _diar([
            ("SPEAKER_00", 0.0, 4.0),
            ("SPEAKER_01", 4.0, 10.0),
        ])
        result = assign_speakers(segments, diarization)
        assert result[0].speaker_id == "SPEAKER_00"
        assert result[1].speaker_id == "SPEAKER_01"

    def test_partial_overlap(self):
        """Segment partially overlapping two speakers gets the one with more overlap."""
        # Segment spans 2.0–6.0.
        # SPEAKER_00 covers 0.0–3.5  → overlap = 1.5s  (3.5 - 2.0)
        # SPEAKER_01 covers 3.5–8.0  → overlap = 2.5s  (6.0 - 3.5)
        segments = [_seg("s1", 2.0, 6.0, "overlap test")]
        diarization = _diar([
            ("SPEAKER_00", 0.0, 3.5),
            ("SPEAKER_01", 3.5, 8.0),
        ])
        result = assign_speakers(segments, diarization)
        assert result[0].speaker_id == "SPEAKER_01"
