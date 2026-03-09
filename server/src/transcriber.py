"""Thin wrapper around faster-whisper for speech-to-text transcription.

Supports standard Whisper models (tiny, base, small, medium, large-v3)
and NVIDIA Parakeet CTC models via BatchedInferencePipeline.
"""

from __future__ import annotations

import logging

import numpy as np
from faster_whisper import WhisperModel, BatchedInferencePipeline

from src.models import Segment, TranscriptionResult

logger = logging.getLogger(__name__)

# Known model aliases for convenience
MODEL_ALIASES: dict[str, str] = {
    "parakeet": "nvidia/parakeet-tdt-0.6b-v2",
    "parakeet-v2": "nvidia/parakeet-tdt-0.6b-v2",
    "parakeet-ctc": "nvidia/parakeet-ctc-1.1b",
}

# Models that need BatchedInferencePipeline (CTC/TDT architecture)
BATCHED_MODELS = {"nvidia/parakeet-tdt-0.6b-v2", "nvidia/parakeet-ctc-1.1b"}


class Transcriber:
    """Load a faster-whisper model and transcribe audio arrays.

    Supports both Whisper encoder-decoder models and NVIDIA Parakeet
    CTC/TDT models. Parakeet models offer better punctuation, grammar,
    and are significantly faster on CPU.

    Model options:
        Standard Whisper:  tiny, base, small, medium, large-v3
        Parakeet:          parakeet (alias for nvidia/parakeet-tdt-0.6b-v2)
                           parakeet-ctc (alias for nvidia/parakeet-ctc-1.1b)
    """

    def __init__(self, model_size: str = "base") -> None:
        # Resolve aliases
        self.model_name = MODEL_ALIASES.get(model_size, model_size)
        self.is_batched = self.model_name in BATCHED_MODELS

        logger.info(
            "Loading transcription model: %s%s",
            self.model_name,
            " (Parakeet/BatchedInference)" if self.is_batched else "",
        )

        if self.is_batched:
            # Parakeet models use BatchedInferencePipeline
            self.model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            self.pipeline = BatchedInferencePipeline(model=self.model)
        else:
            self.model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            self.pipeline = None

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

        if self.pipeline is not None:
            # BatchedInferencePipeline for Parakeet models
            segments_gen, info = self.pipeline.transcribe(audio, batch_size=16)
        else:
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
