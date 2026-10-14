"""Alert -> events + event_detections rows (DATABASE A4.7-A4.8)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import Camera, Event, Site
from app.db.models.event import EventDetection
from app.services.alerts.stage import Alert
from app.services.events.persist import attach_media, create_event, mark_delivery


def _alert(**overrides: object) -> Alert:
    defaults: dict[str, object] = {
        "rule_id": 3,
        "rule_name": "After-hours",
        "severity": "critical",
        "track_id": 9,
        "class_name": "person",
        "confidence": 0.81,
        "zone": "Loading dock",
        "fired_at": datetime(2026, 10, 6, 22, 0, tzinfo=UTC),
        "summary": "1 person in Loading dock",
        "camera_id": 0,
        "bbox": (12, 24, 120, 300),
        "notify": True,
    }
    defaults.update(overrides)
    return Alert(**defaults)  # type: ignore[arg-type]


def _camera(db, site: Site) -> Camera:
    camera = Camera(site_id=site.id, name="Back door", rtsp_url="rtsp://10.0.0.6/ch1")
    db.add(camera)
    db.commit()
    return camera


def test_create_event_writes_event_and_detection(db_session, seeded) -> None:
    site, _admin, _viewer = seeded
    camera = _camera(db_session, site)
    event = create_event(db_session, _alert(camera_id=camera.id))
    assert event.site_id == site.id and event.delivery_status == "pending"
    assert event.started_at.tzinfo is None, "DB columns are naive UTC"
    rows = (
        db_session.execute(select(EventDetection).where(EventDetection.event_id == event.id))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    det = rows[0]
    assert det.bbox == [12, 24, 120, 300]
    assert det.class_name == "person" and det.zone_name == "Loading dock"
    assert det.camera_id == camera.id


def test_notify_false_starts_skipped(db_session, seeded) -> None:
    site, _admin, _viewer = seeded
    camera = _camera(db_session, site)
    event = create_event(db_session, _alert(camera_id=camera.id, notify=False))
    assert event.delivery_status == "skipped"


def test_attach_media_and_mark_delivery(db_session, seeded) -> None:
    site, _admin, _viewer = seeded
    camera = _camera(db_session, site)
    event = create_event(db_session, _alert(camera_id=camera.id))
    attach_media(
        db_session,
        event.id,
        thumbnail_path="stills/1.jpg",
        clip_path="clips/1.mp4",
        clip_bytes=2048,
        duration_ms=9000,
    )
    mark_delivery(
        db_session,
        event.id,
        status="sent",
        attempts=1,
        delivered=datetime(2026, 10, 6, 22, 1, tzinfo=UTC),
        attempted=datetime(2026, 10, 6, 22, 1, tzinfo=UTC),
    )
    db_session.expire_all()
    row = db_session.get(Event, event.id)
    assert row is not None
    assert row.clip_path == "clips/1.mp4" and row.clip_bytes == 2048
    assert row.delivery_status == "sent" and row.delivery_attempts == 1
    assert row.delivered_at is not None and row.last_attempt_at is not None
