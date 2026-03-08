#!/usr/bin/env python3
"""Post-hoc meeting transcription CLI (M0).

Records audio from the microphone, then runs Whisper transcription and
pyannote diarization to produce a speaker-labeled markdown transcript.

Usage:
    python transcribe.py [--model base] [--output meeting.md] [--device 0]

Press Ctrl+C to stop recording. The transcript is generated after
recording ends.
"""

from __future__ import annotations

import argparse
import datetime
import io
import os
import signal
import sys
import wave
from typing import Optional

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SAMPLE_RATE = 16_000  # 16 kHz mono – what Whisper expects
CHANNELS = 1
DTYPE = "int16"

# ---------------------------------------------------------------------------
# Audio recording
# ---------------------------------------------------------------------------


def record_audio(device: Optional[int] = None) -> np.ndarray:
    """Record from the microphone until Ctrl+C is pressed.

    Returns the recorded audio as a numpy int16 array.
    """
    print("Recording… press Ctrl+C to stop.\n")

    frames: list[np.ndarray] = []
    stop_event = False

    def _callback(indata, frame_count, time_info, status):  # noqa: ARG001
        if status:
            print(f"  ⚠ sounddevice status: {status}", file=sys.stderr)
        frames.append(indata.copy())

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype=DTYPE,
        device=device,
        callback=_callback,
    )

    # Use a flag + signal handler so we can stop cleanly.
    def _sigint_handler(sig, frame):  # noqa: ARG001
        nonlocal stop_event
        stop_event = True

    prev_handler = signal.signal(signal.SIGINT, _sigint_handler)

    stream.start()
    try:
        while not stop_event:
            sd.sleep(100)  # 100 ms ticks
    finally:
        stream.stop()
        stream.close()
        signal.signal(signal.SIGINT, prev_handler)

    if not frames:
        print("No audio captured.", file=sys.stderr)
        sys.exit(1)

    audio = np.concatenate(frames, axis=0).flatten()
    duration = len(audio) / SAMPLE_RATE
    print(f"\nCaptured {duration:.1f}s of audio.")
    return audio


