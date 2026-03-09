"""Ollama API client for local LLM inference.

Handles model provisioning, health checks, and chat completions.
Sprint 1 story #28: Ollama model provisioning and health checks.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

# Models we want available for the assistant
PREFERRED_MODELS = [
    "phi4-mini",       # 3.8B, 128K ctx — fast reasoning
    "qwen3:4b",        # 4B, 256K ctx — long sessions
]

DEFAULT_MODEL = "phi4-mini"


@dataclass
class OllamaHealth:
    """Health check result for the Ollama service."""

    reachable: bool = False
    version: str = ""
    models_available: list[str] = field(default_factory=list)
    preferred_model: Optional[str] = None
    error: Optional[str] = None

    @property
    def ready(self) -> bool:
        """True if Ollama is reachable and has at least one preferred model."""
        return self.reachable and self.preferred_model is not None


@dataclass
class ChatMessage:
    """A single message in a chat conversation."""

    role: str  # "system", "user", "assistant"
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class ChatResponse:
    """Response from a chat completion."""

    content: str
    model: str
    total_duration_ms: float = 0.0
    prompt_eval_count: int = 0
    eval_count: int = 0

    @property
    def tokens_per_second(self) -> float:
        if self.total_duration_ms > 0:
            return self.eval_count / (self.total_duration_ms / 1000)
        return 0.0


class OllamaClient:
    """Async client for the Ollama HTTP API.

    Usage:
        client = OllamaClient()
        health = await client.check_health()
        if health.ready:
            response = await client.chat([
                ChatMessage("system", "You are a meeting assistant."),
                ChatMessage("user", "Summarize the following transcript..."),
            ])
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: Optional[str] = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._configured_model = model
        self._active_model: Optional[str] = None
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ── Health & Provisioning ────────────────────────────

    async def check_health(self) -> OllamaHealth:
        """Check Ollama availability and find the best available model."""
        health = OllamaHealth()
        session = await self._get_session()

        try:
            async with session.get(f"{self.base_url}/api/tags") as resp:
                if resp.status != 200:
                    health.error = f"HTTP {resp.status}"
                    return health

                data = await resp.json()
                health.reachable = True
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            health.error = str(exc)
            return health

        # Extract model names (strip :latest suffix for matching)
        raw_names = [m.get("name", "") for m in data.get("models", [])]
        health.models_available = raw_names

        # Find the best preferred model
        if self._configured_model:
            # User specified a model — check if it's available
            for name in raw_names:
                if self._configured_model in name:
                    health.preferred_model = name
                    break
            if not health.preferred_model:
                health.error = f"Configured model '{self._configured_model}' not found"
        else:
            # Auto-detect: pick first preferred model that's available
            for preferred in PREFERRED_MODELS:
                for name in raw_names:
                    if preferred in name:
                        health.preferred_model = name
                        break
                if health.preferred_model:
                    break

        if health.preferred_model:
            self._active_model = health.preferred_model
            logger.info("Ollama ready — using model: %s", self._active_model)
        elif health.reachable:
            health.error = f"No preferred model found. Available: {raw_names}"
            logger.warning("Ollama reachable but no preferred model: %s", raw_names)

        return health

    async def ensure_model(self, model_name: Optional[str] = None) -> bool:
        """Pull a model if it's not already available. Returns True on success."""
        target = model_name or DEFAULT_MODEL
        session = await self._get_session()

        logger.info("Pulling model %s (this may take a while)...", target)
        try:
            async with session.post(
                f"{self.base_url}/api/pull",
                json={"name": target, "stream": False},
            ) as resp:
                if resp.status == 200:
                    logger.info("Model %s pulled successfully", target)
                    return True
                else:
                    body = await resp.text()
                    logger.error("Failed to pull %s: HTTP %d — %s", target, resp.status, body)
                    return False
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error("Failed to pull %s: %s", target, exc)
            return False

    @property
    def model(self) -> str:
        """Return the active model name."""
        return self._active_model or self._configured_model or DEFAULT_MODEL

    # ── Chat Completion ──────────────────────────────────

    async def chat(
        self,
        messages: list[ChatMessage],
        temperature: float = 0.3,
        model: Optional[str] = None,
    ) -> ChatResponse:
        """Send a chat completion request to Ollama.

        Args:
            messages: Conversation history.
            temperature: Sampling temperature (lower = more focused).
            model: Override the active model for this request.

        Returns:
            ChatResponse with the assistant's reply.
        """
        target_model = model or self.model
        session = await self._get_session()

        payload = {
            "model": target_model,
            "messages": [m.to_dict() for m in messages],
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        try:
            async with session.post(
                f"{self.base_url}/api/chat",
                json=payload,
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(f"Ollama chat failed: HTTP {resp.status} — {body}")

                data = await resp.json()

                content = data.get("message", {}).get("content", "")
                total_ns = data.get("total_duration", 0)

                return ChatResponse(
                    content=content,
                    model=target_model,
                    total_duration_ms=total_ns / 1_000_000,
                    prompt_eval_count=data.get("prompt_eval_count", 0),
                    eval_count=data.get("eval_count", 0),
                )

        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise RuntimeError(f"Ollama chat request failed: {exc}") from exc

    # ── Generate (single-shot, no conversation) ──────────

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        model: Optional[str] = None,
    ) -> ChatResponse:
        """Convenience wrapper: single prompt → response."""
        messages = []
        if system:
            messages.append(ChatMessage(role="system", content=system))
        messages.append(ChatMessage(role="user", content=prompt))
        return await self.chat(messages, temperature=temperature, model=model)
