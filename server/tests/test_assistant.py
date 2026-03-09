"""Tests for the Assistant pipeline stage — summary and action item extraction."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.assistant import (
    Assistant,
    AssistantConfig,
    MeetingSummary,
    ActionItem,
    WS_MSG_ASSISTANT_SUMMARY,
    WS_MSG_ASSISTANT_ACTION_ITEMS,
    WS_MSG_ASSISTANT_STATUS,
)
from src.models import Segment, WSMessage
from src.ollama_client import ChatResponse, OllamaHealth


def make_segments(count: int = 5, start_time: float = 0.0, interval: float = 30.0) -> list[Segment]:
    """Create test segments spread over time."""
    segments = []
    for i in range(count):
        t = start_time + i * interval
        segments.append(Segment(
            id=f"seg_{i+1:03d}",
            start=t,
            end=t + interval - 1,
            text=f"Test segment {i+1} content here.",
            speaker_id=f"SPEAKER_{i % 2:02d}",
            speaker_name=f"Speaker {i % 2}",
        ))
    return segments


@pytest.fixture
def config():
    return AssistantConfig(
        enabled=True,
        ollama_url="http://localhost:11434",
        window_seconds=120,
        overlap_seconds=30,
    )


@pytest.fixture
def broadcast_mock():
    return AsyncMock()


@pytest.fixture
def assistant(config, broadcast_mock):
    return Assistant(config=config, broadcast=broadcast_mock)


class TestAssistantConfig:
    def test_defaults(self):
        cfg = AssistantConfig()
        assert cfg.enabled is True
        assert cfg.window_seconds == 180
        assert cfg.overlap_seconds == 60

    def test_disabled(self):
        cfg = AssistantConfig(enabled=False)
        assert cfg.enabled is False


class TestMeetingSummary:
    def test_to_ws_data(self):
        summary = MeetingSummary(
            summary="They discussed testing.",
            session=1,
            timestamp=1000.0,
            window_start=0.0,
            window_end=180.0,
        )
        data = summary.to_ws_data()
        assert data["summary"] == "They discussed testing."
        assert data["session"] == 1
        assert data["window_start"] == 0.0
        assert data["window_end"] == 180.0


class TestActionItem:
    def test_to_dict(self):
        item = ActionItem(text="Fix the bug", assignee="Thomas", source_segment_id="seg_001")
        d = item.to_dict()
        assert d["text"] == "Fix the bug"
        assert d["assignee"] == "Thomas"

    def test_to_dict_no_assignee(self):
        item = ActionItem(text="Review PR")
        d = item.to_dict()
        assert d["assignee"] is None


class TestAssistantStart:
    @pytest.mark.asyncio
    async def test_start_disabled(self, broadcast_mock):
        config = AssistantConfig(enabled=False)
        assistant = Assistant(config=config, broadcast=broadcast_mock)
        result = await assistant.start()
        assert result is False

    @pytest.mark.asyncio
    async def test_start_ollama_ready(self, assistant, broadcast_mock):
        health = OllamaHealth(reachable=True, preferred_model="phi4-mini:latest")

        with patch.object(assistant._ollama, 'check_health', return_value=health):
            result = await assistant.start()
            assert result is True
            assert assistant._ready is True

        # Should broadcast ready status
        broadcast_mock.assert_called()
        msg = broadcast_mock.call_args[0][0]
        assert msg.type == WS_MSG_ASSISTANT_STATUS
        assert msg.data["status"] == "ready"

    @pytest.mark.asyncio
    async def test_start_ollama_unavailable(self, assistant, broadcast_mock):
        health = OllamaHealth(reachable=False, error="connection refused")

        with patch.object(assistant._ollama, 'check_health', return_value=health):
            result = await assistant.start()
            assert result is False
            assert assistant._ready is False

        msg = broadcast_mock.call_args[0][0]
        assert msg.data["status"] == "unavailable"


class TestAssistantFeedSegments:
    @pytest.mark.asyncio
    async def test_feed_ignores_when_not_ready(self, assistant):
        """Segments are silently dropped if assistant hasn't started."""
        assistant._ready = False
        segments = make_segments(5)
        assistant.feed_segments(segments)
        assert len(assistant._segments) == 0

    @pytest.mark.asyncio
    async def test_feed_accumulates_segments(self, assistant):
        assistant._ready = True
        segments = make_segments(3)
        assistant.feed_segments(segments)
        assert len(assistant._segments) == 3

    @pytest.mark.asyncio
    async def test_feed_triggers_analysis_at_window(self, assistant, broadcast_mock):
        """Analysis should trigger when accumulated time >= window_seconds."""
        assistant._ready = True
        assistant._config.window_seconds = 100

        # Feed segments spanning 150 seconds — should trigger analysis
        segments = make_segments(6, start_time=0.0, interval=30.0)

        with patch.object(assistant, '_run_analysis', new_callable=AsyncMock) as mock_analysis:
            assistant.feed_segments(segments)
            # Give the scheduled task a moment to start
            await asyncio.sleep(0.05)
            mock_analysis.assert_called_once()


