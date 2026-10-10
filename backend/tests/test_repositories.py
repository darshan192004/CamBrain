"""Repository-layer schema tests: uniqueness, CHECK constraints, JSON round-trip (DATABASE §4).

These assert the structural constraints that keep the schema honest — the
things SQLite would let slide (CHECK, FK) but that the product depends on.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Camera, Roi, Rule, Site, User
from app.db.session import create_engine_for


@pytest.fixture
def db(tmp_path):
    engine = create_engine_for(tmp_path / "t.db")
    from app.db.base import Base

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _site(db: Session, name: str = "S") -> Site:
    site = Site(name=name, timezone="Asia/Kolkata")
    db.add(site)
    db.flush()
    return site


def test_users_username_unique_per_site(db: Session) -> None:
    """UNIQUE(site_id, username) — two sites may each have an 'admin'."""
    a, b = _site(db, "A"), _site(db, "B")
    db.add(User(site_id=a.id, username="admin", password_hash="h", role="admin"))
    db.flush()
    # Same username on a different site is fine.
    db.add(User(site_id=b.id, username="admin", password_hash="h", role="admin"))
    db.flush()
    # Same username on the SAME site must be rejected.
    db.add(User(site_id=a.id, username="admin", password_hash="h", role="viewer"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_user_role_check_rejects_invalid(db: Session) -> None:
    """role is constrained to admin|viewer (DATABASE §4.2 CHECK)."""
    site = _site(db)
    db.add(User(site_id=site.id, username="u", password_hash="h", role="root"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_camera_sample_fps_check(db: Session) -> None:
    """sample_fps is CHECK-constrained to 0.1–10 (DATABASE §4.4)."""
    site = _site(db)
    db.add(Camera(site_id=site.id, name="c", rtsp_url="rtsp://h/s", sample_fps=50.0))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_roi_points_roundtrip_as_json(db: Session) -> None:
    """rois.points is JSON and round-trips (DATABASE §4.5)."""
    site = _site(db)
    cam = Camera(site_id=site.id, name="c", rtsp_url="rtsp://h/s")
    db.add(cam)
    db.flush()
    pts = [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]]
    roi = Roi(site_id=site.id, camera_id=cam.id, name="dock", points=pts)
    db.add(roi)
    db.commit()
    got = db.get(Roi, roi.id)
    assert got is not None
    assert got.points == pts


def test_rule_classes_roundtrip_and_soft_delete_column(db: Session) -> None:
    """rules.classes is JSON of COCO names; deleted_at supports soft delete."""
    site = _site(db)
    cam = Camera(site_id=site.id, name="c", rtsp_url="rtsp://h/s")
    db.add(cam)
    db.flush()
    rule = Rule(
        site_id=site.id,
        camera_id=cam.id,
        name="r",
        classes=["person"],
        confidence_threshold=0.55,
        cooldown_seconds=60,
    )
    db.add(rule)
    db.commit()
    got = db.get(Rule, rule.id)
    assert got is not None
    assert got.classes == ["person"]
    assert got.deleted_at is None
