"""Protocol conformance for the source seam and FileSource (spec §5.1).

Everything here runs offline from a generated clip. The 1080p row of the
verification matrix (§12) is split: the gate's downscale handling is proven
by pipeline tests; the frame contract is proven here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.services.stream.file_source import FileSource
from app.services.stream.source import Frame, FrameSource
from tests.make_fixtures import FRAME_COUNT


async def test_file_source_yields_owned_frames(clip_path: Path) -> None:
    """Frames carry real dimensions, monotonic capture times, owned buffers."""
    src = FileSource(clip_path)
    frames = src.frames()
    try:
        frames_seen: list[Frame] = [await anext(frames) for _ in range(3)]
    finally:
        await frames.aclose()
        await src.close()

    assert frames_seen[0].width == 640
    assert frames_seen[0].height == 360
    assert frames_seen[0].data.shape == (360, 640, 3)
    assert frames_seen[0].data.dtype == np.uint8
    assert [f.data.base is None for f in frames_seen] == [True, True, True]
    assert frames_seen[0].timestamp <= frames_seen[1].timestamp
    assert frames_seen[1].timestamp <= frames_seen[2].timestamp


async def test_later_decode_does_not_corrupt_earlier_data(clip_path: Path) -> None:
    """`data` must be an owned copy — decoder buffers are reused by PyAV."""
    src = FileSource(clip_path)
    frames = src.frames()
    try:
        first = await anext(frames)
        snapshot = first.data.copy()
        await anext(frames)
        await anext(frames)
        assert np.array_equal(first.data, snapshot)
        assert not np.shares_memory(snapshot, first.data)
    finally:
        await frames.aclose()
        await src.close()


async def test_file_source_once_mode_ends(clip_path: Path) -> None:
    """`loop=False` yields exactly the clip's frames, then stops."""
    src = FileSource(clip_path, loop=False)
    count = 0
    frames = src.frames()
    try:
        async for _ in frames:
            count += 1
    finally:
        await frames.aclose()
        await src.close()
    assert count == FRAME_COUNT


async def test_file_source_loop_mode_wraps(clip_path: Path) -> None:
    """`loop=True` (default) keeps yielding past the end of the clip.

    The motion clip is 300 frames; a loop must pass the boundary.
    """
    src = FileSource(clip_path)
    frames = src.frames()
    count = 0
    try:
        async for _ in frames:
            count += 1
            if count > FRAME_COUNT + 5:
                break
        assert count > FRAME_COUNT
    finally:
        await frames.aclose()
        await src.close()


async def test_close_is_idempotent_and_terminates_iteration(clip_path: Path) -> None:
    """close() twice is safe, and the iterator ends after close (spec §5.1)."""
    src = FileSource(clip_path)
    frames = src.frames()
    first = await anext(frames)
    assert first.width == 640
    await src.close()
    await src.close()
    with pytest.raises(StopAsyncIteration):
        await anext(frames)
    await frames.aclose()


def test_file_source_satisfies_protocol(clip_path: Path) -> None:
    """Static structural check that FileSource implements FrameSource."""
    src: FrameSource = FileSource(clip_path)
    assert callable(src.frames)
    assert callable(src.close)
