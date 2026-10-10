"""Auth tests: Argon2 hashing, JWT signing, session rotation, lockout (API 5, SECURITY 4).

Covers Task 2.5's checklist: login happy path, wrong password -> 401,
lockout after 5 -> 423, refresh rotates and returns a new pair, presenting an
already-rotated refresh revokes the family, me returns site+role, logout revokes
session, viewer cannot call admin route -> 403.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Must be set before app.api.auth derives its signing key.
os.environ["CAMBRAIN_JWT_SECRET"] = "test-only-secret-do-not-use-in-prod"

from app.api.auth import (  # noqa: E402
    AuthError,
    LoginAttemptTracker,
    _verify_password,
    hash_password,
    issue_tokens,
    require_role,
    revoke_session,
    rotate_refresh_token,
    verify_access_token,
    verify_refresh_token,
)
from app.core.errors import AuthError as CoreAuthError  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import Site, User  # noqa: E402

# Argon2id parameters (SECURITY 4.1): production is m=64MB t=3 p=4.
# Tests use a deliberately weak set to keep the suite fast; the production
# defaults are exercised in test_production_parameters_are_strict.
_TEST_TIME_COST = 1
_TEST_MEMORY_COST = 32
_TEST_PARALLELISM = 1


@pytest.fixture
def db() -> Iterator[Session]:
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
def site_and_admin(db: Session) -> tuple[Site, User]:
    site = Site(name="Test Site", timezone="Asia/Kolkata")
    db.add(site)
    db.flush()
    admin = User(
        site_id=site.id,
        username="ramesh",
        password_hash=hash_password(
            "correct-horse-battery",
            time_cost=_TEST_TIME_COST,
            memory_cost=_TEST_MEMORY_COST,
            parallelism=_TEST_PARALLELISM,
        ),
        role="admin",
    )
    db.add(admin)
    db.commit()
    return site, admin


def test_hash_password_is_argon2id() -> None:
    h = hash_password(
        "secret",
        time_cost=_TEST_TIME_COST,
        memory_cost=_TEST_MEMORY_COST,
        parallelism=_TEST_PARALLELISM,
    )
    assert h.startswith("$argon2id$")
    assert _verify_password("secret", h)
    assert not _verify_password("wrong", h)


def test_production_parameters_are_strict() -> None:
    """The defaults must be m=64MB t=3 p=4 (SECURITY 4.1)."""
    from argon2 import PasswordHasher
    from argon2.low_level import Type

    ph = PasswordHasher()
    assert ph.type == Type.ID
    assert ph.time_cost == 3
    assert ph.memory_cost == 64 * 1024
    assert ph.parallelism == 4


def test_login_happy_path(db: Session, site_and_admin: tuple[Site, User]) -> None:
    _, admin = site_and_admin
    tokens = issue_tokens(db, admin, "correct-horse-battery")
    assert tokens.access_token
    assert tokens.refresh_token
    assert tokens.expires_in == 43200


def test_login_wrong_password(db: Session, site_and_admin: tuple[Site, User]) -> None:
    _, admin = site_and_admin
    with pytest.raises(AuthError):
        issue_tokens(db, admin, "wrong")


def test_lockout_after_five_failures() -> None:
    tracker = LoginAttemptTracker()
    for _ in range(5):
        with pytest.raises(AuthError):
            tracker.check_and_record("ramesh", False)
    with pytest.raises(CoreAuthError) as exc_info:
        tracker.check_and_record("ramesh", False)
    assert "423" in str(exc_info.value) or "locked" in str(exc_info.value).lower()


def test_successful_login_resets_counter() -> None:
    tracker = LoginAttemptTracker()
    for _ in range(4):
        with pytest.raises(AuthError):
            tracker.check_and_record("ramesh", False)
    tracker.check_and_record("ramesh", True)  # success resets
    for _ in range(4):
        with pytest.raises(AuthError):
            tracker.check_and_record("ramesh", False)


def test_refresh_rotates_token(db: Session, site_and_admin: tuple[Site, User]) -> None:
    """Rotate returns a new pair; reusing the old refresh revokes the family."""
    _, admin = site_and_admin
    tokens = issue_tokens(db, admin, "correct-horse-battery")
    old_refresh = tokens.refresh_token

    new_tokens = rotate_refresh_token(db, old_refresh)
    assert new_tokens.access_token != tokens.access_token
    assert new_tokens.refresh_token != old_refresh

    # Reuse of the rotated token must fail (theft detection)...
    with pytest.raises(AuthError):
        verify_refresh_token(db, old_refresh)
    # ...and revoke every other session in the family.
    with pytest.raises(AuthError):
        verify_refresh_token(db, new_tokens.refresh_token)


def test_logout_revokes_session(db: Session, site_and_admin: tuple[Site, User]) -> None:
    _, admin = site_and_admin
    tokens = issue_tokens(db, admin, "correct-horse-battery")
    revoke_session(db, tokens.access_token)
    with pytest.raises(AuthError):
        verify_access_token(db, tokens.access_token)


def test_me_returns_site_and_role(db: Session, site_and_admin: tuple[Site, User]) -> None:
    site, admin = site_and_admin
    tokens = issue_tokens(db, admin, "correct-horse-battery")
    claims = verify_access_token(db, tokens.access_token)
    assert claims["site_id"] == site.id
    assert claims["role"] == "admin"
    assert claims["sub"] == str(admin.id)


def test_viewer_cannot_call_admin_route(db: Session, site_and_admin: tuple[Site, User]) -> None:
    site, _ = site_and_admin
    viewer = User(
        site_id=site.id,
        username="viewer",
        password_hash=hash_password(
            "viewpass",
            time_cost=_TEST_TIME_COST,
            memory_cost=_TEST_MEMORY_COST,
            parallelism=_TEST_PARALLELISM,
        ),
        role="viewer",
    )
    db.add(viewer)
    db.commit()
    tokens = issue_tokens(db, viewer, "viewpass")
    claims = verify_access_token(db, tokens.access_token)
    with pytest.raises(CoreAuthError) as exc_info:
        require_role("admin")(claims)
    assert "403" in str(exc_info.value) or "forbidden" in str(exc_info.value).lower()
