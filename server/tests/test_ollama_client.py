"""Tests for the Ollama client — health checks, model detection, chat."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ollama_client import (
    ChatMessage,
    ChatResponse,
    OllamaClient,
    OllamaHealth,
    DEFAULT_MODEL,
    PREFERRED_MODELS,
)


@pytest.fixture
def client():
    return OllamaClient(base_url="http://localhost:11434")


@pytest.fixture
def mock_tags_response():
    """Simulated /api/tags response with preferred models."""
    return {
        "models": [
            {"name": "phi4-mini:latest", "size": 2500000000},
            {"name": "gemma3:1b", "size": 1000000000},
            {"name": "mxbai-embed-large:latest", "size": 669000000},
        ]
    }


class TestOllamaHealth:
    def test_ready_when_reachable_and_model(self):
        health = OllamaHealth(reachable=True, preferred_model="phi4-mini:latest")
        assert health.ready is True

    def test_not_ready_when_unreachable(self):
        health = OllamaHealth(reachable=False)
        assert health.ready is False

    def test_not_ready_when_no_model(self):
        health = OllamaHealth(reachable=True, preferred_model=None)
        assert health.ready is False


class TestChatMessage:
    def test_to_dict(self):
        msg = ChatMessage(role="user", content="hello")
        assert msg.to_dict() == {"role": "user", "content": "hello"}


class TestChatResponse:
    def test_tokens_per_second(self):
        resp = ChatResponse(
            content="test",
            model="phi4-mini",
            total_duration_ms=2000,
            eval_count=100,
        )
        assert resp.tokens_per_second == 50.0

    def test_tokens_per_second_zero_duration(self):
        resp = ChatResponse(content="test", model="phi4-mini")
        assert resp.tokens_per_second == 0.0


class TestOllamaClientHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_success(self, client, mock_tags_response):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_tags_response)

        mock_session = make_mock_session(get=MagicMock(return_value=AsyncContextManager(mock_resp)))
        client._session = mock_session

        health = await client.check_health()
        assert health.reachable is True
        assert health.preferred_model == "phi4-mini:latest"
        assert client._active_model == "phi4-mini:latest"
        await client.close()

    @pytest.mark.asyncio
    async def test_health_check_unreachable(self, client):
        import aiohttp

        mock_session = make_mock_session(get=MagicMock(side_effect=aiohttp.ClientError("connection refused")))
        client._session = mock_session

        health = await client.check_health()
        assert health.reachable is False
        assert health.ready is False
        await client.close()

    @pytest.mark.asyncio
    async def test_health_check_no_preferred_model(self, client):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "models": [{"name": "some-random-model:latest"}]
        })

        mock_session = make_mock_session(get=MagicMock(return_value=AsyncContextManager(mock_resp)))
        client._session = mock_session

        health = await client.check_health()
        assert health.reachable is True
        assert health.preferred_model is None
        assert health.ready is False
        await client.close()

    @pytest.mark.asyncio
    async def test_health_check_configured_model(self):
        client = OllamaClient(model="gemma3:1b")

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "models": [
                {"name": "gemma3:1b"},
                {"name": "phi4-mini:latest"},
            ]
        })

        mock_session = make_mock_session(get=MagicMock(return_value=AsyncContextManager(mock_resp)))
        client._session = mock_session

        health = await client.check_health()
        assert health.preferred_model == "gemma3:1b"
        await client.close()


class TestOllamaClientChat:
    @pytest.mark.asyncio
    async def test_chat_success(self, client):
        client._active_model = "phi4-mini:latest"

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "message": {"role": "assistant", "content": "Hello!"},
            "total_duration": 500_000_000,  # 500ms in ns
            "prompt_eval_count": 10,
            "eval_count": 5,
        })

        mock_session = make_mock_session(post=MagicMock(return_value=AsyncContextManager(mock_resp)))
        client._session = mock_session

        response = await client.chat([
            ChatMessage(role="user", content="Hi"),
        ])

        assert response.content == "Hello!"
        assert response.model == "phi4-mini:latest"
        assert response.total_duration_ms == 500.0
        await client.close()

    @pytest.mark.asyncio
    async def test_chat_error(self, client):
        client._active_model = "phi4-mini"

        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.text = AsyncMock(return_value="Internal Server Error")

        mock_session = make_mock_session(post=MagicMock(return_value=AsyncContextManager(mock_resp)))
        client._session = mock_session

        with pytest.raises(RuntimeError, match="Ollama chat failed"):
            await client.chat([ChatMessage(role="user", content="Hi")])
        await client.close()

    @pytest.mark.asyncio
    async def test_generate_convenience(self, client):
        client._active_model = "phi4-mini:latest"

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "message": {"role": "assistant", "content": "Generated!"},
            "total_duration": 100_000_000,
            "prompt_eval_count": 5,
            "eval_count": 3,
        })

        mock_session = make_mock_session(post=MagicMock(return_value=AsyncContextManager(mock_resp)))
        client._session = mock_session

        response = await client.generate(
            prompt="test prompt",
            system="you are helpful",
        )

        assert response.content == "Generated!"
        # Verify it sent system + user messages
        call_kwargs = mock_session.post.call_args
        assert call_kwargs is not None
        await client.close()


# ── Helper ───────────────────────────────────────────────

class AsyncContextManager:
    """Wraps an async mock to work as an async context manager."""

    def __init__(self, mock):
        self._mock = mock

    async def __aenter__(self):
        return self._mock

    async def __aexit__(self, *args):
        pass


def make_mock_session(**overrides):
    """Create a mock aiohttp session that won't be replaced by _get_session."""
    session = AsyncMock()
    session.closed = False  # Prevent _get_session from creating a real session
    for k, v in overrides.items():
        setattr(session, k, v)
    return session
