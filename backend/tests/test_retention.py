"""Retention: batched age deletes, unlink-before-commit, orphan sweep."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.db.models import Camera, Event, Site
from app.services.events.retention import prune_events, sweep_orphans


def _site(db, **overrides) -> Site:
    site = Site(name="s", timezone="UTC", **overrides)
    db.add(site)
    db.commit()
    return site


def _camera(db, site: Site) -> Camera:
    camera = Camera(site_id=site.id, name="c", rtsp_url="rtsp://10.0.0.7/ch1")
    db.add(camera)
    db.commit()
    return camera


def _event(
    db,
    site: Site,
    started_at: datetime,
    *,
    clip: str | None = None,
    thumb: str | None = None,
) -> Event:
    event = Event(
        site_id=site.id,
        camera_id=_camera(db, site).id,
        rule_id=None,
        triggered_by="system",
        started_at=started_at,
        severity="warning",
        summary="s",
        clip_path=clip,
        thumbnail_path=thumb,
    )
    db.add(event)
    db.commit()
    return event


def test_prune_deletes_only_events_past_retention(db_session, tmp_path: Path) -> None:
    site = _site(db_session)
    now = datetime(2026, 10, 6, 12, 0)
    old = _event(db_session, site, now - timedelta(days=8))
    fresh = _event(db_session, site, now - timedelta(days=1))
    deleted = prune_events(db_session, site_id=site.id, now=now, media_root=tmp_path)
    assert deleted == 1
    db_session.expire_all()
    assert db_session.get(Event, old.id) is None
    assert db_session.get(Event, fresh.id) is not None


def test_prune_unlinks_clip_and_still_before_deleting_row(db_session, tmp_path: Path) -> None:
    site = _site(db_session)
    (tmp_path / "clips").mkdir()
    (tmp_path / "stills").mkdir()
    (tmp_path / "clips" / "1.mp4").write_bytes(b"v")
    (tmp_path / "stills" / "1.jpg").write_bytes(b"j")
    now = datetime(2026, 10, 6, 12, 0)
    _event(
        db_session,
        site,
        now - timedelta(days=9),
        clip="clips/1.mp4",
        thumb="stills/1.jpg",
    )
    assert prune_events(db_session, site_id=site.id, now=now, media_root=tmp_path) == 1
    assert not (tmp_path / "clips" / "1.mp4").exists()
    assert not (tmp_path / "stills" / "1.jpg").exists()


def test_prune_batches_and_respects_per_site_retention(db_session, tmp_path: Path) -> None:
    site_a = _site(db_session, retention_days=1)
    site_b = _site(db_session, retention_days=30)
    now = datetime(2026, 10, 6, 12, 0)
    camera = _camera(db_session, site_a)
    for _ in range(700):
        db_session.add(
            Event(
                site_id=site_a.id,
                camera_id=camera.id,
                triggered_by="system",
                started_at=now - timedelta(days=5),
                severity="warning",
                summary="s",
            )
        )
    db_session.commit()
    _event(db_session, site_b, now - timedelta(days=5))
    deleted = prune_events(db_session, site_id=site_a.id, now=now, media_root=tmp_path, batch=500)
    assert deleted == 700, "two batches of 500 + 200, all one site's rows"
    db_session.expire_all()
    kept = db_session.execute(select(Event).where(Event.site_id == site_b.id)).scalars().all()
    assert len(kept) == 1, "retention never crosses a tenant boundary"


def test_retention_days_zero_means_nothing_pruned(db_session, tmp_path: Path) -> None:
    site = _site(db_session, retention_days=0)
    now = datetime(2026, 10, 6, 12, 0)
    _event(db_session, site, now - timedelta(days=365))
    assert prune_events(db_session, site_id=site.id, now=now, media_root=tmp_path) == 0


def test_orphan_sweep_removes_old_unreferenced_files(db_session, tmp_path: Path) -> None:
    site = _site(db_session)
    (tmp_path / "clips").mkdir()
    orphan = tmp_path / "clips" / "999.mp4"
    orphan.write_bytes(b"v")
    stale = datetime(2026, 10, 6, 12, 0)
    old_ts = (stale - timedelta(hours=25)).timestamp()
    os.utime(orphan, (old_ts, old_ts))
    fresh = tmp_path / "clips" / "1000.mp4"
    fresh.write_bytes(b"v")
    removed = sweep_orphans(db_session, site_id=site.id, media_root=tmp_path, now=stale)
    assert removed == 1 and not orphan.exists() and fresh.exists()


def test_orphan_sweep_keeps_files_with_a_row(db_session, tmp_path: Path) -> None:
    site = _site(db_session)
    (tmp_path / "clips").mkdir()
    kept = tmp_path / "clips" / "1.mp4"
    kept.write_bytes(b"v")
    old = datetime(2026, 10, 6, 12, 0) - timedelta(hours=40)
    os.utime(kept, (old.timestamp(), old.timestamp()))
    _event(db_session, site, datetime(2026, 10, 1), clip="clips/1.mp4")
    assert (
        sweep_orphans(
            db_session, site_id=site.id, media_root=tmp_path, now=datetime(2026, 10, 6, 12, 0)
        )
        == 0
    )
    assert kept.exists()


def test_missing_files_never_break_a_prune(db_session, tmp_path: Path) -> None:
    site = _site(db_session)
    now = datetime(2026, 10, 6, 12, 0)
    _event(
        db_session,
        site,
        now - timedelta(days=9),
        clip="clips/gone.mp4",
        thumb="stills/gone.jpg",
    )
    assert prune_events(db_session, site_id=site.id, now=now, media_root=tmp_path) == 1
