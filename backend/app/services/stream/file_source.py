"""Decode a local clip. Loop or once. The CI-safe stand-in for a camera.

Every Phase 1 offline test runs from this class through the ``FrameSource``
seam, so a camera is never required (spec §11.1).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

import av

from app.services.stream.source import Frame


class FileSource:
    """Decode ``path`` repeatedly (loop) or once, yielding owned RGB frames.

    The container closes in ``finally`` on every path — including
    cancellation — so a handle is never leaked across reconnects (spec §4.5).
    """

    def __init__(self, path: Path, *, loop: bool = True) -> None:
        self._path = path
        self._loop = loop
        self._closed = False

    async def frames(self) -> AsyncIterator[Frame]:
        while not self._closed:
            container = av.open(str(self._path))
            try:
                stream = container.streams.video[0]
                iterator = container.decode(stream)
                while not self._closed:
                    try:
                        raw = next(iterator)
                    except StopIteration:
                        break
                    data = raw.to_ndarray(format="rgb24").copy()
                    yield Frame(
                        data=data,
                        timestamp=time.monotonic(),
                        width=raw.width,
                        height=raw.height,
                    )
            finally:
                container.close()
            if not self._loop:
                return
            await asyncio.sleep(0)

    async def close(self) -> None:
        """Idempotent: repeated calls and calls mid-iteration are safe."""
        self._closed = True
