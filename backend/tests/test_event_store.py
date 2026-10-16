"""Alert intake: row + detection + media + broadcast, loss-free."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from app.api.ws.hub import clear, recent
from app.db.models import Camera, Event, Site
from app.services.alerts.stage import Alert
from app.services.events.store import store_alert
from app.services.stream.source import Frame


def _alert() -> Alert:
    return Alert(
        rule_id=7,
        rule_name="Back door",
        severity="critical",
        track_id=3,
        class_name="person",
        confidence=0.8,
        zone="Loading dock",
        fired_at=datetime.now(UTC),
        summary="1 person in Loading dock",
    )


def _frame() -> Frame:
    return Frame(data=np.full((36, 64, 3), 120, dtype=np.uint8), timestamp=0.0, width=64, height=36)


def test_store_persists_event_detection_media_and_broadcast(
    db_session: Session, seeded: tuple[Site, object, object], tmp_path: Path
) -> None:
    site, _, _ = seeded
    camera = Camera(site_id=site.id, name="c1", rtsp_url="rtsp://10.0.0.5:554/s")
    db_session.add(camera)
    db_session.commit()
    clear()
    event, still = store_alert(
        db_session,
        site_id=site.id,
        camera_id=camera.id,
        alert=_alert(),
        media_root=tmp_path,
        pre_roll=[_frame()],
        quota_pct=100,
    )
    assert db_session.get(Event, event.id) is not None
    assert event.thumbnail_path is not None and event.clip_path is not None
    assert still[:2] == b"\xff\xd8"
    assert recent()[-1]["data"]["id"] == event.id


def test_quota_refusal_keeps_the_row(
    db_session: Session, seeded: tuple[Site, object, object], tmp_path: Path
) -> None:
    """The clip is refused; the evidence row is not."""
    site, _, _ = seeded
    camera = Camera(site_id=site.id, name="c1", rtsp_url="rtsp://10.0.0.5:554/s")
    db_session.add(camera)
    db_session.commit()
    event, _ = store_alert(
        db_session,
        site_id=site.id,
        camera_id=camera.id,
        alert=_alert(),
        media_root=tmp_path,
        pre_roll=[_frame()],
        quota_pct=0,
    )
    assert db_session.get(Event, event.id) is not None
    assert event.clip_path is None


def test_prune_removes_old_rows_and_files(
    db_session: Session, seeded: tuple[Site, object, object], tmp_path: Path
) -> None:
    from datetime import timedelta

    from app.db.repositories.events import EventRepository

    site, _, _ = seeded
    repo = EventRepository(db_session, site_id=site.id)
    media = tmp_path / "clips"
    media.mkdir()
    orphan = media / "1.mp4"
    orphan.write_bytes(b"x")
    old = repo.create_from_alert(
        camera_id=1,
        severity="info",
        summary="old",
        started_at=datetime.now(UTC) - timedelta(days=30),
    )
    old.clip_path = str(orphan.resolve().relative_to(tmp_path.resolve()))
    db_session.commit()
    assert repo.prune_older_than(7, tmp_path) == 1
    assert db_session.get(Event, old.id) is None
    assert not orphan.exists()
