"""Speaker diarization using pyannote.audio.

Wraps the pyannote speaker-diarization pipeline for incremental use:
audio chunks are accumulated, and diarization is run on the full buffer
each time ``run_diarization`` is called.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import numpy as np
import torch
from pyannote.audio import Pipeline as DiarizationPipeline

from src.models import DiarizationResult, Segment

# Default sample rate — Whisper / capture chain uses 16 kHz mono int16.
_SAMPLE_RATE = 16_000


class Diarizer:
    """Accumulates audio and runs pyannote diarization on demand."""

    def __init__(self, hf_token: str) -> None:
        self._hf_token = hf_token
        self._pipeline: Optional[DiarizationPipeline] = None
        self._chunks: list[np.ndarray] = []
        self._revision: int = 0

    # -- audio accumulation --------------------------------------------------

    def accumulate(self, chunk: np.ndarray) -> None:
        """Append an int16 audio chunk to the internal buffer."""
        self._chunks.append(chunk)

    # -- diarization ---------------------------------------------------------

    def _ensure_pipeline(self) -> None:
        """Lazily load the pyannote pipeline on first use."""
        if self._pipeline is None:
            self._pipeline = DiarizationPipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                token=self._hf_token,
            )

    def _run_sync(self) -> DiarizationResult:
        """Blocking diarization — meant to run in a thread-pool executor."""
        self._revision += 1

        if not self._chunks:
            return DiarizationResult(
                revision=self._revision,
                speaker_timeline=[],
            )

        self._ensure_pipeline()

        # Concatenate all accumulated chunks into one contiguous array.
        audio = np.concatenate(self._chunks)

        # Convert int16 numpy → float32 torch tensor (1 x samples).
        waveform = torch.from_numpy(
            audio.astype(np.float32) / 32768.0
        ).unsqueeze(0)

        result = self._pipeline(
            {"waveform": waveform, "sample_rate": _SAMPLE_RATE}
        )

        timeline: list[tuple[str, float, float]] = []
        for turn, _track, speaker in result.speaker_diarization.itertracks(
            yield_label=True
        ):
            timeline.append((speaker, turn.start, turn.end))

        return DiarizationResult(
            revision=self._revision,
            speaker_timeline=timeline,
        )

    async def run_diarization(self) -> DiarizationResult:
        """Run diarization asynchronously (offloads blocking work to a thread)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._run_sync)


# ---------------------------------------------------------------------------
# Standalone speaker-assignment helper
# ---------------------------------------------------------------------------


def assign_speakers(
    segments: list[Segment],
    diarization: DiarizationResult,
    labels: Optional[dict[str, str]] = None,
) -> list[Segment]:
    """Assign speaker IDs (and optional names) to transcription segments.

    For each segment the diarization timeline entry with the greatest time
    overlap determines the ``speaker_id``.  If *labels* is provided,
    ``speaker_name`` is looked up from it.

    Returns the same list of segments (mutated in-place).
    """
    for seg in segments:
        best_speaker: Optional[str] = None
        best_overlap = 0.0

        for speaker_id, start, end in diarization.speaker_timeline:
            overlap_start = max(seg.start, start)
            overlap_end = min(seg.end, end)
            overlap = max(0.0, overlap_end - overlap_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker_id

        seg.speaker_id = best_speaker

        if labels and best_speaker and best_speaker in labels:
            seg.speaker_name = labels[best_speaker]

    return segments
