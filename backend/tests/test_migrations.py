"""Migration up/down against a *populated* database, not an empty one (DATABASE §10).

A downgrade that only works on an empty DB is worthless — the customer's box
always has data. This seeds a site/user/camera/rule/event, drops everything,
re-creates it, and re-seeds to prove the schema is reusable after a rollback.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.db.models import Camera, Event, Rule, Site, User
from app.db.session import create_engine_for

pytestmark = pytest.mark.slow


def _alembic_cfg(tmp_path) -> Config:  # type: ignore[no-untyped-def]
    """Alembic config pointed at a temp DB, offline from the dev DB."""
    cfg = Config("backend/alembic.ini")
    cfg.set_main_option("script_location", "backend/migrations")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path}/mig.db")
    return cfg


def _table_names(url: str) -> set[str]:  # type: ignore[no-untyped-def]
    eng = create_engine(url)
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


def test_migration_up_down_on_populated(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """upgrade → seed → downgrade → upgrade → re-seed all succeed."""
    url = f"sqlite:///{tmp_path}/mig.db"
    cfg = _alembic_cfg(tmp_path)

    command.upgrade(cfg, "head")
    after_up = _table_names(url)
    for table in (
        "sites",
        "users",
        "sessions",
        "cameras",
        "rois",
        "rules",
        "events",
        "event_detections",
        "audit_log",
        "alembic_version",
    ):
        assert table in after_up, f"missing table {table}"

    # Seed real data so the downgrade runs against a populated DB.
    engine = create_engine_for(tmp_path / "mig.db")
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = factory()
    try:
        site = Site(name="S", timezone="Asia/Kolkata")
        db.add(site)
        db.flush()
        db.add(User(site_id=site.id, username="admin", password_hash="h", role="admin"))
        cam = Camera(site_id=site.id, name="c", rtsp_url="rtsp://h/s")
        db.add(cam)
        db.flush()
        db.add(Rule(site_id=site.id, camera_id=cam.id, name="r", classes=["person"]))
        db.add(
            Event(
                site_id=site.id,
                camera_id=cam.id,
                severity="warning",
                started_at=datetime.now(UTC),
            )
        )
        db.commit()
        populated = db.query(Site).count()
        assert populated == 1
    finally:
        db.close()
        engine.dispose()

    # Downgrade drops everything cleanly even though data exists.
    command.downgrade(cfg, "base")
    after_down = _table_names(url)
    assert "sites" not in after_down
    assert "events" not in after_down

    # Re-upgrade and re-seed to prove the schema is reusable post-rollback.
    command.upgrade(cfg, "head")
    engine2 = create_engine_for(tmp_path / "mig.db")
    db2 = sessionmaker(bind=engine2, autoflush=False, expire_on_commit=False)()
    try:
        site2 = Site(name="T", timezone="UTC")
        db2.add(site2)
        db2.commit()
        assert db2.query(Site).count() == 1
    finally:
        db2.close()
        engine2.dispose()
