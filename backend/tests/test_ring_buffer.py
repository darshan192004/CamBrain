"""Pre-roll ring buffer: ten seconds of frames, oldest dropped first."""

from __future__ import annotations

import numpy as np

from app.services.events.clips import RingBuffer
from app.services.stream.source import Frame


def _frame(index: int) -> Frame:
    return Frame(
        data=np.full((36, 64, 3), index % 256, dtype=np.uint8),
        timestamp=float(index) / 2.0,
        width=64,
        height=36,
    )


def test_holds_ten_seconds() -> None:
    """10s at 2fps keeps the newest 20 frames and drops the rest."""
    ring = RingBuffer.from_seconds(10.0, fps=2.0)
    for i in range(30):
        ring.push(_frame(i))
    snapshot = ring.snapshot()
    assert len(snapshot) == 20
    assert snapshot[0].timestamp == 10 / 2.0
    assert snapshot[-1].timestamp == 29 / 2.0


def test_snapshot_is_oldest_first() -> None:
    ring = RingBuffer(capacity=3)
    for i in range(3):
        ring.push(_frame(i))
    assert [f.timestamp for f in ring.snapshot()] == [0.0, 0.5, 1.0]


def test_clear_empties() -> None:
    ring = RingBuffer(capacity=4)
    ring.push(_frame(0))
    ring.clear()
    assert ring.snapshot() == []
    assert len(ring) == 0
