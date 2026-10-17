"""Pre/post-roll ring buffer: holds ten seconds of pre-roll (spec A5.7, matrix)."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pytest

from app.services.events.clips import FrameRingBuffer
from app.services.stream.source import Frame


class Clock:
    """Deterministic monotonic clock."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def frame(index: int) -> Frame:
    return Frame(
        data=np.full((36, 64, 3), index % 255, dtype=np.uint8),
        timestamp=float(index),
        width=64,
        height=36,
    )


@pytest.fixture
def clock() -> Iterator[Clock]:
    yield Clock()


def test_holds_ten_seconds(clock: Clock) -> None:
    """A 10s pre-roll must survive: 50 frames at 5 FPS over 10s all stay."""
    ring = FrameRingBuffer(duration_s=30.0, now=clock)
    for i in range(51):
        ring.append(frame(i))
        clock.t += 0.2  # 5 FPS; t spans 0.0..10.0
    assert len(ring) == 51, "every frame of a 10s window is still pre-roll"


def test_evicts_past_duration(clock: Clock) -> None:
    ring = FrameRingBuffer(duration_s=30.0, now=clock)
    ring.append_jpeg(0.0, b"old")
    clock.t = 31.0
    ring.append_jpeg(31.0, b"new")
    assert [f.jpeg for f in ring.slice(0.0, 32.0)] == [b"new"]
    assert ring.latest_jpeg() == b"new"


def test_slice_is_half_open_and_ordered(clock: Clock) -> None:
    ring = FrameRingBuffer(now=clock)
    for at in (1.0, 2.0, 3.0, 4.0):
        ring.append_jpeg(at, f"f{at}".encode())
    got = [f.at for f in ring.slice(2.0, 4.0)]
    assert got == [2.0, 3.0], "start inclusive, end exclusive"


def test_latest_is_none_when_empty() -> None:
    assert FrameRingBuffer().latest_jpeg() is None
