"""Own the pipeline lifecycle.

One thread per camera, each running its own asyncio loop (spec §4.3:
threads, not processes). The source factory is injected so the manager is
testable offline with ``FileSource`` and exercises the real RTSP path with
``RtspSource``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable

from app.services.stream.pipeline import (
    CameraConfig,
    CameraPipeline,
    FrameSink,
    PipelineStatus,
)
from app.services.stream.source import FrameSource

log = logging.getLogger(__name__)

SourceFactory = Callable[[CameraConfig], FrameSource]


class _CameraWorker:
    """A dedicated thread running one camera's asyncio event loop."""

    def __init__(self, camera_id: str) -> None:
        self.camera_id = camera_id
        self.loop = asyncio.new_event_loop()
        self.task: asyncio.Task[None] | None = None
        self.thread = threading.Thread(
            target=self.loop.run_forever,
            name=f"camera-{camera_id}",
            daemon=True,
        )
        self.pipeline: CameraPipeline | None = None


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

    def add_camera(
        self,
        config: CameraConfig,
        *,
        sink: FrameSink | None = None,
        on_frame: FrameSink | None = None,
    ) -> None:
        """Start a pipeline for ``config`` on a fresh thread+loop.

        Args:
            config: Camera settings for the new pipeline.
            sink: Per-camera override; falls back to the manager-wide sink.
                Phase 3 passes one AlertStage per camera through this slot.
            on_frame: Raw-frame hook before the motion gate (T13 bridge).

        Raises:
            ValueError: If the camera is already running.
        """
        with self._lock:
            if config.camera_id in self._workers:
                raise ValueError(f"camera {config.camera_id} is already running")
            worker = _CameraWorker(config.camera_id)
            source = self._factory(config)
            worker.pipeline = CameraPipeline(config, source, sink or self._sink, on_frame=on_frame)
            worker.thread.start()

            def _spawn() -> None:
                # Create the task on its own loop thread: only the owning
                # loop can cancel a coroutine, and the done callback parks an
                # idle loop when the pipeline ends on its own.
                pipeline = worker.pipeline
                assert pipeline is not None  # set two lines above
                worker.task = worker.loop.create_task(pipeline.run())
                task = worker.task
                task.add_done_callback(lambda _t: self._on_done(config.camera_id, worker, task))

            worker.loop.call_soon_threadsafe(_spawn)
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
        # Cancel the task ON its own loop thread (only the owning loop may
        # cancel a coroutine) and let the join(5s) below return once the task
        # has finalized: the done callback stops the loop, so by the time stop
        # returns the generator's finally has run and the source is closed —
        # pause() is airtight, reattaching never finds a mid-flight chain.

        def _cancel_on_loop() -> None:
            if worker.task is None:
                worker.loop.call_later(0.02, _cancel_on_loop)
                return
            if worker.task.done():
                worker.loop.stop()
                return
            worker.task.cancel()
            # The done callback in _on_done early-returns on CancelledError,
            # so parking the loop here belongs to the stop path.
            worker.task.add_done_callback(lambda _t: worker.loop.stop())

        worker.loop.call_soon_threadsafe(_cancel_on_loop)
        worker.thread.join(timeout=5.0)

    def _on_done(
        self,
        camera_id: str,
        worker: _CameraWorker,
        task: asyncio.Task[None],
    ) -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            log.error("camera %s pipeline died: %r", camera_id, exc, exc_info=exc)
        with self._lock:
            # Identity guard: a removed-and-re-added camera must not have its
            # fresh worker deleted by the old one's late callback.
            if self._workers.get(camera_id) is worker:
                del self._workers[camera_id]
        # A pipeline that ended on its own (source exhausted, fatal error)
        # would otherwise leave run_forever idling; park the loop so the
        # thread exits. remove_camera's path stops it too — this is the
        # no-one-is-watching path (T13).
        if worker.loop.is_running():
            worker.loop.call_soon_threadsafe(worker.loop.stop)
