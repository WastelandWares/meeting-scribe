"""AI Assistant pipeline stage for meeting analysis.

Processes transcript segments in batched windows, producing summaries,
action items, and topic insights via a local Ollama LLM.

Sprint 1 stories: #17 (skeleton), #18 (summary), #19 (action items).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Optional

from src.models import Segment, WSMessage
from src.ollama_client import OllamaClient, ChatMessage, ChatResponse

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────

DEFAULT_WINDOW_SECONDS = 180   # 3-minute analysis windows
DEFAULT_OVERLAP_SECONDS = 60   # 1-minute overlap for context continuity
MIN_SEGMENTS_PER_WINDOW = 3    # Don't analyze near-empty windows


@dataclass
class AssistantConfig:
    """Configuration for the assistant pipeline stage."""

    enabled: bool = True
    model: Optional[str] = None
    ollama_url: str = "http://localhost:11434"
    window_seconds: float = DEFAULT_WINDOW_SECONDS
    overlap_seconds: float = DEFAULT_OVERLAP_SECONDS
    temperature: float = 0.3


# ── Output Types ─────────────────────────────────────────

@dataclass
class MeetingSummary:
    """Rolling meeting summary produced by the assistant."""

    summary: str
    session: int
    timestamp: float
    window_start: float
    window_end: float

    def to_ws_data(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "session": self.session,
            "timestamp": self.timestamp,
            "window_start": self.window_start,
            "window_end": self.window_end,
        }


@dataclass
class ActionItem:
    """An extracted action item from the conversation."""

    text: str
    assignee: Optional[str] = None
    source_segment_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "assignee": self.assignee,
            "source_segment_id": self.source_segment_id,
        }


# ── WS Message Types ────────────────────────────────────

WS_MSG_ASSISTANT_SUMMARY = "assistant_summary"
WS_MSG_ASSISTANT_ACTION_ITEMS = "assistant_action_items"
WS_MSG_ASSISTANT_STATUS = "assistant_status"


# ── Prompts ──────────────────────────────────────────────

SYSTEM_PROMPT = """You are a meeting assistant embedded in a live transcription system.
You receive transcript segments from an ongoing meeting and produce structured analysis.

Rules:
- Be concise and factual. Only include what was actually said.
- Use the speakers' names when available (speaker_name field).
- If no speaker is identified, use "Someone" or "A participant".
- Output valid JSON only — no markdown, no explanation outside the JSON.
- Do not hallucinate or infer things not present in the transcript."""

SUMMARY_PROMPT_TEMPLATE = """Analyze these transcript segments and produce a rolling meeting summary.

Previous summary (for context continuity):
{previous_summary}

New transcript segments:
{segments_text}

Respond with JSON:
{{
  "summary": "A concise 2-4 sentence summary of what was discussed in this window, building on the previous summary.",
  "key_points": ["point 1", "point 2"]
}}"""

ACTION_ITEMS_PROMPT_TEMPLATE = """Extract any action items, decisions, or commitments from these transcript segments.
An action item is something someone agreed to do, was asked to do, or a decision that was made.

Transcript segments:
{segments_text}

Respond with JSON:
{{
  "action_items": [
    {{"text": "description of the action item", "assignee": "person name or null", "segment_id": "source segment id or null"}}
  ]
}}

