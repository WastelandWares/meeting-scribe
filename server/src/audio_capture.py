"""Audio capture using sounddevice with async chunk delivery."""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Optional

import numpy as np
import sounddevice as sd


class AudioCapture:
    """Captures audio from an input device and yields fixed-duration chunks.

    The sounddevice callback runs on a separate thread. Chunks are delivered
    to async consumers via an asyncio.Queue using loop.call_soon_threadsafe.
    """

    def __init__(
        self,
        chunk_duration: int = 30,
        sample_rate: int = 16000,
        device: Optional[int] = None,
    ) -> None:
        self.chunk_duration = chunk_duration
        self.sample_rate = sample_rate
        self.device = device

        self._stream: Optional[sd.InputStream] = None
        self._queue: asyncio.Queue[np.ndarray] = asyncio.Queue()
        self._buffer: list[np.ndarray] = []
        self._buffer_samples: int = 0
        self._paused: bool = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._chunk_size: int = chunk_duration * sample_rate

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: object,
    ) -> None:
        """Called by sounddevice on the audio thread."""
        if self._paused:
            return

        # Flatten to mono 1-D
        audio = indata[:, 0].copy()
        self._buffer.append(audio)
        self._buffer_samples += len(audio)

        # Emit complete chunks
        while self._buffer_samples >= self._chunk_size:
            concatenated = np.concatenate(self._buffer)
            chunk = concatenated[: self._chunk_size]
            leftover = concatenated[self._chunk_size :]

            if len(leftover) > 0:
                self._buffer = [leftover]
                self._buffer_samples = len(leftover)
            else:
                self._buffer = []
                self._buffer_samples = 0

            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, chunk)

    async def start(self) -> None:
        """Open the audio stream and begin recording."""
        self._loop = asyncio.get_running_loop()
        self._paused = False
        self._buffer = []
        self._buffer_samples = 0

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype=np.float32,
            device=self.device,
            callback=self._audio_callback,
        )
        self._stream.start()

    async def stop(self) -> None:
        """Stop and close the audio stream."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._buffer = []
        self._buffer_samples = 0
        # Put sentinel to unblock chunks() generator
        self._queue.put_nowait(None)

    async def pause(self) -> None:
        """Pause chunk emission; audio callbacks are silently dropped."""
        self._paused = True
        self._buffer = []
        self._buffer_samples = 0

    async def resume(self) -> None:
        """Resume chunk emission after a pause."""
        self._paused = False

    async def chunks(self) -> AsyncGenerator[np.ndarray, None]:
        """Async generator that yields audio chunks of chunk_duration seconds."""
        while True:
            chunk = await self._queue.get()
            if chunk is None:
                return
            yield chunk
