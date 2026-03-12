"""Shared data models for the transcription server."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ServerState(Enum):
    """Possible states of the transcription server."""

    RECORDING = "recording"
    PAUSED = "paused"
    STOPPED = "stopped"
    PROCESSING = "processing"


@dataclass
class Segment:
    """A single transcription segment with optional speaker attribution."""

    id: str
    start: float
    end: float
    text: str
    speaker_id: Optional[str] = None
    speaker_name: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "speaker_id": self.speaker_id,
            "speaker_name": self.speaker_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Segment:
        return cls(
            id=data["id"],
            start=data["start"],
            end=data["end"],
            text=data["text"],
            speaker_id=data.get("speaker_id"),
            speaker_name=data.get("speaker_name"),
        )


@dataclass
class TranscriptionResult:
    """Result of a transcription operation."""

    segments: list[Segment] = field(default_factory=list)
    audio_duration: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "segments": [s.to_dict() for s in self.segments],
            "audio_duration": self.audio_duration,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TranscriptionResult:
        return cls(
            segments=[Segment.from_dict(s) for s in data.get("segments", [])],
            audio_duration=data.get("audio_duration", 0.0),
        )


@dataclass
class DiarizationResult:
    """Result of a diarization pass over recorded audio.

    Each revision represents a complete re-run of the diarization pipeline;
    the speaker_timeline lists (speaker_id, start_seconds, end_seconds) tuples
    covering the full audio duration.
    """

    revision: int = 0
    speaker_timeline: list[tuple[str, float, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "speaker_timeline": [
                {"speaker_id": sid, "start": s, "end": e}
                for sid, s, e in self.speaker_timeline
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiarizationResult:
        timeline = [
            (entry["speaker_id"], entry["start"], entry["end"])
            for entry in data.get("speaker_timeline", [])
        ]
        return cls(
            revision=data.get("revision", 0),
            speaker_timeline=timeline,
        )


# ---------------------------------------------------------------------------
# Recognized WebSocket message types
# ---------------------------------------------------------------------------
# Existing:
#   "segments"             – transcription segments update
#   "status"               – server state change
# New (M2 – diarization):
#   "diarization_update"   – updated speaker timeline from diarization pipeline
#   "label_speaker"        – client request to rename / label a speaker

WS_MSG_SEGMENTS = "segments"
WS_MSG_STATUS = "status"
WS_MSG_DIARIZATION_UPDATE = "diarization_update"
WS_MSG_LABEL_SPEAKER = "label_speaker"

# Assistant message types (Sprint 1)
WS_MSG_ASSISTANT_SUMMARY = "assistant_summary"
WS_MSG_ASSISTANT_ACTION_ITEMS = "assistant_action_items"
WS_MSG_ASSISTANT_STATUS = "assistant_status"
WS_MSG_ASSISTANT_TOPIC_CHANGE = "assistant_topic_change"


@dataclass
class WSMessage:
    """WebSocket message with JSON serialization."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "data": self.data})

    @classmethod
    def from_json(cls, json_str: str) -> WSMessage:
        parsed = json.loads(json_str)
        return cls(type=parsed["type"], data=parsed.get("data", {}))
