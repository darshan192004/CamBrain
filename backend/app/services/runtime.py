"""The process-wide brain: pipelines, the alert chain, and the DB bridge.

Owned by main.py's lifespan. Every collaborator is constructed here once:
one detector, one hub, one delivery worker, one retention runner per site,
and per camera a ring buffer + handler + AlertStage (arch A7).

`enabled=False` (conftest, CAMBRAIN_RUNTIME_ENABLED=0) makes start() a
no-op so the API test suite never opens a socket or a model file (D10).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import CamBrainError
from app.db.models import Camera, Site
from app.db.repositories.rois import RoiRepository
from app.db.repositories.rules import RuleRepository
from app.db.session import SessionLocal
from app.services.alerts.delivery import DeliveryWorker
from app.services.alerts.hub import AlertHub, event_message, get_alert_hub
from app.services.alerts.latch import QuotaLatch
from app.services.alerts.replay import rule_config
from app.services.alerts.rules import RuleConfig
from app.services.alerts.stage import AlertStage
from app.services.events.clips import ClipWriter, FrameRingBuffer
from app.services.events.handler import AlertHandler
from app.services.events.persist import create_system_event
from app.services.events.retention import RetentionRunner
from app.services.stream.factory import default_source_factory
from app.services.stream.pipeline import CameraConfig
from app.services.stream.source import Frame
from app.services.stream.stream_manager import StreamManager

log = logging.getLogger(__name__)

SourceFactory = Callable[[CameraConfig], Any]
DetectorFactory = Callable[..., Any]


async def _noop_sink(_frame: Frame) -> None:
    """Manager-wide sink; each camera overrides it with its own chain."""
    return


class Runtime:
    """Start and stop the whole alerting chain; own its lifecycle."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] = SessionLocal,
        enabled: bool | None = None,
        source_factory: SourceFactory | None = None,
        detector_factory: DetectorFactory | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._enabled = settings.runtime_enabled if enabled is None else enabled
        self._source_factory = source_factory
        self._detector_factory = detector_factory
        self._hub: AlertHub | None = None
        self._worker: DeliveryWorker | None = None
        self._retention: list[RetentionRunner] = []
        self._manager: StreamManager | None = None
        self._detector: Any = None
        self._handlers: dict[str, AlertHandler] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._camera_rows: dict[str, Camera] = {}
        self._bridged: set[int] = set()
        self._latches: dict[int, QuotaLatch] = {}
        self.cameras: dict[str, dict[str, Any]] = {}

    @property
    def hub(self) -> AlertHub:
        """The alert hub the WS endpoint serves (module singleton, T5)."""
        if self._hub is None:
            self._hub = get_alert_hub()
        return self._hub

    async def start(self) -> None:
        """Construct and launch everything; no-op when disabled (D10)."""
        if not self._enabled:
            return
        self._hub = get_alert_hub()
        self._detector = self._open_detector_safely()
        manager = StreamManager(self._manager_source_factory(), _noop_sink)
        self._manager = manager
        db = self._session_factory()
        try:
            # Cameras were live when the process died: say so until a frame proves it.
            db.execute(
                update(Camera)
                .where(Camera.status.in_(("live", "starting")))
                .values(status="offline")
                .execution_options(synchronize_session=False)
            )
            db.commit()
            rows = list(db.execute(select(Camera).where(Camera.enabled.is_(True))).scalars())
        finally:
            db.close()
        self._camera_rows = {str(c.id): c for c in rows}
        for camera in rows:
            self._start_camera(camera, manager)
        self._worker = DeliveryWorker(session_factory=self._session_factory)
        self._tasks.append(asyncio.create_task(self._worker.run()))
        for site_id in sorted({c.site_id for c in rows}):
            runner = RetentionRunner(site_id=site_id, session_factory=self._session_factory)
            self._retention.append(runner)
            self._tasks.append(asyncio.create_task(runner.run()))

    async def drain(self) -> None:
        """Test affordance: wait for finite test pipelines to finish."""
        for _ in range(200):
            if self._manager is None or not self._manager.status_all():
                return
            await asyncio.sleep(0.01)

    async def stop(self) -> None:
        """Cancel loops, stop pipelines, close detector and handlers."""
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            # CancelledError is BaseException; shutdown swallows it alongside
            # any sweep failure the loops already suppressed.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        if self._worker is not None:
            await self._worker.close()
            self._worker = None
        for runner in self._retention:
            await runner.close()
        self._retention.clear()
        if self._manager is not None:
            self._manager.stop()
            await asyncio.sleep(0)  # let pipelines run their finally blocks
            self._mark_offline()
            self._manager = None
        for handler in self._handlers.values():
            await handler.close()
        self._handlers.clear()
        self.cameras.clear()
        self._camera_rows.clear()
        self._bridged.clear()
        self._latches.clear()
        if self._detector is not None:
            with contextlib.suppress(Exception):
                await self._detector.close()
            self._detector = None

    # -- internals ---------------------------------------------------------

    def _open_detector_safely(self) -> Any:
        """Open the detector; missing weights -> degraded start (D10)."""
        try:
            if self._detector_factory is not None:
                return self._detector_factory(
                    model_path=settings.model_path, input_size=settings.model_input_size
                )
            from app.services.inference.detector import open_detector

            return open_detector(settings.model_path, input_size=settings.model_input_size)
        except (FileNotFoundError, CamBrainError):
            log.warning("detector weights missing; starting degraded (D10)")
            return None

    def _manager_source_factory(self) -> SourceFactory:
        """The manager's factory: Runtime's override, else the default RTSP."""
        if self._source_factory is not None:
            return self._source_factory
        # connect_url/decrypt lives inside default_source_factory (it reads the
        # credential columns off the row); CameraConfig.url is never used there.
        return lambda config: default_source_factory(self._camera_rows[config.camera_id])

    def _start_camera(self, camera: Camera, manager: StreamManager) -> None:
        """Build one camera's full chain and hand it to the manager."""
        config = CameraConfig(
            camera_id=str(camera.id),
            name=camera.name,
            url=camera.rtsp_url,
            # The DB allows 0.1..10; the pipeline contract is 2..5 (spec A1.5).
            sample_fps=min(5.0, max(2.0, camera.sample_fps)),
        )
        ring = FrameRingBuffer(duration_s=30.0)
        handler = AlertHandler(
            camera_id=camera.id,
            site_id=camera.site_id,
            camera_name=camera.name,
            ring=ring,
            writer=ClipWriter(media_root=settings.media_root),
            hub=self.hub,
            session_factory=self._session_factory,
            quota_pct=lambda: self._site_quota(camera.site_id),
        )
        handler.set_quota_hook(self._quota_hook(camera.site_id, camera.name))
        self._handlers[config.camera_id] = handler
        rules = self._load_rules(camera)
        stage: AlertStage | None = None
        if self._detector is not None and rules:
            stage = AlertStage(
                detector=self._detector, rules=rules, camera_id=camera.id, on_alert=handler
            )

        async def sink(frame: Frame) -> None:
            ring.append(frame)
            if stage is not None:
                await stage(frame)

        async def on_frame(frame: Frame) -> None:
            # Pre-gate: a quiet scene still earns "live" + dims (T13).
            await self._bridge(camera, frame)

        manager.add_camera(config, sink=sink, on_frame=on_frame)
        self.cameras[config.camera_id] = {"ring": ring, "handler": handler}

    async def _bridge(self, camera: Camera, frame: Frame) -> None:
        """Write frame dims + live status once per camera (stream->db debt)."""
        if camera.id in self._bridged:
            return
        self._bridged.add(camera.id)
        db = self._session_factory()
        try:
            db.execute(
                update(Camera)
                .where(Camera.id == camera.id)
                .values(
                    frame_width=frame.width,
                    frame_height=frame.height,
                    status="live",
                )
            )
            db.commit()
        finally:
            db.close()

    def _load_rules(self, camera: Camera) -> list[RuleConfig]:
        """Enabled rules for one camera, ROIs joined, notify projected."""
        db = self._session_factory()
        try:
            rules = RuleRepository(db, site_id=camera.site_id).list()
            rois = {r.id: r for r in RoiRepository(db, site_id=camera.site_id).list()}
            return [
                rule_config(r, rois.get(r.roi_id) if r.roi_id is not None else None)
                for r in rules
                if r.camera_id == camera.id and r.enabled
            ]
        finally:
            db.close()

    def _quota_hook(self, site_id: int, camera_name: str) -> Callable[[str], None]:
        """Quota refusal -> one system event per crossing (D12)."""

        def _persist(full: str) -> None:
            db = self._session_factory()
            try:
                event = create_system_event(db, site_id=site_id, severity="critical", summary=full)
                self.hub.broadcast(event.site_id, event_message(event, None))
            finally:
                db.close()

        latch = self._latches.get(site_id)
        if latch is None:
            latch = QuotaLatch(site_id=site_id, on_fire=_persist)
            self._latches[site_id] = latch

        def fire(summary: str) -> None:
            latch.fire(f"{summary} (camera {camera_name})")

        return fire

    def _site_quota(self, site_id: int) -> float:
        db = self._session_factory()
        try:
            site = db.get(Site, site_id)
            return float(site.disk_quota_pct) if site else 80.0
        finally:
            db.close()

    def _mark_offline(self) -> None:
        db = self._session_factory()
        try:
            ids = [int(k) for k in self.cameras]
            if ids:
                db.execute(
                    update(Camera)
                    .where(Camera.id.in_(ids))
                    .values(status="offline")
                    .execution_options(synchronize_session=False)
                )
                db.commit()
        finally:
            db.close()
