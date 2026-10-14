"""Fixed-duration ring buffer of JPEG frames behind every alert (spec A5.7).

Owns nothing but bytes and timestamps: it is fed by the runtime's tee, sliced
by the handler at fire time, and evicts anything older than its window so a
camera that runs for a month costs one window of memory, not a month of it.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from app.services.stream.jpeg import encode_jpeg
from app.services.stream.source import Frame


@dataclass(frozen=True, slots=True)
class BufferedFrame:
    """One buffered JPEG stamped with a monotonic time."""

    at: float
    jpeg: bytes


class FrameRingBuffer:
    """Hold the last ``duration_s`` of sampled frames.

    Args:
        duration_s: Retention window; 30s covers 10s pre-roll + 20s post-roll
            (spec A5.7) because assembly happens after the post-roll elapses.
        now: Monotonic clock, injected for deterministic tests.
    """

    def __init__(
        self, *, duration_s: float = 30.0, now: Callable[[], float] = time.monotonic
    ) -> None:
        self._duration_s = duration_s
        self._now = now
        self._frames: deque[BufferedFrame] = deque()

    def append(self, frame: Frame) -> None:
        """Encode and buffer one pipeline frame."""
        self.append_jpeg(self._now(), encode_jpeg(frame))

    def append_jpeg(self, at: float, jpeg: bytes) -> None:
        """Buffer a pre-encoded JPEG stamped at ``at`` (monotonic seconds)."""
        self._frames.append(BufferedFrame(at=at, jpeg=jpeg))
        while self._frames and at - self._frames[0].at > self._duration_s:
            self._frames.popleft()

    def latest_jpeg(self) -> bytes | None:
        """The newest buffered JPEG, or None when the window is empty."""
        return self._frames[-1].jpeg if self._frames else None

    def slice(self, start: float, end: float) -> list[BufferedFrame]:
        """Frames with ``start <= at < end``, oldest first."""
        return [f for f in self._frames if start <= f.at < end]

    def __len__(self) -> int:
        return len(self._frames)
