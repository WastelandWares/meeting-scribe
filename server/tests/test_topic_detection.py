"""Tests for topic detection in the assistant."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.assistant import (
    Assistant,
    AssistantConfig,
    TopicChange,
    WS_MSG_ASSISTANT_TOPIC_CHANGE,
)
from src.models import Segment, WSMessage
from src.ollama_client import ChatResponse, OllamaHealth


def make_segments(count=5, start_time=0.0, interval=30.0):
    segments = []
    for i in range(count):
        t = start_time + i * interval
        segments.append(Segment(
            id=f"seg_{i+1:03d}",
            start=t,
            end=t + interval - 1,
            text=f"Test segment {i+1}",
            speaker_id=f"SPEAKER_{i % 2:02d}",
            speaker_name=f"Speaker {i % 2}",
        ))
    return segments


class TestTopicChange:
    def test_to_dict(self):
        tc = TopicChange(
            new_topic="API Design",
            previous_topic="Requirements",
            timestamp=120.0,
            confidence=0.85,
        )
        d = tc.to_dict()
        assert d["new_topic"] == "API Design"
        assert d["previous_topic"] == "Requirements"
        assert d["timestamp"] == 120.0
        assert d["confidence"] == 0.85

    def test_to_dict_no_previous(self):
        tc = TopicChange(new_topic="Intro", timestamp=0.0)
        d = tc.to_dict()
        assert d["previous_topic"] is None


class TestTopicDetection:
    @pytest.fixture
    def config(self):
        return AssistantConfig(
            enabled=True,
            ollama_url="http://localhost:11434",
            window_seconds=120,
            overlap_seconds=30,
        )

    @pytest.fixture
    def broadcast_mock(self):
        return AsyncMock()

    @pytest.fixture
    def assistant(self, config, broadcast_mock):
        return Assistant(config=config, broadcast=broadcast_mock)

    @pytest.mark.asyncio
    async def test_detect_topic_first_time(self, assistant):
        """First topic detection sets current topic but returns None (no change)."""
        mock_response = ChatResponse(
            content=json.dumps({
                "current_topic": "Project kickoff",
                "topic_changed": False,
                "confidence": 0.9,
            }),
            model="phi4-mini",
        )

        with patch.object(assistant._ollama, 'chat', return_value=mock_response):
            result = await assistant._detect_topic("segment text", 0.0)

        assert result is None  # No change on first detection
        assert assistant._current_topic == "Project kickoff"

    @pytest.mark.asyncio
    async def test_detect_topic_change(self, assistant):
        """Topic change returns a TopicChange object."""
        assistant._current_topic = "Requirements"

        mock_response = ChatResponse(
            content=json.dumps({
                "current_topic": "API Design",
                "topic_changed": True,
                "confidence": 0.85,
            }),
            model="phi4-mini",
        )

        with patch.object(assistant._ollama, 'chat', return_value=mock_response):
            result = await assistant._detect_topic("segment text", 120.0)

        assert result is not None
        assert result.new_topic == "API Design"
        assert result.previous_topic == "Requirements"
        assert assistant._current_topic == "API Design"
        assert len(assistant._topic_history) == 1

    @pytest.mark.asyncio
    async def test_detect_topic_no_change(self, assistant):
        """Same topic returns None."""
        assistant._current_topic = "Requirements"

        mock_response = ChatResponse(
            content=json.dumps({
                "current_topic": "Requirements",
                "topic_changed": False,
                "confidence": 0.9,
            }),
            model="phi4-mini",
        )

        with patch.object(assistant._ollama, 'chat', return_value=mock_response):
            result = await assistant._detect_topic("segment text", 120.0)

        assert result is None
        assert assistant._current_topic == "Requirements"

    @pytest.mark.asyncio
    async def test_detect_topic_empty_response(self, assistant):
        """Empty topic in response returns None."""
        mock_response = ChatResponse(
            content='{"current_topic": "", "topic_changed": false}',
            model="phi4-mini",
        )

        with patch.object(assistant._ollama, 'chat', return_value=mock_response):
            result = await assistant._detect_topic("segment text", 0.0)

        assert result is None

    @pytest.mark.asyncio
    async def test_topic_history_accumulates(self, assistant):
        """Multiple topic changes build up history."""
        topics = [
            ("Requirements", False),
            ("API Design", True),
            ("Database Schema", True),
        ]

        for topic, changed in topics:
            mock_response = ChatResponse(
                content=json.dumps({
                    "current_topic": topic,
                    "topic_changed": changed,
                    "confidence": 0.8,
                }),
                model="phi4-mini",
            )
            with patch.object(assistant._ollama, 'chat', return_value=mock_response):
                await assistant._detect_topic("text", 0.0)

        assert len(assistant._topic_history) == 2  # Two changes (first was not a change)
        assert assistant._current_topic == "Database Schema"
