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


# NOTE: DiarizationResult will be added in M2.


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
