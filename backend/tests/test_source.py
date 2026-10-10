"""Protocol conformance for the source seam and FileSource (spec §5.1).

Everything here runs offline from a generated clip. The 1080p row of the
verification matrix (§12) is split: the gate's downscale handling is proven
by pipeline tests; the frame contract is proven here.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import pytest

from app.services.stream.file_source import FileSource
from app.services.stream.pipeline import CameraConfig, CameraPipeline
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


async def test_1080p_input_downscaled() -> None:
    """A 1080p input works end to end (verification matrix §12 row).

    The gate downscales internally to its 640x360 work size; the consumer
    still receives the frame at its native size — no hidden resize of the
    data other stages see.

    The motion gate is injected open so this tests the frame *contract* (a
    1080p buffer reaches the sink untouched), not motion detection — that is
    already covered by the pipeline tests. A synthetic source that spins as
    fast as ``sleep(0)`` allows starves the loop and races the gate's
    priming cooldown, so the source is paced like a real sub-stream.
    """
    import time

    from app.services.stream.source import Frame

    received: list[Frame] = []

    async def sink(frame: Frame) -> None:
        received.append(frame)

    class AlwaysOpenGate:
        def update(self, _frame: Frame) -> bool:
            return True

        def reset(self) -> None:
            return None

    class PacedSource:
        async def frames(self) -> AsyncIterator[Frame]:
            arr = np.full((1080, 1920, 3), 20, dtype=np.uint8)
            arr[200:800, 900:1020] = 240
            while True:
                # Native 1080p, paced like a real sub-stream: the pipeline's
                # 5 Hz sample limiter (0.2 s) decides what reaches the sink.
                yield Frame(arr, time.monotonic(), 1920, 1080)
                await asyncio.sleep(0.05)

        async def close(self) -> None:
            return None

    pipeline = CameraPipeline(
        CameraConfig("cam", "Cam", "loop://1080p", sample_fps=5.0),
        PacedSource(),
        sink,
        motion=AlwaysOpenGate(),  # type: ignore[arg-type]
    )
    task = asyncio.create_task(pipeline.run())
    try:
        # > one priming cooldown (~0.6 s at 0.05 s/frame) + a 5 Hz sample tick.
        await asyncio.sleep(1.5)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert received
    assert received[0].width == 1920
    assert received[0].height == 1080
    assert received[0].data.shape == (1080, 1920, 3)
