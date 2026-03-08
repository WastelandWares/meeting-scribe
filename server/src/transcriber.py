"""Thin wrapper around faster-whisper for speech-to-text transcription."""

from __future__ import annotations

import numpy as np
from faster_whisper import WhisperModel

from src.models import Segment, TranscriptionResult


class Transcriber:
    """Load a faster-whisper model and transcribe audio arrays."""

    def __init__(self, model_size: str = "base") -> None:
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe(
        self, audio: np.ndarray, sr: int = 16000
    ) -> TranscriptionResult:
        """Transcribe an audio numpy array and return a TranscriptionResult.

        Parameters
        ----------
        audio:
            Mono audio samples.  Converted to float32 if needed.
        sr:
            Sample rate (default 16 000 Hz, what Whisper expects).
        """
        audio = audio.astype(np.float32, copy=False)

        segments_gen, info = self.model.transcribe(audio, beam_size=5)

        segments: list[Segment] = []
        for idx, fw_seg in enumerate(segments_gen, start=1):
            segments.append(
                Segment(
                    id=f"seg_{idx:03d}",
                    start=fw_seg.start,
                    end=fw_seg.end,
                    text=fw_seg.text,
                )
            )

        return TranscriptionResult(
            segments=segments,
            audio_duration=info.duration,
        )