def audio_to_wav_bytes(audio: np.ndarray) -> bytes:
    """Encode int16 audio as an in-memory WAV file."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)  # int16 = 2 bytes
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Transcription (faster-whisper)
# ---------------------------------------------------------------------------


def transcribe(audio: np.ndarray, model_name: str) -> list[dict]:
    """Run Whisper on the audio and return segments with timestamps.

    Each segment dict has keys: start, end, text.
    """
    print(f"Loading Whisper model '{model_name}'…")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")

    # faster-whisper accepts float32 in [-1, 1]
    audio_f32 = audio.astype(np.float32) / 32768.0

    print("Transcribing…")
    segments_iter, _info = model.transcribe(audio_f32, beam_size=5)

    segments = []
    for seg in segments_iter:
        segments.append(
            {"start": seg.start, "end": seg.end, "text": seg.text.strip()}
        )

    print(f"  {len(segments)} segment(s) transcribed.")
    return segments


# ---------------------------------------------------------------------------
# Diarization (pyannote)
# ---------------------------------------------------------------------------


def diarize(wav_bytes: bytes) -> list[dict]:
    """Run pyannote speaker diarization on the audio.

    Returns a list of dicts with keys: start, end, speaker.
    """
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        print(
            "WARNING: HF_TOKEN not set. pyannote diarization requires a "
            "HuggingFace token with access to pyannote models.\n"
            "  Set it:  export HF_TOKEN='hf_...'\n"
            "  Accept terms at:\n"
            "    https://huggingface.co/pyannote/speaker-diarization-3.1\n"
            "    https://huggingface.co/pyannote/segmentation-3.0\n",
            file=sys.stderr,
        )
        return []

    from pyannote.audio import Pipeline as DiarizationPipeline

    print("Loading diarization pipeline…")
    pipeline = DiarizationPipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        token=hf_token,
    )

    # Load audio as waveform dict to avoid torchcodec dependency
    import torch
    import torchaudio

    wav_buf = io.BytesIO(wav_bytes)
    waveform, sample_rate = torchaudio.load(wav_buf)
    audio_input = {"waveform": waveform, "sample_rate": sample_rate}

    print("Diarizing…")
    diarization = pipeline(audio_input)

    turns: list[dict] = []
    for turn, _track, speaker in diarization.itertracks(yield_label=True):
        turns.append(
            {"start": turn.start, "end": turn.end, "speaker": speaker}
        )
    print(f"  {len(turns)} diarization turn(s) found.")
    return turns


# ---------------------------------------------------------------------------
# Speaker assignment
# ---------------------------------------------------------------------------


def assign_speakers(
    segments: list[dict], diar_turns: list[dict]
) -> list[dict]:
    """Assign a speaker to each transcription segment by maximum time overlap.

    Mutates each segment dict to add a 'speaker' key. If no diarization
    data is available, assigns 'SPEAKER_00' to everything.
    """
    if not diar_turns:
        for seg in segments:
            seg["speaker"] = "SPEAKER_00"
        return segments

    for seg in segments:
        best_speaker = "SPEAKER_00"
        best_overlap = 0.0
        seg_start, seg_end = seg["start"], seg["end"]

        for turn in diar_turns:
            overlap_start = max(seg_start, turn["start"])
            overlap_end = min(seg_end, turn["end"])
            overlap = max(0.0, overlap_end - overlap_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = turn["speaker"]

        seg["speaker"] = best_speaker

    return segments


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------


def fmt_ts(seconds: float) -> str:
    """Format seconds as MM:SS."""
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def build_markdown(
    segments: list[dict],
    duration: float,
    model_name: str,
    date: str,
) -> str:
    """Build the final markdown string with YAML frontmatter and transcript."""
    # Collect unique speakers
    speakers = sorted({seg["speaker"] for seg in segments})

    # --- YAML frontmatter ---
    lines: list[str] = ["---"]
    lines.append(f"date: {date}")
    lines.append(f"duration: {fmt_ts(duration)}")
    lines.append(f"model: {model_name}")
    lines.append("speakers:")
    for spk in speakers:
        lines.append(f"  - {spk}")
    lines.append("---")
    lines.append("")

    # --- Speaker legend ---
    lines.append("## Speakers")
    lines.append("")
    for spk in speakers:
        lines.append(f"- **{spk}**")
    lines.append("")

    # --- Transcript ---
    lines.append("## Transcript")
    lines.append("")

    # Group consecutive segments from the same speaker
    if segments:
        current_speaker = segments[0]["speaker"]
        group_start = segments[0]["start"]
        group_texts: list[str] = []

        def flush_group():
            ts = fmt_ts(group_start)
            lines.append(f"> **{current_speaker}** [{ts}]")
            lines.append(">")
            for t in group_texts:
                lines.append(f"> {t}")
            lines.append("")

        for seg in segments:
            if seg["speaker"] != current_speaker:
                flush_group()
                current_speaker = seg["speaker"]
                group_start = seg["start"]
                group_texts = []
            group_texts.append(seg["text"])

        flush_group()

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Record and transcribe a meeting with speaker diarization."
    )
    parser.add_argument(
        "--model",
        default="base",
        help="Whisper model size (default: base)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output markdown file (default: transcript_YYYYMMDD_HHMMSS.md)",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Audio input device index (see `python -m sounddevice`)",
    )
    args = parser.parse_args()

    now = datetime.datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    output_path = args.output or now.strftime("transcript_%Y%m%d_%H%M%S.md")

    # 1. Record
    audio = record_audio(device=args.device)
    duration = len(audio) / SAMPLE_RATE

    # 2. Transcribe
    segments = transcribe(audio, args.model)
    if not segments:
        print("No speech detected.", file=sys.stderr)
        sys.exit(1)

    # 3. Diarize
    wav_bytes = audio_to_wav_bytes(audio)
    diar_turns = diarize(wav_bytes)

    # 4. Assign speakers
    assign_speakers(segments, diar_turns)

    # 5. Write markdown
    md = build_markdown(segments, duration, args.model, date_str)
    with open(output_path, "w") as f:
        f.write(md)

    print(f"\nTranscript written to {output_path}")


if __name__ == "__main__":
    main()
