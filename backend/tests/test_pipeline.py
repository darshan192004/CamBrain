"""CameraPipeline: gating, sampling, concurrency, ownership (spec §5, §12)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import psutil
import pytest

from app.core.errors import ValidationError
from app.services.stream.file_source import FileSource
from app.services.stream.pipeline import CameraConfig, CameraPipeline, FrameSink
from app.services.stream.source import Frame


async def _run_for(pipeline: CameraPipeline, seconds: float) -> None:
    task = asyncio.create_task(pipeline.run())
    try:
        await asyncio.sleep(seconds)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_sample_fps_is_honoured(clip_path: Path) -> None:
    """With the gate open (motion clip), emissions follow sample_fps (≤5Hz)."""
    consumed: list[Frame] = []

    async def sink(frame: Frame) -> None:
        consumed.append(frame)

    pipeline = CameraPipeline(
        CameraConfig("cam", "Cam", str(clip_path), sample_fps=5.0),
        FileSource(clip_path),
        sink,
    )
    await _run_for(pipeline, 3.0)

    # FileSource decodes unpaced, so the loop may starve the sleep timer and
    # the run lasts longer than 3s wall time — assert the *rate*, which is
    # what "sample_fps is honoured" means, not a count over an assumed window.
    assert len(consumed) >= 8, "the gate never opened for the motion clip"
    span = consumed[-1].timestamp - consumed[0].timestamp
    rate = (len(consumed) - 1) / span
    assert 4.0 <= rate <= 5.5, f"emission rate {rate:.1f}Hz, expected ~5Hz"


def test_sample_fps_out_of_range_is_rejected() -> None:
    """Sample rate is 2–5 FPS (spec §1.5); config refuses anything else."""
    with pytest.raises(ValidationError):
        CameraConfig("cam", "Cam", "file://x", sample_fps=1.0)
    with pytest.raises(ValidationError):
        CameraConfig("cam", "Cam", "file://x", sample_fps=7.0)
    assert CameraConfig("cam", "Cam", "file://x", sample_fps=5.0)


async def test_eight_pipelines_concurrently(clip_path: Path) -> None:
    """Eight cameras, each with its own pipeline, all live at once."""
    consumed: dict[str, list[Frame]] = {}

    def make_sink(camera_id: str) -> FrameSink:
        async def sink(frame: Frame) -> None:
            consumed.setdefault(camera_id, []).append(frame)

        return sink

    pipelines = [
        CameraPipeline(
            CameraConfig(f"cam{i}", f"Cam {i}", str(clip_path), sample_fps=5.0),
            FileSource(clip_path),
            make_sink(f"cam{i}"),
        )
        for i in range(8)
    ]
    tasks = [asyncio.create_task(p.run()) for p in pipelines]
    try:
        await asyncio.sleep(2.5)
        for i in range(8):
            assert consumed[f"cam{i}"], f"camera cam{i} consumed nothing"
            assert pipelines[i].snapshot().state == "live"
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.slow
async def test_idle_cpu_under_5_percent() -> None:
    """No motion → no consumer work, and the process idles (spec §1.5)."""

    class PacedSource:
        """Feeds one static frame at a camera's real rate (paced, no decode)."""

        def __init__(self, fps: float) -> None:
            self._interval = 1.0 / fps
            self._closed = False
            # One buffer reused every tick, like a camera's decode pool: the
            # measurement must be the gate's economics, not 15 allocations
            # per second (which would swamp the 5% bar on their own).
            self._buf = np.full((360, 640, 3), 30, dtype=np.uint8)

        async def frames(self) -> AsyncIterator[Frame]:
            while not self._closed:
                yield Frame(
                    data=self._buf,
                    timestamp=time.monotonic(),
                    width=640,
                    height=360,
                )
                await asyncio.sleep(self._interval)

        async def close(self) -> None:
            self._closed = True

    consumed: list[Frame] = []

    async def sink(frame: Frame) -> None:
        consumed.append(frame)

    pipeline = CameraPipeline(
        CameraConfig("cam", "Cam", "paced://static", sample_fps=2.0),
        PacedSource(fps=15.0),
        sink,
    )
    proc = psutil.Process()
    proc.cpu_percent()  # prime the interval sample
    await _run_for(pipeline, 3.0)
    cpu = proc.cpu_percent()  # % of one core over the last 3 s

    assert consumed == []  # the gate economics: closed gate does zero work
    assert cpu < 5.0


async def test_pipeline_closes_source_on_cancel(clip_path: Path) -> None:
    """Cancellation must close the source in finally (spec §4.5, §5.1)."""

    class TrackingSource(FileSource):
        def __init__(self, path: Path) -> None:
            super().__init__(path)
            self.closed = False

        async def close(self) -> None:
            await super().close()
            self.closed = True

    async def sink(_frame: Frame) -> None:
        return None

    source = TrackingSource(clip_path)
    pipeline = CameraPipeline(
        CameraConfig("cam", "Cam", str(clip_path), sample_fps=2.0),
        source,
        sink,
    )
    await _run_for(pipeline, 0.5)
    assert source.closed
