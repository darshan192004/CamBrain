"""Runtime wiring: pipelines, the DB bridge, and degraded start (D10)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Camera, Site, User
from app.services.alerts.replay import rule_config
from app.services.runtime import Runtime
from app.services.stream.source import Frame


class FakeDetector:
    """Records frames; returns no detections so nothing fires."""

    def __init__(self) -> None:
        self.frames = 0
        self.last_frame: Frame | None = None

    async def infer(self, frame: Frame) -> list[Any]:
        self.frames += 1
        self.last_frame = frame
        return []

    async def close(self) -> None:
        return None


class FakeSource:
    """Yields three frames then ends."""

    def __init__(self) -> None:
        self.closed = False

    async def frames(self) -> Any:
        import numpy as np

        for i in range(3):
            yield Frame(
                data=np.zeros((36, 64, 3), dtype=np.uint8),
                timestamp=float(i),
                width=64,
                height=36,
            )

    async def close(self) -> None:
        self.closed = True


def _camera(db_session: Session, seeded: tuple[Site, User, User]) -> Camera:
    site = seeded[0]
    camera = Camera(site_id=site.id, name="Front", rtsp_url="rtsp://x/ch1")
    db_session.add(camera)
    db_session.commit()
    return camera


def _factory(db_session: Session) -> Any:
    """Production-shaped sessions: a fresh one per call, shared engine."""
    return sessionmaker(bind=db_session.get_bind(), autoflush=False, expire_on_commit=False)


async def test_runtime_disabled_starts_nothing(db_session: Session) -> None:
    runtime = Runtime(session_factory=_factory(db_session), enabled=False)
    await runtime.start()
    assert runtime.cameras == {}
    await runtime.stop()


async def test_runtime_wires_bridge_and_writes_dims(
    db_session: Session, seeded: tuple[Site, User, User]
) -> None:
    camera = _camera(db_session, seeded)
    runtime = Runtime(
        session_factory=_factory(db_session),
        enabled=True,
        detector_factory=lambda **_kw: FakeDetector(),
        source_factory=lambda _config: FakeSource(),
    )
    await runtime.start()
    await runtime.drain()  # lets the pipelines finish their finite sources
    db_session.expire_all()
    row = db_session.get(Camera, camera.id)
    assert row is not None
    assert row.frame_width == 64 and row.frame_height == 36, "bridge records dims"
    assert row.status in ("live", "offline")
    await runtime.stop()


async def test_runtime_survives_missing_weights(
    db_session: Session, seeded: tuple[Site, User, User]
) -> None:
    """Degraded start (D10): no model on disk -> cameras still run, no detector."""
    camera = _camera(db_session, seeded)

    def boom(**_kw: object) -> Any:
        raise FileNotFoundError("yolox_nano.onnx")

    runtime = Runtime(
        session_factory=_factory(db_session),
        enabled=True,
        detector_factory=boom,
        source_factory=lambda _config: FakeSource(),
    )
    await runtime.start()
    await runtime.drain()
    db_session.expire_all()
    row = db_session.get(Camera, camera.id)
    assert row is not None and row.frame_width == 64, "degraded still bridges dims"
    await runtime.stop()


async def test_runtime_stop_closes_everything(
    db_session: Session, seeded: tuple[Site, User, User]
) -> None:
    _camera(db_session, seeded)
    sources: list[FakeSource] = []

    def make(_config: object) -> FakeSource:
        source = FakeSource()
        sources.append(source)
        return source

    runtime = Runtime(
        session_factory=_factory(db_session),
        enabled=True,
        detector_factory=lambda **_kw: FakeDetector(),
        source_factory=make,
    )
    await runtime.start()
    await runtime.drain()
    await runtime.stop()
    assert runtime.cameras == {}
    assert all(s.closed for s in sources)


def test_rule_config_projects_notify() -> None:
    from app.db.models import Rule

    rule = Rule(
        site_id=1,
        camera_id=1,
        name="r",
        severity="critical",
        classes=["person"],
        confidence_threshold=0.5,
        cooldown_seconds=60,
        notify=False,
    )
    assert rule_config(rule, None).notify is False
