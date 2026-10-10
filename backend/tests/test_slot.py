"""Backpressure semantics (spec §4.4): full means replace, never block."""

from __future__ import annotations

import asyncio

import numpy as np

from app.services.stream.slot import LatestFrameSlot
from app.services.stream.source import Frame


def _frame(seed: int = 0) -> Frame:
    return Frame(
        data=np.full((360, 640, 3), seed, dtype=np.uint8),
        timestamp=float(seed),
        width=640,
        height=360,
    )


async def test_newest_replaces_oldest() -> None:
    slot = LatestFrameSlot()
    await slot.put(_frame(1))
    await slot.put(_frame(2))
    got = await slot.get()
    assert got is not None and got.data[0, 0, 0] == 2


async def test_put_never_blocks_when_full() -> None:
    slot = LatestFrameSlot()
    await slot.put(_frame(1))
    # The queue is full; put() must return immediately, not block or raise.
    await asyncio.wait_for(slot.put(_frame(2)), timeout=0.05)


async def test_dropped_counts_overwrites() -> None:
    slot = LatestFrameSlot()
    for seed in range(5):
        await slot.put(_frame(seed))
    # First put filled the empty slot; four newer frames replaced older ones.
    assert slot.dropped == 4


async def test_get_timeout_returns_none() -> None:
    slot = LatestFrameSlot()
    assert await slot.get(timeout=0.05) is None


async def test_close_unblocks_waiter() -> None:
    slot = LatestFrameSlot()
    waiter = asyncio.create_task(slot.get())
    await asyncio.sleep(0.01)
    slot.close()
    result = await asyncio.wait_for(waiter, timeout=1.0)
    assert result is None


async def test_put_after_close_is_a_noop() -> None:
    slot = LatestFrameSlot()
    slot.close()
    await asyncio.wait_for(slot.put(_frame(1)), timeout=0.05)
    assert await slot.get(timeout=0.01) is None