class TestAssistantAnalysis:
    @pytest.mark.asyncio
    async def test_format_segments(self, assistant):
        segments = make_segments(2)
        text = assistant._format_segments(segments)
        assert "Speaker 0:" in text
        assert "Speaker 1:" in text
        assert "Test segment 1" in text

    @pytest.mark.asyncio
    async def test_parse_json_response_clean(self, assistant):
        content = '{"summary": "test", "key_points": ["a"]}'
        result = Assistant._parse_json_response(content)
        assert result["summary"] == "test"

    @pytest.mark.asyncio
    async def test_parse_json_response_fenced(self, assistant):
        content = '```json\n{"summary": "fenced"}\n```'
        result = Assistant._parse_json_response(content)
        assert result["summary"] == "fenced"

    @pytest.mark.asyncio
    async def test_parse_json_response_with_preamble(self, assistant):
        content = 'Here is the JSON:\n{"summary": "embedded"}\nDone.'
        result = Assistant._parse_json_response(content)
        assert result["summary"] == "embedded"

    @pytest.mark.asyncio
    async def test_parse_json_response_garbage(self, assistant):
        result = Assistant._parse_json_response("not json at all")
        assert result == {}

    @pytest.mark.asyncio
    async def test_generate_summary(self, assistant, broadcast_mock):
        mock_response = ChatResponse(
            content='{"summary": "They discussed project plans.", "key_points": ["planning"]}',
            model="phi4-mini",
        )

        with patch.object(assistant._ollama, 'chat', return_value=mock_response):
            summary = await assistant._generate_summary("segment text", 0.0, 180.0)

        assert summary.summary == "They discussed project plans."
        assert summary.window_start == 0.0
        assert summary.window_end == 180.0

    @pytest.mark.asyncio
    async def test_extract_action_items(self, assistant):
        mock_response = ChatResponse(
            content=json.dumps({
                "action_items": [
                    {"text": "Fix the bug", "assignee": "Thomas", "segment_id": "seg_001"},
                    {"text": "Review PR", "assignee": None, "segment_id": None},
                ]
            }),
            model="phi4-mini",
        )

        with patch.object(assistant._ollama, 'chat', return_value=mock_response):
            items = await assistant._extract_action_items("segment text")

        assert len(items) == 2
        assert items[0].text == "Fix the bug"
        assert items[0].assignee == "Thomas"
        assert items[1].text == "Review PR"
        assert items[1].assignee is None

    @pytest.mark.asyncio
    async def test_extract_action_items_empty(self, assistant):
        mock_response = ChatResponse(
            content='{"action_items": []}',
            model="phi4-mini",
        )

        with patch.object(assistant._ollama, 'chat', return_value=mock_response):
            items = await assistant._extract_action_items("segment text")

        assert items == []


class TestAssistantStop:
    @pytest.mark.asyncio
    async def test_stop_cleans_up(self, assistant):
        with patch.object(assistant._ollama, 'close', new_callable=AsyncMock) as mock_close:
            await assistant.stop()
            mock_close.assert_called_once()
