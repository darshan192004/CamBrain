"""Fixtures shared by every backend test.

Clips are generated on demand and never committed (spec 11.2). The API
fixtures wire a FastAPI TestClient against a temp SQLite file with a seeded
site plus an admin and a viewer, so no test needs a camera or the real DB.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# Must be set before app.api.auth derives its signing key at import time.
os.environ.setdefault("CAMBRAIN_JWT_SECRET", "test-only-secret-do-not-use-in-prod")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.api.auth import hash_password  # noqa: E402
from app.api.auth import tracker as login_tracker  # noqa: E402
from app.api.deps import get_db  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import Site, User  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.make_fixtures import CLIP_NAMES, ensure_clip  # noqa: E402
from tests.rtsp.conftest import mediamtx_pause, mediamtx_url  # noqa: F401, E402

# Weak Argon2 params keep the suite fast; production uses m=64MB t=3 p=4.
_HASH_KW = {"time_cost": 1, "memory_cost": 32, "parallelism": 1}


@pytest.fixture(autouse=True)
def _reset_login_tracker() -> Iterator[None]:
    """The tracker is module-level; reset it so lockouts don't leak across tests."""
    login_tracker.reset()
    yield
    login_tracker.reset()


@pytest.fixture
def clip_path() -> Path:
    """Path to the generated motion clip — the default input for stream tests."""
    return ensure_clip("motion")


@pytest.fixture
def clips() -> dict[str, Path]:
    """Every documented fixture clip, generated lazily on first access."""
    return {name: ensure_clip(name) for name in CLIP_NAMES}


@pytest.fixture
def db_session(tmp_path: Path) -> Iterator[Session]:
    """A fresh temp-DB session per test, torn down on exit."""
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def seeded(db_session: Session) -> tuple[Site, User, User]:
    """One site with an admin and a viewer user."""
    site = Site(name="Test Site", timezone="Asia/Kolkata")
    db_session.add(site)
    db_session.flush()
    admin = User(
        site_id=site.id,
        username="ramesh",
        password_hash=hash_password("correct-horse-battery", **_HASH_KW),
        role="admin",
    )
    viewer = User(
        site_id=site.id,
        username="viewer",
        password_hash=hash_password("viewpass", **_HASH_KW),
        role="viewer",
    )
    db_session.add_all([admin, viewer])
    db_session.commit()
    return site, admin, viewer


@pytest.fixture
def client(
    db_session: Session,
    seeded: tuple[Site, User, User],  # noqa: ARG001
) -> Iterator[TestClient]:
    """Wired TestClient over the temp DB, with CSRF headers on every request."""
    app = create_app()

    def _override_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    with TestClient(
        app,
        base_url="http://testserver",
        headers={"X-CambBrain-Client": "tests"},
    ) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def admin_headers(
    client: TestClient,
    seeded: tuple[Site, User, User],  # noqa: ARG001
) -> dict[str, str]:
    return _login(client, "ramesh", "correct-horse-battery")


@pytest.fixture
def viewer_headers(
    client: TestClient,
    seeded: tuple[Site, User, User],  # noqa: ARG001
) -> dict[str, str]:
    return _login(client, "viewer", "viewpass")
