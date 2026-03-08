#!/usr/bin/env python3
"""Simple CLI WebSocket test client for the transcription server.

Usage:
    python -m tests.test_client [--host HOST] [--port PORT]

Connects to the server, sends a "start" command, prints received segments,
and sends "stop" on Ctrl+C before disconnecting.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys

import websockets


def _format_time(seconds: float) -> str:
    """Format seconds as MM:SS."""
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


async def run_client(host: str, port: int) -> None:
    uri = f"ws://{host}:{port}"
    print(f"Connecting to {uri} ...")

    async with websockets.connect(uri) as ws:
        # Read initial status
        raw = await ws.recv()
        msg = json.loads(raw)
        print(f"Server status: {msg['data'].get('state', 'unknown')}")

        # Send start command
        await ws.send(json.dumps({"type": "start"}))
        print("Sent 'start' command — listening for segments...\n")

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def _on_sigint() -> None:
            stop_event.set()

        loop.add_signal_handler(signal.SIGINT, _on_sigint)

        try:
            while not stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                msg = json.loads(raw)

                if msg["type"] == "segments":
                    for seg in msg["data"].get("segments", []):
                        ts = _format_time(seg.get("start", 0))
                        speaker = seg.get("speaker_name") or seg.get("speaker_id") or "SPEAKER_??"
                        text = seg.get("text", "").strip()
                        print(f"[{ts}] {speaker}: {text}")

                elif msg["type"] == "diarization_update":
                    print("\n--- diarization update ---")
                    for seg in msg["data"].get("segments", []):
                        ts = _format_time(seg.get("start", 0))
                        speaker = seg.get("speaker_name") or seg.get("speaker_id") or "SPEAKER_??"
                        text = seg.get("text", "").strip()
                        print(f"[{ts}] {speaker}: {text}")
                    print("--- end update ---\n")

                elif msg["type"] == "status":
                    state = msg["data"].get("state", "unknown")
                    print(f"--- status: {state} ---")

        finally:
            # Send stop before disconnecting
            print("\nSending 'stop' command...")
            await ws.send(json.dumps({"type": "stop"}))
            await asyncio.sleep(0.2)
            print("Disconnected.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test client for meeting-scribe server")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=9876)
    args = parser.parse_args()

    try:
        asyncio.run(run_client(args.host, args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