If there are no action items, respond with: {{"action_items": []}}"""


# ── Assistant Service ────────────────────────────────────

class Assistant:
    """Pipeline stage that analyzes transcript segments via Ollama.

    Receives segments from the pipeline, accumulates them into analysis
    windows, and produces summaries + action items.
    """

    def __init__(
        self,
        config: AssistantConfig,
        broadcast: Callable[[WSMessage], Awaitable[None]],
    ) -> None:
        self._config = config
        self._broadcast = broadcast
        self._ollama = OllamaClient(
            base_url=config.ollama_url,
            model=config.model,
        )

        # Segment accumulator
        self._segments: list[Segment] = []
        self._last_analysis_time: float = 0.0
        self._analysis_count: int = 0

        # Rolling state
        self._previous_summary: str = ""
        self._all_action_items: list[ActionItem] = []

        # Background processing
        self._analysis_task: Optional[asyncio.Task] = None
        self._ready = False

    async def start(self) -> bool:
        """Initialize the assistant. Returns True if Ollama is ready."""
        if not self._config.enabled:
            logger.info("Assistant disabled by config")
            return False

        health = await self._ollama.check_health()
        if not health.ready:
            logger.warning(
                "Assistant unavailable — Ollama not ready: %s", health.error
            )
            await self._broadcast(WSMessage(
                type=WS_MSG_ASSISTANT_STATUS,
                data={"status": "unavailable", "error": health.error},
            ))
            return False

        self._ready = True
        logger.info("Assistant ready — model: %s", self._ollama.model)
        await self._broadcast(WSMessage(
            type=WS_MSG_ASSISTANT_STATUS,
            data={"status": "ready", "model": self._ollama.model},
        ))
        return True

    async def stop(self) -> None:
        """Clean up resources."""
        if self._analysis_task and not self._analysis_task.done():
            self._analysis_task.cancel()
            try:
                await self._analysis_task
            except asyncio.CancelledError:
                pass
        await self._ollama.close()
        logger.info("Assistant stopped")

    def feed_segments(self, segments: list[Segment]) -> None:
        """Feed new transcript segments into the accumulator.

        Called by the pipeline whenever new segments arrive.
        Triggers analysis when the window is full.
        """
        if not self._ready:
            return

        self._segments.extend(segments)

        # Check if we have enough data for an analysis window
        if self._should_analyze():
            self._schedule_analysis()
        else:
            # Broadcast countdown so the plugin can show progress
            self._schedule_countdown()

    def _schedule_countdown(self) -> None:
        """Broadcast a countdown message showing time until next analysis."""
        if not self._segments:
            return
        latest = self._segments[-1].end
        time_since_last = latest - self._last_analysis_time
        remaining = max(0, self._config.window_seconds - time_since_last)
        seg_count = len(self._segments)
        asyncio.create_task(self._broadcast(WSMessage(
            type=WS_MSG_ASSISTANT_STATUS,
            data={
                "status": "waiting",
                "countdown_seconds": round(remaining, 0),
                "segments_accumulated": seg_count,
                "window_seconds": self._config.window_seconds,
            },
        )))

    def _should_analyze(self) -> bool:
        """Determine if we have enough accumulated segments for analysis."""
        if len(self._segments) < MIN_SEGMENTS_PER_WINDOW:
            return False

        if not self._segments:
            return False

        # Check time span of accumulated segments
        earliest = self._segments[0].start
        latest = self._segments[-1].end
        span = latest - earliest

        # Only analyze if we've accumulated a full window worth
        time_since_last = latest - self._last_analysis_time
        return time_since_last >= self._config.window_seconds

    def _schedule_analysis(self) -> None:
        """Schedule an analysis task if one isn't already running."""
        if self._analysis_task and not self._analysis_task.done():
            return  # Already analyzing
        self._analysis_task = asyncio.create_task(self._run_analysis())

    async def _run_analysis(self) -> None:
        """Run a full analysis window: summary + action items."""
        try:
            # Snapshot the current segments for this window
            window_segments = list(self._segments)
            if not window_segments:
                return

            window_start = window_segments[0].start
            window_end = window_segments[-1].end
            self._analysis_count += 1

            logger.info(
                "Analysis #%d: %d segments (%.1f–%.1fs)",
                self._analysis_count,
                len(window_segments),
                window_start,
                window_end,
            )

            # Format segments for the LLM
            segments_text = self._format_segments(window_segments)

            # Run summary and action items in parallel
            summary_coro = self._generate_summary(segments_text, window_start, window_end)
            actions_coro = self._extract_action_items(segments_text)

            summary_result, actions_result = await asyncio.gather(
                summary_coro, actions_coro, return_exceptions=True
            )

            # Broadcast results
            if isinstance(summary_result, MeetingSummary):
                self._previous_summary = summary_result.summary
                await self._broadcast(WSMessage(
                    type=WS_MSG_ASSISTANT_SUMMARY,
                    data=summary_result.to_ws_data(),
                ))
                logger.info("Summary broadcast: %s", summary_result.summary[:80])

            elif isinstance(summary_result, Exception):
                logger.error("Summary generation failed: %s", summary_result)

            if isinstance(actions_result, list):
                if actions_result:
                    self._all_action_items.extend(actions_result)
                    await self._broadcast(WSMessage(
                        type=WS_MSG_ASSISTANT_ACTION_ITEMS,
                        data={"items": [a.to_dict() for a in actions_result]},
                    ))
                    logger.info("Action items broadcast: %d items", len(actions_result))

            elif isinstance(actions_result, Exception):
                logger.error("Action item extraction failed: %s", actions_result)

            # Advance the window: keep overlap segments for context
            self._last_analysis_time = window_end
            overlap_start = window_end - self._config.overlap_seconds
            self._segments = [s for s in self._segments if s.start >= overlap_start]

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Analysis failed")

    def _format_segments(self, segments: list[Segment]) -> str:
        """Format segments into readable text for the LLM."""
        lines = []
        for seg in segments:
            speaker = seg.speaker_name or seg.speaker_id or "Unknown"
            time_str = f"[{seg.start:.1f}s]"
            lines.append(f"{time_str} {speaker}: {seg.text.strip()}")
        return "\n".join(lines)

    async def _generate_summary(
        self,
        segments_text: str,
        window_start: float,
        window_end: float,
    ) -> MeetingSummary:
        """Generate a rolling summary from transcript segments."""
        prompt = SUMMARY_PROMPT_TEMPLATE.format(
            previous_summary=self._previous_summary or "(none — this is the start of the meeting)",
            segments_text=segments_text,
        )

        response = await self._ollama.chat(
            messages=[
                ChatMessage(role="system", content=SYSTEM_PROMPT),
                ChatMessage(role="user", content=prompt),
            ],
            temperature=self._config.temperature,
        )

        parsed = self._parse_json_response(response.content)
        summary_text = parsed.get("summary", response.content)

        return MeetingSummary(
            summary=summary_text,
            session=self._analysis_count,
            timestamp=time.time(),
            window_start=window_start,
            window_end=window_end,
        )

    async def _extract_action_items(
        self, segments_text: str
    ) -> list[ActionItem]:
        """Extract action items from transcript segments."""
        prompt = ACTION_ITEMS_PROMPT_TEMPLATE.format(
            segments_text=segments_text,
        )

        response = await self._ollama.chat(
            messages=[
                ChatMessage(role="system", content=SYSTEM_PROMPT),
                ChatMessage(role="user", content=prompt),
            ],
            temperature=self._config.temperature,
        )

        parsed = self._parse_json_response(response.content)
        items = parsed.get("action_items", [])

        return [
            ActionItem(
                text=item.get("text", ""),
                assignee=item.get("assignee"),
                source_segment_id=item.get("segment_id"),
            )
            for item in items
            if item.get("text")
        ]

    @staticmethod
    def _parse_json_response(content: str) -> dict[str, Any]:
        """Attempt to parse JSON from an LLM response, handling common issues."""
        content = content.strip()

        # Strip markdown code fences if present
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            content = "\n".join(lines)

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to find JSON object in the response
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(content[start:end])
                except json.JSONDecodeError:
                    pass
            logger.warning("Failed to parse LLM response as JSON: %s", content[:200])
            return {}
