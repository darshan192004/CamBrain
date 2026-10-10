"""Own the pipeline lifecycle.

One thread per camera, each running its own asyncio loop (spec §4.3:
threads, not processes). The source factory is injected so the manager is
testable offline with ``FileSource`` and exercises the real RTSP path with
``RtspSource``.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import threading
from collections.abc import Callable

from app.services.stream.pipeline import (
    CameraConfig,
    CameraPipeline,
    FrameSink,
    PipelineStatus,
)
from app.services.stream.source import FrameSource

SourceFactory = Callable[[CameraConfig], FrameSource]


class _CameraWorker:
    """A dedicated thread running one camera's asyncio event loop."""

    def __init__(self, camera_id: str) -> None:
        self.camera_id = camera_id
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self.loop.run_forever,
            name=f"camera-{camera_id}",
            daemon=True,
        )
        self.pipeline: CameraPipeline | None = None
        self.future: concurrent.futures.Future[None] | None = None


class StreamManager:
    """Create, stop, and observe pipelines; owns their lifecycle (arch §2).

    Args:
        source_factory: Builds a ``FrameSource`` for a config. The injected
            seam that keeps the manager hardware-free.
        sink: What each pipeline hands motion frames to (later phases wire
            the detector slot here).
    """

    def __init__(self, source_factory: SourceFactory, sink: FrameSink) -> None:
        self._factory = source_factory
        self._sink = sink
        self._workers: dict[str, _CameraWorker] = {}
        self._lock = threading.Lock()

    def add_camera(self, config: CameraConfig) -> None:
        """Start a pipeline for ``config`` on a fresh thread+loop."""
        with self._lock:
            if config.camera_id in self._workers:
                raise ValueError(f"camera {config.camera_id} is already running")
            worker = _CameraWorker(config.camera_id)
            source = self._factory(config)
            worker.pipeline = CameraPipeline(config, source, self._sink)
            worker.thread.start()
            worker.future = asyncio.run_coroutine_threadsafe(worker.pipeline.run(), worker.loop)
            worker.future.add_done_callback(
                lambda fut: self._on_done(config.camera_id, worker, fut)
            )
            self._workers[config.camera_id] = worker

    def remove_camera(self, camera_id: str) -> bool:
        """Stop a camera's pipeline and join its thread. Unknown id → False."""
        with self._lock:
            worker = self._workers.get(camera_id)
            if worker is None:
                return False
            del self._workers[camera_id]
        self._stop_worker(worker)
        return True

    def status_all(self) -> dict[str, PipelineStatus]:
        """Snapshot every running pipeline. Safe to call from any thread."""
        with self._lock:
            workers = list(self._workers.values())
        return {w.camera_id: w.pipeline.snapshot() for w in workers if w.pipeline is not None}

    def stop(self) -> None:
        """Stop every camera."""
        for camera_id in list(self.status_all()):
            self.remove_camera(camera_id)

    def _stop_worker(self, worker: _CameraWorker) -> None:
        if worker.future is not None:
            worker.future.cancel()
        # Give the loop 50 ms to deliver the cancellation (so the pipeline's
        # finally closes the source), then stop the run_forever thread.
        worker.loop.call_soon_threadsafe(lambda: worker.loop.call_later(0.05, worker.loop.stop))
        worker.thread.join(timeout=5.0)

    def _on_done(
        self,
        camera_id: str,
        worker: _CameraWorker,
        fut: concurrent.futures.Future[None],
    ) -> None:
        with contextlib.suppress(concurrent.futures.CancelledError):
            fut.exception()  # swallow CancelledError and failures; log held them
        with self._lock:
            # Identity guard: a removed-and-re-added camera must not have its
            # fresh worker deleted by the old one's late callback.
            if self._workers.get(camera_id) is worker:
                del self._workers[camera_id]
