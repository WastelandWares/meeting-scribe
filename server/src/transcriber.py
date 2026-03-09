"""Thin wrapper around faster-whisper for speech-to-text transcription.

Supports standard Whisper models (tiny, base, small, medium, large-v3)
and NVIDIA Parakeet CTC models via BatchedInferencePipeline.

Device auto-detection: prefers CUDA > MPS (Apple Silicon) > CPU.
"""

from __future__ import annotations

import logging
import platform

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


def _detect_device() -> tuple[str, str]:
    """Auto-detect the best available compute device.

    Returns (device, compute_type) tuple.
    Priority: CUDA (float16) > MPS (float32) > CPU (int8).

    Note: CTranslate2 (used by faster-whisper) doesn't support MPS natively,
    but WhisperModel can use 'auto' device which falls through to CPU.
    For actual MPS acceleration, torch-based whisper would be needed.
    We still detect and log it for future-proofing.
    """
    # Check CUDA
    try:
        import ctranslate2
        if "cuda" in ctranslate2.get_supported_compute_types("cuda"):
            logger.info("CUDA detected — using GPU acceleration")
            return "cuda", "float16"
    except Exception:
        pass

    # Check Apple Silicon MPS availability
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        try:
            import torch
            if torch.backends.mps.is_available():
                logger.info("Apple Silicon MPS available — using float32 (CTranslate2 runs on CPU, torch ops use MPS)")
                # CTranslate2 doesn't support MPS directly, but we use float32
                # for better quality on Apple Silicon's fast FP32 units
                return "cpu", "float32"
        except ImportError:
            pass
        # Even without torch, Apple Silicon benefits from float32 over int8
        logger.info("Apple Silicon detected — using float32 compute for better quality")
        return "cpu", "float32"

    logger.info("Using CPU with int8 quantization")
    return "cpu", "int8"


class Transcriber:
    """Load a faster-whisper model and transcribe audio arrays.

    Supports both Whisper encoder-decoder models and NVIDIA Parakeet
    CTC/TDT models. Parakeet models offer better punctuation, grammar,
    and are significantly faster on CPU.

    Device selection:
        - CUDA GPUs: float16 for speed
        - Apple Silicon (M1/M2/M3): float32 for quality (CTranslate2 CPU path)
        - Other CPU: int8 quantization for memory efficiency

    Model options:
        Standard Whisper:  tiny, base, small, medium, large-v3
        Parakeet:          parakeet (alias for nvidia/parakeet-tdt-0.6b-v2)
                           parakeet-ctc (alias for nvidia/parakeet-ctc-1.1b)
    """

    def __init__(self, model_size: str = "base", device: str | None = None) -> None:
        # Resolve aliases
        self.model_name = MODEL_ALIASES.get(model_size, model_size)
        self.is_batched = self.model_name in BATCHED_MODELS

        # Auto-detect device or use explicit override
        if device is not None:
            self.device = device
            self.compute_type = "float16" if device == "cuda" else "float32" if device == "mps" else "int8"
        else:
            self.device, self.compute_type = _detect_device()

        logger.info(
            "Loading transcription model: %s (device=%s, compute=%s)%s",
            self.model_name,
            self.device,
            self.compute_type,
            " [Parakeet/Batched]" if self.is_batched else "",
        )

        if self.is_batched:
            # Parakeet models use BatchedInferencePipeline
            self.model = WhisperModel(
                self.model_name, device=self.device, compute_type=self.compute_type,
            )
            self.pipeline = BatchedInferencePipeline(model=self.model)
        else:
            self.model = WhisperModel(
                self.model_name, device=self.device, compute_type=self.compute_type,
            )
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
