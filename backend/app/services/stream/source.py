"""Frame contract and the source seam that removes hardware dependency.

Spec §5.1. Every source implements ``FrameSource``, so the entire pipeline
is testable from a file on disk and CI needs no cameras. Because it is
narrow, a new source (ONVIF, USB webcam, vendor SDK) is one new class.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True, slots=True)
class Frame:
    """One decoded frame.

    Frozen so a consumer cannot mutate a frame another consumer holds.
    ``slots`` because these are allocated continuously and per-instance
    ``__dict__`` overhead is measurable at 8 cameras x 15fps.

    ``data`` is owned by the frame — never a borrowed view of a decoder
    buffer, which PyAV reuses on the next decode.
    """

    data: np.ndarray  # (H, W, 3) uint8 RGB, owned.
    timestamp: float  # monotonic seconds from capture.
    width: int
    height: int


class FrameSource(Protocol):
    """Produces frames from something. The seam that removes hardware."""

    def frames(self) -> AsyncIterator[Frame]:
        """Yield frames until cancelled or the source is exhausted.

        An async generator function: calling it returns the iterator, so
        ``async for frame in source.frames()`` needs no ``await``.
        """
        ...

    async def close(self) -> None:
        """Release every resource. Idempotent and safe mid-iteration."""
        ...
