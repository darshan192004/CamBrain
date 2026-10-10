"""StreamManager lifecycle + the reconnect canaries (spec §1.5, §12)."""

from __future__ import annotations

import asyncio
import gc
import random
import statistics
import threading
import time
from pathlib import Path

import psutil
import pytest

from app.services.stream.file_source import FileSource
from app.services.stream.pipeline import CameraConfig
from app.services.stream.rtsp_source import RtspSource, next_backoff
from app.services.stream.source import Frame, FrameSource
from app.services.stream.stream_manager import StreamManager


def test_backoff_reaches_cap() -> None:
    """Jittered exponential backoff caps at 60s (spec §1.5)."""
    random.seed(3)
    assert all(delay >= 0.0 for delay in (next_backoff(a) for a in range(20)))
    assert all(delay < 60.0 for delay in (next_backoff(a) for a in range(20)))
    samples = [next_backoff(10, cap=60.0) for _ in range(300)]
    assert max(samples) > 58.0  # the cap domain is actually reached
    assert all(0.0 <= delay < 1.0 for delay in [next_backoff(0) for _ in range(20)])
    assert next_backoff(30, base=1.0, cap=60.0) < 60.0


def test_backoff_has_jitter() -> None:
    """No thundering herd (spec §4.6): retries are random, not lockstep."""
    random.seed(11)
    first = [next_backoff(3) for _ in range(50)]
    random.seed(11)
    second = [next_backoff(3) for _ in range(50)]
    assert first == second  # deterministic under a seed — reproducible failures
    distinct = {round(d, 3) for d in first}
    assert len(distinct) > 10  # spans a range, not lockstep
    assert min(first) < 1.0 and max(first) < 8.0  # within [0, 2**attempt)


def test_add_remove_status_all(clip_path: Path) -> None:
    """Manager owns a pipeline's lifecycle from one injected factory."""
    first_frame = threading.Event()

    def make_source(_config: CameraConfig) -> FrameSource:
        return FileSource(clip_path, loop=True)

    async def sink(_frame: Frame) -> None:
        first_frame.set()

    manager = StreamManager(make_source, sink)
    cfg = CameraConfig("office", "Office", "file://motion.mp4", sample_fps=5.0)
    manager.add_camera(cfg)

    deadline = time.monotonic() + 5.0
    while not first_frame.is_set() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert first_frame.is_set()

    statuses = manager.status_all()
    assert set(statuses) == {"office"}
    assert statuses["office"].frames_consumed >= 1

    assert manager.remove_camera("office") is True
    assert manager.remove_camera("office") is False  # idempotent-ish contract
    assert manager.status_all() == {}


@pytest.mark.rtsp
async def test_transient_drop_recovers_fast(mediamtx_pause) -> None:
    """Transient RTSP drop recovers within 5s (spec §1.5, §12)."""
    url, pause = mediamtx_pause
    received: list[float] = []
    src = RtspSource(url)
    frames = src.frames()
    try:
        first = await asyncio.wait_for(anext(frames), timeout=10.0)
        received.append(first.timestamp)
        await pause(2.0)  # publisher silent for 2 s
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            frame = await asyncio.wait_for(anext(frames), timeout=5.0)
            received.append(frame.timestamp)
            gap = received[-1] - received[-2]
            if gap >= 1.0:  # the drop really happened, and frames flow again
                return
        pytest.fail("RtspSource did not resume within 5s of a transient drop")
    finally:
        await frames.aclose()
        await src.close()


@pytest.mark.rtsp
@pytest.mark.slow
async def test_memory_is_flat_across_reconnects(mediamtx_url: str) -> None:
    """50 reconnect cycles; resident memory must plateau, not climb (spec §11.4).

    A ceiling assertion passes on a slow leak; a trend assertion catches it.
    """
    proc = psutil.Process()
    samples: list[tuple[int, int]] = []
    for cycle in range(50):
        src = RtspSource(mediamtx_url)
        frames = src.frames()
        try:
            frame = await asyncio.wait_for(anext(frames), timeout=10.0)
            assert frame.width == 640
        finally:
            await frames.aclose()
            await src.close()
        gc.collect()
        samples.append((cycle, proc.memory_info().rss))

    early = [rss for _, rss in samples[:10]]
    late = [rss for _, rss in samples[-10:]]
    growth = (statistics.fmean(late) - statistics.fmean(early)) / statistics.fmean(early)
    assert growth < 0.10, f"RSS grew {growth * 100:.1f}% over 50 reconnects"
