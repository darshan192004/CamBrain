"""AlertHandler: persist -> still -> broadcast -> post-roll clip (arch A7)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import select

from app.db.models import Camera, Event
from app.db.models.event import EventDetection
from app.services.alerts.stage import Alert
from app.services.events.clips import ClipWriter, FrameRingBuffer
from app.services.events.handler import AlertHandler
from app.services.stream.jpeg import encode_jpeg
from app.services.stream.source import Frame


class FakeHub:
    """Records broadcasts instead of touching sockets."""

    def __init__(self) -> None:
        self.messages: list[tuple[int, dict]] = []

    def broadcast(self, site_id: int, message: dict) -> None:
        self.messages.append((site_id, message))


def _alert(camera_id: int) -> Alert:
    return Alert(
        rule_id=3,
        rule_name="After-hours",
        severity="critical",
        track_id=9,
        class_name="person",
        confidence=0.81,
        zone="Loading dock",
        fired_at=datetime(2026, 10, 6, 22, 0, tzinfo=UTC),
        summary="1 person in Loading dock",
        camera_id=camera_id,
        bbox=(12, 24, 120, 300),
        notify=True,
    )


@pytest.fixture
def world(db_session, seeded, tmp_path: Path):
    site, _admin, _viewer = seeded
    camera = Camera(site_id=site.id, name="Back door", rtsp_url="rtsp://10.0.0.6/ch1")
    db_session.add(camera)
    db_session.commit()
    ring = FrameRingBuffer()
    for i in range(6):
        frame = Frame(
            data=np.full((64, 96, 3), (i * 10) % 255, dtype=np.uint8),
            timestamp=float(i),
            width=96,
            height=64,
        )
        ring.append_jpeg(float(i), encode_jpeg(frame))
    hub = FakeHub()
    slept: list[float] = []

    async def instant(seconds: float) -> None:
        slept.append(seconds)

    handler = AlertHandler(
        camera_id=camera.id,
        site_id=site.id,
        camera_name="Back door",
        ring=ring,
        # Host disk state is irrelevant: inject a mostly-empty disk.
        writer=ClipWriter(tmp_path, disk_usage=lambda _p: (1, 100)),
        hub=hub,  # type: ignore[arg-type]
        session_factory=lambda: db_session,
        sleep=instant,
        # Frames are buffered at t=0..5; fire "now" so the window covers them.
        now=lambda: 5.0,
        quota_pct=lambda: 99.0,
    )
    return handler, db_session, hub, slept, tmp_path, camera.id


async def test_fire_persists_still_broadcasts_then_clips(world) -> None:
    handler, db, hub, slept, _tmp, camera_id = world
    await handler(_alert(camera_id))
    event = db.execute(select(Event)).scalars().one()
    assert event.thumbnail_path == f"stills/{event.id}.jpg"
    assert event.clip_path is None, "clip lands after the post-roll"
    assert hub.messages[0][1]["data"]["has_clip"] is False
    await asyncio.sleep(0)  # let the scheduled _finish task run (sleep is instant)

    db.expire_all()
    event = db.execute(select(Event)).scalars().one()
    assert slept == pytest.approx([20.0]), "post-roll waits 20s"
    assert event.clip_path == f"clips/{event.id}.mp4"
    assert hub.messages[-1][1]["data"]["has_clip"] is True
    dets = db.execute(select(EventDetection)).scalars().all()
    assert len(dets) == 1 and dets[0].bbox == [12, 24, 120, 300]


async def test_quota_refusal_fires_system_hook(world) -> None:
    handler, db, hub, _slept, _tmp, camera_id = world
    quotas: list[str] = []
    handler.set_quota_hook(lambda summary: quotas.append(summary))
    handler._quota_pct = lambda: 0.0  # noqa: SLF001 - force refusal
    await handler(_alert(camera_id))
    await asyncio.sleep(0)
    assert quotas and "quota" in quotas[0]
    event = db.execute(select(Event)).scalars().one()
    assert event.clip_path is None, "refused clip leaves the row, not debris"
