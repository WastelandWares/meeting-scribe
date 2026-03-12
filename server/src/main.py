"""Entry point for the meeting-scribe transcription server."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from src.assistant import AssistantConfig
from src.pipeline import Pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Meeting Scribe — real-time transcription server",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="WebSocket server host (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9876,
        help="WebSocket server port (default: 9876)",
    )
    parser.add_argument(
        "--model",
        default="base",
        help="Whisper model size (default: base)",
    )
    parser.add_argument(
        "--chunk-duration",
        type=int,
        default=30,
        help="Audio chunk duration in seconds (default: 30)",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Audio input device index (default: system default)",
    )
    parser.add_argument(
        "--diarization-interval",
        type=int,
        default=3,
        help="Run diarization every N chunks (default: 3)",
    )

    # Assistant options
    parser.add_argument(
        "--no-assistant",
        action="store_true",
        help="Disable the AI assistant (summary/action items)",
    )
    parser.add_argument(
        "--assistant-model",
        default=None,
        help="Ollama model for assistant (default: auto-detect preferred)",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://localhost:11434",
        help="Ollama API base URL (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--assistant-window",
        type=float,
        default=180,
        help="Analysis window in seconds (default: 180)",
    )
    parser.add_argument(
        "--skills-path",
        type=str,
        default=None,
        help="Path to user skills directory (markdown files)",
    )

    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> None:
    assistant_config = AssistantConfig(
        enabled=not args.no_assistant,
        model=args.assistant_model,
        ollama_url=args.ollama_url,
        window_seconds=args.assistant_window,
        skills_path=args.skills_path,
    )

    pipeline = Pipeline(
        model_size=args.model,
        chunk_duration=args.chunk_duration,
        host=args.host,
        port=args.port,
        device=args.device,
        diarization_interval=args.diarization_interval,
        assistant_config=assistant_config,
    )

    loop = asyncio.get_running_loop()

    def _shutdown() -> None:
        logger.info("Received shutdown signal, stopping...")
        asyncio.ensure_future(pipeline.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    await pipeline.run()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logger.info(
        "Starting server on %s:%d with model=%s chunk_duration=%ds",
        args.host,
        args.port,
        args.model,
        args.chunk_duration,
    )
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        logger.info("Interrupted")


if __name__ == "__main__":
    main()
