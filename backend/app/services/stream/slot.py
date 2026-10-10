"""Backpressure: drop, never block, never accumulate (spec §4.4).

The single most important streaming rule. Between the source and every
consumer sits a latest-frame slot; a full queue means replace the oldest
frame. If inference falls behind reality, stale frames are dropped — never
queued — so a backlog cannot consume RAM or add latency to alerts.
"""

from __future__ import annotations

import asyncio

from app.services.stream.source import Frame


class LatestFrameSlot:
    """Single-slot mailbox where a new frame replaces an old one.

    Backs onto ``asyncio.Queue(maxsize=1)`` but drops the older frame instead
    of blocking, so a slow consumer never back-pressures the source. The
    ``dropped`` counter is observability, not decoration: it is how a field
    report of "the image froze" is diagnosed without attaching a debugger.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Frame | None] = asyncio.Queue(maxsize=1)
        self._dropped = 0
        self._closed = False

    async def put(self, frame: Frame) -> None:
        """Store the newest frame, replacing any older one held."""
        if self._closed:
            return
        if self._queue.full():
            self._queue.get_nowait()
            self._dropped += 1
        await self._queue.put(frame)

    async def get(self, timeout: float | None = None) -> Frame | None:  # noqa: ASYNC109
        """Return the newest frame, or None on timeout or after close().

        ``timeout`` is part of the documented contract (spec §4.4 consumers
        poll with a bound); the wait itself is ``asyncio.wait_for`` below.
        """
        try:
            item = await asyncio.wait_for(self._queue.get(), timeout)
        except TimeoutError:
            return None
        return None if item is None else item

    def close(self) -> None:
        """Unblock any waiter: a None sentinel lets it return frame-less."""
        self._closed = True
        if not self._queue.full():
            self._queue.put_nowait(None)

    @property
    def dropped(self) -> int:
        """How many frames were overwritten because a consumer was slow."""
        return self._dropped
