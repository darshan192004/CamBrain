"""Repository-layer tests: CRUD, tenant scoping, and the cross-tenant 404 (DATABASE §2, §4).

The cross-tenant row is the one that matters: a 403 would confirm the row
exists, which is an enumeration oracle. Tenancy violations must surface as
not-found, so the repository returns None and the API maps it to a 404.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Camera, Site
from app.db.repositories.cameras import CameraRepository
from app.db.repositories.rois import RoiRepository
from app.db.repositories.rules import RuleRepository


@pytest.fixture
def db() -> Iterator[Session]:
    """In-memory schema-fresh session per test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def two_sites(db: Session) -> tuple[int, int]:
    """Two tenant sites; returns (site_a_id, site_b_id)."""
    a = Site(name="A", timezone="Asia/Kolkata")
    b = Site(name="B", timezone="UTC")
    db.add_all([a, b])
    db.commit()
    return a.id, b.id


def _camera(db: Session, site_id: int, name: str = "cam") -> Camera:
    cam = Camera(site_id=site_id, name=name, rtsp_url="rtsp://h/s")
    db.add(cam)
    db.commit()
    return cam


def test_cross_tenant_read_returns_none(db: Session, two_sites: tuple[int, int]) -> None:
    """A camera in site A is invisible to a repository scoped to site B."""
    site_a, site_b = two_sites
    cam = _camera(db, site_a)

    scoped_to_b = CameraRepository(db, site_id=site_b)
    assert scoped_to_b.get(cam.id) is None

    scoped_to_a = CameraRepository(db, site_id=site_a)
    assert scoped_to_a.get(cam.id) is not None


def test_cross_tenant_list_is_empty(db: Session, two_sites: tuple[int, int]) -> None:
    """Listing another tenant's cameras yields nothing, not an error."""
    site_a, site_b = two_sites
    _camera(db, site_a, "only-in-a")

    scoped_to_b = CameraRepository(db, site_id=site_b)
    assert scoped_to_b.list() == []


def test_camera_crud_roundtrip(db: Session, two_sites: tuple[int, int]) -> None:
    """create → get → update → delete within one tenant."""
    site_a, _ = two_sites
    repo = CameraRepository(db, site_id=site_a)

    cam = repo.create(name="front", rtsp_url="rtsp://cam/stream")
    assert cam.id is not None

    got = repo.get(cam.id)
    assert got is not None and got.name == "front"

    repo.update(cam.id, name="front-door")
    assert repo.get(cam.id).name == "front-door"  # type: ignore[union-attr]

    repo.delete(cam.id)
    assert repo.get(cam.id) is None


def test_roi_belongs_to_camera_and_tenant(db: Session, two_sites: tuple[int, int]) -> None:
    """An ROI is scoped to both its camera and its site."""
    site_a, site_b = two_sites
    cam = _camera(db, site_a)

    roi_repo_a = RoiRepository(db, site_id=site_a)
    roi = roi_repo_a.create(
        camera_id=cam.id, name="dock", points=[[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]]
    )

    assert roi_repo_a.get(roi.id) is not None
    # Cross-tenant lookup of the ROI is invisible.
    assert RoiRepository(db, site_id=site_b).get(roi.id) is None


def test_rule_soft_delete_hides_from_list(db: Session, two_sites: tuple[int, int]) -> None:
    """A soft-deleted rule leaves the default list but keeps its row."""
    site_a, _ = two_sites
    cam = _camera(db, site_a)
    repo = RuleRepository(db, site_id=site_a)

    rule = repo.create(camera_id=cam.id, name="after-hours", classes=["person"])
    assert len(repo.list()) == 1

    repo.soft_delete(rule.id)
    assert repo.list() == []
    # Row still present (events reference it); get() also hides it.
    assert repo.get(rule.id) is None
